"""x10_c_margin_erasure.py -- BET C: constellation-margin-aware RS erasure
decoding, validated on REAL capture tape9_run1.wav (RX-only).

Premise (measured, x10_c_evm_probe + m9 results): on the N256 rungs the 750 Hz
carrier runs ~40% SER and its quadrants touch ~4/10 of all stream bytes, i.e.
~39 bad bytes per RS(255,179) codeword -- right AT the t=38 errors-only limit.
That is why m5 sat at 2 failed codewords (2632 net bps) and m7 at 5 (2896).
RS errors-and-erasures corrects E+2T <= n-k = 76, so flagging most true errors
as erasures (worth 1 instead of 2) buys back the budget -- IF the reliability
signal is at the right granularity. m9's erasure sweep used a frame-level dtau
proxy (useless; monotonically hurt). Here the signal is per-BYTE: the worst
post-refine constellation margin (45deg - |residual|) over the byte's 4
quadrant symbols, from the same soft demod that produced the bits.

Per failed codeword, a CRC32-guarded retry ladder (errors-only -> rank-based
erasure counts -> margin-threshold erasures) accepts the FIRST decode whose
CRC32 matches the manifest -- per-codeword adaptive, miscorrection-guarded
(false accept ~ n_tries * 2^-32). Same legality as m9's CRC-verified sweep.

Arms per section: diff (proven decision path) and dfdd_g0.5 (x10_c_vv_coherent's
decision-feedback differential, which halved m7's failures).

Output: results/x10_c_margin_erasure.json
Usage:
    OPENBLAS_NUM_THREADS=2 OMP_NUM_THREADS=2 python3 \
        experiments/tape_v2/x10_c_margin_erasure.py [capture.wav]
"""
from __future__ import annotations

import json
import pathlib
import sys
import zlib
from fractions import Fraction

import numpy as np
import soundfile as sf
from scipy.signal import resample_poly

_HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))

import m9_decode as m9d                      # noqa: E402
import m3_codec as codec                     # noqa: E402
from h4_dqpsk import FS, PAD_LO_S, PAD_HI_S  # noqa: E402
import hyp_common as hc                      # noqa: E402

am2 = m9d.am2
SR = codec.FS

TARGETS = {                       # section -> EMA alpha (tape9 winner)
    "m9_m4_n256_rs159": 0.6,
    "m9_m5_n256_rs179": 0.6,
    "m9_m6_n256_rs191": 0.6,
    "m9_m7_n256_p11_9000": 0.5,
    "m9_m8_dense375": 0.5,        # regression guard: must stay exact
}
RANK_LADDER = (8, 16, 24, 32, 40, 48, 56, 64, 70)   # erase E worst bytes
THR_LADDER_DEG = (25.0, 20.0, 15.0, 10.0, 6.0)       # erase margin < thr


def _wrap(x):
    return (x + np.pi) % (2 * np.pi) - np.pi


def _ema_demod_soft(sch, y, nd, alpha):
    """h4 EMA-integer-drift loop (mirrors x9 _demod_ema); returns c, dtau."""
    y = np.asarray(y, np.float64)
    ds = hc.find_preamble(y.astype(np.float32), sch.preamble_seconds)
    total = nd + 1
    N, skip, Nw = sch.N, sch.skip, sch.Nw
    fpil = sch.freqs[sch.pilot_idx]
    freqs = sch.freqs
    win = sch._win
    c = np.zeros((total, sch.P + 1), np.complex128)
    dtau = np.zeros(total)
    drift = 0.0
    sm = 0.0
    for i in range(total):
        base = ds + i * N + int(round(drift))
        lo = base + skip
        seg = y[lo: lo + Nw]
        if len(seg) < Nw:
            seg = np.concatenate([seg, np.zeros(Nw - len(seg))])
        tt = (lo + np.arange(Nw)) / FS
        E = np.exp(-2j * np.pi * np.outer(freqs, tt))
        c[i] = E @ (seg * win)
        if i > 0:
            dp = float(np.angle(c[i, sch.pilot_idx] * np.conj(c[i - 1, sch.pilot_idx])))
            sm = (1 - alpha) * (dp / (2 * np.pi * fpil)) + alpha * sm
            dtau[i] = sm
            drift -= dtau[i] * FS
            drift = float(np.clip(drift, -200, 200))
    return c, dtau


def _diff_decide_soft(sch, c, dtau):
    """Differential decision (mirror of _decide, refine=True) returning bits
    AND per-quadrant |residual| (rad) at the final decision."""
    fd = sch.freqs[sch.data_idx]
    d = c[1:, :] * np.conj(c[:-1, :])
    dphi = np.angle(d[:, sch.data_idx]) - 2 * np.pi * np.outer(dtau[1:], fd)
    q = np.round(dphi / (np.pi / 2.0)).astype(int) % 4
    res = _wrap(dphi - q * (np.pi / 2.0))
    dtau_res = (res * fd[None, :]).sum(axis=1) / (2 * np.pi * (fd ** 2).sum())
    dphi2 = dphi - 2 * np.pi * dtau_res[:, None] * fd[None, :]
    q = np.round(dphi2 / (np.pi / 2.0)).astype(int) % 4
    resid = np.abs(_wrap(dphi2 - q * (np.pi / 2.0)))
    return sch.quadrants_to_bits(q), resid


