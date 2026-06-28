"""m10_decode.py -- the COMPOSED SUPERSET decoder for master10 (and, via
--manifest, any m8/m9-format capture: the composed-regression blocking gate).

ONE pipeline composing every x10 survivor receiver upgrade, strictly additive
(a CRC-passing codeword is FINAL; rescue paths are offered ONLY CRC-failing
codewords and can never replace a passing one):

  pass 1  ENSEMBLE UNION (survivor C-redundancy-architecture-1): CRC32-guarded
          per-codeword union across the widened timing-front-end bank --
          resampling_pll(30 Hz) + ema {0.5, 0.6, 0.65, 0.7, 0.8, 0.4}.
          dense2x sections sweep the manifest rx_window_plan geometries
          (hann256_skip0 primary, rect128_skip64 alternate) x (ema/pll), the
          probe-ranked order of x10_b_aggr_05_dense2x_decode.
  pass 2  LATE-WINDOW dc0 at N256 (survivor B-cons-01), WIDENED pre-registered
          grid [0,8,16,24,32,40,48,56,64,72,80] (+72/+80 fit N256: window start
          skip+80 < N), OTHER_GRID (-8,0,8), truth-free per-carrier decision-EVM
          argmin, bases ema0.6 + pll30. Scalar-dc0 + argmin stitched branches
          join the union (fill-only).
  pass 3  CARRIER-CLASS ERRORS-AND-ERASURES RS RETRY LADDER (survivor
          A-fec-gmd-erasure): truth-free residual-dispersion carrier ranking,
          singleton/pair/triple sets from the 4 worst carriers, <=60 patterns
          per codeword, 4 best branches, CRC32-guarded, fill-only.

Every RS decode attempt and CRC acceptance test is ledgered; the cumulative
false-accept bound (crc_checks * 2^-32) is reported and must stay < 1e-4.
erase_frac=0 everywhere outside the structural ladder (pre-registered: blanket
erasures monotonically hurt on tape9).

Per-rung result records the best SINGLE front-end (m9-style winner) AND the
union-final outcome; per-carrier SER vs the payload sidecar (scoring only).

Usage:
    python3 experiments/tape_v2/m10_decode.py experiments/tape_v2/master10.wav \
        --out-tag selfcheck_nochan
    python3 experiments/tape_v2/m10_decode.py experiments/tape_v2/captures/tape10_run1.wav
    # composed-regression gate (master9 capture through THIS pipeline):
    python3 experiments/tape_v2/m10_decode.py experiments/tape_v2/captures/tape9_run1.wav \
        --manifest master9_manifest.json --out-tag composed_regression_tape9_run1 \
        --sections m9_m5_n256_rs179,m9_m6_n256_rs191

Output: results/x10_m10_results_<tag>.json (checkpointed; chunked --sections
runs merge into the same file).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import pathlib
import sys
import time
import zlib
from concurrent.futures import ProcessPoolExecutor
from fractions import Fraction

import numpy as np
import soundfile as sf
from scipy.signal import resample_poly

np.seterr(divide="ignore", over="ignore", invalid="ignore")

_HERE = pathlib.Path(__file__).resolve().parent
ROOT = pathlib.Path("/Users/magnus/repos/cassette-ai")
for _p in (ROOT / "src", ROOT / "tests" / "e2e", ROOT / "experiments" / "deepdive2",
           ROOT / "experiments" / "capacity", _HERE):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import analyze_master2 as am2                          # noqa: E402
import inband_crc as ib                                # noqa: E402 (self-describing CRC framing)
import m3_codec as codec                               # noqa: E402
from m3_codec import Rung                              # noqa: E402
import m9_decode as m9d                                # noqa: E402 (read-only import)
from h4_dqpsk import DQPSKScheme, PAD_LO_S, PAD_HI_S   # noqa: E402
from h9_payload_codec import unpack_payload            # noqa: E402
from x9_resampling_pll import ResamplingPLLDemod       # noqa: E402
from x10_a_fec_gmd_erasure import (                    # noqa: E402
    carrier_class_map, ResidCaptureDemod, _rx_mat,
)
from x10_b_cons_01_late_window_dc0 import (            # noqa: E402
    _shift_pass_ema, _pll_warp, _shift_pass_pll, _decide_refine,
)
from x10_b_aggr_05_dense2x_master import (             # noqa: E402
    Dense2xScheme, Dense2xDropScheme,
)
from rs_backend import RSCodec, ReedSolomonError, BACKEND as _RS_BACKEND  # noqa: E402

# Re-pin _HERE at sys.path[0] now that all imports are done.
#
# analyze_master2 (imported above) contains module-level code that inserts
# the MAIN REPO's tape_v2 at sys.path[0], pushing _HERE down.  That was
# fine during this module's own import (all needed modules were already
# cached in sys.modules), but it means spawned subprocesses inherit a
# sys.path where the main repo appears first and find the main-repo copy of
# m10_decode.py (which lacks _mp_branch_worker) instead of this file.
# Moving _HERE back to position 0 fixes subprocess lookup without affecting
# any already-imported module.
if not sys.path or sys.path[0] != str(_HERE):
    if str(_HERE) in sys.path:
        sys.path.remove(str(_HERE))
    sys.path.insert(0, str(_HERE))

SR = codec.FS
RESULTS_DIR = _HERE / "results"
CAP_DIR = _HERE / "captures"
DEFAULT_MANIFEST = _HERE / "master10_manifest.json"
MASTER_ID = "master10"

# Thread-count env vars capped to 1 per worker process so N worker processes
# use ~N cores rather than N * default_BLAS_threads cores.  Set before
# forking so children inherit the cap.
_MP_THREAD_VARS = (
    "OMP_NUM_THREADS",
    "OPENBLAS_NUM_THREADS",
    "MKL_NUM_THREADS",
    "VECLIB_MAXIMUM_THREADS",
    "NUMEXPR_NUM_THREADS",
)

# ---- pass-1 banks (pre-registered orders) ---------------------------------
PLL_BW_HZ = 30.0
DQPSK_BANK = (("resampling_pll30", dict(front_end="pll", pll_bw_hz=30.0)),
              ("ema0.5", dict(front_end="ema", ema_alpha=0.5)),
              ("ema0.6", dict(front_end="ema", ema_alpha=0.6)),
              ("ema0.65", dict(front_end="ema", ema_alpha=0.65)),
              ("ema0.7", dict(front_end="ema", ema_alpha=0.7)),
              ("ema0.8", dict(front_end="ema", ema_alpha=0.8)),
              ("ema0.4", dict(front_end="ema", ema_alpha=0.4)))
D2X_PLAN = (("hann256_skip0", "ema", 0.7), ("hann256_skip0", "ema", 0.8),
            ("hann256_skip0", "ema", 0.6), ("hann256_skip0", "pll", 30.0),
            ("hann256_skip0", "pll", 45.0), ("rect128_skip64", "ema", 0.7),
            ("rect128_skip64", "pll", 30.0), ("hann256_skip0", "ema", 0.5))

# ---- pass-2 late-window grids (WIDENED, pre-registered before tape day) ----
DC0_GRID_WIDE = (0, 8, 16, 24, 32, 40, 48, 56, 64, 72, 80)
OTHER_GRID = (-8, 0, 8)
LW_SHIFTS = tuple(sorted(set(DC0_GRID_WIDE) | set(OTHER_GRID)))
LW_BASES = ("ema0.6", "pll30")

# ---- pass-3 ladder bounds (survivor A-fec-gmd-erasure, frozen) -------------
TOP_RANKED = 4
N_LADDER_BRANCHES = 4
MAX_PATTERNS_PER_CW = 60

FA_BUDGET = 1e-4


# ===========================================================================
# scheme factories
# ===========================================================================
def _tx_scheme(sec):
    kind = sec["kind"]
    if kind == "dense2x":
        p = sec["dqpsk_params"]
        return Dense2xScheme(p["P"], skip=p.get("skip") or 64)
    if kind == "dense2x_drop":
        p = sec["dqpsk_params"]
        return Dense2xDropScheme(p["P"], p["drop_freqs_hz"],
                                 pilot_hz=p["pilot_hz"], skip=p.get("skip") or 64)
    return m9d._scheme_from_entry(sec)      # dqpsk / dqpsk_dropnull / freqdiff


def _d2x_rx_scheme(sec, geometry):
    p = sec["dqpsk_params"]
    skip = 0 if geometry == "hann256_skip0" else 64
    if sec["kind"] == "dense2x":
        sch = Dense2xScheme(p["P"], skip=skip)
    else:
        sch = Dense2xDropScheme(p["P"], p["drop_freqs_hz"],
                                pilot_hz=p["pilot_hz"], skip=skip)
    if geometry == "rect128_skip64":
        sch._win = np.ones(sch.Nw)
    return sch


def _frontends_for(sec):
    """Ordered (label, rx_scheme, demod_callable) for pass 1."""
    out = []
    if sec["kind"] in ("dense2x", "dense2x_drop"):
        for geo, fe, val in D2X_PLAN:
            sch = _d2x_rx_scheme(sec, geo)
            if fe == "ema":
                dem = ResamplingPLLDemod(sch, front_end="ema", ema_alpha=val)
                label = f"{geo}_ema{val}"
            else:
                dem = ResamplingPLLDemod(sch, pll_bw_hz=val, front_end="pll")
                label = f"{geo}_pll{val:g}"
            out.append((label, sch, lambda w, nd, d=dem: d.demod(w, nd)))
        return out
    sch = _tx_scheme(sec)
    for label, kw in DQPSK_BANK:
        dem = ResamplingPLLDemod(sch, **kw)
        out.append((label, sch, lambda w, nd, d=dem: d.demod(w, nd)))
    return out


# ===========================================================================
# CRC-guarded per-codeword RS decode (errors-only) -- the acceptance channel.
# ===========================================================================
def _per_cw_decode(rx_mat, meta, crc_table, ledger, *, erase_pos_per_cw=None,
                   only_cw=None, inband=False):
    rs_n, rs_k, n_cw = meta["rs_n"], meta["rs_k"], meta["n_codewords"]
    rsc = RSCodec(rs_n - rs_k)
    ok = np.zeros(n_cw, bool)
    msgs: list[bytes | None] = [None] * n_cw
    rows = range(n_cw) if only_cw is None else only_cw
    for i in rows:
        epos = (erase_pos_per_cw or {}).get(i, [])
        ledger["rs_attempts"] += 1
        try:
            row = bytearray(rx_mat[i].tobytes())
            dec = rsc.decode(row, erase_pos=epos)[0] if epos else rsc.decode(row)[0]
            msg = bytes(dec)
        except (ReedSolomonError, Exception):
            continue
        ledger["crc_checks"] += 1
        if inband:
            # self-describing: recompute+verify the in-band CRC; no external table
            if not ib.accept_message(msg)[0]:
                ledger["crc_rejects"] += 1
                continue
        elif i < len(crc_table) and (zlib.crc32(msg) & 0xFFFFFFFF) != crc_table[i]:
            ledger["crc_rejects"] += 1
            continue
        ledger["crc_accepts"] += 1
        ok[i] = True
        msgs[i] = msg
    return ok, msgs


def _assemble(meta, msgs):
    out = bytearray()
    for i in range(meta["n_codewords"]):
        out += msgs[i] if msgs[i] is not None else bytes(meta["rs_k"])
    return bytes(out)[:meta["payload_len"]]


def _union_fill(union_msgs, union_src, msgs, label):
    """STRICTLY ADDITIVE: only fills codewords that have no CRC-passing
    message yet. Never replaces. Returns #newly filled."""
    new = 0
    for i in range(len(union_msgs)):
        if union_msgs[i] is None and msgs[i] is not None:
            union_msgs[i] = msgs[i]
            union_src[i] = label
            new += 1
    return new


