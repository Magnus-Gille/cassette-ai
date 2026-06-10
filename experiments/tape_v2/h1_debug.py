"""h1_debug.py — diagnose why the h1 harness control (WS_M16_K1_sp3_N256 @
RS(255,191), sim_v2 channel) shows raw BER 0.114 instead of the expected ~0.034.

Caches the channeled section (results/h1_debug_ctrl_seed0.npy) so decode
variants can be iterated cheaply. Diagnostics:
  1. per-frame raw BER (drift / window problem -> rises with frame index)
  2. per-symbol-index error profile within frames (tracker losing lock?)
  3. per-tone confusion (true tone -> detected tone; EQ tilt problem?)
  4. EQ variants: params-EQ (harness), flat EQ, oracle-measured EQ from the
     channeled audio itself (sounder-style, like m7_decode does)
  5. aac on/off and v1-conditions reference (rs_closure-style raw BER)
"""
from __future__ import annotations

import json
import pathlib
import sys

import numpy as np

_HERE = pathlib.Path(__file__).resolve().parent
ROOT = pathlib.Path("/Users/magnus/repos/cassette-ai")
for _p in (ROOT / "src", _HERE):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import hyp_common as hc                      # noqa: E402
import real_channel_sim as rcs               # noqa: E402
import sim_v2                                # noqa: E402
import m3_codec as codec                     # noqa: E402
from m3_codec import Rung                    # noqa: E402
from assault_widespace import (              # noqa: E402
    build as ws_build, eq_for, _energies_at, _score, _sym_from_score,
)
from h1_m16k2_sp3 import build_section, FS, PAD_S, FRAME_BYTES, RS_N  # noqa: E402

CASS = ROOT / "experiments" / "dpd" / "cassette_llm" / "stories260K_int4.cass"
RESULTS = _HERE / "results"
TRACK = 15