def _dfdd_decide_soft(sch, c, dtau, gamma=0.5):
    """DFDD (x10_c_vv_coherent) returning bits + per-quadrant |residual|."""
    fd = sch.freqs[sch.data_idx]
    cd = c[:, sch.data_idx]
    total, P = cd.shape
    dphi = np.zeros((total - 1, P))
    for j in range(P):
        rot_t = np.exp(2j * np.pi * fd[j] * dtau)
        R = cd[0, j]
        for i in range(1, total):
            Rp = R * rot_t[i]
            dp = float(np.angle(cd[i, j] * np.conj(Rp)))
            qd = int(np.round(dp / (np.pi / 2.0))) % 4
            dphi[i - 1, j] = dp
            R = (1.0 - gamma) * cd[i, j] + gamma * Rp * np.exp(1j * qd * np.pi / 2.0)
    q = np.round(dphi / (np.pi / 2.0)).astype(int) % 4
    res = _wrap(dphi - q * (np.pi / 2.0))
    dtau_res = (res * fd[None, :]).sum(axis=1) / (2 * np.pi * (fd ** 2).sum())
    dphi2 = dphi - 2 * np.pi * dtau_res[:, None] * fd[None, :]
    q = np.round(dphi2 / (np.pi / 2.0)).astype(int) % 4
    resid = np.abs(_wrap(dphi2 - q * (np.pi / 2.0)))
    return sch.quadrants_to_bits(q), resid