def _nominal_bits(meta):
    fb, n = meta["frame_bits"], meta["n_frames"]
    return [fb] * (n - 1) + [meta["stream_bits"] - fb * (n - 1)]


# ===========================================================================
# pass 2: late-window dc0 stitched branches (WIDENED grid) for N256 DQPSK.
# Low-level shifted-window passes imported from the validated survivor module.
# ===========================================================================
def _late_window_branches(audio_nom, align, sec, sch, verbose=True):
    meta = sec["meta"]
    nom_bits = _nominal_bits(meta)
    pad_lo, pad_hi = int(PAD_LO_S * SR), int(PAD_HI_S * SR)
    flen_full = len(np.asarray(sch.modulate(np.zeros(meta["frame_bits"], np.uint8))))
    P = len(sch.data_idx)
    import hyp_common as hc

    n_pre = m9d._preamble_n(sch.preamble_seconds)
    out = {}
    for base in LW_BASES:
        q_by_shift = {s: [] for s in LW_SHIFTS}
        evm_sum = np.zeros((P, len(LW_SHIFTS)))
        evm_n = np.zeros((P, len(LW_SHIFTS)))
        t0 = time.time()
        drift_pred = 0   # per-frame timing drift tracker (issue #26)
        for fi, st in enumerate(sec["frame_starts"]):
            nd = sch.nsym_data(nom_bits[fi])
            total = nd + 1
            st_i = int(st) + align + drift_pred
            w_lo = max(0, st_i - pad_lo)
            w_hi = min(len(audio_nom), st_i + flen_full + pad_hi)
            y = np.asarray(audio_nom[w_lo:w_hi], np.float64)
            ds = int(hc.find_preamble(y.astype(np.float32), sch.preamble_seconds))
            drift_pred = m9d._drift_update(
                drift_pred, (w_lo + ds - n_pre) - st_i, y, sch.preamble_seconds)
            y2 = _pll_warp(sch, y, ds, total) if base == "pll30" else None
            for si, s in enumerate(LW_SHIFTS):
                if base == "pll30":
                    c, dtau = _shift_pass_pll(sch, y2, ds, total, s)
                else:
                    c, dtau = _shift_pass_ema(sch, y, ds, total, 0.6, s)
                q, res = _decide_refine(sch, c, dtau)
                q_by_shift[s].append(q.astype(np.int8))
                evm_sum[:, si] += np.abs(res).sum(axis=0)
                evm_n[:, si] += res.shape[0]
        evm = evm_sum / np.maximum(evm_n, 1)

        sidx = {s: i for i, s in enumerate(LW_SHIFTS)}
        vec = np.zeros(P, int)
        vec[0] = DC0_GRID_WIDE[int(np.argmin([evm[0, sidx[s]] for s in DC0_GRID_WIDE]))]
        for j in range(1, P):
            vec[j] = OTHER_GRID[int(np.argmin([evm[j, sidx[s]] for s in OTHER_GRID]))]

        branches = {}
        for S in DC0_GRID_WIDE[1:]:
            bvec = np.zeros(P, int)
            bvec[0] = S
            branches[f"lw_{base}_S{S}"] = bvec
        branches[f"lw_{base}_argmin"] = vec

        def stitch(bvec):
            frames = []
            for fi in range(len(q_by_shift[0])):
                qs = q_by_shift[int(bvec[0])][fi].copy()
                for j in range(P):
                    qs[:, j] = q_by_shift[int(bvec[j])][fi][:, j]
                frames.append(np.asarray(sch.quadrants_to_bits(qs.astype(int)),
                                         np.uint8))
            return frames

        dc0_evm_deg = {str(s): round(float(np.degrees(evm[0, sidx[s]])), 3)
                       for s in DC0_GRID_WIDE}
        # dc0-grid gate (pre-registered): argmin interior OR edge improvement
        # flattened (<10% relative EVM gain at the new edge)
        edge, prev = DC0_GRID_WIDE[-1], DC0_GRID_WIDE[-2]
        e_edge = float(evm[0, sidx[edge]])
        e_prev = float(evm[0, sidx[prev]])
        rel_gain = (e_prev - e_edge) / max(e_prev, 1e-12)
        gate = {"argmin_dc0": int(vec[0]),
                "argmin_interior": bool(vec[0] != edge),
                "edge_rel_evm_gain": round(float(rel_gain), 4),
                "edge_flattened": bool(rel_gain < 0.10),
                "pass": bool(vec[0] != edge or rel_gain < 0.10)}
        out[base] = {"branches": {bn: stitch(bv) for bn, bv in branches.items()},
                     "vecs": {bn: bv.tolist() for bn, bv in branches.items()},
                     "argmin_vec": vec.tolist(), "dc0_evm_deg": dc0_evm_deg,
                     "dc0_grid_gate": gate}
        if verbose:
            print(f"    [lw {sec['name']} base={base}] argmin={vec.tolist()} "
                  f"gate={'PASS' if gate['pass'] else 'FAIL'} "
                  f"({time.time()-t0:.1f}s)", flush=True)
    return out


