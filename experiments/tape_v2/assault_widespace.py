"""assault_widespace.py — Hypothesis A: WIDE-SPACED tones + guard bands.

The wall (REAL_DECODE_FINDINGS.md): every scheme so far packs K-of-M tones ONE
FFT bin apart. The real cassette channel smears energy into ADJACENT bins
(~11% M16 / ~5% M32) plus a length-independent ~25% diffuse floor. With 1-bin
spacing the adjacent smear lands directly on neighbour DATA tones, so a spurious
3rd tone clears the lit pair and the genie floors at ~0.17-0.20 bit-BER.

ATTACK: place FEWER tones spaced GUARD+1 bins apart, with EMPTY guard bins between
them, so the FFT-skirt / adjacent-symbol smear lands in GUARD bins (ignored) not on
neighbour data tones. Use a longer symbol N so finer bins make room for guards.
Also offer a CONTRAST detector: score a tone by (its energy) - (mean of its own
guard bins), which subtracts the local diffuse pedestal instead of trusting an
absolute top-K.

Methodology (mandatory, REAL_DECODE_FINDINGS.md):
  1. no-channel SANITY BER ~0 (catch demod bugs)
  2. evaluate through the FAITHFUL real_channel_sim.real_channel
  3. report BOTH genie ceiling (oracle symbol + best per-symbol timing + EQ) AND
     achievable (real tracker) BER, and whether a robust interleaved RS (rate ~0.5,
     byte-correct fraction 0.251) closes the ACHIEVABLE path to byte-exact (judged
     on byte-error rate, the true RS input).

A config "works" only if the ACHIEVABLE path is RS-closable, not just the genie.
"""
from __future__ import annotations

import argparse
import itertools
import json
import math
import pathlib
import sys
from dataclasses import dataclass

import numpy as np

ROOT = pathlib.Path("/Users/magnus/repos/cassette-ai")
for _p in ("src", "experiments/capacity", "experiments/tape_v2"):
    s = str(ROOT / _p)
    if s not in sys.path:
        sys.path.insert(0, s)

import hyp_common as hc                 # noqa: E402
import real_channel_sim as rcs          # noqa: E402

FS = 48_000
F_LOW = 400.0
F_HIGH = 11_000.0
PREAMBLE_SECONDS = 0.25

# robust interleaved RS(255,127): corrects up to t=64 byte errors -> fraction 0.251.
RS_CEIL = 0.251
RS_MARGIN = 0.18   # "comfortably closable" (matches m2_modem_survival / validate)


