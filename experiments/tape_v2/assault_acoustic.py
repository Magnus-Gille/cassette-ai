"""assault_acoustic.py — do NOT give up on the acoustic path: search the FAITHFUL
sim (real_channel_sim) for a modulation that beats the ~25% diffuse cross-bin floor.

Tests, all through experiments/tape_v2/real_channel_sim.py (the VALIDATED sim that
reproduces the real M16 failure), with the SAME genie-ceiling + achievable + RS
methodology as validate_real_sim.py / m2_modem_survival:

  A. ComboMFSK M32,K2 (N=159) -- the prior best (genie byte-ER 0.16, RS-closable on
     the GENIE path only). Baseline to beat.
  B. WIDE-SPACED low-M MFSK (K=1, tones many bins apart) -- the hypothesis that
     separating tones past the adjacent-smear reach survives. (NEGATIVE control.)
  C. ComboMFSK M32,K2 with SYMBOL REPETITION x2/x3 (energy-combine repeated symbols)
     -- frequency/time diversity against the diffuse floor on the ACHIEVABLE path.

For each: zero-channel sanity, GENIE bit-BER + byte-ER, ACHIEVABLE bit-BER + byte-ER
(fixed-grid top-K, no oracle), and whether robust interleaved RS(255,127) closes the
ACHIEVABLE byte-ER to byte-exact. A config "survives" only if the ACHIEVABLE path is
RS-closable -- not just the genie.

Run:  python experiments/tape_v2/assault_acoustic.py
"""
from __future__ import annotations

import json
import math
import pathlib
import sys
import time
from itertools import combinations

import numpy as np

ROOT = pathlib.Path("/Users/magnus/repos/cassette-ai")
for _p in ("src", "tests/e2e", "experiments/capacity", "experiments/tape_v2"):
    s = str(ROOT / _p)
    if s not in sys.path:
        sys.path.insert(0, s)

import hyp_common as hc                       # noqa: E402
import real_channel_sim as rcs                # noqa: E402
from c2_combo_mfsk import ComboMFSKScheme      # noqa: E402

FS = 48_000
RESULTS = ROOT / "experiments" / "tape_v2" / "results"
RS_CEIL = 0.251        # robust interleaved RS(255,127) byte-correction fraction
RS_MARGIN = 0.20       # comfortable close (interleave headroom)
PARAMS = rcs.load_params()
CAPTURE = "master3"


def _eq_for(scheme):
    Hf = PARAMS["Hf_magnitude"]
    fm = np.asarray(Hf[f"sounder_freqs_{CAPTURE}"], float)
    Hd = np.asarray(Hf[f"H_db_{CAPTURE}"], float)
    Hl = 10.0 ** (np.interp(scheme.freqs, fm, Hd) / 20.0)
    Hl = Hl / (Hl.max() + 1e-12)
    clip = PARAMS.get("_sim", {}).get("eq_clip", 0.05)
    return np.clip(Hl, clip, None)


# ---------------------------------------------------------------------------
# Wide-spaced low-M MFSK (K=1) scheme — custom orthogonal grid with spacing>1 bin
# ---------------------------------------------------------------------------
class WideMFSK(ComboMFSKScheme):
    def __init__(self, M, spacing_bins, f_low=400.0, f_high=10000.0,
                 preamble_seconds=0.25):
        sr = FS
        bw = f_high - f_low
        delta_f_est = bw / max((M - 1) * spacing_bins, 1)
        grid = None
        for dN in range(-20, 60):
            N = int(round(sr / delta_f_est)) + dN
            if N <= 0:
                continue
            delta_f = sr / N
            b0 = int(np.ceil(f_low / delta_f))
            bins = np.array([b0 + i * spacing_bins for i in range(M)])
            if bins[-1] * delta_f <= f_high + 1:
                grid = (N, bins, bins * delta_f)
                break
        if grid is None:
            raise ValueError(f"no grid for M={M} spacing={spacing_bins}")
        N, bins, freqs = grid
        self.M = M; self.K = 1; self.preamble_seconds = preamble_seconds
        self.samples_per_sym = N; self._bin_indices = bins; self.freqs = freqs
        self.delta_f = sr / N; self.T_sym = N / sr
        subs = list(combinations(range(M), 1))
        self._table = [np.array(s, dtype=np.int32) for s in subs]
        self._rev_table = {s: i for i, s in enumerate(subs)}
        self.n_symbols = len(subs)
        self.bits_per_sym = max(1, int(math.floor(math.log2(self.n_symbols))))
        self._sym_cap = 1 << self.bits_per_sym
        self._preamble = hc.make_preamble(preamble_seconds).astype(np.float32)
        self.name = f"WideMFSK_M{M}_sp{spacing_bins}"