# ===========================================================================
# pass 3: carrier-class errors-and-erasures retry ladder (fill-only).
# ===========================================================================
def _rank_carriers(audio_nom, align, sec, verbose=True):
    """Truth-free per-carrier RMS post-decision phase-residual ranking."""
    if sec["kind"] in ("dense2x", "dense2x_drop"):
        sch = _d2x_rx_scheme(sec, "hann256_skip0")
        dem = ResidCaptureDemod(sch, front_end="ema", ema_alpha=0.7)
    else:
        sch = _tx_scheme(sec)
        dem = ResidCaptureDemod(sch, front_end="ema", ema_alpha=0.6)
    meta = sec["meta"]
    nom_bits = _nominal_bits(meta)
    pad_lo, pad_hi = int(PAD_LO_S * SR), int(PAD_HI_S * SR)
    flen_full = len(np.asarray(sch.modulate(np.zeros(meta["frame_bits"], np.uint8))))
    P = len(sch.data_idx)
    n_pre = m9d._preamble_n(sch.preamble_seconds)
    ss = np.zeros(P)
    nn = 0
    drift_pred = 0   # per-frame timing drift tracker (issue #26)
    for fi, st in enumerate(sec["frame_starts"]):
        nd = sch.nsym_data(nom_bits[fi])
        st_i = int(st) + align + drift_pred
        w_lo = max(0, st_i - pad_lo)
        w_hi = min(len(audio_nom), st_i + flen_full + pad_hi)
        win = np.asarray(audio_nom[w_lo:w_hi], np.float64)
        _bits, _diag = dem.demod(win, nd)
        _ds = _diag.get("preamble_at")
        if _ds is not None:
            drift_pred = m9d._drift_update(
                drift_pred, (w_lo + int(_ds) - n_pre) - st_i, win, sch.preamble_seconds)
        resd = dem.last_resd
        ss += (resd ** 2).sum(axis=0)
        nn += resd.shape[0]
    disp_deg = np.degrees(np.sqrt(ss / max(1, nn)))
    rank = [int(c) for c in np.argsort(-disp_deg)]
    if verbose:
        print(f"    [ladder {sec['name']}] rank(worst first)={rank[:6]} "
              f"disp={[round(float(disp_deg[c]), 1) for c in rank[:4]]} deg",
              flush=True)
    return rank, [round(float(x), 2) for x in disp_deg]