# ---------------------------------------------------------------------------
# Wide-spaced combinatorial K-of-M scheme with guard bins
# ---------------------------------------------------------------------------
@dataclass
class WideSpaceScheme:
    """K-of-M multitone with tones spaced `spacing` FFT bins apart.

    M tones occupy bins  b0, b0+spacing, b0+2*spacing, ...  so spacing-1 EMPTY
    guard bins sit between consecutive data tones. N (samples/symbol) sets the bin
    width sr/N; a larger N narrows bins so a given physical guard (Hz) costs fewer
    samples. We choose N so the whole grid fits in [F_LOW, F_HIGH].
    """
    M: int
    K: int
    spacing: int            # bins between consecutive tone CENTRES (1 = legacy)
    N: int                  # samples/symbol
    preamble_seconds: float = PREAMBLE_SECONDS

    def __post_init__(self):
        assert 1 <= self.K < self.M
        df = FS / self.N
        b0 = math.ceil(F_LOW / df)
        bins = b0 + self.spacing * np.arange(self.M)
        if bins[-1] * df > F_HIGH + 1e-6 or bins[-1] >= self.N // 2:
            raise ValueError(
                f"grid overflow: M={self.M} spacing={self.spacing} N={self.N} "
                f"-> top {bins[-1]*df:.0f} Hz")
        self._bin_indices = bins.astype(int)
        self.freqs = (bins * df).astype(np.float64)
        self.delta_f = df
        self.samples_per_sym = self.N
        # guard bins: the spacing-1 bins immediately around each tone (for contrast)
        self._guard_bins = []
        for b in self._bin_indices:
            g = []
            for off in range(1, self.spacing):
                for s in (-off, off):
                    bb = b + s
                    if 0 <= bb < self.N // 2 and bb not in self._bin_indices:
                        g.append(bb)
            self._guard_bins.append(np.array(sorted(set(g)), dtype=int))
        # combinatorial tables
        subsets = list(itertools.combinations(range(self.M), self.K))
        self._table = [np.array(s, dtype=int) for s in subsets]
        self._rev_table = {s: i for i, s in enumerate(subsets)}
        self.n_symbols = len(subsets)
        self.bits_per_sym = max(1, int(math.floor(math.log2(self.n_symbols))))
        self._sym_cap = 1 << self.bits_per_sym
        self._preamble = hc.make_preamble(self.preamble_seconds).astype(np.float32)
        self.name = f"WS_M{self.M}_K{self.K}_sp{self.spacing}_N{self.N}"

    # --- bit<->symbol ---
    def _bits_to_sym(self, b) -> int:
        v = 0
        for x in b:
            v = (v << 1) | int(x)
        return min(v, self._sym_cap - 1)

    def _sym_to_bits(self, si) -> list[int]:
        return [(si >> (self.bits_per_sym - 1 - j)) & 1 for j in range(self.bits_per_sym)]

    # --- modulate ---
    def modulate(self, bits) -> np.ndarray:
        bits = np.asarray(bits, np.uint8)
        bps = self.bits_per_sym
        pad = (-len(bits)) % bps
        if pad:
            bits = np.concatenate([bits, np.zeros(pad, np.uint8)])
        nsym = len(bits) // bps
        N = self.N
        t = np.arange(N) / FS
        amp = 1.0 / self.K
        waves = (amp * np.sin(2 * math.pi * self.freqs[:, None] * t[None, :]))
        body = np.zeros(nsym * N)
        for i in range(nsym):
            si = self._bits_to_sym(bits[i * bps:(i + 1) * bps])
            for ti in self._table[si]:
                body[i * N:(i + 1) * N] += waves[ti]
        audio = np.concatenate([self._preamble.astype(np.float64), body])
        peak = np.max(np.abs(audio))
        if peak > 0:
            audio = audio / peak * 0.70
        return audio.astype(np.float32)


def eq_for(scheme, params, capture):
    """Per-tone sounder-H(f) EQ gain (normalized, clipped)."""
    Hf = params["Hf_magnitude"]
    fm = np.asarray(Hf[f"sounder_freqs_{capture}"], float)
    Hd = np.asarray(Hf[f"H_db_{capture}"], float)
    Hl = 10.0 ** (np.interp(scheme.freqs, fm, Hd) / 20.0)
    Hl = Hl / (Hl.max() + 1e-12)
    clip = params.get("_sim", {}).get("eq_clip", 0.05)
    return np.clip(Hl, clip, None)


# ---------------------------------------------------------------------------
# Detectors. `topk` = absolute top-K of EQ'd tone energy (legacy).
#            `contrast` = top-K of (EQ'd tone energy - mean EQ'd guard energy).
# ---------------------------------------------------------------------------
def _score(e_tone, e_guard, eq, detector):
    s = e_tone / eq
    if detector == "contrast":
        s = s - e_guard / eq
    return s


def _sym_from_score(scheme, score):
    K = scheme.K
    tk = tuple(sorted(np.argpartition(score, -K)[-K:].tolist()))
    return min(scheme._rev_table.get(tk, 0), scheme._sym_cap - 1)


def _energies_at(y, p, N, tone_bins, guard_bins):
    """Return (tone_energy[M], guard_mean_energy[M]) for the window at sample p."""
    seg = y[p:p + N]
    if len(seg) < N:
        if len(seg) < N // 2:
            return None, None
        seg = np.concatenate([seg, np.zeros(N - len(seg))])
    sp = np.abs(np.fft.rfft(seg, n=N))
    e_tone = sp[tone_bins]
    e_guard = np.array([sp[g].mean() if len(g) else 0.0 for g in guard_bins])
    return e_tone, e_guard


# ---------------------------------------------------------------------------
# Evaluation: sanity / genie / achievable, returns bit-BER + byte-ER.
# ---------------------------------------------------------------------------
def _byte_er(bits_tx, bits_rx):
    nbytes = len(bits_tx) // 8
    tb = np.packbits(bits_tx[:nbytes * 8])
    rb = bits_rx[:nbytes * 8]
    if len(rb) < nbytes * 8:
        rb = np.concatenate([rb, np.zeros(nbytes * 8 - len(rb), np.uint8)])
    rbp = np.packbits(rb)
    return int(np.count_nonzero(tb != rbp)), nbytes