def demod_frame_diag(ws, eq, y_frame, nsym):
    """achievable tracker; returns (bits, syms, locks, offsets)."""
    N, bps = ws.N, ws.bits_per_sym
    tone_bins = np.clip(ws._bin_indices, 0, N // 2)
    guard_bins = ws._guard_bins
    ds = hc.find_preamble(y_frame.astype(np.float32), ws.preamble_seconds)
    yy = y_frame.astype(np.float64)
    drift = 0.0
    bits_out, syms, offs = [], [], []
    for sidx in range(nsym):
        base = ds + sidx * N + int(round(drift))
        best = None
        for d in range(-TRACK, TRACK + 1):
            et, eg = _energies_at(yy, base + d, N, tone_bins, guard_bins)
            if et is None:
                continue
            sc = _score(et, eg, eq, "contrast")
            si = _sym_from_score(ws, sc)
            srt = np.sort(sc)[::-1]
            lock = (srt[ws.K - 1] - srt[ws.K]) / (abs(srt[0]) + 1e-9)
            if best is None or lock > best[0]:
                best = (lock, si, d)
        if best is None:
            bits_out.extend([0] * bps); syms.append(0); offs.append(0); continue
        bits_out.extend(ws._sym_to_bits(best[1]))
        syms.append(best[1]); offs.append(best[2])
        drift += best[2]
    return np.array(bits_out, np.uint8), syms, offs, ds


def decode_section(ws, eq, y, tx_frames, starts, label):
    pad = int(PAD_S * FS)
    pre = len(ws._preamble)
    N, bps = ws.N, ws.bits_per_sym
    per_frame = []
    tone_conf = np.zeros((ws.M, ws.M), int)  # K=1 only: true tone -> detected
    nseg = 8
    seg_err = np.zeros(nseg); seg_tot = np.zeros(nseg)
    raw_err = raw_tot = 0
    for fi, tb in enumerate(tx_frames):
        nbits = len(tb)
        nsym = int(np.ceil(nbits / bps))
        flen = pre + nsym * N
        st = starts[fi]
        w_lo = max(0, st - pad); w_hi = min(len(y), st + flen + pad)
        rb, syms, offs, ds = demod_frame_diag(ws, eq, y[w_lo:w_hi], nsym)
        m = min(len(tb), len(rb))
        fe = int(np.count_nonzero(tb[:m] != rb[:m])) + (len(tb) - m)
        raw_err += fe; raw_tot += len(tb)
        per_frame.append(round(fe / len(tb), 4))
        # truth syms
        tbits = tb
        padb = (-len(tbits)) % bps
        if padb:
            tbits = np.concatenate([tbits, np.zeros(padb, np.uint8)])
        nerr_sym = 0
        for sidx in range(nsym):
            ts = ws._bits_to_sym(tbits[sidx * bps:(sidx + 1) * bps])
            dsym = syms[sidx]
            seg = min(nseg - 1, sidx * nseg // nsym)
            seg_tot[seg] += 1
            if dsym != ts:
                seg_err[seg] += 1; nerr_sym += 1
            if ws.K == 1:
                tone_conf[ws._table[ts][0], ws._table[dsym][0]] += 1
    ber = raw_err / max(1, raw_tot)
    print(f"\n[{label}] raw BER = {ber:.4f}")
    print(f"  per-frame BER: {per_frame}")
    with np.errstate(invalid="ignore"):
        prof = np.where(seg_tot > 0, seg_err / np.maximum(seg_tot, 1), 0)
    print(f"  sym-err by position-in-frame (8 segs): "
          + " ".join(f"{p:.3f}" for p in prof))
    if ws.K == 1:
        tot = tone_conf.sum(axis=1)
        err = tot - np.diag(tone_conf)
        with np.errstate(invalid="ignore", divide="ignore"):
            per_tone = np.where(tot > 0, err / np.maximum(tot, 1), 0)
        print("  per-tone sym-err: "
              + " ".join(f"{i}:{p:.3f}" for i, p in enumerate(per_tone)))
        # top confusion pairs
        cm = tone_conf.copy(); np.fill_diagonal(cm, 0)
        flat = np.argsort(cm.ravel())[::-1][:8]
        pairs = [(int(f // ws.M), int(f % ws.M), int(cm.ravel()[f]))
                 for f in flat if cm.ravel()[f] > 0]
        print(f"  top confusions (true->det,count): {pairs}")
    return ber


def oracle_eq(ws, y, tx_frames, starts):
    """Sounder-style EQ measured from the channeled audio itself: average
    detected energy of each tone when it is TRULY lit (genie timing at nominal
    starts). Mirrors what m7_decode gets from the sounder section."""
    N, bps = ws.N, ws.bits_per_sym
    pre = len(ws._preamble)
    tone_bins = np.clip(ws._bin_indices, 0, N // 2)
    acc = np.zeros(ws.M); cnt = np.zeros(ws.M)
    for fi, tb in list(enumerate(tx_frames))[:4]:
        tbits = tb
        padb = (-len(tbits)) % bps
        if padb:
            tbits = np.concatenate([tbits, np.zeros(padb, np.uint8)])
        nsym = len(tbits) // bps
        st = starts[fi] + pre
        for sidx in range(nsym):
            ts = ws._bits_to_sym(tbits[sidx * bps:(sidx + 1) * bps])
            et, _ = _energies_at(y.astype(np.float64), st + sidx * N, N,
                                 tone_bins, ws._guard_bins)
            if et is None:
                continue
            for ti in ws._table[ts]:
                acc[ti] += et[ti]; cnt[ti] += 1
    g = acc / np.maximum(cnt, 1)
    g = g / (g.max() + 1e-12)
    return np.clip(g, 0.05, None)


def main():
    full = CASS.read_bytes()
    payload = full[16384:16384 + 8192]
    ws = ws_build(16, 1, 3, 256)
    rung = Rung(name="dbg", M=16, K=1, rs_n=RS_N, rs_k=191,
                frame_bytes=FRAME_BYTES)
    tx_frames, meta = codec.encode_payload(payload, rung)
    section, starts = build_section(ws, tx_frames)
    print(f"section {len(section)/FS:.1f}s, {meta['n_frames']} frames")

    cache = RESULTS / "h1_debug_ctrl_seed0.npy"
    if cache.exists():
        y = np.load(cache)
        print("loaded cached channeled section")
    else:
        y = sim_v2.channel_v2(section.astype(np.float64), profile="tape7",
                              aac=True, seed_offset=0).astype(np.float32)
        np.save(cache, y)
        print("channeled + cached")

    params = rcs.load_params()
    eq_p = eq_for(ws, params, "master3")
    print(f"params-EQ: {np.round(eq_p, 3).tolist()}")
    decode_section(ws, eq_p, y, tx_frames, starts, "params-EQ (harness)")

    eq_flat = np.ones(ws.M)
    decode_section(ws, eq_flat, y, tx_frames, starts, "flat-EQ")

    eq_o = oracle_eq(ws, y, tx_frames, starts)
    print(f"oracle-EQ: {np.round(eq_o, 3).tolist()}")
    decode_section(ws, eq_o, y, tx_frames, starts, "oracle-EQ (sounder-style)")

    # no-AAC reference at same profile
    cache2 = RESULTS / "h1_debug_ctrl_seed0_noaac.npy"
    if cache2.exists():
        y2 = np.load(cache2)
    else:
        y2 = sim_v2.channel_v2(section.astype(np.float64), profile="tape7",
                               aac=False, seed_offset=0).astype(np.float32)
        np.save(cache2, y2)
    decode_section(ws, eq_o, y2, tx_frames, starts, "oracle-EQ, aac=False")


if __name__ == "__main__":
    main()