def _erasure_ladder(sec, meta, crc, branch_mats, union_msgs, union_src,
                    rank, ledger, verbose=True, *, inband=False):
    """Bounded structural-erasure retry on CRC-failing codewords ONLY."""
    n_cw = meta["n_codewords"]
    nk = meta["rs_n"] - meta["rs_k"]
    failed = [i for i in range(n_cw) if union_msgs[i] is None]
    rec = {"target_cws": list(failed), "accepted": [], "trials": 0,
           "skipped_sets_infeasible": 0, "branches": [m[0] for m in branch_mats]}
    if not failed:
        return rec
    P = len(_tx_scheme(sec).data_idx)
    positions, _ = carrier_class_map(meta, P)
    top = [c for c in rank if c < P][:TOP_RANKED]
    sets = ([(c,) for c in top]
            + [(top[a], top[b]) for a in range(len(top))
               for b in range(a + 1, len(top))]
            + [tuple(top[x] for x in range(len(top)) if x != skip)
               for skip in range(len(top) - 1, -1, -1)])
    rsc = RSCodec(nk)
    for i in failed:
        recovered = False
        n_tr = 0
        for s in sets:
            if recovered:
                break
            epos = sorted(set().union(*[positions[i][c] for c in s]))
            if len(epos) > nk:
                rec["skipped_sets_infeasible"] += 1
                continue
            for bname, mat in branch_mats:
                if n_tr >= MAX_PATTERNS_PER_CW:
                    break
                n_tr += 1
                ledger["rs_attempts"] += 1
                row = bytearray(mat[i].tobytes())
                try:
                    msg = bytes(rsc.decode(row, erase_pos=list(epos))[0])
                except (ReedSolomonError, Exception):
                    continue
                ledger["crc_checks"] += 1
                if inband:
                    if not ib.accept_message(msg)[0]:
                        ledger["crc_rejects"] += 1
                        continue
                elif (zlib.crc32(msg) & 0xFFFFFFFF) != crc[i]:
                    ledger["crc_rejects"] += 1
                    continue
                ledger["crc_accepts"] += 1
                # fill-only: i is by construction CRC-failing here
                union_msgs[i] = msg
                union_src[i] = f"ladder:{bname}:erase{list(s)}(e={len(epos)})"
                rec["accepted"].append({"cw": int(i), "branch": bname,
                                        "erased_carriers": [int(c) for c in s],
                                        "n_erased": len(epos),
                                        "trials_used": n_tr})
                recovered = True
                break
        rec["trials"] += n_tr
    if verbose:
        print(f"    [ladder {sec['name']}] recovered "
              f"{len(rec['accepted'])}/{len(failed)} ({rec['trials']} trials)",
              flush=True)
    return rec


# ===========================================================================
# WIN 2: parallel front-end ensemble worker (process-level)
#
# ProcessPoolExecutor bypasses the GIL entirely, so BOTH the numpy/scipy
# demod (previously GIL-released but starved by RS) AND the reedsolo RS
# decode (pure-Python, GIL-bound under threads) run truly in parallel.
#
# Profiled on the gate mini-master (11 frames, 406 CW, clean):
#   per-branch demod: ~4.5s, per-branch RS: ~4.7s, per_carrier_ser: ~1.6s
#   pickle overhead for 26.6 MB float32 audio_nom: ~6 ms/branch = negligible
#
# Measured thread speedup:     ~1.1x  (GIL held RS)
# Expected process speedup:    ~4–8x on 10 cores (gate 8-branch noisy)
#
# On CLEAN captures the serial WIN-1 early-exit (1 branch) is faster than
# running all 8 branches in parallel; use parallel=None for clean captures.
# ===========================================================================
def _mp_branch_worker(args):
    """ProcessPoolExecutor branch worker.

    Takes only picklable args.  Reconstructs the scheme and demodulator
    from the branch index so no lambda / scheme object needs to cross
    the process boundary.  audio_nom is passed as a numpy array; for
    typical gate audio (~27 MB float32) pickle overhead is <10 ms,
    negligible vs demod time (~4–5 s/branch on 11-frame gate).

    Returns (ok, msgs, rx_frames, local_ledger) — all picklable.
    """
    audio_nom, sec, align, branch_idx = args

    kind = sec["kind"]
    meta = sec["meta"]
    # inband CRC mode is self-describing -- no external crc32 table to consult.
    inband = sec.get("crc_mode") == "inband"
    crc = sec.get("crc32_codewords")

    if kind in ("dense2x", "dense2x_drop"):
        geo, fe_type, val = D2X_PLAN[branch_idx]
        sch_rx = _d2x_rx_scheme(sec, geo)
        if fe_type == "ema":
            dem = ResamplingPLLDemod(sch_rx, front_end="ema", ema_alpha=val)
        else:
            dem = ResamplingPLLDemod(sch_rx, pll_bw_hz=val, front_end="pll")
    else:
        sch_rx = _tx_scheme(sec)
        _label, kw = DQPSK_BANK[branch_idx]
        dem = ResamplingPLLDemod(sch_rx, **kw)

    fe = lambda w, nd, d=dem: d.demod(w, nd)  # noqa: E731

    local_ledger = {"rs_attempts": 0, "crc_checks": 0,
                    "crc_rejects": 0, "crc_accepts": 0}
    rx_frames, _ = m9d._demod_section_frames(audio_nom, sec, align, sch_rx, fe)
    ok, msgs = _per_cw_decode(_rx_mat(rx_frames, meta), meta, crc, local_ledger,
                              inband=inband)
    return ok, msgs, rx_frames, local_ledger