def eval_scheme(scheme, params, capture, *, detector="contrast", reps=8,
                nsym=64, track=15, contamination=1.0, sanity=False):
    """Returns dict with sanity_ber (if sanity), genie_ber/byte_er,
    achievable_ber/byte_er. contamination scales diffuse+ISI gains DOWN."""
    N = scheme.N
    bps = scheme.bits_per_sym
    tone_bins = np.clip(scheme._bin_indices, 0, N // 2)
    guard_bins = scheme._guard_bins
    eq = eq_for(scheme, params, capture)
    rg = np.random.default_rng(2025)

    # contamination knob: scale the two added smear terms in a copy of params
    p = json.loads(json.dumps(params))
    base_diff = params["_sim"].get("diffuse_gain", 0.5)
    base_adj = params["_sim"].get("adj_gain", 1.0)
    p["_sim"]["diffuse_gain"] = base_diff * contamination
    p["_sim"]["adj_gain"] = base_adj * contamination

    g_bit_err = g_bit_tot = g_byte_err = g_byte_tot = 0
    a_bit_err = a_byte_err = 0
    s_bit_err = s_bit_tot = 0

    for rep in range(reps):
        bits = rg.integers(0, 2, size=nsym * bps, dtype=np.uint8)
        audio = scheme.modulate(bits)

        if sanity:
            # no-channel: demod straight from clean audio (catch demod bugs)
            ds = hc.find_preamble(audio.astype(np.float32), scheme.preamble_seconds)
            rb = []
            for sidx in range(nsym):
                pos = ds + sidx * N
                et, eg = _energies_at(audio.astype(np.float64), pos, N, tone_bins, guard_bins)
                if et is None:
                    rb.extend([0] * bps); continue
                si = _sym_from_score(scheme, _score(et, eg, eq, detector))
                rb.extend(scheme._sym_to_bits(si))
            rb = np.array(rb[:len(bits)], np.uint8)
            m = min(len(bits), len(rb))
            s_bit_err += int(np.count_nonzero(bits[:m] != rb[:m]))
            s_bit_tot += len(bits)
            continue

        y = rcs.real_channel(audio, params=p, capture=capture,
                             symbol_len=N, seed_offset=rep)
        ds = hc.find_preamble(y.astype(np.float32), scheme.preamble_seconds)
        y = y.astype(np.float64)

        # ground-truth symbols
        gt = [scheme._bits_to_sym(bits[s * bps:(s + 1) * bps]) for s in range(nsym)]

        # --- GENIE: oracle symbol + best per-symbol timing in +/-track + EQ ---
        grec, arec = [], []
        drift = 0.0
        for sidx in range(nsym):
            best_g = None
            best_a = None          # achievable: pick offset by detector lock score
            base = ds + sidx * N + int(round(drift))
            chosen_d = 0
            for d in range(-track, track + 1):
                et, eg = _energies_at(y, base + d, N, tone_bins, guard_bins)
                if et is None:
                    continue
                sc = _score(et, eg, eq, detector)
                si = _sym_from_score(scheme, sc)
                # genie: prefer offset decoding the known symbol, nearest center
                if si == gt[sidx] and (best_g is None or abs(d) < best_g[0]):
                    best_g = (abs(d), si)
                # achievable lock: concentration gap between Kth and (K+1)th score
                srt = np.sort(sc)[::-1]
                lock = (srt[scheme.K - 1] - srt[scheme.K]) / (abs(srt[0]) + 1e-9)
                if best_a is None or lock > best_a[0]:
                    best_a = (lock, si, d)
            if best_g is None and best_a is not None:
                # genie fallback: take the center decode
                best_g = (track + 1, best_a[1])
            grec.append(best_g[1] if best_g else 0)
            if best_a is not None:
                arec.append(best_a[1]); chosen_d = best_a[2]
                drift += chosen_d
            else:
                arec.append(0)

        gb = np.array([b for si in grec for b in scheme._sym_to_bits(si)][:len(bits)], np.uint8)
        ab = np.array([b for si in arec for b in scheme._sym_to_bits(si)][:len(bits)], np.uint8)
        m = min(len(bits), len(gb))
        g_bit_err += int(np.count_nonzero(bits[:m] != gb[:m]))
        g_bit_tot += len(bits)
        be, nb = _byte_er(bits, gb); g_byte_err += be; g_byte_tot += nb
        a_bit_err += int(np.count_nonzero(bits[:m] != ab[:m]))
        be, _ = _byte_er(bits, ab); a_byte_err += be

    if sanity:
        return {"sanity_ber": s_bit_err / max(1, s_bit_tot)}
    return {
        "genie_ber": g_bit_err / max(1, g_bit_tot),
        "genie_byte_er": g_byte_err / max(1, g_byte_tot),
        "achievable_ber": a_bit_err / max(1, g_bit_tot),
        "achievable_byte_er": a_byte_err / max(1, g_byte_tot),
        "bits_per_sym": bps,
    }


def net_bps(scheme, code_rate=0.498):
    """Net payload bps = gross * RS code rate (robust = 0.498).
    gross = bps_per_sym / T_sym (ignoring preamble overhead -> upper bound; we
    discount preamble per typical 2000-byte frame separately in report)."""
    T = scheme.N / FS
    gross = scheme.bits_per_sym / T
    return gross * code_rate


# ---------------------------------------------------------------------------
# Sweep + main
# ---------------------------------------------------------------------------
def build(M, K, spacing, N):
    try:
        return WideSpaceScheme(M=M, K=K, spacing=spacing, N=N)
    except ValueError:
        return None


def sweep(params, capture="master3", reps=6, detector="contrast"):
    rows = []
    # M tones, spacing bins apart, N samples/symbol. K<=2 (proven viable regime).
    # spacing 1 = legacy baseline; 2..8 = guard bands. N chosen so the grid fits.
    grid = []
    for M in (8, 12, 16, 20, 24):
        for K in (1, 2):
            if K >= M:
                continue
            for spacing in (1, 2, 3, 4, 6, 8):
                # need bins b0..b0+spacing*(M-1) inside [F_LOW,F_HIGH]; df=FS/N.
                # top freq <= F_HIGH => bin_top*df<=F_HIGH. choose smallest N that fits
                # then a couple larger N for finer bins.
                for N in (96, 128, 160, 200, 256, 320, 400):
                    grid.append((M, K, spacing, N))
    seen = set()
    for (M, K, spacing, N) in grid:
        key = (M, K, spacing, N)
        if key in seen:
            continue
        seen.add(key)
        sch = build(M, K, spacing, N)
        if sch is None:
            continue
        if sch.bits_per_sym < 2:
            continue
        san = eval_scheme(sch, params, capture, detector=detector, reps=2,
                          nsym=48, sanity=True)["sanity_ber"]
        if san > 1e-6:
            continue  # demod bug for this grid; skip
        r = eval_scheme(sch, params, capture, detector=detector, reps=reps, nsym=64)
        nb = net_bps(sch)
        rs_close_ach = r["achievable_byte_er"] < RS_CEIL
        rows.append({
            "M": M, "K": K, "spacing": spacing, "N": N,
            "bin_hz": round(sch.delta_f, 1),
            "guard_hz": round(sch.delta_f * spacing, 1),
            "top_hz": round(float(sch.freqs[-1]), 0),
            "bps_sym": sch.bits_per_sym,
            "sanity_ber": round(san, 6),
            "genie_ber": round(r["genie_ber"], 4),
            "genie_byte_er": round(r["genie_byte_er"], 4),
            "achievable_ber": round(r["achievable_ber"], 4),
            "achievable_byte_er": round(r["achievable_byte_er"], 4),
            "net_bps": round(nb, 1),
            "rs_close_genie": bool(r["genie_byte_er"] < RS_CEIL),
            "rs_close_achievable": bool(rs_close_ach),
        })
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--capture", default="master3")
    ap.add_argument("--reps", type=int, default=6)
    ap.add_argument("--detector", default="contrast", choices=["contrast", "topk"])
    args = ap.parse_args()

    params = rcs.load_params()
    print(f"# assault_widespace  capture={args.capture}  detector={args.detector}  "
          f"reps={args.reps}  RS_CEIL={RS_CEIL}")

    # baseline sanity: legacy 1-bin M16K2 N77 must be ~0 with no channel (catch bugs)
    base = WideSpaceScheme(M=16, K=2, spacing=1, N=77)
    for det in ("topk", "contrast"):
        sb = eval_scheme(base, params, args.capture, detector=det, reps=2,
                         nsym=48, sanity=True)["sanity_ber"]
        print(f"  [sanity] M16K2 sp1 N77 {det}: BER={sb:.2e}")

    rows = sweep(params, args.capture, reps=args.reps, detector=args.detector)
    # rank: RS-closable ACHIEVABLE first, then net_bps
    rows.sort(key=lambda r: (not r["rs_close_achievable"], -r["net_bps"]))
    print(f"\n# {len(rows)} configs evaluated. Top by (RS-closable-achievable, net_bps):")
    hdr = (f"  {'config':28} {'binHz':>6} {'gdHz':>6} {'bps':>3} {'sane':>6} "
           f"{'gBER':>6} {'gByER':>6} {'aBER':>6} {'aByER':>6} {'net':>6} {'gRS':>4} {'aRS':>4}")
    print(hdr)
    for r in rows[:25]:
        name = f"M{r['M']}K{r['K']}sp{r['spacing']}N{r['N']}"
        print(f"  {name:28} {r['bin_hz']:>6.0f} {r['guard_hz']:>6.0f} {r['bps_sym']:>3} "
              f"{r['sanity_ber']:>6.0e} {r['genie_ber']:>6.3f} {r['genie_byte_er']:>6.3f} "
              f"{r['achievable_ber']:>6.3f} {r['achievable_byte_er']:>6.3f} "
              f"{r['net_bps']:>6.0f} {'Y' if r['rs_close_genie'] else 'n':>4} "
              f"{'Y' if r['rs_close_achievable'] else 'n':>4}")

    best = rows[0] if rows else None
    out = {"capture": args.capture, "detector": args.detector, "reps": args.reps,
           "rs_ceil": RS_CEIL, "n_configs": len(rows), "rows": rows, "best": best}

    # contamination sweep for the best ACHIEVABLE-leaning config (or best genie if
    # none closes achievable): how far must we lower reverb/ISI for RS-close?
    cand = next((r for r in rows if r["rs_close_achievable"]), None) or \
        min(rows, key=lambda r: r["achievable_byte_er"]) if rows else None
    if cand:
        sch = WideSpaceScheme(M=cand["M"], K=cand["K"], spacing=cand["spacing"], N=cand["N"])
        print(f"\n# contamination sweep on best candidate {sch.name} "
              f"(genie_byteER={cand['genie_byte_er']}, ach_byteER={cand['achievable_byte_er']})")
        print(f"  {'contam':>7} {'gBER':>6} {'gByER':>6} {'aBER':>6} {'aByER':>6} "
              f"{'gRS':>4} {'aRS':>4}")
        csweep = []
        thr_g = thr_a = None
        for c in (1.0, 0.8, 0.6, 0.5, 0.4, 0.3, 0.2, 0.1, 0.0):
            rr = eval_scheme(sch, params, args.capture, detector=args.detector,
                             reps=max(args.reps, 8), nsym=64, contamination=c)
            grs = rr["genie_byte_er"] < RS_CEIL
            ars = rr["achievable_byte_er"] < RS_CEIL
            if grs and thr_g is None:
                thr_g = c
            if ars and thr_a is None:
                thr_a = c
            print(f"  {c:>7.2f} {rr['genie_ber']:>6.3f} {rr['genie_byte_er']:>6.3f} "
                  f"{rr['achievable_ber']:>6.3f} {rr['achievable_byte_er']:>6.3f} "
                  f"{'Y' if grs else 'n':>4} {'Y' if ars else 'n':>4}")
            csweep.append({"contam": c, **{k: round(v, 4) for k, v in rr.items()
                                           if isinstance(v, float)},
                           "rs_close_genie": bool(grs), "rs_close_achievable": bool(ars)})
        out["contamination_sweep"] = {
            "config": sch.name,
            "genie_rs_close_at_contam_le": thr_g,
            "achievable_rs_close_at_contam_le": thr_a,
            "rows": csweep,
        }
        print(f"\n  genie RS-closes at contamination <= {thr_g}")
        print(f"  achievable RS-closes at contamination <= {thr_a}")

    RESULTS = ROOT / "experiments" / "tape_v2" / "results"
    RESULTS.mkdir(parents=True, exist_ok=True)
    op = RESULTS / f"assault_widespace_{args.capture}_{args.detector}.json"
    op.write_text(json.dumps(out, indent=2, default=float))
    print(f"\n[done] wrote {op}")
    return out


if __name__ == "__main__":
    main()


# ---------------------------------------------------------------------------
# TRUE end-to-end RS-closure test (faithful sim, achievable tracker).
# Encodes a real payload via m3_codec (RS + global interleave), modulates each
# frame with the wide-space scheme, pushes through real_channel, demods with the
# achievable concentration-lock tracker, de-interleaves + RS-decodes. Reports
# whether the result is BYTE-EXACT.
# ---------------------------------------------------------------------------
def _demod_frame_achievable(scheme, eq, y_frame, nsym, detector, track=15):
    """Achievable per-symbol concentration-lock tracker on one frame's audio."""
    N = scheme.N
    bps = scheme.bits_per_sym
    tone_bins = np.clip(scheme._bin_indices, 0, N // 2)
    guard_bins = scheme._guard_bins
    ds = hc.find_preamble(y_frame.astype(np.float32), scheme.preamble_seconds)
    yy = y_frame.astype(np.float64)
    drift = 0.0
    out = []
    for sidx in range(nsym):
        base = ds + sidx * N + int(round(drift))
        best = None
        for d in range(-track, track + 1):
            et, eg = _energies_at(yy, base + d, N, tone_bins, guard_bins)
            if et is None:
                continue
            sc = _score(et, eg, eq, detector)
            si = _sym_from_score(scheme, sc)
            srt = np.sort(sc)[::-1]
            lock = (srt[scheme.K - 1] - srt[scheme.K]) / (abs(srt[0]) + 1e-9)
            if best is None or lock > best[0]:
                best = (lock, si, d)
        if best is None:
            out.extend([0] * bps); continue
        out.extend(scheme._sym_to_bits(best[1]))
        drift += best[2]
    return np.array(out, dtype=np.uint8)


def rs_closure_test(scheme, params, capture, *, detector="contrast",
                    rs_n=255, rs_k=127, frame_bytes=2000, payload_len=40000,
                    contamination=1.0, seed=7):
    """True end-to-end: returns (byte_exact, byte_err_frac, cw_failed, n_cw)."""
    import m3_codec as codec
    from m3_codec import Rung
    rung = Rung(name="ws", M=scheme.M, K=scheme.K, rs_n=rs_n, rs_k=rs_k,
                frame_bytes=frame_bytes)
    rg = np.random.default_rng(seed)
    payload = bytes(rg.integers(0, 256, size=payload_len, dtype=np.uint8))
    frames, meta = codec.encode_payload(payload, rung)
    eq = eq_for(scheme, params, capture)

    p = json.loads(json.dumps(params))
    p["_sim"]["diffuse_gain"] = params["_sim"].get("diffuse_gain", 0.5) * contamination
    p["_sim"]["adj_gain"] = params["_sim"].get("adj_gain", 1.0) * contamination

    rec_frames = []
    for fi, fb in enumerate(frames):
        nsym = int(np.ceil(len(fb) / scheme.bits_per_sym))
        audio = scheme.modulate(fb)
        y = rcs.real_channel(audio, params=p, capture=capture,
                             symbol_len=scheme.N, seed_offset=fi)
        rec_frames.append(_demod_frame_achievable(scheme, eq, y, nsym, detector))
    recovered = codec.decode_payload(rec_frames, meta)
    cw_failed = codec.decode_payload.last_codewords_failed
    exact = recovered == payload
    byte_err = sum(a != b for a, b in zip(recovered, payload)) + abs(len(recovered) - len(payload))
    return {
        "byte_exact": bool(exact),
        "byte_err_frac": byte_err / max(1, len(payload)),
        "cw_failed": cw_failed,
        "n_cw": meta["n_codewords"],
        "n_frames": meta["n_frames"],
    }