def _byte_margins(frame_resids, meta, P):
    """Per-stream-byte margin (rad): pi/4 - max|residual| over the byte's 4
    quadrants. Mirrors the bit/byte layout of _rs_merge_guarded: stream bits =
    concat of frame bit-streams; bit p of a frame -> quadrant p//2 of its
    flattened (nd,P) decision matrix."""
    fb_bits = meta["frame_bits"]
    n_frames = meta["n_frames"]
    stream_bits = meta["stream_bits"]
    n_bytes = meta["rs_n"] * meta["n_codewords"]
    # flatten residuals to the stream-quadrant domain
    qres = []
    for fi in range(n_frames):
        nominal = fb_bits if fi < n_frames - 1 else (stream_bits - fb_bits * (n_frames - 1))
        r = frame_resids[fi].ravel() if fi < len(frame_resids) else \
            np.full(nominal // 2, np.pi)
        need = nominal // 2
        if len(r) < need:
            r = np.concatenate([r, np.full(need - len(r), np.pi)])
        qres.append(r[:need])
    qres = np.concatenate(qres)               # (stream_bits/2,)
    nq = stream_bits // 2
    if len(qres) < nq:
        qres = np.concatenate([qres, np.full(nq - len(qres), np.pi)])
    # byte b covers bits 8b..8b+7 -> quadrants 4b..4b+3
    worst = qres[: (nq // 4) * 4].reshape(-1, 4).max(axis=1)
    worst = worst[:n_bytes]
    if len(worst) < n_bytes:
        worst = np.concatenate([worst, np.full(n_bytes - len(worst), np.pi)])
    return (np.pi / 4.0) - worst               # margin: lower = less reliable


def _merge_margin_erasure(rx_frames, frame_resids, meta, crc_table, P):
    """CRC32-guarded per-codeword retry ladder with margin-ranked erasures."""
    from reedsolo import RSCodec, ReedSolomonError
    rs_n, rs_k = meta["rs_n"], meta["rs_k"]
    n_cw = meta["n_codewords"]
    twot = rs_n - rs_k
    fb_bits = meta["frame_bits"]
    n_frames = meta["n_frames"]
    stream_bits = meta["stream_bits"]

    pieces = []
    for fi in range(n_frames):
        nominal = fb_bits if fi < n_frames - 1 else (stream_bits - fb_bits * (n_frames - 1))
        rb = (np.asarray(rx_frames[fi], np.uint8).ravel()
              if fi < len(rx_frames) else np.zeros(nominal, np.uint8))
        if len(rb) < nominal:
            rb = np.concatenate([rb, np.zeros(nominal - len(rb), np.uint8)])
        pieces.append(rb[:nominal])
    rx_bits = np.concatenate(pieces)[:stream_bits]
    rx_bytes = np.packbits(rx_bits)[:n_cw * rs_n]
    rx_mat = rx_bytes.reshape(rs_n, n_cw).T

    margins = _byte_margins(frame_resids, meta, P)       # (n_cw*rs_n,)
    # rel_cw[i, j] = margin of stream byte j*n_cw + i
    rel = margins[: n_cw * rs_n].reshape(rs_n, n_cw).T   # (n_cw, rs_n)

    rsc = RSCodec(twot)
    recovered = bytearray()
    cw_failed = 0
    ladder_used = []
    for i in range(n_cw):
        row = bytes(rx_mat[i].tobytes())
        order = np.argsort(rel[i])                        # worst margin first
        ok_msg = None
        used = None
        # ladder: errors-only, then rank erasures, then threshold erasures
        trials = [("errors_only", [])]
        for E in RANK_LADDER:
            if E <= twot - 2:
                trials.append((f"rank{E}", [int(j) for j in order[:E]]))
        for thr in THR_LADDER_DEG:
            # erase bytes whose margin (45deg - worst |residual|) < thr degrees
            sel = sorted(int(j) for j in np.where(rel[i] < np.radians(thr))[0])
            if 0 < len(sel) <= twot - 2:
                trials.append((f"thr{thr:g}", sel))
        for name, epos in trials:
            try:
                dec = (rsc.decode(bytearray(row), erase_pos=epos)[0]
                       if epos else rsc.decode(bytearray(row))[0])
            except (ReedSolomonError, Exception):
                continue
            msg = bytes(dec)
            if i < len(crc_table) and (zlib.crc32(msg) & 0xFFFFFFFF) == crc_table[i]:
                ok_msg = msg
                used = name
                break
        if ok_msg is None:
            cw_failed += 1
            recovered += bytes(rs_k)
            ladder_used.append("FAIL")
        else:
            recovered += ok_msg
            ladder_used.append(used)
    out = bytes(recovered)[:meta["payload_len"]]
    return out, cw_failed, ladder_used


def run_section(audio_nom, sec, align, alpha):
    sch = m9d._scheme_from_entry(sec)
    meta = sec["meta"]
    crc_table = sec["crc32_codewords"]
    expected_packed = (_HERE / sec["payload_sidecar"]).read_bytes()
    nom_bits = m9d._nominal_frame_bits(meta)
    pad_lo, pad_hi = int(PAD_LO_S * SR), int(PAD_HI_S * SR)
    flen_full = len(np.asarray(sch.modulate(np.zeros(meta["frame_bits"], np.uint8))))

    soft = []
    for fi, st in enumerate(sec["frame_starts"]):
        nd = sch.nsym_data(nom_bits[fi])
        st = int(st) + align
        y = np.asarray(audio_nom[max(0, st - pad_lo):
                                 min(len(audio_nom), st + flen_full + pad_hi)],
                       np.float64)
        soft.append(_ema_demod_soft(sch, y, nd, alpha))

    rows = []
    best = None
    for arm, decider in (("diff", _diff_decide_soft), ("dfdd_g0.5", _dfdd_decide_soft)):
        rx_frames, resids = [], []
        for (c, dtau) in soft:
            bits, resid = decider(sch, c, dtau)
            rx_frames.append(np.asarray(bits, np.uint8))
            resids.append(resid)
        out, cwf, ladder = _merge_margin_erasure(rx_frames, resids, meta,
                                                 crc_table, sch.P)
        exact = out == expected_packed
        byte_err = sum(a != b for a, b in zip(out, expected_packed)) + abs(
            len(out) - len(expected_packed))
        from collections import Counter
        lc = dict(Counter(ladder))
        row = {"arm": arm, "byte_exact": bool(exact), "cw_failed": int(cwf),
               "byte_errors": int(byte_err), "ladder_counts": lc}
        rows.append(row)
        print(f"  {sec['name']:22s} {arm:9s} exact={exact} cwf={cwf} "
              f"be={byte_err} ladder={lc}")
        if best is None or (row["byte_exact"], -row["cw_failed"]) > \
                (best["byte_exact"], -best["cw_failed"]):
            best = row
        if exact:
            break
    return {"section": sec["name"], "phy": sec["phy"], "alpha": alpha,
            "net_bps": sec.get("projected_net_bps"), "arms": rows,
            "best_exact": best["byte_exact"], "best_cwf": best["cw_failed"]}


def main():
    cap = sys.argv[1] if len(sys.argv) > 1 else str(
        _HERE / "captures" / "tape9_run1.wav")
    manifest = json.loads(m9d.MANIFEST_PATH.read_text())
    audio, sr = sf.read(cap, dtype="float32", always_2d=False)
    if audio.ndim > 1:
        audio = audio.mean(axis=1)
    if sr != SR:
        frac = Fraction(SR, sr).limit_denominator(20000)
        audio = resample_poly(audio.astype(np.float64), frac.numerator, frac.denominator)
    sync = am2.global_sync_and_resample(audio, manifest)
    audio_nom = sync["audio_nominal"]
    align = sync["chirp0_nominal"] - manifest["tx_chirp0"]

    out = {"capture": cap, "rank_ladder": list(RANK_LADDER),
           "thr_ladder_deg": list(THR_LADDER_DEG), "sections": []}
    for sec in manifest["ws_payloads"]:
        if sec["name"] in TARGETS and not sec.get("skipped"):
            out["sections"].append(
                run_section(audio_nom, sec, align, TARGETS[sec["name"]]))

    rp = _HERE / "results" / "x10_c_margin_erasure.json"
    rp.write_text(json.dumps(out, indent=2, default=float))
    print(f"[x10_c_margin_erasure] wrote {rp}")


if __name__ == "__main__":
    main()