# ===========================================================================
# composed per-section decode
# ===========================================================================
def _decode_section(audio_nom, sec, align, ledger, *, rescue=True, verbose=True,
                    parallel: int | None = None):
    t0 = time.time()
    meta = sec["meta"]
    # inband (self-describing) CRC mode: each RS message carries its own CRC32,
    # so there is NO external crc32_codewords table to consult.
    inband = sec.get("crc_mode") == "inband"
    crc = sec.get("crc32_codewords")
    expected_packed = (_HERE / sec["payload_sidecar"]).read_bytes()
    n_cw = meta["n_codewords"]
    sch_tx = _tx_scheme(sec)
    truth_msgs = None
    if expected_packed is not None:          # post-hoc miscorrection audit only
        k = meta["rs_k"]
        if inband:
            # the on-air RS messages are the in-band FRAMES of the payload, not
            # raw payload chunks -- regenerate them for the audit.
            truth_msgs = ib.frame_payload(expected_packed, k)
        else:
            pad = (-len(expected_packed)) % k
            padded = expected_packed + bytes(pad)
            truth_msgs = [padded[i * k:(i + 1) * k] for i in range(n_cw)]

    union_msgs: list[bytes | None] = [None] * n_cw
    union_src: list[str | None] = [None] * n_cw
    branch_records = []
    branch_frames_pool: list[tuple[str, list]] = []
    best = None      # best SINGLE branch (m9-style winner)

    # ---- pass 1: front-end ensemble union --------------------------------
    # WIN 2: when parallel>1, run branches concurrently with ProcessPoolExecutor.
    # ProcessPoolExecutor bypasses the GIL entirely so both the numpy/scipy
    # demod AND the reedsolo RS decode run in true parallel (vs ~1.1x with
    # threads where the GIL serialised the pure-Python RS step).
    #
    # Results are collected in the ORIGINAL BRANCH ORDER (not as_completed)
    # so that union_fill produces the same codeword-source assignment as the
    # serial path, guaranteeing byte-identical assembled payload.
    #
    # Data movement: audio_nom is passed to each worker via pickle (~6 ms for
    # the 27 MB gate float32 array, negligible vs 4–5 s/branch demod time).
    # For much larger arrays the _load_capture cache (.npy mmap) is preferred;
    # callers that pre-save audio_nom should pass the mmap'd array directly —
    # numpy pickle of a memory-mapped array serialises only the live data,
    # not the entire backing file.
    #
    # The serial path (parallel<=1) is unchanged and still benefits from the
    # WIN 1 early-exit break below.  inband CRC mode is threaded through both
    # the parallel worker (recomputed from sec) and the serial path.
    frontends = _frontends_for(sec)
    n_workers = parallel if (parallel is not None) else 1
    use_parallel = (n_workers >= 2 and len(frontends) >= 2)

    if use_parallel:
        # Submit all branches; collect in original order for deterministic union.
        # Each worker gets (audio_nom, sec, align, branch_idx); it reconstructs
        # the scheme and demodulator from branch_idx so no non-picklable objects
        # (lambdas, scheme instances) cross the process boundary.
        #
        # 'fork' context: inherits the parent's warm numpy/scipy (no re-import
        # overhead, no pocketfft plan re-build), avoids spawn startup time, and
        # resolves the sys.path ordering issue where analyze_master2 may have
        # promoted the main-repo tape_v2 above the worktree copy.  On macOS
        # fork is safe here because (a) no Cocoa/CoreFoundation calls happen in
        # the worker, and (b) numpy thread pools are forked quiescent (parent is
        # single-threaded at fork time).
        #
        # Thread-limit env vars (_MP_THREAD_VARS) cap each worker to 1 BLAS/OMP
        # thread so N worker processes use N cores total rather than N*T cores
        # where T is the default BLAS thread count.  Set before forking so the
        # child inherits them before numpy reads them.
        import multiprocessing as _mp
        _fork_ctx = _mp.get_context("fork")
        _saved = {v: os.environ.get(v) for v in _MP_THREAD_VARS}
        for _var in _MP_THREAD_VARS:
            os.environ[_var] = "1"
        try:
            worker_args = [(audio_nom, sec, align, idx)
                           for idx in range(len(frontends))]
            n_proc = min(n_workers, len(frontends))
            with ProcessPoolExecutor(max_workers=n_proc,
                                     mp_context=_fork_ctx) as pool:
                futures = [pool.submit(_mp_branch_worker, a)
                           for a in worker_args]
                par_results = [f.result() for f in futures]  # deterministic
        finally:
            for _var, _val in _saved.items():
                if _val is None:
                    os.environ.pop(_var, None)
                else:
                    os.environ[_var] = _val

        for (label, sch_rx, fe), (ok, msgs, rx_frames, local_ledger) in zip(
                frontends, par_results):
            failed = [int(i) for i in np.flatnonzero(~ok)]
            branch_records.append({"branch": label, "stage": "ensemble",
                                   "cw_failed": len(failed), "failed_idx": failed})
            branch_frames_pool.append((label, rx_frames))
            for k in ledger:
                ledger[k] += local_ledger[k]
            _union_fill(union_msgs, union_src, msgs, label)
            if best is None or len(failed) < best["cw_failed"]:
                best = {"branch": label, "cw_failed": len(failed),
                        "rx_frames": rx_frames}
            if verbose:
                print(f"    [{sec['name']}] {label}: {len(failed)}/{n_cw} [mp]",
                      flush=True)
    else:
        # Serial path (WIN 1): early-exit as soon as union is complete.
        for label, sch_rx, fe in frontends:
            rx_frames, _d = m9d._demod_section_frames(audio_nom, sec, align, sch_rx, fe)
            ok, msgs = _per_cw_decode(_rx_mat(rx_frames, meta), meta, crc, ledger,
                                      inband=inband)
            failed = [int(i) for i in np.flatnonzero(~ok)]
            branch_records.append({"branch": label, "stage": "ensemble",
                                   "cw_failed": len(failed), "failed_idx": failed})
            branch_frames_pool.append((label, rx_frames))
            _union_fill(union_msgs, union_src, msgs, label)
            if best is None or len(failed) < best["cw_failed"]:
                best = {"branch": label, "cw_failed": len(failed),
                        "rx_frames": rx_frames}
            if verbose:
                print(f"    [{sec['name']}] {label}: {len(failed)}/{n_cw}", flush=True)
            if not [i for i in range(n_cw) if union_msgs[i] is None]:
                break                                        # WIN 1: union complete

    still = [i for i in range(n_cw) if union_msgs[i] is None]

    # ---- pass 2: late-window dc0 (N256 DQPSK only) ------------------------
    lw_rec = None
    if rescue and still and sec["kind"] in ("dqpsk", "dqpsk_dropnull") \
            and sec["dqpsk_params"]["N"] == 256:
        lw = _late_window_branches(audio_nom, align, sec, sch_tx, verbose=verbose)
        lw_rec = {b: {"argmin_vec": lw[b]["argmin_vec"],
                      "dc0_evm_deg": lw[b]["dc0_evm_deg"],
                      "dc0_grid_gate": lw[b]["dc0_grid_gate"],
                      "branches": {}} for b in lw}
        for base in lw:
            for bn, frames in lw[base]["branches"].items():
                ok, msgs = _per_cw_decode(_rx_mat(frames, meta), meta, crc, ledger,
                                          inband=inband)
                failed = [int(i) for i in np.flatnonzero(~ok)]
                lw_rec[base]["branches"][bn] = {"cw_failed": len(failed)}
                branch_records.append({"branch": bn, "stage": "late_window",
                                       "cw_failed": len(failed),
                                       "failed_idx": failed})
                branch_frames_pool.append((bn, frames))
                _union_fill(union_msgs, union_src, msgs, bn)
                if len(failed) < best["cw_failed"]:
                    best = {"branch": bn, "cw_failed": len(failed),
                            "rx_frames": frames}
        still = [i for i in range(n_cw) if union_msgs[i] is None]

    # ---- pass 3: carrier-class erasure ladder (fill-only) -----------------
    ladder_rec = None
    rank = disp = None
    if rescue and still:
        rank, disp = _rank_carriers(audio_nom, align, sec, verbose=verbose)
        pool_sorted = sorted(
            branch_frames_pool,
            key=lambda bf: next(br["cw_failed"] for br in branch_records
                                if br["branch"] == bf[0]))
        branch_mats = [(bn, _rx_mat(frames, meta))
                       for bn, frames in pool_sorted[:N_LADDER_BRANCHES]]
        ladder_rec = _erasure_ladder(sec, meta, crc, branch_mats, union_msgs,
                                     union_src, rank, ledger, verbose=verbose,
                                     inband=inband)
        still = [i for i in range(n_cw) if union_msgs[i] is None]

    # ---- assemble + audit --------------------------------------------------
    if inband:
        # strip each codeword's in-band CRC and trim via the in-band header;
        # the result IS the original payload bytes (the sidecar), self-described.
        data_chunks = [None if m is None else m[:-ib.CRC_BYTES] for m in union_msgs]
        body, _hdr = ib.reassemble(data_chunks, meta["rs_k"])
        assembled = body if body is not None else b""
    else:
        assembled = _assemble(meta, union_msgs)
    byte_exact = assembled == expected_packed
    byte_err = sum(a != b for a, b in zip(assembled, expected_packed)) + abs(
        len(assembled) - len(expected_packed))
    misc = sum(1 for i in range(n_cw)
               if union_msgs[i] is not None and truth_msgs is not None
               and union_msgs[i] != truth_msgs[i])
    per_carrier_ser = m9d._per_carrier_ser(best["rx_frames"], sec, sch_tx,
                                           expected_packed) if best else None

    res = {
        "name": sec["name"], "kind": sec["kind"], "tier": sec.get("tier"),
        "role": sec.get("role", ""), "scheme": sec["phy"], "phy": sec["phy"],
        "status": sec.get("status", "ACTIVE"),
        "forensic_only": bool(sec.get("forensic_only")),
        "llm_offset": sec.get("llm_offset", 0),
        "payload_bytes": len(expected_packed),
        "n_frames": meta["n_frames"], "n_codewords": n_cw,
        "rs_n": meta["rs_n"], "rs_k": meta["rs_k"],
        "gross_bps": sec.get("gross_bps"),
        "projected_net_bps": sec.get("projected_net_bps"),
        "section_net_bps": sec.get("section_net_bps"),
        "x_record": sec.get("x_record"),
        "rs_codewords_failed": len(still),
        "miscorrected_cw": int(misc),
        "byte_errors": int(byte_err),
        "byte_exact": bool(byte_exact),
        "front_end_used": best["branch"] if best else None,
        "best_single_branch": {"branch": best["branch"],
                               "cw_failed": best["cw_failed"]} if best else None,
        "erase_frac_used": 0.0,
        "union_sources": sorted({s for s in union_src if s}),
        "rescued_cw": [
            {"cw": i, "source": union_src[i]} for i in range(n_cw)
            if union_src[i] and (union_src[i].startswith("lw_")
                                 or union_src[i].startswith("ladder:"))],
        "per_carrier_ser": per_carrier_ser,
        "branch_records": branch_records,
        "late_window": lw_rec,
        "ladder": ladder_rec,
        "carrier_rank_worst_first": rank,
        "carrier_dispersion_deg": disp,
        "elapsed_s": round(time.time() - t0, 1),
    }
    return res, assembled