# ---------------------------------------------------------------------------
# Generic genie + achievable evaluation for any ComboMFSK-like scheme
# ---------------------------------------------------------------------------
def eval_scheme(sch, *, reps=10, nsym=160, track=15, rep_factor=1):
    """rep_factor>1: each data symbol is transmitted rep_factor times in a row;
    the ACHIEVABLE demod energy-combines the repeats before top-K. The GENIE still
    sees one symbol per repeat-group (oracle). Diversity against the diffuse floor."""
    N = sch.samples_per_sym
    bps = sch.bits_per_sym
    K = sch.K
    bins = np.clip(sch._bin_indices, 0, N // 2)
    eq = _eq_for(sch)
    rg = np.random.default_rng(11 + sch.M * 3 + rep_factor)

    # sanity (no channel)
    sb = rg.integers(0, 2, size=nsym * bps, dtype=np.uint8)
    a = sch.modulate(sb)
    rec = sch.demodulate(a, FS)
    m = min(len(sb), len(rec))
    sanity = (int(np.count_nonzero(sb[:m] != rec[:m])) + (len(sb) - m)) / len(sb)

    g_be = g_bt = a_be = a_bt = 0
    g_byte_e = g_byte_t = a_byte_e = a_byte_t = 0
    for rep in range(reps):
        bits = rg.integers(0, 2, size=nsym * bps, dtype=np.uint8)
        gt = [sch._bits_to_sym(bits[s * bps:(s + 1) * bps]) for s in range(nsym)]
        # build a bit stream with each symbol repeated rep_factor times
        if rep_factor > 1:
            tx_syms = [si for si in gt for _ in range(rep_factor)]
            tx_bits = np.array([b for si in tx_syms for b in sch._sym_to_bits(si)], np.uint8)
        else:
            tx_bits = bits
        audio = sch.modulate(tx_bits)
        y = rcs.real_channel(audio, params=PARAMS, capture=CAPTURE,
                             symbol_len=N, seed_offset=rep)
        ds = hc.find_preamble(y.astype(np.float32), sch.preamble_seconds)
        n_tx_sym = len(tx_bits) // bps

        # ACHIEVABLE: the m3_decode_v2.HardDemod design — a drift-carrying
        # concentration-lock tracker with a small CENTER-BIAS (prefer the offset
        # near the predicted grid position) so a noisy lock score does not let the
        # window wander off the grid. This is the honest best real tracker; energy
        # of repeated symbols is combined per group before the top-K decision.
        a_e_groups = []
        cur_group = np.zeros(sch.M)
        drift = 0.0
        center_bias = 0.02
        for s in range(n_tx_sym):
            base = ds + s * N + int(round(drift))
            abest = None
            for d in range(-track, track + 1):
                p = base + d
                if p < 0 or p + N > len(y):
                    continue
                e = np.abs(np.fft.rfft(y[p:p + N], n=N))[bins] / eq
                srt = np.sort(e)[::-1]
                lock = ((srt[K - 1] - srt[K]) / (srt[0] + 1e-9)) * (1.0 - center_bias * abs(d))
                if abest is None or lock > abest[0]:
                    abest = (lock, d, e)
            if abest is not None:
                _, d, e = abest
                drift += d
                cur_group = cur_group + e
            if (s % rep_factor) == rep_factor - 1:
                a_e_groups.append(cur_group.copy())
                cur_group = np.zeros(sch.M)

        # GENIE: a group is correct iff SOME repeat decodes the known symbol at SOME
        # offset (oracle timing). This is the strict per-group ceiling.
        g_ok = [False] * nsym
        for gi in range(nsym):
            ok = False
            for r in range(rep_factor):
                s = gi * rep_factor + r
                for d in range(-track, track + 1):
                    p = ds + s * N + d
                    if p < 0 or p + N > len(y):
                        continue
                    e = np.abs(np.fft.rfft(y[p:p + N], n=N))[bins] / eq
                    tk = tuple(sorted(np.argpartition(e, -K)[-K:].tolist()))
                    si = min(sch._rev_table.get(tk, 0), sch._sym_cap - 1)
                    if si == gt[gi]:
                        ok = True
                        break
                if ok:
                    break
            g_ok[gi] = ok
        g_syms = [gt[gi] if g_ok[gi] else ((gt[gi] + 1) % sch._sym_cap) for gi in range(nsym)]

        # ACHIEVABLE decode from energy-combined groups
        a_syms = []
        for gi in range(nsym):
            e = a_e_groups[gi] if gi < len(a_e_groups) else np.zeros(sch.M)
            tk = tuple(sorted(np.argpartition(e, -K)[-K:].tolist()))
            a_syms.append(min(sch._rev_table.get(tk, 0), sch._sym_cap - 1))

        gb = np.array([b for si in g_syms for b in sch._sym_to_bits(si)][:len(bits)], np.uint8)
        ab = np.array([b for si in a_syms for b in sch._sym_to_bits(si)][:len(bits)], np.uint8)
        g_be += int(np.count_nonzero(bits[:len(gb)] != gb)); g_bt += len(bits)
        a_be += int(np.count_nonzero(bits[:len(ab)] != ab)); a_bt += len(bits)
        nbytes = (nsym * bps) // 8
        tbp = np.packbits(bits[:nbytes * 8])
        g_byte_e += int(np.count_nonzero(tbp != np.packbits(gb[:nbytes * 8]))); g_byte_t += nbytes
        a_byte_e += int(np.count_nonzero(tbp != np.packbits(ab[:nbytes * 8]))); a_byte_t += nbytes

    gross = sch.gross_bps if not callable(getattr(sch, "gross_bps", None)) else sch.gross_bps
    gross = float(gross) / rep_factor
    return {
        "phy": sch.name + (f" x{rep_factor}" if rep_factor > 1 else ""),
        "N": N, "bin_hz": FS / N, "bits_per_sym": bps, "gross_bps": gross,
        "sanity_ber": sanity,
        "genie_ber": g_be / max(1, g_bt),
        "achievable_ber": a_be / max(1, a_bt),
        "genie_byte_er": g_byte_e / max(1, g_byte_t),
        "achievable_byte_er": a_byte_e / max(1, a_byte_t),
        "rs_closable_genie": bool((g_byte_e / max(1, g_byte_t)) < RS_MARGIN),
        "rs_closable_achievable": bool((a_byte_e / max(1, a_byte_t)) < RS_MARGIN),
    }


def main():
    t0 = time.time()
    out = {"capture": CAPTURE, "rs_ceiling": RS_CEIL, "rs_margin": RS_MARGIN,
           "results": {}}
    print("=" * 100)
    print("ACOUSTIC assault through the FAITHFUL real_channel_sim (capture=%s)" % CAPTURE)
    print("=" * 100)
    hdr = (f"  {'phy':<22} {'N':>4} {'binHz':>6} {'gross':>6} {'sanity':>7} "
           f"{'genieBER':>9} {'achBER':>7} {'gByteER':>8} {'aByteER':>8} "
           f"{'RS(g)':>6} {'RS(a)':>6}")
    print(hdr)

    schemes = [
        ("A_M32K2", ComboMFSKScheme(M=32, K=2), 1),
        ("B_wideM8_sp4", WideMFSK(8, 4), 1),
        ("B_wideM4_sp8", WideMFSK(4, 8), 1),
        ("C_M32K2_x2", ComboMFSKScheme(M=32, K=2), 2),
        ("C_M32K2_x3", ComboMFSKScheme(M=32, K=2), 3),
    ]
    for tag, sch, rf in schemes:
        r = eval_scheme(sch, rep_factor=rf)
        out["results"][tag] = r
        print(f"  {r['phy']:<22} {r['N']:>4} {r['bin_hz']:>6.0f} {r['gross_bps']:>6.0f} "
              f"{r['sanity_ber']:>7.3f} {r['genie_ber']:>9.4f} {r['achievable_ber']:>7.4f} "
              f"{r['genie_byte_er']:>8.3f} {r['achievable_byte_er']:>8.3f} "
              f"{'YES' if r['rs_closable_genie'] else 'no':>6} "
              f"{'YES' if r['rs_closable_achievable'] else 'no':>6}")

    # verdict
    survivors = [t for t, r in out["results"].items() if r["rs_closable_achievable"]]
    genie_only = [t for t, r in out["results"].items()
                  if r["rs_closable_genie"] and not r["rs_closable_achievable"]]
    out["survivors_achievable"] = survivors
    out["genie_only"] = genie_only
    out["verdict"] = ("SURVIVES" if survivors else
                      ("PARTIAL" if genie_only else "FAILS"))
    print(f"\n  achievable RS-closable survivors: {survivors or 'NONE'}")
    print(f"  genie-only (RS-closable on genie, not achievable): {genie_only or 'NONE'}")
    print(f"  VERDICT: {out['verdict']}")

    RESULTS.mkdir(parents=True, exist_ok=True)
    outp = RESULTS / "assault_acoustic.json"
    outp.write_text(json.dumps(out, indent=2, default=float))
    print(f"\n[done] wrote {outp}  ({time.time()-t0:.0f}s)")
    return out


if __name__ == "__main__":
    main()
