"""x10_a_underwater_pfft_adaptive.py -- X10 candidate #4: A-underwater-pfft-adaptive.

Partial-FFT demodulation with adaptive per-carrier segment weights
(differential-OFDM eigen/MVDR variant, UWA partial-FFT lineage:
Yerramalli/Stojanovic/Mitra TSP 2012; Han et al. differential-OFDM).

Per X10_PLAN.md candidate #4 (frozen 2026-06-11). Receiver-only; validates on
the REAL captures/tape9_run1.wav (gold evidence). No frozen file is modified;
all production demod machinery is imported (h4_dqpsk, x9_resampling_pll,
m9_decode, analyze_master2) and replicated read-only where instrumentation is
needed (the proven x10_forensics_errors.py pattern: replicas verified
bit-exact against production decisions per frame).

MECHANISM
---------
The production demod computes, per symbol, one Hann-windowed DFT over the
Nw-sample analysis window. Here that DFT is split into Q contiguous partial
sums per carrier (shape (nsym, nc, Q)); summing over Q at uniform weights
reproduces the production value exactly (HARD PRECONDITION, verified per
frame against the unmodified ResamplingPLLDemod decisions). Per-carrier
complex weights w (pilot stays uniform; timing trajectories untouched) then
re-combine the segments: y_i = w^H z_i. For carriers whose early window
segments are contaminated by previous-symbol acoustic-echo ISI (the measured
dc0/750 Hz killer at N256, x10_forensics_errors.json), the weights can
de-emphasize/cancel the contaminated segments -- a strict superset of window
placement (late-window) that can also synthesize cancellation, not just
avoidance.

PRE-REGISTERED OPERATIONALIZATION (frozen BEFORE any decode of this file)
-------------------------------------------------------------------------
Grid (per plan): Q in {2, 4}; front-ends {resampling_pll(bw30), ema0.6,
ema0.7}; adaptation modes {block, slide64} -> 12 pfft branches per section.
Segment edges: round(q*Nw/Q), q=0..Q (Q=2 edges are a subset of Q=4 edges).

STEP 1 diagnostic (decides solver investment, KILL gate): per-segment
single-segment decisions on the failed m4/m5 sections (winner fe ema0.6,
Q=4): genie-scored dc0 SER and genie phase-error RMS per segment.
KILL if NO early-segment excess: ratio ser(seg0)/ser(seg_last) <= 1.1 on
both m4 and m5 (scoring only; truth never feeds decisions).

STEP 2 weight solver (decision-directed, truth-free):
  block mode: per audio frame, n_iter=3 fixed iterations. Iteration:
    decisions q + front-end dtau + DD residual define the expected rotation
    rot_i = exp(j(q_i*pi/2 + 2*pi*(dtau_i+dd_i)*f_c)); difference-error
    vectors e_i = z_i - rot_i*z_{i-1}; R = mean(e e^H) + 5e-3*tr(R)/Q*I
    (the decision-error covariance; its inverse applied to the clean-signal
    steering vector g_q = sum of Hann window mass in segment q is the
    MVDR/min-eigen-direction weight w = R^{-1} g, scaled so w^H g =
    sum(g) > 0 real, which pins the combined-signal phase = uniform's and
    makes weights phase-consistent). Pilot carrier: w = uniform always.
    After the iterations, a per-carrier TRUTH-FREE revert: carriers whose
    decision-EVM (RMS angular residual to the decided centroid) did not
    improve vs uniform are reverted to uniform weights (never-worse on the
    visible metric; same statistic family the late-window plan
    pre-registered).
  slide64 mode: one sweep, seeded from the block solution (weights AND
    decisions). Sliding centered window of 64 symbols, hop 16; QUALITY
    GATING per plan: a hop's update is FROZEN (previous weights held) when
    the local truth-free low-quality fraction (|residual| > 30 deg) exceeds
    0.10. Same final per-carrier revert-to-uniform selector.
  NOTE (stated deviation): the plan says weights are "seeded from
  h4_dqpsk.measure_sounder_eq spans"; segment-domain weights have no direct
  frequency-domain seed, so adaptation is seeded from uniform-weight
  decisions instead (and slide64 from the block solution). Logged as a
  deviation, not a gate change.

BASELINE (stated deviation, sequencing): the plan sequences this candidate
AFTER x10_late_window; its results file is absent at execution time, so the
union+late-window baseline is SELF-COMPUTED here per the late-window plan's
own pre-registered search space -- scalar dc0 late-shift S in {16,24,32,40}
(carriers 1..P center) plus the decoupled-argmin stitched vector (dc0 shift
in {0,8,16,24,32,40}, others in {-8,0,8}, per-carrier argmin of truth-free
decision-EVM), each under the same 3 front-ends => 15 late-window branches.
A STRONGER baseline only makes this candidate's PASS harder (honest
direction). If results/x10_late_window_tape9_run1.json exists at evaluation
time its failed-sets are unioned into the baseline too.

GATE (verbatim from X10_PLAN.md, operationalized):
  PRECONDITION: uniform weights reproduce the production demod bit-exactly
    (per-frame quadrant equality vs unmodified ResamplingPLLDemod, all
    sections x fes).
  KILL: step-1 shows no early-segment error excess at dc0 (definition above).
  PASS (landed): >= 1 additional CRC-verified codeword on m6 or m7 vs the
    union(probe-6-frontend bank)+late-window baseline.
  DIAGNOSTIC PASS: best-pfft pooled dc0 SER (over m4/m5/m6/m7, genie-scored)
    <= best-late-window pooled dc0 SER / 1.5, with zero additional codewords.
  Both tiers: 0 regressions on the full named 4-capture suite,
    miscorrected_cw = 0 post-hoc vs manifest truth on all 4 captures, CRC
    acceptance trial count logged (campaign budget < 4e5 trials).

Trials ledger: every (branch x codeword) RS-decode-then-CRC-check attempt
counts as one CRC-acceptance trial; totals logged in the results JSON for
the campaign ledger.

Deterministic (no RNG anywhere). Seeds: N/A. numpy/scipy versions logged.

Usage (each invocation << 8 min, checkpoints results/x10_pfft_tape9_run1.json):
    python3 x10_a_underwater_pfft_adaptive.py step1
    python3 x10_a_underwater_pfft_adaptive.py adapt   --section m9_m5_n256_rs179
    python3 x10_a_underwater_pfft_adaptive.py latewin --section m9_m6_n256_rs191
    python3 x10_a_underwater_pfft_adaptive.py evaluate
    python3 x10_a_underwater_pfft_adaptive.py regress_tape9
    python3 x10_a_underwater_pfft_adaptive.py regress_m8
    python3 x10_a_underwater_pfft_adaptive.py regress_ws
    python3 x10_a_underwater_pfft_adaptive.py summarize
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys
import time
import zlib
from fractions import Fraction

import numpy as np
import soundfile as sf

np.seterr(divide="ignore", over="ignore", invalid="ignore")

_HERE = pathlib.Path(__file__).resolve().parent
ROOT = pathlib.Path("/Users/magnus/repos/cassette-ai")
for _p in (ROOT / "src", ROOT / "tests" / "e2e", ROOT / "experiments" / "deepdive2",
           ROOT / "experiments" / "capacity", _HERE):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import analyze_master2 as am2                        # noqa: E402
import m3_codec as codec                             # noqa: E402
from m3_codec import Rung                            # noqa: E402
from h4_dqpsk import FS, PAD_LO_S, PAD_HI_S          # noqa: E402
import m9_decode as m9d                              # noqa: E402
from x9_resampling_pll import (ResamplingPLLDemod,   # noqa: E402
                               _pi_loop_gains)
import hyp_common as hc                              # noqa: E402
from reedsolo import RSCodec, ReedSolomonError       # noqa: E402

SR = codec.FS
CAPTURE = _HERE / "captures" / "tape9_run1.wav"
CACHE_NPY = _HERE / "captures" / "x10_audio_nom_tape9_run1.npy"   # forensics cache
SYNC_JSON = _HERE / "results" / "x10_forensics_sync.json"
OUT_JSON = _HERE / "results" / "x10_pfft_tape9_run1.json"
REGRESS_JSON = _HERE / "results" / "x10_pfft_regression_4captures.json"
MANIFEST = json.loads((_HERE / "master9_manifest.json").read_text())
LATEWIN_RESULTS = _HERE / "results" / "x10_late_window_tape9_run1.json"

# --- pre-registered grids (see docstring) ----------------------------------
PFFT_FES = ("resampling_pll", "ema0.6", "ema0.7")
PFFT_QS = (4, 2)
PFFT_MODES = ("block", "slide64")
LW_SCALAR_S = (16, 24, 32, 40)
LW_ALL_SHIFTS = (-8, 0, 8, 16, 24, 32, 40)
LW_DC0_SET = (0, 8, 16, 24, 32, 40)
LW_OTHER_SET = (-8, 0, 8)
N_ITER_BLOCK = 3
DIAG_LOAD = 5e-3
SLIDE_WIN = 64
SLIDE_HOP = 16
LOWQ_DEG = 30.0
FREEZE_FRAC = 0.10
KILL_RATIO = 1.1          # ser(seg0)/ser(seg_last) <= this on m4 AND m5 -> KILL

FRONTIER = ("m9_m4_n256_rs159", "m9_m5_n256_rs179",
            "m9_m6_n256_rs191", "m9_m7_n256_p11_9000")
GATE_SECTIONS = ("m9_m6_n256_rs191", "m9_m7_n256_p11_9000")
# the existing validated 6-frontend union bank (x10_union_probe)
PROBE6 = (("resampling_pll30", dict(front_end="pll", pll_bw_hz=30.0)),
          ("ema0.5", dict(front_end="ema", ema_alpha=0.5)),
          ("ema0.6", dict(front_end="ema", ema_alpha=0.6)),
          ("ema0.65", dict(front_end="ema", ema_alpha=0.65)),
          ("ema0.7", dict(front_end="ema", ema_alpha=0.7)),
          ("ema0.8", dict(front_end="ema", ema_alpha=0.8)))
TAPE9_LANDED = ("m9_m0_reprove934", "m9_m1_thin159", "m9_m2_thin191",
                "m9_m3_dropnull9c", "m9_m4b_n256_rs159_var", "m9_m8_dense375")
TAPE9_BANKED = ("m9_m4_n256_rs159", "m9_m5_n256_rs179")


# ===========================================================================
# shared helpers
# ===========================================================================
def _load_nominal():
    audio_nom = np.load(CACHE_NPY, mmap_mode="r")
    sync = json.loads(SYNC_JSON.read_text())
    return audio_nom, sync


def _get_section(name, manifest=None):
    for sec in (manifest or MANIFEST)["ws_payloads"]:
        if sec["name"] == name:
            return sec
    raise KeyError(name)


def _ckpt_load(path, init):
    return json.loads(path.read_text()) if path.exists() else dict(init)


def _ckpt_save(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=1, default=float))


def _seg_edges(Nw, Q):
    return [int(round(q * Nw / Q)) for q in range(Q + 1)]


def _make_prod_frontend(sch, fe_name):
    """The UNMODIFIED production front-end (reference for the precondition)."""
    if fe_name in ("resampling_pll", "resampling_pll30"):
        return ResamplingPLLDemod(sch, pll_bw_hz=30.0, front_end="pll")
    if fe_name.startswith("ema"):
        return ResamplingPLLDemod(sch, front_end="ema", ema_alpha=float(fe_name[3:]))
    raise ValueError(fe_name)


def _decide_refine(sch, c_carriers, dtau_total, refine=True):
    """Replica of x9_resampling_pll._decide returning soft outputs.
    (verified pattern: x10_forensics_errors q_mismatch == 0 everywhere)."""
    fd = sch.freqs[sch.data_idx]
    d = c_carriers[1:, :] * np.conj(c_carriers[:-1, :])
    dphi = np.angle(d[:, sch.data_idx]) - 2 * np.pi * np.outer(dtau_total[1:], fd)
    q = np.round(dphi / (np.pi / 2.0)).astype(int) % 4
    nd = dphi.shape[0]
    dtau_dd = np.zeros(nd)
    if refine:
        res = (dphi - q * (np.pi / 2.0) + np.pi) % (2 * np.pi) - np.pi
        num = (res * fd[None, :]).sum(axis=1)
        den = (fd ** 2).sum()
        dtau_dd = num / (2 * np.pi * den)
        dphi = dphi - 2 * np.pi * dtau_dd[:, None] * fd[None, :]
        q = np.round(dphi / (np.pi / 2.0)).astype(int) % 4
    res_final = (dphi - q * (np.pi / 2.0) + np.pi) % (2 * np.pi) - np.pi
    return q, dphi, res_final, dtau_dd


# ===========================================================================
# segmented DFT passes -- replicas of the production loops (tracking driven
# by the FULL-window DFT, computed with the identical op order), with the Q
# partial sums as additional outputs.
# ===========================================================================
def _ema_pass_seg(sch, y, ds, total, alpha, Q):
    N, skip, Nw = sch.N, sch.skip, sch.Nw
    win, freqs = sch._win, sch.freqs
    nc = len(freqs)
    edges = _seg_edges(Nw, Q)
    fpil = freqs[sch.pilot_idx]
    cfull = np.zeros((total, nc), np.complex128)
    Z = np.zeros((total, nc, Q), np.complex128)
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
        sw = seg * win
        cfull[i] = E @ sw                       # IDENTICAL op to production
        for qi in range(Q):
            a, b = edges[qi], edges[qi + 1]
            Z[i, :, qi] = E[:, a:b] @ sw[a:b]
        if i > 0:
            dp = float(np.angle(cfull[i, sch.pilot_idx] *
                                np.conj(cfull[i - 1, sch.pilot_idx])))
            sm = (1 - alpha) * (dp / (2 * np.pi * fpil)) + alpha * sm
            dtau[i] = sm
            drift -= dtau[i] * FS
            drift = float(np.clip(drift, -200, 200))
    return cfull, Z, dtau


def _plain_pass_seg(sch, y, ds, total, Q):
    N, skip, Nw = sch.N, sch.skip, sch.Nw
    win, freqs = sch._win, sch.freqs
    nc = len(freqs)
    edges = _seg_edges(Nw, Q)
    cfull = np.zeros((total, nc), np.complex128)
    Z = np.zeros((total, nc, Q), np.complex128)
    for i in range(total):
        lo = ds + i * N + skip
        seg = y[lo: lo + Nw]
        if len(seg) < Nw:
            seg = np.concatenate([seg, np.zeros(Nw - len(seg))])
        tt = (lo + np.arange(Nw)) / FS
        E = np.exp(-2j * np.pi * np.outer(freqs, tt))
        sw = seg * win
        cfull[i] = E @ sw
        for qi in range(Q):
            a, b = edges[qi], edges[qi + 1]
            Z[i, :, qi] = E[:, a:b] @ sw[a:b]
    return cfull, Z


def _frame_pass_seg(sch, fe_name, y, ds, total, Q):
    """Run the production-replica front-end on one frame, returning the
    ACTIVE stream's (cfull, Z, dtau, used) exactly as production selects it.

    used: 'ema' or 'pll' (the strict-superset per-frame selector replica).
    """
    if fe_name.startswith("ema"):
        alpha = float(fe_name[3:])
        cfull, Z, dtau = _ema_pass_seg(sch, y, ds, total, alpha, Q)
        return cfull, Z, dtau, "ema"
    # resampling PLL: pass1 EMA(0.5) -> PI loop -> warp -> pass2 plain DFT
    alpha = 0.5
    pll_bw, zeta = 30.0, 0.707
    t_sym = sch.N / FS
    c1, Z1, dtau_ema = _ema_pass_seg(sch, y, ds, total, alpha, Q)
    kp, ki = _pi_loop_gains(pll_bw, t_sym, zeta)
    tau = v = 0.0
    tau_sym = np.zeros(total)
    for i in range(1, total):
        err = dtau_ema[i] - v
        v += ki * err
        tau += v + kp * err
        tau_sym[i] = tau
    N = sch.N
    sym_centers = ds + (np.arange(total) + 0.5) * N
    body_lo = ds
    body_hi = min(len(y), ds + total * N + N)
    tgrid = np.arange(body_lo, body_hi, dtype=np.float64)
    tau_t = np.interp(tgrid, sym_centers, tau_sym, left=tau_sym[0], right=tau_sym[-1])
    src = np.clip(tgrid - tau_t * FS, 0.0, len(y) - 1.0)
    y2 = y.copy()
    y2[body_lo:body_hi] = np.interp(src, np.arange(len(y)), y)
    c2, Z2 = _plain_pass_seg(sch, y2, ds, total, Q)
    fpil = sch.freqs[sch.pilot_idx]
    dtau_res = np.zeros(total)
    for i in range(1, total):
        dp = float(np.angle(c2[i, sch.pilot_idx] * np.conj(c2[i - 1, sch.pilot_idx])))
        dtau_res[i] = dp / (2 * np.pi * fpil)
    # strict-superset selector replica (no truth)
    q_pll, _, res_pll, _ = _decide_refine(sch, c2, dtau_res)
    q_ema, _, res_ema, _ = _decide_refine(sch, c1, dtau_ema)
    qual_pll = float(np.sqrt(np.mean(res_pll ** 2)))
    qual_ema = float(np.sqrt(np.mean(res_ema ** 2)))
    if qual_pll <= qual_ema:
        return c2, Z2, dtau_res, "pll"
    return c1, Z1, dtau_ema, "ema"


# ===========================================================================
# per-section frame iteration (m9_decode._demod_section_frames geometry)
# ===========================================================================
def _frame_windows(audio_nom, sec, align, sch):
    meta = sec["meta"]
    nom_bits = m9d._nominal_frame_bits(meta)
    pad_lo, pad_hi = int(PAD_LO_S * SR), int(PAD_HI_S * SR)
    flen_full = len(np.asarray(sch.modulate(np.zeros(meta["frame_bits"], np.uint8))))
    out = []
    for fi, st in enumerate(sec["frame_starts"]):
        nd = sch.nsym_data(nom_bits[fi])
        st = int(st) + align
        w_lo = max(0, int(st - pad_lo))
        w_hi = min(len(audio_nom), int(st + flen_full + pad_hi))
        y = np.asarray(audio_nom[w_lo:w_hi], np.float64)
        ds = int(hc.find_preamble(y.astype(np.float32), sch.preamble_seconds))
        out.append({"y": y, "ds": ds, "nd": nd, "nom_bits": nom_bits[fi]})
    return out


def _section_truth(sec, sch):
    meta = sec["meta"]
    expected_packed = (_HERE / sec["payload_sidecar"]).read_bytes()
    rung = Rung(name=meta["rung"], M=meta["M"], K=meta["K"], rs_n=meta["rs_n"],
                rs_k=meta["rs_k"], frame_bytes=meta["frame_bytes"])
    tx_frames, _ = codec.encode_payload(expected_packed, rung)
    fb = meta["frame_bits"]
    n_frames = meta["n_frames"]
    stream_bits = meta["stream_bits"]
    pieces = []
    for fi in range(n_frames):
        nominal = fb if fi < n_frames - 1 else (stream_bits - fb * (n_frames - 1))
        rb = np.asarray(tx_frames[fi], np.uint8).ravel()
        if len(rb) < nominal:
            rb = np.concatenate([rb, np.zeros(nominal - len(rb), np.uint8)])
        pieces.append(rb[:nominal])
    tx_bits = np.concatenate(pieces)[:stream_bits]
    return expected_packed, tx_bits


def _truth_cw_chunks(expected_packed, meta):
    rs_k, n_cw = meta["rs_k"], meta["n_codewords"]
    pad = expected_packed + bytes(max(0, n_cw * rs_k - len(expected_packed)))
    return [pad[i * rs_k:(i + 1) * rs_k] for i in range(n_cw)]


def _per_cw_decode(rx_frames, meta, crc_table):
    """Errors-only RS per codeword + CRC32 guard (union-probe verbatim).
    Returns (ok_mask, msgs, n_trials)."""
    rs_n, rs_k, n_cw = meta["rs_n"], meta["rs_k"], meta["n_codewords"]
    # reassemble (identical math to m9_decode._rs_merge_guarded)
    fb_bits, n_frames = meta["frame_bits"], meta["n_frames"]
    stream_bits = meta["stream_bits"]
    pieces = []
    for fi in range(n_frames):
        nominal = fb_bits if fi < n_frames - 1 else stream_bits - fb_bits * (n_frames - 1)
        rb = (np.asarray(rx_frames[fi], np.uint8).ravel()
              if fi < len(rx_frames) else np.zeros(nominal, np.uint8))
        if len(rb) < nominal:
            rb = np.concatenate([rb, np.zeros(nominal - len(rb), np.uint8)])
        pieces.append(rb[:nominal])
    rx_bits = np.concatenate(pieces)[:stream_bits]
    if len(rx_bits) < stream_bits:
        rx_bits = np.concatenate([rx_bits, np.zeros(stream_bits - len(rx_bits), np.uint8)])
    rx_bytes = np.packbits(rx_bits)[:n_cw * rs_n]
    rx_mat = rx_bytes.reshape(rs_n, n_cw).T
    rsc = RSCodec(rs_n - rs_k)
    ok = np.zeros(n_cw, bool)
    msgs: list = [None] * n_cw
    for i in range(n_cw):
        try:
            msg = bytes(rsc.decode(bytearray(rx_mat[i].tobytes()))[0])
        except (ReedSolomonError, Exception):
            continue
        if i < len(crc_table) and (zlib.crc32(msg) & 0xFFFFFFFF) != crc_table[i]:
            continue
        ok[i] = True
        msgs[i] = msg
    return ok, msgs, n_cw


def _genie_dc_ser(sch, q_frames, frames, tx_bits, dci=0):
    """Genie-scored SER for data-carrier dci (SCORING ONLY)."""
    pos = 0
    n_err = n_tot = 0
    for f, q in zip(frames, q_frames):
        nb, nd = f["nom_bits"], f["nd"]
        txb = tx_bits[pos:pos + nb]
        tq = sch.bits_to_quadrants(txb)[:nd]
        blk = 2 * nd
        nv = max(0, min(blk, nb - dci * blk)) // 2
        n_err += int((q[:nv, dci] != tq[:nv, dci]).sum())
        n_tot += nv
        pos += nb
    return n_err / max(1, n_tot), n_err, n_tot


def _bits_from_q(sch, q_frames):
    return [np.asarray(sch.quadrants_to_bits(q), np.uint8) for q in q_frames]


# ===========================================================================
# STEP 2: adaptive segment weights
# ===========================================================================
def _steering(sch, Q):
    edges = _seg_edges(sch.Nw, Q)
    return np.array([sch._win[a:b].sum() for a, b in zip(edges[:-1], edges[1:])])


def _combine(Z, W):
    """y[i,c] = W[c]^H z[i,c]; W (nc,Q) static."""
    return np.einsum("tcq,cq->tc", Z, np.conj(W))


def _solve_w(Zc, rot, g, delta=DIAG_LOAD):
    """MVDR-style weights from the decision-error covariance of one carrier.
    Zc (total, Q); rot (total-1,) expected differential rotation."""
    e = Zc[1:] - rot[:, None] * Zc[:-1]
    Q = Zc.shape[1]
    R = e.conj().T @ e / max(len(e), 1)
    tr = float(np.trace(R).real)
    R = R + (delta * tr / Q + 1e-30) * np.eye(Q)
    try:
        w = np.linalg.solve(R, g.astype(complex))
    except np.linalg.LinAlgError:
        return np.ones(Q, complex)
    denom = float((np.conj(w) @ g).real)
    if denom <= 0:
        return np.ones(Q, complex)
    return w * (float(g @ g) / denom)


def _rot_for(sch, ci, q_col, dtau, dd):
    f = sch.freqs[sch.data_idx][ci]
    ang = q_col * (np.pi / 2.0) + 2 * np.pi * (dtau[1:] + dd) * f
    return np.exp(1j * ang)


def _adapt_block(sch, Z, dtau):
    """Block (per-frame) adaptation. Returns (q_final, W, evm_table)."""
    nc, Q = Z.shape[1], Z.shape[2]
    g = _steering(sch, Q)
    W = np.ones((nc, Q), complex)
    cU = Z.sum(axis=2)
    qU, _, resU, ddU = _decide_refine(sch, cU, dtau)
    q_cur, dd_cur = qU, ddU
    for _ in range(N_ITER_BLOCK):
        for ci, c in enumerate(sch.data_idx):
            rot = _rot_for(sch, ci, q_cur[:, ci], dtau, dd_cur)
            W[c] = _solve_w(Z[:, c, :], rot, g)
        cW = _combine(Z, W)
        q_cur, _, res_cur, dd_cur = _decide_refine(sch, cW, dtau)
    # truth-free per-carrier revert vs uniform (never-worse on visible metric)
    evmU = np.sqrt(np.mean(resU ** 2, axis=0))
    evmW = np.sqrt(np.mean(res_cur ** 2, axis=0))
    for ci, c in enumerate(sch.data_idx):
        if evmW[ci] > evmU[ci]:
            W[c] = np.ones(Q, complex)
    cF = _combine(Z, W)
    qF, _, resF, _ = _decide_refine(sch, cF, dtau)
    return qF, W, {"evm_uniform_deg": np.degrees(evmU).round(2).tolist(),
                   "evm_adapted_deg": np.degrees(np.sqrt(np.mean(resF ** 2,
                                                                 axis=0))).round(2).tolist()}


def _adapt_slide(sch, Z, dtau, W_seed, q_seed, dd_seed, res_seed):
    """Sliding-64 adaptation (one sweep, seeded from the block solution)."""
    total, nc, Q = Z.shape
    g = _steering(sch, Q)
    Wt = np.tile(W_seed[None], (total, 1, 1)).astype(complex)
    lowq_thr = np.radians(LOWQ_DEG)
    for ci, c in enumerate(sch.data_idx):
        f = sch.freqs[sch.data_idx][ci]
        w_prev = W_seed[c].copy()
        for s0 in range(0, total, SLIDE_HOP):
            a = max(0, s0 - (SLIDE_WIN - SLIDE_HOP) // 2)
            b = min(total, a + SLIDE_WIN)
            ta, tb = a, b - 1                      # transition rows in [0, total-1)
            if tb - ta < 8:
                Wt[s0:s0 + SLIDE_HOP, c] = w_prev
                continue
            resc = res_seed[ta:tb, ci]
            lowq = float(np.mean(np.abs(resc) > lowq_thr))
            if lowq > FREEZE_FRAC:
                w = w_prev                          # QUALITY GATE: freeze update
            else:
                # transition t pairs symbols (t, t+1): needs dtau[t+1], dd[t]
                ang = (q_seed[ta:tb, ci] * (np.pi / 2.0)
                       + 2 * np.pi * (dtau[ta + 1:tb + 1] + dd_seed[ta:tb]) * f)
                rot = np.exp(1j * ang)
                w = _solve_w(Z[ta:tb + 1, c, :], rot, g)
            Wt[s0:s0 + SLIDE_HOP, c] = w
            w_prev = w
    cW = np.einsum("tcq,tcq->tc", Z, np.conj(Wt))
    qW, _, resW, _ = _decide_refine(sch, cW, dtau)
    # final per-carrier truth-free revert vs uniform
    cU = Z.sum(axis=2)
    qU, _, resU, _ = _decide_refine(sch, cU, dtau)
    evmU = np.sqrt(np.mean(resU ** 2, axis=0))
    evmW = np.sqrt(np.mean(resW ** 2, axis=0))
    q_final = qW.copy()
    for ci in range(len(sch.data_idx)):
        if evmW[ci] > evmU[ci]:
            q_final[:, ci] = qU[:, ci]
    return q_final


# ===========================================================================
# subcommand: step1 (precondition + per-segment diagnostic)
# ===========================================================================
def step1():
    t0 = time.time()
    audio_nom, sync = _load_nominal()
    align = int(sync["align"])
    out = _ckpt_load(OUT_JSON, _init_out())
    precond = {}
    seg_diag = {}
    for name in FRONTIER:
        sec = _get_section(name)
        sch = m9d._scheme_from_entry(sec)
        expected_packed, tx_bits = _section_truth(sec, sch)
        frames = _frame_windows(audio_nom, sec, align, sch)
        for fe_name in PFFT_FES:
            prod = _make_prod_frontend(sch, fe_name)
            mismatch_prod = mismatch_sum = 0
            max_dev = 0.0
            n_frames_chk = 0
            seg_acc = None
            pos = 0
            for f in frames:
                total = f["nd"] + 1
                bits_ref, diag_ref = prod.demod(f["y"], f["nd"])
                cfull, Z4, dtau, used = _frame_pass_seg(sch, fe_name, f["y"],
                                                        f["ds"], total, 4)
                # precondition A: replica (full DFT) decisions == production
                qA, _, _, _ = _decide_refine(sch, cfull, dtau)
                mismatch_prod += int((qA != diag_ref["quadrants"]).sum())
                # precondition B: uniform partial-sum decisions == production
                cS = Z4.sum(axis=2)
                qB, _, _, _ = _decide_refine(sch, cS, dtau)
                mismatch_sum += int((qB != diag_ref["quadrants"]).sum())
                md = float(np.max(np.abs(cS - cfull)) /
                           max(float(np.max(np.abs(cfull))), 1e-30))
                max_dev = max(max_dev, md)
                # Q=2 derived sums must also reproduce
                Z2 = np.stack([Z4[:, :, 0] + Z4[:, :, 1],
                               Z4[:, :, 2] + Z4[:, :, 3]], axis=2)
                q2, _, _, _ = _decide_refine(sch, Z2.sum(axis=2), dtau)
                mismatch_sum += int((q2 != diag_ref["quadrants"]).sum())
                n_frames_chk += 1
                # per-segment single-segment decisions at the SECTION winner fe
                if fe_name == "ema0.6":
                    nb, nd = f["nom_bits"], f["nd"]
                    txb = tx_bits[pos:pos + nb]
                    tq = sch.bits_to_quadrants(txb)[:nd]
                    blk = 2 * nd
                    nv0 = max(0, min(blk, nb - 0 * blk)) // 2
                    if seg_acc is None:
                        seg_acc = {qi: [0, 0, 0.0] for qi in range(4)}
                    for qi in range(4):
                        qS, gph, _, _ = _decide_refine(sch, Z4[:, :, qi], dtau)
                        ge = (gph[:nv0, 0] - tq[:nv0, 0] * (np.pi / 2.0)
                              + np.pi) % (2 * np.pi) - np.pi
                        seg_acc[qi][0] += int((qS[:nv0, 0] != tq[:nv0, 0]).sum())
                        seg_acc[qi][1] += nv0
                        seg_acc[qi][2] += float((ge ** 2).sum())
                pos += f["nom_bits"]
            precond[f"{name}|{fe_name}"] = {
                "q_mismatch_vs_production": mismatch_prod,
                "q_mismatch_uniform_sum": mismatch_sum,
                "max_rel_dev_sum_vs_full": max_dev,
                "n_frames": n_frames_chk}
            if seg_acc is not None:
                seg_diag[name] = {
                    "fe": "ema0.6", "Q": 4,
                    "dc0_ser_per_segment": [round(seg_acc[qi][0] / max(1, seg_acc[qi][1]), 5)
                                            for qi in range(4)],
                    "dc0_gerr_rms_deg_per_segment": [
                        round(float(np.degrees(np.sqrt(
                            seg_acc[qi][2] / max(1, seg_acc[qi][1])))), 2)
                        for qi in range(4)]}
            print(f"[step1] {name} {fe_name}: prod_mismatch={mismatch_prod} "
                  f"sum_mismatch={mismatch_sum} dev={max_dev:.2e}", flush=True)
    pre_pass = all(v["q_mismatch_vs_production"] == 0 and
                   v["q_mismatch_uniform_sum"] == 0 for v in precond.values())
    # KILL evaluation on m4/m5 (pre-registered)
    ratios = {}
    for nm in ("m9_m4_n256_rs159", "m9_m5_n256_rs179"):
        s = seg_diag[nm]["dc0_ser_per_segment"]
        ratios[nm] = round(s[0] / max(s[-1], 1e-9), 3)
    kill = all(r <= KILL_RATIO for r in ratios.values())
    out["precondition"] = {"per_run": precond, "pass": bool(pre_pass)}
    out["step1"] = {"per_section": seg_diag,
                    "early_over_late_ser_ratio": ratios,
                    "kill_rule": f"KILL if ratio <= {KILL_RATIO} on both m4 and m5",
                    "kill": bool(kill),
                    "elapsed_s": round(time.time() - t0, 1)}
    _ckpt_save(OUT_JSON, out)
    print(f"[step1] precondition pass={pre_pass} kill={kill} ratios={ratios} "
          f"({time.time()-t0:.0f}s)")


def _init_out():
    import scipy
    return {"experiment": "x10_a_underwater_pfft_adaptive",
            "plan": "X10_PLAN.md candidate #4 (A-underwater-pfft-adaptive)",
            "capture": str(CAPTURE), "deterministic": True, "seeds": "N/A",
            "numpy": np.__version__, "scipy": scipy.__version__,
            "grids": {"fes": list(PFFT_FES), "Q": list(PFFT_QS),
                      "modes": list(PFFT_MODES), "n_iter_block": N_ITER_BLOCK,
                      "diag_load": DIAG_LOAD, "slide_win": SLIDE_WIN,
                      "slide_hop": SLIDE_HOP, "lowq_deg": LOWQ_DEG,
                      "freeze_frac": FREEZE_FRAC,
                      "lw_scalar_S": list(LW_SCALAR_S),
                      "lw_dc0_set": list(LW_DC0_SET),
                      "lw_other_set": list(LW_OTHER_SET)}}


# ===========================================================================
# subcommand: adapt -- pfft branches for one section
# ===========================================================================
def adapt(section):
    t0 = time.time()
    audio_nom, sync = _load_nominal()
    align = int(sync["align"])
    sec = _get_section(section)
    sch = m9d._scheme_from_entry(sec)
    meta = sec["meta"]
    crc = sec["crc32_codewords"]
    expected_packed, tx_bits = _section_truth(sec, sch)
    truth_chunks = _truth_cw_chunks(expected_packed, meta)
    frames = _frame_windows(audio_nom, sec, align, sch)
    out = _ckpt_load(OUT_JSON, _init_out())
    sec_out = out.setdefault("pfft", {}).setdefault(section, {
        "n_codewords": meta["n_codewords"], "branches": {}})
    n_trials = 0
    for fe_name in PFFT_FES:
        # one segmented pass per fe (Q=4; Q=2 derived), shared by all modes
        per_frame = []
        for f in frames:
            cfull, Z4, dtau, used = _frame_pass_seg(sch, fe_name, f["y"],
                                                    f["ds"], f["nd"] + 1, 4)
            per_frame.append({"Z4": Z4, "dtau": dtau, "used": used})
        for Q in PFFT_QS:
            q_block_frames, q_slide_frames = [], []
            for f, pf in zip(frames, per_frame):
                Z = pf["Z4"]
                if Q == 2:
                    Z = np.stack([Z[:, :, 0] + Z[:, :, 1],
                                  Z[:, :, 2] + Z[:, :, 3]], axis=2)
                dtau = pf["dtau"]
                qB, W, _evm = _adapt_block(sch, Z, dtau)
                q_block_frames.append(qB)
                cB = _combine(Z, W)
                qSeed, _, resSeed, ddSeed = _decide_refine(sch, cB, dtau)
                qS = _adapt_slide(sch, Z, dtau, W, qSeed, ddSeed, resSeed)
                q_slide_frames.append(qS)
            for mode, qf in (("block", q_block_frames), ("slide64", q_slide_frames)):
                bname = f"pfft:{fe_name}:Q{Q}:{mode}"
                bits = _bits_from_q(sch, qf)
                ok, msgs, trials = _per_cw_decode(bits, meta, crc)
                n_trials += trials
                false_acc = sum(1 for i, m in enumerate(msgs)
                                if m is not None and m != truth_chunks[i])
                ser0 = _genie_dc_ser(sch, qf, frames, tx_bits, dci=0)
                failed = [int(i) for i in np.flatnonzero(~ok)]
                sec_out["branches"][bname] = {
                    "cw_failed": len(failed), "failed_idx": failed,
                    "false_accepts_posthoc": false_acc,
                    "dc0_ser": round(ser0[0], 5), "dc0_err": ser0[1],
                    "dc0_n": ser0[2], "crc_trials": trials}
                print(f"[adapt] {section} {bname}: {len(failed)}/{meta['n_codewords']} "
                      f"failed dc0_ser={ser0[0]:.4f} falseacc={false_acc}", flush=True)
        del per_frame
    sec_out["crc_trials_total"] = sum(b["crc_trials"]
                                      for b in sec_out["branches"].values())
    sec_out["elapsed_s"] = round(time.time() - t0, 1)
    _ckpt_save(OUT_JSON, out)
    print(f"[adapt] {section} done {time.time()-t0:.0f}s trials={n_trials}")


# ===========================================================================
# subcommand: latewin -- self-computed union+late-window baseline branches
# ===========================================================================
def _latewin_pass(sch, fe_name, y, ds, total, shifts):
    """Tracked center pass (production replica) + per-shift full DFT matrices
    on the SAME tracked stream. Returns (c_by_shift {S: (total,nc)}, dtau)."""
    N, skip, Nw = sch.N, sch.skip, sch.Nw
    win, freqs = sch._win, sch.freqs
    nc = len(freqs)

    def _dft_at(yy, lo):
        seg = yy[lo: lo + Nw]
        if len(seg) < Nw:
            seg = np.concatenate([seg, np.zeros(Nw - len(seg))])
        tt = (lo + np.arange(Nw)) / FS
        E = np.exp(-2j * np.pi * np.outer(freqs, tt))
        return E @ (seg * win)

    if fe_name.startswith("ema"):
        alpha = float(fe_name[3:])
        fpil = freqs[sch.pilot_idx]
        cS = {S: np.zeros((total, nc), np.complex128) for S in shifts}
        dtau = np.zeros(total)
        drift = 0.0
        sm = 0.0
        for i in range(total):
            base = ds + i * N + int(round(drift))
            lo = base + skip
            for S in shifts:
                cS[S][i] = _dft_at(y, lo + S)
            c0 = cS[0][i] if 0 in cS else _dft_at(y, lo)
            if i > 0:
                c0p = cS[0][i - 1] if 0 in cS else None
                dp = float(np.angle(c0[sch.pilot_idx] * np.conj(c0p[sch.pilot_idx])))
                sm = (1 - alpha) * (dp / (2 * np.pi * fpil)) + alpha * sm
                dtau[i] = sm
                drift -= dtau[i] * FS
                drift = float(np.clip(drift, -200, 200))
        return cS, dtau
    # pll: pass1 ema0.5 tracked, warp, pass2 plain DFT at each shift
    c1, _Z1, dtau_ema = _ema_pass_seg(sch, y, ds, total, 0.5, 2)
    kp, ki = _pi_loop_gains(30.0, sch.N / FS, 0.707)
    tau = v = 0.0
    tau_sym = np.zeros(total)
    for i in range(1, total):
        err = dtau_ema[i] - v
        v += ki * err
        tau += v + kp * err
        tau_sym[i] = tau
    sym_centers = ds + (np.arange(total) + 0.5) * N
    body_lo = ds
    body_hi = min(len(y), ds + total * N + N)
    tgrid = np.arange(body_lo, body_hi, dtype=np.float64)
    tau_t = np.interp(tgrid, sym_centers, tau_sym, left=tau_sym[0], right=tau_sym[-1])
    src = np.clip(tgrid - tau_t * FS, 0.0, len(y) - 1.0)
    y2 = y.copy()
    y2[body_lo:body_hi] = np.interp(src, np.arange(len(y)), y)
    cS = {S: np.zeros((total, nc), np.complex128) for S in shifts}
    for i in range(total):
        lo = ds + i * N + skip
        for S in shifts:
            cS[S][i] = _dft_at(y2, lo + S)
    fpil = freqs[sch.pilot_idx]
    dtau_res = np.zeros(total)
    for i in range(1, total):
        dp = float(np.angle(cS[0][i, sch.pilot_idx] *
                            np.conj(cS[0][i - 1, sch.pilot_idx])))
        dtau_res[i] = dp / (2 * np.pi * fpil)
    return cS, dtau_res


def latewin(section):
    t0 = time.time()
    audio_nom, sync = _load_nominal()
    align = int(sync["align"])
    sec = _get_section(section)
    sch = m9d._scheme_from_entry(sec)
    meta = sec["meta"]
    crc = sec["crc32_codewords"]
    expected_packed, tx_bits = _section_truth(sec, sch)
    truth_chunks = _truth_cw_chunks(expected_packed, meta)
    frames = _frame_windows(audio_nom, sec, align, sch)
    out = _ckpt_load(OUT_JSON, _init_out())
    sec_out = out.setdefault("latewin_baseline", {}).setdefault(section, {
        "n_codewords": meta["n_codewords"], "branches": {},
        "source": "self-computed (x10_late_window results absent at run time)"})
    Pd = len(sch.data_idx)
    for fe_name in PFFT_FES:
        # one multi-shift pass per fe; decide each shift fully; stitch columns.
        q_by_shift = {S: [] for S in LW_ALL_SHIFTS}
        evm_cols = {S: np.zeros(Pd) for S in LW_ALL_SHIFTS}
        evm_n = 0
        for f in frames:
            cS, dtau = _latewin_pass(sch, fe_name, f["y"], f["ds"],
                                     f["nd"] + 1, LW_ALL_SHIFTS)
            for S in LW_ALL_SHIFTS:
                qq, _, res, _ = _decide_refine(sch, cS[S], dtau)
                q_by_shift[S].append(qq)
                evm_cols[S] += (res ** 2).mean(axis=0)
            evm_n += 1
        # scalar branches: dc0 from +S, all other carriers center (S=0)
        for S in LW_SCALAR_S:
            qf = []
            for qc, ql in zip(q_by_shift[0], q_by_shift[S]):
                q = qc.copy()
                q[:, 0] = ql[:, 0]
                qf.append(q)
            _eval_branch(sec_out, f"lw:{fe_name}:S{S}", sch, qf, frames,
                         tx_bits, meta, crc, truth_chunks)
        # decoupled-argmin branch (truth-free decision-EVM per carrier)
        pick = []
        for ci in range(Pd):
            allowed = LW_DC0_SET if ci == 0 else LW_OTHER_SET
            pick.append(min(allowed, key=lambda S: evm_cols[S][ci]))
        qf = []
        for fi in range(len(frames)):
            q = q_by_shift[0][fi].copy()
            for ci in range(Pd):
                q[:, ci] = q_by_shift[pick[ci]][fi][:, ci]
            qf.append(q)
        b = _eval_branch(sec_out, f"lw:{fe_name}:argmin", sch, qf, frames,
                         tx_bits, meta, crc, truth_chunks)
        b["picked_shifts"] = pick
        print(f"[latewin] {section} {fe_name}: argmin picks {pick}", flush=True)
    sec_out["crc_trials_total"] = sum(b["crc_trials"]
                                      for b in sec_out["branches"].values())
    sec_out["elapsed_s"] = round(time.time() - t0, 1)
    _ckpt_save(OUT_JSON, out)
    print(f"[latewin] {section} done {time.time()-t0:.0f}s")


def _eval_branch(sec_out, bname, sch, q_frames, frames, tx_bits, meta, crc,
                 truth_chunks):
    bits = _bits_from_q(sch, q_frames)
    ok, msgs, trials = _per_cw_decode(bits, meta, crc)
    false_acc = sum(1 for i, m in enumerate(msgs)
                    if m is not None and m != truth_chunks[i])
    ser0 = _genie_dc_ser(sch, q_frames, frames, tx_bits, dci=0)
    failed = [int(i) for i in np.flatnonzero(~ok)]
    rec = {"cw_failed": len(failed), "failed_idx": failed,
           "false_accepts_posthoc": false_acc,
           "dc0_ser": round(ser0[0], 5), "dc0_err": ser0[1], "dc0_n": ser0[2],
           "crc_trials": trials}
    sec_out["branches"][bname] = rec
    print(f"  [{bname}] {len(failed)}/{meta['n_codewords']} failed "
          f"dc0_ser={ser0[0]:.4f} falseacc={false_acc}", flush=True)
    return rec


# ===========================================================================
# subcommand: evaluate -- gate arithmetic on tape9 frontier sections
# ===========================================================================
def evaluate():
    out = _ckpt_load(OUT_JSON, _init_out())
    probe = json.loads((_HERE / "results" /
                        "x10_union_probe_tape9_run1.json").read_text())
    probe_sec = {s["name"]: s for s in probe["sections"]}
    lw_ext = None
    if LATEWIN_RESULTS.exists():
        try:
            lw_ext = json.loads(LATEWIN_RESULTS.read_text())
        except Exception:
            lw_ext = None
    ev = {}
    for name in FRONTIER:
        n_cw = _get_section(name)["meta"]["n_codewords"]
        fail_probe = set(probe_sec[name]["union"]["failed_idx"])
        lw_branches = out.get("latewin_baseline", {}).get(name, {}).get("branches", {})
        fail_lw = set(fail_probe)
        for b in lw_branches.values():
            fail_lw &= set(b["failed_idx"])
        if lw_ext is not None:
            # union in any external late-window failed-sets if present
            try:
                for srec in lw_ext.get("sections", {}).get(name, {}).get(
                        "branches", {}).values():
                    fail_lw &= set(srec.get("failed_idx", range(n_cw)))
            except Exception:
                pass
        pf_branches = out.get("pfft", {}).get(name, {}).get("branches", {})
        fail_all = set(fail_lw)
        for b in pf_branches.values():
            fail_all &= set(b["failed_idx"])
        recovered_beyond_lw = sorted(fail_lw - fail_all)
        best_lw_dc0 = min((b["dc0_ser"] for b in lw_branches.values()),
                          default=None)
        best_pf_dc0 = min((b["dc0_ser"] for b in pf_branches.values()),
                          default=None)
        ev[name] = {
            "n_codewords": n_cw,
            "union_probe6_failed": sorted(fail_probe),
            "union_plus_latewin_failed": sorted(fail_lw),
            "union_plus_latewin_plus_pfft_failed": sorted(fail_all),
            "pfft_recovered_beyond_latewin": recovered_beyond_lw,
            "best_latewin_dc0_ser": best_lw_dc0,
            "best_pfft_dc0_ser": best_pf_dc0,
        }
        print(f"[evaluate] {name}: probe6={len(fail_probe)} "
              f"+latewin={len(fail_lw)} +pfft={len(fail_all)} "
              f"pfft_beyond_lw={recovered_beyond_lw} "
              f"dc0 lw={best_lw_dc0} pfft={best_pf_dc0}", flush=True)
    # pooled dc0 SER (pre-registered diagnostic statistic)
    pooled = {}
    for fam, key in (("latewin", "latewin_baseline"), ("pfft", "pfft")):
        best = None
        branch_names = set()
        for name in FRONTIER:
            branch_names |= set(out.get(key, {}).get(name, {}).get("branches", {}))
        for bn in sorted(branch_names):
            n_err = n_tot = 0
            okk = True
            for name in FRONTIER:
                b = out.get(key, {}).get(name, {}).get("branches", {}).get(bn)
                if b is None:
                    okk = False
                    break
                n_err += b.get("dc0_err", round(b["dc0_ser"] * b["dc0_n"]))
                n_tot += b["dc0_n"]
            if okk and n_tot:
                r = n_err / n_tot
                if best is None or r < best[1]:
                    best = (bn, r)
        pooled[fam] = {"best_branch": best[0] if best else None,
                       "pooled_dc0_ser": round(best[1], 5) if best else None}
    n_add = sum(len(ev[n]["pfft_recovered_beyond_latewin"]) for n in GATE_SECTIONS)
    diag_ratio = None
    if pooled["latewin"]["pooled_dc0_ser"] and pooled["pfft"]["pooled_dc0_ser"]:
        diag_ratio = pooled["latewin"]["pooled_dc0_ser"] / max(
            pooled["pfft"]["pooled_dc0_ser"], 1e-9)
    trials = _tally_trials(out)
    out["evaluation"] = {
        "per_section": ev,
        "pooled_dc0": pooled,
        "diagnostic_ratio_lw_over_pfft": round(diag_ratio, 3) if diag_ratio else None,
        "additional_cw_on_m6_m7_beyond_union_latewin": n_add,
        "external_latewin_results_used": bool(lw_ext is not None),
        "crc_trials": trials,
    }
    _ckpt_save(OUT_JSON, out)
    print(f"[evaluate] additional cw on m6/m7 beyond union+latewin: {n_add}; "
          f"diag ratio={diag_ratio}")


def _tally_trials(out):
    t = 0
    for key in ("pfft", "latewin_baseline"):
        for sec in out.get(key, {}).values():
            if isinstance(sec, dict):
                t += sec.get("crc_trials_total", 0)
    return t


# ===========================================================================
# regression: tape9 landed+banked rungs under the full bank incl pfft
# ===========================================================================
def regress_tape9():
    t0 = time.time()
    audio_nom, sync = _load_nominal()
    align = int(sync["align"])
    reg = _ckpt_load(REGRESS_JSON, {"experiment": "x10_pfft_regression",
                                    "suites": {}})
    suite = reg["suites"].setdefault("tape9_run1", {"sections": {}})
    n_trials = 0
    for name in TAPE9_LANDED + TAPE9_BANKED:
        sec = _get_section(name)
        sch = m9d._scheme_from_entry(sec)
        meta = sec["meta"]
        crc = sec["crc32_codewords"]
        expected_packed, tx_bits = _section_truth(sec, sch)
        truth_chunks = _truth_cw_chunks(expected_packed, meta)
        frames = _frame_windows(audio_nom, sec, align, sch)
        n_cw = meta["n_codewords"]
        merged = [None] * n_cw
        branch_log = {}
        false_total = 0
        # production 6-frontend bank
        for fe_name, kw in PROBE6:
            dem = ResamplingPLLDemod(sch, **kw)
            bits = [np.asarray(dem.demod(f["y"], f["nd"])[0], np.uint8)
                    for f in frames]
            ok, msgs, trials = _per_cw_decode(bits, meta, crc)
            n_trials += trials
            fa = sum(1 for i, m in enumerate(msgs)
                     if m is not None and m != truth_chunks[i])
            false_total += fa
            branch_log[f"fe:{fe_name}"] = {"cw_failed": int((~ok).sum()),
                                           "false_accepts": fa}
            for i, m in enumerate(msgs):
                if merged[i] is None and m is not None:
                    merged[i] = m
        # pfft branches
        for fe_name in PFFT_FES:
            per_frame = [(_frame_pass_seg(sch, fe_name, f["y"], f["ds"],
                                          f["nd"] + 1, 4)) for f in frames]
            for Q in PFFT_QS:
                for mode in PFFT_MODES:
                    qf = []
                    for f, (cfull, Z4, dtau, used) in zip(frames, per_frame):
                        Z = Z4 if Q == 4 else np.stack(
                            [Z4[:, :, 0] + Z4[:, :, 1],
                             Z4[:, :, 2] + Z4[:, :, 3]], axis=2)
                        qB, W, _ = _adapt_block(sch, Z, dtau)
                        if mode == "block":
                            qf.append(qB)
                        else:
                            cB = _combine(Z, W)
                            qSeed, _, resSeed, ddSeed = _decide_refine(sch, cB, dtau)
                            qf.append(_adapt_slide(sch, Z, dtau, W, qSeed,
                                                   ddSeed, resSeed))
                    bits = _bits_from_q(sch, qf)
                    ok, msgs, trials = _per_cw_decode(bits, meta, crc)
                    n_trials += trials
                    fa = sum(1 for i, m in enumerate(msgs)
                             if m is not None and m != truth_chunks[i])
                    false_total += fa
                    branch_log[f"pfft:{fe_name}:Q{Q}:{mode}"] = {
                        "cw_failed": int((~ok).sum()), "false_accepts": fa}
                    for i, m in enumerate(msgs):
                        if merged[i] is None and m is not None:
                            merged[i] = m
            del per_frame
        out_bytes = b"".join(m if m is not None else bytes(meta["rs_k"])
                             for m in merged)[:meta["payload_len"]]
        exact = out_bytes == expected_packed
        n_fail = sum(1 for m in merged if m is None)
        suite["sections"][name] = {
            "union_cw_failed": n_fail, "byte_exact_packed": bool(exact),
            "false_accepts_posthoc": false_total, "branches": branch_log}
        print(f"[regress_tape9] {name}: union_failed={n_fail} exact={exact} "
              f"falseacc={false_total} ({time.time()-t0:.0f}s)", flush=True)
        _ckpt_save(REGRESS_JSON, reg)
    suite["crc_trials"] = n_trials
    suite["expect"] = "all landed+banked rungs byte_exact, 0 false accepts"
    suite["pass"] = all(s["byte_exact_packed"] and
                        s["false_accepts_posthoc"] == 0
                        for s in suite["sections"].values())
    suite["elapsed_s"] = round(time.time() - t0, 1)
    _ckpt_save(REGRESS_JSON, reg)
    print(f"[regress_tape9] pass={suite['pass']} trials={n_trials}")


# ===========================================================================
# regression: m8_tape_mono_lossless (m8_dq_p10n512_rs127, DQPSK)
# ===========================================================================
def regress_m8():
    t0 = time.time()
    m8_manifest = json.loads((_HERE / "master8_manifest.json").read_text())
    cache = _HERE / "captures" / "x10_pfft_audio_nom_m8lossless.npy"
    sync_cache = _HERE / "results" / "x10_pfft_m8_sync.json"
    if cache.exists() and sync_cache.exists():
        audio_nom = np.load(cache, mmap_mode="r")
        align = int(json.loads(sync_cache.read_text())["align"])
    else:
        cap = _HERE / "captures" / "m8_tape_mono_lossless.wav"
        audio, sr = sf.read(str(cap), dtype="float32", always_2d=False)
        if audio.ndim > 1:
            audio = audio.mean(axis=1)
        if sr != SR:
            from scipy.signal import resample_poly
            frac = Fraction(SR, sr).limit_denominator(20000)
            audio = resample_poly(audio.astype(np.float64),
                                  frac.numerator, frac.denominator)
        syncd = am2.global_sync_and_resample(audio, m8_manifest)
        audio_nom = syncd["audio_nominal"]
        align = int(syncd["chirp0_nominal"]) - int(m8_manifest["tx_chirp0"])
        np.save(cache, np.asarray(audio_nom, np.float32))
        sync_cache.write_text(json.dumps({"align": align,
                                          "speed": float(syncd["speed"])}))
    print(f"[regress_m8] sync ready align={align} ({time.time()-t0:.0f}s)",
          flush=True)
    name = "m8_dq_p10n512_rs127"
    sec = _get_section(name, m8_manifest)
    p = sec["dqpsk_params"]
    from h4_dqpsk import DQPSKScheme
    sch = DQPSKScheme(p["P"], p["N"], p["spacing"])
    meta = sec["meta"]
    crc = sec["crc32_codewords"]
    expected_packed, tx_bits = _section_truth(sec, sch)
    truth_chunks = _truth_cw_chunks(expected_packed, meta)
    frames = _frame_windows(audio_nom, sec, align, sch)
    n_cw = meta["n_codewords"]
    merged = [None] * n_cw
    branch_log = {}
    false_total = 0
    n_trials = 0
    for fe_name, kw in PROBE6:
        dem = ResamplingPLLDemod(sch, **kw)
        bits = [np.asarray(dem.demod(f["y"], f["nd"])[0], np.uint8) for f in frames]
        ok, msgs, trials = _per_cw_decode(bits, meta, crc)
        n_trials += trials
        fa = sum(1 for i, m in enumerate(msgs)
                 if m is not None and m != truth_chunks[i])
        false_total += fa
        branch_log[f"fe:{fe_name}"] = {"cw_failed": int((~ok).sum()),
                                       "false_accepts": fa}
        for i, m in enumerate(msgs):
            if merged[i] is None and m is not None:
                merged[i] = m
        print(f"[regress_m8] fe:{fe_name} failed={int((~ok).sum())}", flush=True)
    for fe_name in PFFT_FES:
        per_frame = [(_frame_pass_seg(sch, fe_name, f["y"], f["ds"],
                                      f["nd"] + 1, 4)) for f in frames]
        for Q in PFFT_QS:
            for mode in PFFT_MODES:
                qf = []
                for f, (cfull, Z4, dtau, used) in zip(frames, per_frame):
                    Z = Z4 if Q == 4 else np.stack(
                        [Z4[:, :, 0] + Z4[:, :, 1],
                         Z4[:, :, 2] + Z4[:, :, 3]], axis=2)
                    qB, W, _ = _adapt_block(sch, Z, dtau)
                    if mode == "block":
                        qf.append(qB)
                    else:
                        cB = _combine(Z, W)
                        qSeed, _, resSeed, ddSeed = _decide_refine(sch, cB, dtau)
                        qf.append(_adapt_slide(sch, Z, dtau, W, qSeed,
                                               ddSeed, resSeed))
                bits = _bits_from_q(sch, qf)
                ok, msgs, trials = _per_cw_decode(bits, meta, crc)
                n_trials += trials
                fa = sum(1 for i, m in enumerate(msgs)
                         if m is not None and m != truth_chunks[i])
                false_total += fa
                branch_log[f"pfft:{fe_name}:Q{Q}:{mode}"] = {
                    "cw_failed": int((~ok).sum()), "false_accepts": fa}
                for i, m in enumerate(msgs):
                    if merged[i] is None and m is not None:
                        merged[i] = m
        del per_frame
        print(f"[regress_m8] pfft:{fe_name} done ({time.time()-t0:.0f}s)", flush=True)
    out_bytes = b"".join(m if m is not None else bytes(meta["rs_k"])
                         for m in merged)[:meta["payload_len"]]
    exact = out_bytes == expected_packed
    n_fail = sum(1 for m in merged if m is None)
    reg = _ckpt_load(REGRESS_JSON, {"experiment": "x10_pfft_regression",
                                    "suites": {}})
    reg["suites"]["m8_tape_mono_lossless"] = {
        "section": name, "union_cw_failed": n_fail,
        "byte_exact_packed": bool(exact),
        "false_accepts_posthoc": false_total, "branches": branch_log,
        "crc_trials": n_trials,
        "pass": bool(exact and false_total == 0),
        "elapsed_s": round(time.time() - t0, 1)}
    _ckpt_save(REGRESS_JSON, reg)
    print(f"[regress_m8] {name}: union_failed={n_fail} exact={exact} "
          f"falseacc={false_total} pass={exact and false_total == 0}")


# ===========================================================================
# regression: tape7/tape4 WS rungs (pfft cannot apply -- M-FSK PHY; the
# standard decoders are re-run to confirm the landed rungs reproduce; pfft
# contributes ZERO CRC-acceptance trials on these captures by construction).
# ===========================================================================
def regress_ws():
    t0 = time.time()
    reg = _ckpt_load(REGRESS_JSON, {"experiment": "x10_pfft_regression",
                                    "suites": {}})
    import m7_decode
    import m4_decode
    res7 = m7_decode.decode(str(_HERE / "captures" / "tape7_run1.wav"),
                            out_tag="x10_pfft_regress_tape7", verbose=False)
    p7 = {p["name"]: p for p in res7["payloads"]}
    want7 = ("m16_rs111_8k", "m16_rs191_8k", "m32_rs95_4k")
    res4 = m4_decode.decode(str(_HERE / "captures" / "tape4_run1.wav"),
                            out_tag="x10_pfft_regress_tape4", verbose=False)
    p4 = {p["name"]: p for p in res4["payloads"]}
    want4 = ("ws_test2k", "ws_llm24k")
    suite = {"note": ("WS M-FSK rungs: pfft is a DQPSK front-end and "
                      "structurally contributes no branches/trials here; "
                      "standard decoders re-run for reproducibility."),
             "tape7_run1": {n: {"byte_exact": bool(p7[n]["byte_exact"]),
                                "miscorrected_cw": int(p7[n].get(
                                    "miscorrected_cw", p7[n].get(
                                        "rs_codewords_miscorrected", 0)) or 0)}
                            for n in want7},
             "tape4_run1": {n: {"byte_exact": bool(p4[n]["byte_exact"]),
                                "miscorrected_cw": int(p4[n].get(
                                    "miscorrected_cw", p4[n].get(
                                        "rs_codewords_miscorrected", 0)) or 0)}
                            for n in want4},
             "crc_trials_from_pfft": 0,
             "elapsed_s": round(time.time() - t0, 1)}
    suite["pass"] = (all(v["byte_exact"] for v in suite["tape7_run1"].values())
                     and all(v["byte_exact"] for v in suite["tape4_run1"].values()))
    reg["suites"]["ws_tape7_tape4"] = suite
    _ckpt_save(REGRESS_JSON, reg)
    print(f"[regress_ws] pass={suite['pass']} "
          f"tape7={suite['tape7_run1']} tape4={suite['tape4_run1']}")


# ===========================================================================
# summarize: assemble the gate verdict
# ===========================================================================
def summarize():
    out = _ckpt_load(OUT_JSON, _init_out())
    reg = _ckpt_load(REGRESS_JSON, {"suites": {}})
    pre = out.get("precondition", {}).get("pass", False)
    kill = out.get("step1", {}).get("kill", True)
    ev = out.get("evaluation", {})
    n_add = ev.get("additional_cw_on_m6_m7_beyond_union_latewin", 0)
    diag_ratio = ev.get("diagnostic_ratio_lw_over_pfft")
    suites = reg.get("suites", {})
    reg_pass = (suites.get("tape9_run1", {}).get("pass") is True
                and suites.get("m8_tape_mono_lossless", {}).get("pass") is True
                and suites.get("ws_tape7_tape4", {}).get("pass") is True)
    false_acc = 0
    for s in suites.values():
        if "sections" in s:
            false_acc += sum(x.get("false_accepts_posthoc", 0)
                             for x in s["sections"].values())
        else:
            false_acc += s.get("false_accepts_posthoc", 0)
    for key in ("pfft", "latewin_baseline"):
        for sec in out.get(key, {}).values():
            if isinstance(sec, dict):
                false_acc += sum(b.get("false_accepts_posthoc", 0)
                                 for b in sec.get("branches", {}).values())
    trials = (_tally_trials(out)
              + suites.get("tape9_run1", {}).get("crc_trials", 0)
              + suites.get("m8_tape_mono_lossless", {}).get("crc_trials", 0))
    within_budget = trials < 4e5
    pass_tier = (pre and not kill and n_add >= 1 and reg_pass
                 and false_acc == 0 and within_budget)
    diag_tier = (pre and not kill and n_add == 0 and diag_ratio is not None
                 and diag_ratio >= 1.5 and reg_pass and false_acc == 0
                 and within_budget)
    verdict = ("PASS" if pass_tier else
               "DIAGNOSTIC_PASS" if diag_tier else
               "KILL" if kill else "FAIL")
    out["gate"] = {
        "precondition_pass": bool(pre),
        "step1_kill": bool(kill),
        "additional_cw_m6_m7_beyond_union_latewin": int(n_add),
        "diagnostic_ratio_lw_over_pfft": diag_ratio,
        "diagnostic_threshold": 1.5,
        "regression_4captures_pass": bool(reg_pass),
        "false_accepts_total_posthoc": int(false_acc),
        "crc_trials_total": int(trials),
        "within_campaign_budget_4e5": bool(within_budget),
        "verdict": verdict,
    }
    _ckpt_save(OUT_JSON, out)
    print(json.dumps(out["gate"], indent=2))


# ===========================================================================
if __name__ == "__main__":
    import warnings
    warnings.filterwarnings("ignore")
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("step1")
    sp = sub.add_parser("adapt")
    sp.add_argument("--section", required=True)
    sp = sub.add_parser("latewin")
    sp.add_argument("--section", required=True)
    sub.add_parser("evaluate")
    sub.add_parser("regress_tape9")
    sub.add_parser("regress_m8")
    sub.add_parser("regress_ws")
    sub.add_parser("summarize")
    args = ap.parse_args()
    if args.cmd == "step1":
        step1()
    elif args.cmd == "adapt":
        adapt(args.section)
    elif args.cmd == "latewin":
        latewin(args.section)
    elif args.cmd == "evaluate":
        evaluate()
    elif args.cmd == "regress_tape9":
        regress_tape9()
    elif args.cmd == "regress_m8":
        regress_m8()
    elif args.cmd == "regress_ws":
        regress_ws()
    elif args.cmd == "summarize":
        summarize()