# ===========================================================================
# capture-level driver with sync cache + chunkable sections + checkpointing
# ===========================================================================
def _load_capture(recording_path, manifest, tag, use_cache=True):
    nom_cache = CAP_DIR / f"x10_m10_nom_{tag}.npy"
    sync_cache = RESULTS_DIR / f"x10_m10_sync_{tag}.json"
    if use_cache and nom_cache.exists() and sync_cache.exists():
        audio_nom = np.load(nom_cache, mmap_mode="r")
        sync = json.loads(sync_cache.read_text())
        return audio_nom, sync, True
    audio, sr = sf.read(str(recording_path), dtype="float32", always_2d=False)
    if audio.ndim > 1:
        audio = audio.mean(axis=1)
    if sr != SR:
        frac = Fraction(SR, sr).limit_denominator(20000)
        audio = resample_poly(audio.astype(np.float64), frac.numerator,
                              frac.denominator)
    sync_full = am2.global_sync_and_resample(audio, manifest)
    audio_nom = sync_full["audio_nominal"]
    sync = {k: (float(v) if isinstance(v, (np.floating, float))
                else int(v) if isinstance(v, (np.integer, int)) else v)
            for k, v in sync_full.items() if k != "audio_nominal"}
    sync["align"] = int(sync_full["chirp0_nominal"]) - int(manifest["tx_chirp0"])
    try:
        sounder = am2.analyze_sounder(audio_nom, manifest, sync_full)
        sync["sounder"] = {k: v for k, v in (sounder or {}).items()
                           if k in ("flutter_wrms_pct", "snr_db_median",
                                    "noise_floor_dbfs", "speed_refine")}
    except Exception as exc:
        sync["sounder"] = {"error": str(exc)}
    if use_cache:
        CAP_DIR.mkdir(parents=True, exist_ok=True)
        RESULTS_DIR.mkdir(parents=True, exist_ok=True)
        np.save(nom_cache, np.asarray(audio_nom, np.float32))
        sync_cache.write_text(json.dumps(sync, indent=2, default=float))
    return audio_nom, sync, False


