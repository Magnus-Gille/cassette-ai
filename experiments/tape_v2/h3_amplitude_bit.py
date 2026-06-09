"""h3_amplitude_bit.py — HYPOTHESIS H3: add a 2-level AMPLITUDE bit to the
proven WS_M16_K1_sp3_N256 geometry.

PHY: same 16-tone wide-spaced grid (562.5..9000 Hz, N=256, spacing 3 bins),
K=1 tone per symbol, but each tone is sent at one of TWO amplitude levels
(0 dB / -level_db). bits/sym = 4 (tone) + 1 (amplitude) = 5 -> 937.5 gross bps.
RS(255,191) -> 702.2 net bps; RS(255,159) -> 584.6 net bps (both > 561.8
baseline).

Decoder: existing contrast tone detection FIRST (argmax of EQ'd tone-minus-
guard-pedestal, +/-15-sample concentration-lock timing tracker — same machinery
as assault_widespace._demod_frame_achievable, K=1), THEN the amplitude bit from
the detected tone's level RELATIVE to a per-tone reference (achievable, no
truth):
  global2m : pooled 1-D 2-means over the frame's level_dB -> midpoint threshold
  tone2m   : per-tone-index 2-means (fallback to global when degenerate)
  dd       : tone2m init + sequential decision-directed EMA center tracking
Level metric: 'con' = contrast score (pedestal-subtracted, EQ'd) or
'raw' = EQ'd tone amplitude.

Harness: m5-style sections (per-frame preamble + 0.12 s gaps), whole section
through sim_v2.channel_v2(profile='tape7', aac=True, seed_offset=s), nominal
frame starts + 0.30 s pad windows (align 0 — channel_v2 preserves length),
m3_codec interleaved RS pipeline. Payload = 8 KB slice of stories260K_int4.cass
at offset 16384 (same as m7 rung m16_rs191_8k).

CONTROL (harness sanity, mandatory): WS_M16_K1_sp3_N256 @ RS(255,191) through
the SAME section harness, seeds {0,1}. Expected: byte-exact seed 0, fail seed 1
(documented RS cliff in sim).

Output: results/h3_amplitude_results.json (+ results/h3_amplitude.log).
Run:    python3 h3_amplitude_bit.py            # full protocol
        python3 h3_amplitude_bit.py --smoke    # sanity + 1 short pass
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys
import time

import numpy as np

_HERE = pathlib.Path(__file__).resolve().parent
ROOT = pathlib.Path("/Users/magnus/repos/cassette-ai")
for _p in (ROOT / "src", ROOT / "experiments" / "capacity", _HERE):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import hyp_common as hc                              # noqa: E402
import real_channel_sim as rcs                       # noqa: E402
import sim_v2                                        # noqa: E402
import m3_codec as codec                             # noqa: E402
from m3_codec import Rung                            # noqa: E402
from assault_widespace import (                      # noqa: E402
    build as ws_build, _energies_at, _demod_frame_achievable,
)
from make_master2 import _build_sounder              # noqa: E402

FS = 48_000
RESULTS = _HERE / "results"
OUT_JSON = RESULTS / "h3_amplitude_results.json"

PAYLOAD_OFFSET = 16384          # same slice as m7 rung m16_rs191_8k
PAYLOAD_BYTES = 8192
FRAME_BYTES = 510
RS_N = 255
GAP_S = 0.12                    # matches m5 WS_FRAME_GAP_S
LEAD_S = 0.5
PAD_S = 0.30                    # matches m5 WS_WINDOW_PAD
TRACK = 15
BASELINE_NET_BPS = 561.8

REF_SCHEMES = ["global2m", "tone2m", "dd"]
LEVEL_METRICS = ["con", "raw"]


def payload_slice() -> bytes:
    full = codec.CASS.read_bytes()
    p = full[PAYLOAD_OFFSET:PAYLOAD_OFFSET + PAYLOAD_BYTES]
    assert len(p) == PAYLOAD_BYTES
    return p


# ---------------------------------------------------------------------------
# Amplitude-bit PHY on top of the proven WS geometry
# ---------------------------------------------------------------------------
class AmpWS:
    """WS_M16_K1_sp3_N256 + 1 amplitude bit per symbol (0 dB / -level_db)."""

    def __init__(self, level_db: float):
        self.ws = ws_build(16, 1, 3, 256)
        assert self.ws is not None and self.ws.name == "WS_M16_K1_sp3_N256"
        self.level_db = float(level_db)
        self.amp_lo = 10.0 ** (-self.level_db / 20.0)
        self.tone_bits = self.ws.bits_per_sym          # 4
        self.bits_per_sym = self.tone_bits + 1         # 5
        self.N = self.ws.N
        self.name = f"AMPWS_M16_K1_sp3_N256_L{level_db:g}dB"

    def modulate(self, bits) -> np.ndarray:
        ws = self.ws
        bits = np.asarray(bits, np.uint8)
        bps = self.bits_per_sym
        pad = (-len(bits)) % bps
        if pad:
            bits = np.concatenate([bits, np.zeros(pad, np.uint8)])
        nsym = len(bits) // bps
        N = self.N
        t = np.arange(N) / FS
        waves = np.sin(2 * np.pi * ws.freqs[:, None] * t[None, :])
        body = np.zeros(nsym * N)
        for i in range(nsym):
            b = bits[i * bps:(i + 1) * bps]
            ti = (int(b[0]) << 3) | (int(b[1]) << 2) | (int(b[2]) << 1) | int(b[3])
            amp = self.amp_lo if b[4] else 1.0
            body[i * N:(i + 1) * N] = amp * waves[ti]
        audio = np.concatenate([ws._preamble.astype(np.float64), body])
        peak = np.max(np.abs(audio))
        if peak > 0:
            audio = audio / peak * 0.70
        return audio.astype(np.float32)

    @staticmethod
    def tx_symbols(bits, bps=5):
        """Truth (diagnostic only): (tone_idx[], amp_bit[]) from tx frame bits."""
        bits = np.asarray(bits, np.uint8)
        pad = (-len(bits)) % bps
        if pad:
            bits = np.concatenate([bits, np.zeros(pad, np.uint8)])
        b = bits.reshape(-1, bps)
        tones = (b[:, 0].astype(int) << 3) | (b[:, 1].astype(int) << 2) | \
                (b[:, 2].astype(int) << 1) | b[:, 3].astype(int)
        return tones, b[:, 4].astype(int)


def demod_frame_amp(aws: AmpWS, eq, win, nsym, track=TRACK):
    """Tone detection + level capture. Achievable: contrast argmax, per-symbol
    +/-track concentration-lock timing, drift accumulation (same structure as
    assault_widespace._demod_frame_achievable, K=1)."""
    ws = aws.ws
    N = ws.N
    tone_bins = np.clip(ws._bin_indices, 0, N // 2)
    guard_bins = ws._guard_bins
    ds = hc.find_preamble(np.asarray(win, np.float32), ws.preamble_seconds)
    yy = np.asarray(win, np.float64)
    drift = 0.0
    tones = np.zeros(nsym, int)
    lev_con = np.full(nsym, 1e-9)
    lev_raw = np.full(nsym, 1e-9)
    for sidx in range(nsym):
        base = ds + sidx * N + int(round(drift))
        best = None
        for d in range(-track, track + 1):
            et, eg = _energies_at(yy, base + d, N, tone_bins, guard_bins)
            if et is None:
                continue
            sc = (et - eg) / eq                       # contrast, EQ'd
            ti = int(np.argmax(sc))
            srt = np.sort(sc)[::-1]
            lock = (srt[0] - srt[1]) / (abs(srt[0]) + 1e-9)
            if best is None or lock > best[0]:
                best = (lock, ti, d, sc[ti], et[ti] / eq[ti])
        if best is None:
            continue
        tones[sidx] = best[1]
        lev_con[sidx] = max(best[3], 1e-9)
        lev_raw[sidx] = max(best[4], 1e-9)
        drift += best[2]
    return tones, lev_con, lev_raw


# ---------------------------------------------------------------------------
# Achievable amplitude-bit decision (per frame, no truth)
# ---------------------------------------------------------------------------
def _two_means(vals_db, iters=25):
    v = np.asarray(vals_db, float)
    c_lo, c_hi = np.percentile(v, 15), np.percentile(v, 85)
    if c_hi - c_lo < 1e-6:
        c_hi = c_lo + 1e-6
    for _ in range(iters):
        mid = 0.5 * (c_lo + c_hi)
        lo, hi = v[v < mid], v[v >= mid]
        n_lo = c_lo if len(lo) == 0 else lo.mean()
        n_hi = c_hi if len(hi) == 0 else hi.mean()
        if abs(n_lo - c_lo) < 1e-9 and abs(n_hi - c_hi) < 1e-9:
            break
        c_lo, c_hi = n_lo, n_hi
    return float(c_lo), float(c_hi)


def am_bits_for_frame(tones, lev, level_db, ref):
    """Returns amp bits (1 = low level). lev = linear level metric."""
    lev_db = 20.0 * np.log10(np.maximum(lev, 1e-12))
    n = len(tones)
    g_lo, g_hi = _two_means(lev_db)
    g_thr = 0.5 * (g_lo + g_hi)
    min_sep = 0.4 * level_db

    if ref == "global2m":
        return (lev_db < g_thr).astype(np.uint8)

    # per-tone thresholds / centers
    thr = np.full(16, g_thr)
    cen = np.tile([g_lo, g_hi], (16, 1)).astype(float)
    for t in range(16):
        v = lev_db[tones == t]
        if len(v) >= 8:
            c_lo, c_hi = _two_means(v)
            if (c_hi - c_lo) >= min_sep:
                thr[t] = 0.5 * (c_lo + c_hi)
                cen[t] = [c_lo, c_hi]
    if ref == "tone2m":
        return (lev_db < thr[tones]).astype(np.uint8)

    if ref == "dd":  # decision-directed EMA tracking of both centers
        alpha = 0.15
        out = np.zeros(n, np.uint8)
        c = cen.copy()
        for i in range(n):
            t = tones[i]
            bit = 1 if abs(lev_db[i] - c[t, 0]) < abs(lev_db[i] - c[t, 1]) else 0
            out[i] = bit
            j = 0 if bit else 1
            c[t, j] = (1 - alpha) * c[t, j] + alpha * lev_db[i]
        return out
    raise ValueError(ref)


def genie_am_ber(tones, lev, tx_amp):
    """DIAGNOSTIC ONLY: best single global threshold chosen with truth."""
    lev_db = 20.0 * np.log10(np.maximum(lev, 1e-12))
    order = np.argsort(lev_db)
    cand = np.concatenate([[lev_db.min() - 1], 0.5 * (np.sort(lev_db)[1:] + np.sort(lev_db)[:-1]),
                           [lev_db.max() + 1]])
    best = 1.0
    for thr in cand[:: max(1, len(cand) // 200)]:
        ber = np.mean((lev_db < thr).astype(int) != tx_amp)
        best = min(best, float(ber))
    return best


# ---------------------------------------------------------------------------
# Section build / channel / decode
# ---------------------------------------------------------------------------
def build_section(frame_audios):
    """lead | SOUNDER (~45 s, for post-channel EQ measurement) | frames | tail.
    Returns (audio, frame_starts, sounder_sections)."""
    gap = np.zeros(int(GAP_S * FS), np.float32)
    lead = np.zeros(int(LEAD_S * FS), np.float32)
    snd_audio, snd_sections = _build_sounder()
    snd_sections = [dict(s, start=s["start"] + len(lead)) for s in snd_sections]
    parts = [lead, snd_audio, np.zeros(int(0.4 * FS), np.float32)]
    pos = len(lead) + len(snd_audio) + int(0.4 * FS)
    starts = []
    for fa in frame_audios:
        starts.append(pos)
        parts.append(fa)
        pos += len(fa)
        parts.append(gap)
        pos += len(gap)
    parts.append(np.zeros(int(LEAD_S * FS), np.float32))
    return np.concatenate(parts), starts, snd_sections


def measure_eq(y, sounder_sections, ws):
    """Per-tone EQ from the in-section multitone sounder, measured POST-channel
    — replicates analyze_master2.analyze_sounder H(f) + m6_decode
    _ws_eq_from_sounder (the proven real-pipeline EQ path)."""
    multitone = [s for s in sounder_sections if s["kind"] == "multitone"]
    freqs = np.asarray(multitone[0]["info"]["freqs"], float)
    Hacc, n_used = np.zeros(len(freqs)), 0
    for mt in multitone:
        ti = int(0.3 * FS)
        seg = np.asarray(y[mt["start"] + ti: mt["start"] + mt["length"] - ti],
                         np.float64)
        if len(seg) < FS:
            continue
        win = np.hanning(len(seg))
        sp = np.abs(np.fft.rfft(seg * win))
        fax = np.fft.rfftfreq(len(seg), 1.0 / FS)
        mags = []
        for f in freqs:
            lo = np.searchsorted(fax, f - 30)
            hi = max(np.searchsorted(fax, f + 30), lo + 1)
            mags.append(float(np.max(sp[lo:hi])))
        Hacc += np.asarray(mags)
        n_used += 1
    Hmag = Hacc / max(1, n_used)
    H_db = 20.0 * np.log10(np.maximum(Hmag / (Hmag.max() + 1e-12), 1e-6))
    Hlin = 10.0 ** (np.interp(ws.freqs, freqs, H_db) / 20.0)
    Hlin = Hlin / (Hlin.max() + 1e-12)
    return np.clip(Hlin, 0.05, None)


def channel_pass(section, seed):
    t0 = time.time()
    y = sim_v2.channel_v2(np.asarray(section, np.float64), profile="tape7",
                          aac=True, seed_offset=int(seed))
    return y, time.time() - t0


def frame_window(y, start, frame_len):
    pad = int(PAD_S * FS)
    lo = max(0, start - pad)
    hi = min(len(y), start + frame_len + pad)
    return y[lo:hi]


# ---------------------------------------------------------------------------
# CONTROL: proven WS rung through this exact harness
# ---------------------------------------------------------------------------
def run_control(payload, seed):
    ws = ws_build(16, 1, 3, 256)
    rung = Rung(name="ctrl_rs191", M=16, K=1, rs_n=RS_N, rs_k=191,
                frame_bytes=FRAME_BYTES)
    frames, meta = codec.encode_payload(payload, rung)
    fa = [np.asarray(ws.modulate(fb), np.float32) for fb in frames]
    section, starts, ssecs = build_section(fa)
    y, ch_t = channel_pass(section, seed)
    eq = measure_eq(y, ssecs, ws)
    raw_err = raw_tot = 0
    rec = []
    for fi, fb in enumerate(frames):
        nsym = int(np.ceil(len(fb) / ws.bits_per_sym))
        flen = len(ws._preamble) + nsym * ws.N
        win = frame_window(y, starts[fi], flen)
        rb = np.asarray(_demod_frame_achievable(ws, eq, win, nsym, "contrast"),
                        np.uint8).ravel()
        m = min(len(fb), len(rb))
        raw_err += int(np.count_nonzero(fb[:m] != rb[:m])) + (len(fb) - m)
        raw_tot += len(fb)
        rec.append(rb)
    recovered = codec.decode_payload(rec, meta)
    cw_failed = codec.decode_payload.last_codewords_failed
    return {
        "seed": seed, "raw_ber": raw_err / max(1, raw_tot),
        "cw_failed": cw_failed, "n_cw": meta["n_codewords"],
        "byte_exact": recovered == payload, "channel_s": round(ch_t, 1),
    }


# ---------------------------------------------------------------------------
# H3 end-to-end: one (level_db, rs_k, seed) pass, all decoder variants
# ---------------------------------------------------------------------------
def run_h3_pass(payload, level_db, rs_k, seed, sanity=False):
    aws = AmpWS(level_db)
    rung = Rung(name=f"h3_L{level_db:g}_rs{rs_k}", M=16, K=1, rs_n=RS_N,
                rs_k=rs_k, frame_bytes=FRAME_BYTES)
    frames, meta = codec.encode_payload(payload, rung)
    fa = [aws.modulate(fb) for fb in frames]
    section, starts, ssecs = build_section(fa)
    if sanity:
        y, ch_t = np.asarray(section, np.float64), 0.0
    else:
        y, ch_t = channel_pass(section, seed)
    eq = measure_eq(y, ssecs, aws.ws)   # post-channel EQ, like the real pipeline

    # demod all frames once (tone detection + levels are decoder-variant-free)
    per_frame = []
    tone_err = tot_sym = 0
    det_err_hi = det_tot_hi = det_err_lo = det_tot_lo = 0
    genie_am_err = genie_am_tot = 0
    for fi, fb in enumerate(frames):
        nsym = int(np.ceil(len(fb) / aws.bits_per_sym))
        flen = len(aws.ws._preamble) + nsym * aws.N
        win = frame_window(y, starts[fi], flen)
        tones, lev_con, lev_raw = demod_frame_amp(aws, eq, win, nsym)
        tx_t, tx_a = AmpWS.tx_symbols(fb)
        per_frame.append((tones, lev_con, lev_raw, tx_t, tx_a, len(fb)))
        # diagnostics (truth used ONLY for reporting)
        tone_err += int(np.count_nonzero(tones != tx_t))
        tot_sym += nsym
        hi, lo = tx_a == 0, tx_a == 1
        det_err_hi += int(np.count_nonzero(tones[hi] != tx_t[hi]))
        det_tot_hi += int(hi.sum())
        det_err_lo += int(np.count_nonzero(tones[lo] != tx_t[lo]))
        det_tot_lo += int(lo.sum())
        genie_am_err += genie_am_ber(tones, lev_con, tx_a) * nsym
        genie_am_tot += nsym

    diag = {
        "tone_sym_er": tone_err / max(1, tot_sym),
        "tone_sym_er_hi_amp": det_err_hi / max(1, det_tot_hi),
        "tone_sym_er_lo_amp": det_err_lo / max(1, det_tot_lo),
        "genie_am_ber_con": genie_am_err / max(1, genie_am_tot),
    }

    variants = {}
    for metric in LEVEL_METRICS:
        for ref in REF_SCHEMES:
            raw_err = raw_tot = am_err = am_tot = tbit_err = 0
            rec = []
            for tones, lev_con, lev_raw, tx_t, tx_a, nbits in per_frame:
                lev = lev_con if metric == "con" else lev_raw
                amp = am_bits_for_frame(tones, lev, level_db, ref)
                bits = np.zeros((len(tones), 5), np.uint8)
                bits[:, 0] = (tones >> 3) & 1
                bits[:, 1] = (tones >> 2) & 1
                bits[:, 2] = (tones >> 1) & 1
                bits[:, 3] = tones & 1
                bits[:, 4] = amp
                rb = bits.reshape(-1)[:nbits]
                rec.append(rb)
                # split diagnostics vs tx
                txb = np.zeros((len(tx_t), 5), np.uint8)
                txb[:, 0] = (tx_t >> 3) & 1
                txb[:, 1] = (tx_t >> 2) & 1
                txb[:, 2] = (tx_t >> 1) & 1
                txb[:, 3] = tx_t & 1
                txb[:, 4] = tx_a
                tb = txb.reshape(-1)[:nbits]
                m = min(len(tb), len(rb))
                raw_err += int(np.count_nonzero(tb[:m] != rb[:m]))
                raw_tot += nbits
                am_err += int(np.count_nonzero(amp != tx_a))
                am_tot += len(tx_a)
                tbit_err += int(np.count_nonzero(
                    txb[:, :4].reshape(-1) != bits[:, :4].reshape(-1)))
            recovered = codec.decode_payload(rec, meta)
            cw_failed = codec.decode_payload.last_codewords_failed
            variants[f"{metric}_{ref}"] = {
                "raw_ber": raw_err / max(1, raw_tot),
                "tone_bit_ber": tbit_err / max(1, am_tot * 4),
                "am_bit_ber": am_err / max(1, am_tot),
                "cw_failed": cw_failed, "n_cw": meta["n_codewords"],
                "byte_exact": recovered == payload,
            }
    return {"level_db": level_db, "rs_k": rs_k, "seed": seed,
            "gross_bps": 5 * FS / 256, "net_bps": round(5 * FS / 256 * rs_k / RS_N, 1),
            "channel_s": round(ch_t, 1), "diag": diag, "variants": variants}


# ---------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true")
    ap.add_argument("--levels", nargs="+", type=float, default=[6.0, 8.0, 10.0])
    ap.add_argument("--seeds", nargs="+", type=int, default=[0, 1, 2])
    args = ap.parse_args()

    RESULTS.mkdir(exist_ok=True)
    payload = payload_slice()

    out = {"hypothesis": "H3 amplitude bit on WS_M16_K1_sp3_N256",
           "payload_offset": PAYLOAD_OFFSET, "payload_bytes": PAYLOAD_BYTES,
           "profile": "tape7", "aac": True,
           "baseline_net_bps": BASELINE_NET_BPS,
           "aac_alignment": sim_v2.test_aac_alignment()}

    def dump():
        OUT_JSON.write_text(json.dumps(out, indent=2, default=float))

    # ---- 0) no-channel sanity (EQ measured from the clean sounder ~ flat) ---
    print("=== SANITY (no channel), level 8 dB, rs191 ===", flush=True)
    s = run_h3_pass(payload, 8.0, 191, seed=-1, sanity=True)
    v = s["variants"]["con_global2m"]
    print(f"  sanity raw_ber={v['raw_ber']:.2e} tone={v['tone_bit_ber']:.2e} "
          f"am={v['am_bit_ber']:.2e} exact={v['byte_exact']}", flush=True)
    out["sanity"] = {"raw_ber": v["raw_ber"], "tone_bit_ber": v["tone_bit_ber"],
                     "am_bit_ber": v["am_bit_ber"], "byte_exact": v["byte_exact"]}
    dump()
    assert v["raw_ber"] < 1e-6 and v["byte_exact"], "SANITY FAILED — demod bug"

    if args.smoke:
        print("=== SMOKE: level 8 dB rs191 seed 0 ===", flush=True)
        r = run_h3_pass(payload, 8.0, 191, seed=0)
        print(json.dumps(r, indent=1, default=float), flush=True)
        out["smoke"] = r
        dump()
        return

    # ---- 1) CONTROL -------------------------------------------------------
    print("\n=== CONTROL WS_M16_K1_sp3_N256 @ RS(255,191), seeds {0,1} ===",
          flush=True)
    out["control"] = []
    for sd in (0, 1):
        c = run_control(payload, sd)
        print(f"  control seed{sd}: raw_ber={c['raw_ber']:.4f} "
              f"cw{c['cw_failed']}/{c['n_cw']} exact={c['byte_exact']} "
              f"({c['channel_s']}s channel)", flush=True)
        out["control"].append(c)
        dump()

    # ---- 2) H3 sweep @ rs191 ----------------------------------------------
    print("\n=== H3 SWEEP rs191: levels x seeds ===", flush=True)
    out["h3_rs191"] = []
    for lv in args.levels:
        for sd in args.seeds:
            r = run_h3_pass(payload, lv, 191, sd)
            d, vs = r["diag"], r["variants"]
            best = min(vs.items(), key=lambda kv: kv[1]["raw_ber"])
            print(f"  L{lv:g} seed{sd}: tone_symER={d['tone_sym_er']:.4f} "
                  f"(hi {d['tone_sym_er_hi_amp']:.4f} / lo {d['tone_sym_er_lo_amp']:.4f}) "
                  f"genieAM={d['genie_am_ber_con']:.4f} | best={best[0]} "
                  f"raw={best[1]['raw_ber']:.4f} am={best[1]['am_bit_ber']:.4f} "
                  f"cw{best[1]['cw_failed']}/{best[1]['n_cw']} "
                  f"exact={best[1]['byte_exact']}", flush=True)
            for k, vv in sorted(vs.items()):
                print(f"      {k:14s} raw={vv['raw_ber']:.4f} tone={vv['tone_bit_ber']:.4f} "
                      f"am={vv['am_bit_ber']:.4f} cw={vv['cw_failed']} "
                      f"exact={vv['byte_exact']}", flush=True)
            out["h3_rs191"].append(r)
            dump()

    # ---- 3) pick best fixed (level, variant) config at rs191; if it doesn't
    #         clear >=2/3 seeds, run rs159 at the best level ------------------
    def seeds_passed(rows, variant):
        return sum(1 for r in rows if r["variants"][variant]["byte_exact"])

    rows191 = out["h3_rs191"]
    cfgs = []
    for lv in args.levels:
        rows = [r for r in rows191 if r["level_db"] == lv]
        for variant in rows[0]["variants"]:
            np_ = seeds_passed(rows, variant)
            mean_raw = float(np.mean([r["variants"][variant]["raw_ber"] for r in rows]))
            cfgs.append({"level_db": lv, "rs_k": 191, "variant": variant,
                         "seeds_passed": np_, "n_seeds": len(rows),
                         "mean_raw_ber": mean_raw,
                         "net_bps": round(5 * FS / 256 * 191 / RS_N, 1)})
    cfgs.sort(key=lambda c: (-c["seeds_passed"], c["mean_raw_ber"]))
    out["rs191_config_ranking"] = cfgs[:10]
    best191 = cfgs[0]
    print(f"\n  best rs191 config: {best191}", flush=True)
    dump()

    if best191["seeds_passed"] < 2:
        # best level by mean am+tone raw BER across variants
        by_level = {}
        for lv in args.levels:
            rows = [r for r in rows191 if r["level_db"] == lv]
            best_v = min(rows[0]["variants"],
                         key=lambda v: float(np.mean(
                             [r["variants"][v]["raw_ber"] for r in rows])))
            by_level[lv] = float(np.mean(
                [r["variants"][best_v]["raw_ber"] for r in rows]))
        lv_best = min(by_level, key=by_level.get)
        print(f"\n=== H3 rs159 fallback at best level {lv_best:g} dB ===", flush=True)
        out["h3_rs159"] = []
        for sd in args.seeds:
            r = run_h3_pass(payload, lv_best, 159, sd)
            vs = r["variants"]
            best = min(vs.items(), key=lambda kv: kv[1]["raw_ber"])
            print(f"  L{lv_best:g} rs159 seed{sd}: best={best[0]} "
                  f"raw={best[1]['raw_ber']:.4f} am={best[1]['am_bit_ber']:.4f} "
                  f"cw{best[1]['cw_failed']}/{best[1]['n_cw']} "
                  f"exact={best[1]['byte_exact']}", flush=True)
            for k, vv in sorted(vs.items()):
                print(f"      {k:14s} raw={vv['raw_ber']:.4f} am={vv['am_bit_ber']:.4f} "
                      f"cw={vv['cw_failed']} exact={vv['byte_exact']}", flush=True)
            out["h3_rs159"].append(r)
            dump()
        rows159 = out["h3_rs159"]
        for variant in rows159[0]["variants"]:
            np_ = sum(1 for r in rows159 if r["variants"][variant]["byte_exact"])
            cfgs.append({"level_db": lv_best, "rs_k": 159, "variant": variant,
                         "seeds_passed": np_, "n_seeds": len(rows159),
                         "mean_raw_ber": float(np.mean(
                             [r["variants"][variant]["raw_ber"] for r in rows159])),
                         "net_bps": round(5 * FS / 256 * 159 / RS_N, 1)})

    # ---- 4) verdict ---------------------------------------------------------
    cfgs.sort(key=lambda c: (-(c["seeds_passed"] >= 2), -c["net_bps"],
                             -c["seeds_passed"], c["mean_raw_ber"]))
    winner = next((c for c in cfgs if c["seeds_passed"] >= 2
                   and c["net_bps"] > BASELINE_NET_BPS), None)
    partial = next((c for c in cfgs if c["seeds_passed"] >= 1
                    and c["net_bps"] > BASELINE_NET_BPS), None)
    best_am = min(
        (r["variants"][v]["am_bit_ber"]
         for r in rows191 for v in r["variants"]), default=1.0)
    if winner:
        verdict = "PASS"
    elif partial or best_am < 0.01:
        verdict = "PARTIAL"
    else:
        verdict = "FAIL"
    out["config_ranking"] = cfgs[:12]
    out["winner"] = winner
    out["best_am_bit_ber_rs191"] = best_am
    out["verdict"] = verdict
    dump()
    print(f"\nVERDICT: {verdict}  winner={winner}  best_am_ber={best_am:.4f}",
          flush=True)
    print(f"[h3] wrote {OUT_JSON}", flush=True)


if __name__ == "__main__":
    main()