def decode(recording_path: str, out_tag: str | None = None,
           manifest_path: str | None = None, sections: list[str] | None = None,
           rescue: bool = True, verbose: bool = True, use_cache: bool = True,
           parallel: int | None = None) -> dict:
    mpath = _HERE / manifest_path if manifest_path else DEFAULT_MANIFEST
    manifest = json.loads(mpath.read_text())
    if manifest_path is None:
        assert manifest.get("master_id") == MASTER_ID, (
            f"manifest master_id {manifest.get('master_id')!r} != {MASTER_ID!r} "
            "-- refusing to decode against the wrong master (DO-NOT-PRINT guard)")
    tag = out_tag or pathlib.Path(recording_path).stem
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    json_path = RESULTS_DIR / f"x10_m10_results_{tag}.json"

    out = (json.loads(json_path.read_text()) if json_path.exists()
           else {"recording": str(recording_path), "tape": manifest.get("tape"),
                 "manifest": str(mpath.name), "decoder": "m10_decode (composed superset)",
                 "composition": ["ensemble_union(pll30+ema .5/.6/.65/.7/.8/.4)",
                                 f"late_window_dc0 N256 grid={list(DC0_GRID_WIDE)}",
                                 "carrier_class_erasure_ladder(<=60/cw)",
                                 "d2x rx_window_plan(hann256_skip0|rect128_skip64)",
                                 "strictly-additive CRC32-guarded fill-only"],
                 "ledger": {"rs_attempts": 0, "crc_checks": 0, "crc_rejects": 0,
                            "crc_accepts": 0},
                 "payloads_by_name": {}, "section_order": [
                     s["name"] for s in manifest["ws_payloads"]]})
    ledger = out["ledger"]

    audio_nom, sync, cached = _load_capture(recording_path, manifest, tag, use_cache)
    out["sync"] = {k: v for k, v in sync.items() if k != "sounder"}
    out["sounder"] = sync.get("sounder")
    align = int(sync["align"])
    if verbose:
        print(f"[m10_decode] {recording_path} (manifest={mpath.name}, "
              f"sync_cached={cached})")
        print(f"  clock {sync.get('speed', 0):.5f}x  align {align:+d}  "
              f"sounder {out['sounder']}", flush=True)

    for sec in manifest["ws_payloads"]:
        if sections and sec["name"] not in sections:
            continue
        if sec.get("skipped"):
            out["payloads_by_name"][sec["name"]] = {
                "name": sec["name"], "kind": sec["kind"], "skipped": True,
                "byte_exact": None}
            continue
        if sec["kind"] == "freqdiff":
            sounder_full = None
            try:
                sounder_full = am2.analyze_sounder(audio_nom, manifest, sync)
            except Exception:
                pass
            r, assembled = m9d._decode_freqdiff_section(audio_nom, sec, align,
                                                        sounder_full)
        else:
            r, assembled = _decode_section(audio_nom, sec, align, ledger,
                                           rescue=rescue, verbose=verbose,
                                           parallel=parallel)
        # ---- unpack + integrity (m9 pattern) ----
        pack = sec["pack"]
        crc_ok = unpack_ok = orig_exact = None
        try:
            recovered_orig = unpack_payload(assembled)
            unpack_ok = True
            sha_o = hashlib.sha256(recovered_orig).hexdigest()
            orig_exact = (sha_o == pack["sha256_orig"]
                          and len(recovered_orig) == pack["orig_len"])
            crc_ok = orig_exact
        except Exception as exc:
            unpack_ok = False
            r["unpack_error"] = str(exc)
        r["effective_bps"] = sec.get("effective_bps")
        r["pack_algo"] = pack["algo"]
        r["orig_len"] = pack["orig_len"]
        r["packed_len"] = pack["packed_len"]
        r["unpack_ok"] = unpack_ok
        r["orig_byte_exact"] = orig_exact
        r["crc_check"] = crc_ok
        out["payloads_by_name"][sec["name"]] = r
        # checkpoint after every section
        results = [out["payloads_by_name"][n] for n in out["section_order"]
                   if n in out["payloads_by_name"]]
        out["payloads"] = results
        out["n_byte_exact_packed"] = sum(bool(x.get("byte_exact")) for x in results)
        out["n_orig_exact"] = sum(bool(x.get("orig_byte_exact")) for x in results)
        out["n_payloads"] = len(results)
        out["false_accept_bound"] = ledger["crc_checks"] * 2.0 ** -32
        out["fa_within_budget"] = bool(out["false_accept_bound"] < FA_BUDGET)
        json_path.write_text(json.dumps(out, indent=2, default=float))
        if verbose:
            print(f"  [{r['name']:28s}] cw {r.get('rs_codewords_failed')}/"
                  f"{r.get('n_codewords')} fe={r.get('front_end_used')} "
                  f"PACK={'YES' if r.get('byte_exact') else 'no'} "
                  f"ORIG={'YES' if r.get('orig_byte_exact') else 'no'} "
                  f"({r.get('elapsed_s')}s) -> checkpointed", flush=True)

    if verbose:
        _print_table(recording_path, sync, out)
        print(f"[m10_decode] wrote {json_path}")
    return out


def _print_table(recording_path, sync, out):
    results = out.get("payloads", [])
    print(f"\n[m10_decode] {recording_path}")
    print(f"  recovered clock: {sync.get('speed', 0):.4f}x, align "
          f"{sync.get('align', 0):+d}, fa_bound {out.get('false_accept_bound', 0):.2e}")
    print(f"\n  {'rung':<28} {'phy':<26} {'RS':>9} {'net':>7} "
          f"{'cwFail':>8} {'front-end':>22} {'PACK':>5} {'ORIG':>5}")
    for r in results:
        if r.get("skipped"):
            print(f"  {r['name']:<28} (skipped)")
            continue
        rs = f"({r.get('rs_n')},{r.get('rs_k')})"
        cw = f"{r.get('rs_codewords_failed')}/{r.get('n_codewords')}"
        pk = "YES" if r.get("byte_exact") else "no"
        og = "YES" if r.get("orig_byte_exact") else "no"
        fe = (r.get("front_end_used") or "-")[:22]
        net = r.get("section_net_bps") or r.get("projected_net_bps") or 0
        tag = " [FORENSIC]" if r.get("forensic_only") else ""
        print(f"  {r['name']:<28} {r['phy']:<26} {rs:>9} {net:7.0f} "
              f"{cw:>8} {fe:>22} {pk:>5} {og:>5}{tag}")
    n_pk = out.get("n_byte_exact_packed", 0)
    n_og = out.get("n_orig_exact", 0)
    print(f"\n  byte-exact (packed): {n_pk}/{len(results)}   "
          f"orig-exact (unpacked): {n_og}/{len(results)}")
    ex = [r for r in results if r.get("orig_byte_exact")
          and not r.get("forensic_only")]
    if ex:
        bestr = max(ex, key=lambda r: r.get("projected_net_bps") or 0)
        print(f"  best orig-exact RECORD-BEARING rung: {bestr['name']} -> "
              f"net {bestr.get('projected_net_bps'):.0f} bps "
              f"(x{bestr.get('x_record')}, {bestr.get('front_end_used')})")
    canary = next((r for r in results if r.get("name", "").endswith("r0_canary_2572")), None)
    if canary is not None:
        ok = bool(canary.get("orig_byte_exact"))
        print(f"  r0 canary reproved 2572: {'YES' if ok else 'NO -- TAPE PASS VOID'}")


if __name__ == "__main__":
    import warnings
    warnings.filterwarnings("ignore")
    ap = argparse.ArgumentParser()
    ap.add_argument("recording")
    ap.add_argument("--out-tag", default=None)
    ap.add_argument("--manifest", default=None,
                    help="alternate manifest (e.g. master9_manifest.json) for "
                         "composed-regression decodes of older captures")
    ap.add_argument("--sections", default="",
                    help="comma-separated section names (chunked runs merge "
                         "into the same results JSON)")
    ap.add_argument("--no-rescue", action="store_true",
                    help="pass-1 ensemble union only (no late-window/ladder)")
    ap.add_argument("--no-cache", action="store_true")
    ap.add_argument("--parallel", type=int, default=None,
                    help="run front-end bank with this many threads (default: serial)")
    args = ap.parse_args()
    decode(args.recording, args.out_tag, manifest_path=args.manifest,
           sections=[s for s in args.sections.split(",") if s] or None,
           rescue=not args.no_rescue, use_cache=not args.no_cache,
           parallel=args.parallel)
