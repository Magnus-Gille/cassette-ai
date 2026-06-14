"""x10_b_cons_01_late_window_dc0.py -- per-carrier DFT window placement at N256.

CANDIDATE: B-cons-01-late-window-dc0 (merged with B-aggr-01-dc0-splitwindow).

Forensics (x10_forensics_errors.json) showed the 2632-2896 bps N256 rungs on
tape9_run1 are killed by previous-symbol ISI on data carrier 0 (750 Hz):
sliding the N256 analysis window late takes dc0 from SER 0.576 @ -24 smp to
0.132 @ +32 smp, while top carriers (6750-8250 Hz) prefer CENTER placement.
This experiment stitches a per-carrier window-placement receiver: dc0 decoded
from a LATE analysis window, every other carrier from its own (near-center)
best window, composed per-carrier into one quadrant matrix, then the proven
CRC32-guarded RS union-bank merge (x10_union_probe pattern, erase_frac=0).

PRE-REGISTERED SEARCH SPACE (frozen before any decode; do not widen):
  * scalar dc0 late-shift branches: S in {16, 24, 32, 40} samples
    (dc0 at +S, all other data carriers at 0)
  * decoupled-argmin stitched branch: dc0 shift in {0,+8,+16,+24,+32,+40},
    data carriers 1..P-1 each in {-8, 0, +8}, selected per-carrier
    INDEPENDENTLY by the truth-free statistic below (no cross-product).
PRE-REGISTERED TRUTH-FREE SELECTION STATISTIC:
  per (data carrier, shift) cell: decision-EVM = mean |angular distance of the
  post-refine differential phase to the nearest QPSK decision centroid| over
  ALL data symbols of ALL frames of the section.  Per-carrier argmin.
  (The pilot carrier is never stitched: it stays at the base front-end's own
  window and drives the timing tracking exactly as in the proven chain.)
BASE FRONT-ENDS for the stitched passes (declared before any decode):
  * ema0.6  -- the m9 winner on m4/m5/m6 and the base of the forensics
               window-shift evidence (probe2 default alpha=0.6).
  * pll30   -- the m9 winner on m7; the plan's "subclass ResamplingPLLDemod"
               language covers both modes. Stitching applies to the Pass-2
               DFT on the PLL-resampled stream (no superset selector -- the
               branch is purely additive in the CRC-guarded union).
  5 registered branches per base (4 scalar + 1 argmin) = 10 stitched branches.
PASS-2 FALLBACK (pre-registered): on codewords still failed after the union,
  errors-AND-erasures RS where the erased byte positions are ONLY bytes
  containing >=1 dc0 bit on which the base's center (shift 0) and the selected
  late dc0 decisions DISAGREE.  CRC32-guarded.  No blanket positional erasure.

Everything is CRC32-per-codeword guarded (manifest crc table). Sidecar bytes
are used for SCORING/post-hoc-miscorrection-verification only, never inside a
decision.  All CRC-acceptance trials are counted into a ledger (campaign
false-accept budget < 1e-4; each trial's false-accept prob <= 2^-32).

Usage (each invocation < 8 min; checkpointed):
  OPENBLAS_NUM_THREADS=2 OMP_NUM_THREADS=2 python3 \
      experiments/tape_v2/x10_b_cons_01_late_window_dc0.py frontier
  ... regress-tape9 | regress-m8 | regress-ws | summarize

Output: experiments/tape_v2/results/x10_late_window_tape9_run1.json
Seeds: deterministic (no RNG anywhere).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import sys
import time
import zlib
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

import analyze_master2 as am2                       # noqa: E402
import m3_codec as codec                            # noqa: E402
import m9_decode as md                              # noqa: E402 (read-only import)
import hyp_common as hc                             # noqa: E402
from h4_dqpsk import FS, PAD_LO_S, PAD_HI_S         # noqa: E402
from h9_payload_codec import unpack_payload         # noqa: E402
from x9_resampling_pll import ResamplingPLLDemod, _pi_loop_gains  # noqa: E402
from reedsolo import RSCodec, ReedSolomonError      # noqa: E402

SR = codec.FS
OUT_JSON = _HERE / "results" / "x10_late_window_tape9_run1.json"

# ---------------------------------------------------------------------------
# PRE-REGISTERED constants (frozen before any decode -- see module docstring)
# ---------------------------------------------------------------------------
SCALAR_S = (16, 24, 32, 40)
DC0_GRID = (0, 8, 16, 24, 32, 40)
OTHER_GRID = (-8, 0, 8)
ALL_SHIFTS = tuple(sorted(set(SCALAR_S) | set(DC0_GRID) | set(OTHER_GRID)))
BASES = ("ema0.6", "pll30")
# 6-FE baseline ensemble = exactly the x10_union_probe registered set
BASELINE_FRONTENDS = (("resampling_pll30", dict(front_end="pll", pll_bw_hz=30.0)),
                      ("ema0.5", dict(front_end="ema", ema_alpha=0.5)),
                      ("ema0.6", dict(front_end="ema", ema_alpha=0.6)),
                      ("ema0.65", dict(front_end="ema", ema_alpha=0.65)),
                      ("ema0.7", dict(front_end="ema", ema_alpha=0.7)),
                      ("ema0.8", dict(front_end="ema", ema_alpha=0.8)))
FRONTIER = ("m9_m4_n256_rs159", "m9_m5_n256_rs179",
            "m9_m6_n256_rs191", "m9_m7_n256_p11_9000")
# tape9 landed rungs (regression): documented m9 winner front-end per rung
TAPE9_LANDED = (("m9_m0_reprove934", "pll30"), ("m9_m1_thin159", "pll30"),
                ("m9_m2_thin191", "pll30"), ("m9_m3_dropnull9c", "pll30"),
                ("m9_m4b_n256_rs159_var", "ema0.6"), ("m9_m8_dense375", "pll30"))

TAPE9_CACHE = _HERE / "captures" / "x10_audio_nom_tape9_run1.npy"
TAPE9_SYNC = _HERE / "results" / "x10_forensics_sync.json"
M8_CACHE = _HERE / "captures" / "x10_lw_audio_nom_m8_lossless.npy"
M8_SYNC = _HERE / "results" / "x10_lw_sync_m8_lossless.json"


# ===========================================================================
# results-JSON checkpointing
# ===========================================================================
def _load_out() -> dict:
    if OUT_JSON.exists():
        return json.loads(OUT_JSON.read_text())
    return {"experiment": "x10_b_cons_01_late_window_dc0",
            "capture_primary": "captures/tape9_run1.wav",
            "deterministic": True,
            "pre_registered": {
                "scalar_S": list(SCALAR_S), "dc0_grid": list(DC0_GRID),
                "other_grid": list(OTHER_GRID), "bases": list(BASES),
                "statistic": "decision-EVM = mean |wrapped(dphi_postrefine - "
                             "q*pi/2)| per (data carrier, shift), per-carrier "
                             "argmin; pilot never stitched",
                "pass2": "disagreement-gated dc0 erasures only",
            },
            "trial_ledger": {"rs_decode_attempts": 0, "crc_checks": 0,
                             "crc_rejects": 0, "crc_accepts": 0},
            "sections": {}, "regression": {}}


def _save_out(out: dict):
    OUT_JSON.parent.mkdir(exist_ok=True)
    OUT_JSON.write_text(json.dumps(out, indent=2, default=float))


def _ledger_add(out, attempts, checks, rejects, accepts):
    led = out["trial_ledger"]
    led["rs_decode_attempts"] += int(attempts)
    led["crc_checks"] += int(checks)
    led["crc_rejects"] += int(rejects)
    led["crc_accepts"] += int(accepts)


# ===========================================================================
# capture loading (nominal-clock cache, forensics pattern)
# ===========================================================================
def _load_tape9():
    if not TAPE9_CACHE.exists() or not TAPE9_SYNC.exists():
        manifest = json.loads((_HERE / "master9_manifest.json").read_text())
        audio, sr = sf.read(str(_HERE / "captures" / "tape9_run1.wav"),
                            dtype="float32", always_2d=False)
        if audio.ndim > 1:
            audio = audio.mean(axis=1)
        assert sr == SR
        sync = am2.global_sync_and_resample(audio, manifest)
        np.save(TAPE9_CACHE, sync["audio_nominal"].astype(np.float32))
        meta = {k: (float(v) if isinstance(v, np.floating) else int(v))
                for k, v in sync.items() if k != "audio_nominal"}
        meta["align"] = int(sync["chirp0_nominal"]) - int(manifest["tx_chirp0"])
        TAPE9_SYNC.write_text(json.dumps(meta, indent=2, default=float))
    audio_nom = np.load(TAPE9_CACHE, mmap_mode="r")
    sync = json.loads(TAPE9_SYNC.read_text())
    manifest = json.loads((_HERE / "master9_manifest.json").read_text())
    return audio_nom, int(sync["align"]), manifest


def _load_m8_lossless():
    manifest = json.loads((_HERE / "master8_manifest.json").read_text())
    if not M8_CACHE.exists() or not M8_SYNC.exists():
        audio, sr = sf.read(str(_HERE / "captures" / "m8_tape_mono_lossless.wav"),
                            dtype="float32", always_2d=False)
        if audio.ndim > 1:
            audio = audio.mean(axis=1)
        if sr != SR:
            frac = Fraction(SR, sr).limit_denominator(20000)
            audio = resample_poly(audio.astype(np.float64),
                                  frac.numerator, frac.denominator)
        sync = am2.global_sync_and_resample(audio, manifest)
        np.save(M8_CACHE, sync["audio_nominal"].astype(np.float32))
        meta = {k: (float(v) if isinstance(v, np.floating) else int(v))
                for k, v in sync.items() if k != "audio_nominal"}
        meta["align"] = int(sync["chirp0_nominal"]) - int(manifest["tx_chirp0"])
        M8_SYNC.write_text(json.dumps(meta, indent=2, default=float))
    audio_nom = np.load(M8_CACHE, mmap_mode="r")
    sync = json.loads(M8_SYNC.read_text())
    return audio_nom, int(sync["align"]), manifest


# ===========================================================================
# shifted-window DFT passes (forensics-faithful; self-contained copies of the
# x10_forensics_errors instrumented loops -- NOT imported, to keep this file
# self-contained per the no-x10_common rule)
# ===========================================================================
def _shift_pass_ema(sch, y, ds, total, alpha, shift):
    """h4/x9 EMA integer-drift loop with the analysis window slid by `shift`
    samples inside the symbol; pilot tracked AT the shifted window (exactly the
    forensics probe2 measurement methodology)."""
    N, skip, Nw = sch.N, sch.skip, sch.Nw
    win = sch._win
    freqs = sch.freqs
    fpil = sch.freqs[sch.pilot_idx]
    pidx = sch.pilot_idx
    c = np.zeros((total, len(freqs)), np.complex128)
    dtau = np.zeros(total)
    drift = 0.0
    sm = 0.0
    for i in range(total):
        base = ds + i * N + int(round(drift))
        lo = base + skip + shift
        seg = y[lo: lo + Nw] if lo >= 0 else np.zeros(0)
        if len(seg) < Nw:
            seg = np.concatenate([seg, np.zeros(Nw - len(seg))])
        tt = (lo + np.arange(Nw)) / FS
        E = np.exp(-2j * np.pi * np.outer(freqs, tt))
        c[i] = E @ (seg * win)
        if i > 0:
            dp = float(np.angle(c[i, pidx] * np.conj(c[i - 1, pidx])))
            sm = (1 - alpha) * (dp / (2 * np.pi * fpil)) + alpha * sm
            dtau[i] = sm
            drift -= dtau[i] * FS
            drift = float(np.clip(drift, -200, 200))
    return c, dtau


def _pll_warp(sch, y, ds, total, *, alpha=0.5, bw=30.0, zeta=0.707):
    """Replicates ResamplingPLLDemod._demod_pll Pass1 (EMA track) + PI loop +
    resample; returns the warped stream y2 (shift-independent)."""
    N = sch.N
    _c1, dtau_ema = _shift_pass_ema(sch, y, ds, total, alpha, 0)
    kp, ki = _pi_loop_gains(bw, sch.N / FS, zeta)
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
    tau_t = np.interp(tgrid, sym_centers, tau_sym,
                      left=tau_sym[0], right=tau_sym[-1])
    src = np.clip(tgrid - tau_t * FS, 0.0, len(y) - 1.0)
    y2 = y.copy()
    y2[body_lo:body_hi] = np.interp(src, np.arange(len(y)), y)
    return y2


def _shift_pass_pll(sch, y2, ds, total, shift):
    """Pass-2 DFT on the PLL-resampled stream with the window slid by `shift`;
    residual pilot dtau re-read at that shift (mirrors _demod_pll Pass 2)."""
    N, skip, Nw = sch.N, sch.skip, sch.Nw
    win = sch._win
    freqs = sch.freqs
    fpil = sch.freqs[sch.pilot_idx]
    pidx = sch.pilot_idx
    c = np.zeros((total, len(freqs)), np.complex128)
    for i in range(total):
        lo = ds + i * N + skip + shift
        seg = y2[lo: lo + Nw] if lo >= 0 else np.zeros(0)
        if len(seg) < Nw:
            seg = np.concatenate([seg, np.zeros(Nw - len(seg))])
        tt = (lo + np.arange(Nw)) / FS
        E = np.exp(-2j * np.pi * np.outer(freqs, tt))
        c[i] = E @ (seg * win)
    dtau = np.zeros(total)
    for i in range(1, total):
        dp = float(np.angle(c[i, pidx] * np.conj(c[i - 1, pidx])))
        dtau[i] = dp / (2 * np.pi * fpil)
    return c, dtau


def _decide_refine(sch, c, dtau):
    """Replica of x9 _decide (refine=True) that also returns the post-refine
    differential phase and the per-symbol residual to decided centroids."""
    fd = sch.freqs[sch.data_idx]
    d = c[1:, :] * np.conj(c[:-1, :])
    dphi = np.angle(d[:, sch.data_idx]) - 2 * np.pi * np.outer(dtau[1:], fd)
    q = np.round(dphi / (np.pi / 2.0)).astype(int) % 4
    res = (dphi - q * (np.pi / 2.0) + np.pi) % (2 * np.pi) - np.pi
    num = (res * fd[None, :]).sum(axis=1)
    den = (fd ** 2).sum()
    dtau_dd = num / (2 * np.pi * den)
    dphi = dphi - 2 * np.pi * dtau_dd[:, None] * fd[None, :]
    q = np.round(dphi / (np.pi / 2.0)).astype(int) % 4
    res = (dphi - q * (np.pi / 2.0) + np.pi) % (2 * np.pi) - np.pi
    return q, res


# ===========================================================================
# RS/CRC helpers (x10_union_probe pattern, self-contained)
# ===========================================================================
def _rx_mat(rx_frames, meta):
    fb_bits, n_frames = meta["frame_bits"], meta["n_frames"]
    stream_bits = meta["stream_bits"]
    rs_n, n_cw = meta["rs_n"], meta["n_codewords"]
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
    return rx_bytes.reshape(rs_n, n_cw).T


def _per_cw_decode(rx_mat, meta, crc_table, *, erase_pos_per_cw=None):
    """Errors-only (or errors-and-erasures) RS per codeword + CRC32 guard.
    Returns (ok_mask, msgs, ledger_tuple)."""
    rs_n, rs_k, n_cw = meta["rs_n"], meta["rs_k"], meta["n_codewords"]
    rsc = RSCodec(rs_n - rs_k)
    ok = np.zeros(n_cw, bool)
    msgs: list[bytes | None] = [None] * n_cw
    attempts = checks = rejects = accepts = 0
    for i in range(n_cw):
        epos = (erase_pos_per_cw or {}).get(i, [])
        attempts += 1
        try:
            row = bytearray(rx_mat[i].tobytes())
            dec = rsc.decode(row, erase_pos=epos)[0] if epos else rsc.decode(row)[0]
            msg = bytes(dec)
        except (ReedSolomonError, Exception):
            continue
        checks += 1
        if i < len(crc_table) and (zlib.crc32(msg) & 0xFFFFFFFF) != crc_table[i]:
            rejects += 1
            continue
        accepts += 1
        ok[i] = True
        msgs[i] = msg
    return ok, msgs, (attempts, checks, rejects, accepts)


def _assemble(meta, msgs):
    out = bytearray()
    for i in range(meta["n_codewords"]):
        out += msgs[i] if msgs[i] is not None else bytes(meta["rs_k"])
    return bytes(out)[:meta["payload_len"]]


def _truth_msgs(expected_packed, meta):
    """Truth message bytes per codeword (post-hoc miscorrection check only)."""
    rs_k, n_cw = meta["rs_k"], meta["n_codewords"]
    padded = expected_packed + bytes(max(0, n_cw * rs_k - len(expected_packed)))
    return [padded[i * rs_k:(i + 1) * rs_k] for i in range(n_cw)]


def _nominal_bits(meta):
    fb, n = meta["frame_bits"], meta["n_frames"]
    return [fb] * (n - 1) + [meta["stream_bits"] - fb * (n - 1)]


# ===========================================================================
# core: stitched-shift decode of one DQPSK section on one base front-end
# ===========================================================================
def run_stitched_section(audio_nom, align, sec, base, verbose=True):
    """Runs all ALL_SHIFTS passes for `base` over every frame of `sec`;
    returns dict with per-(carrier,shift) decision-EVM, per-branch stitched
    rx_frames bits, q matrices per shift per frame."""
    sch = md._scheme_from_entry(sec)
    meta = sec["meta"]
    nom_bits = _nominal_bits(meta)
    pad_lo, pad_hi = int(PAD_LO_S * SR), int(PAD_HI_S * SR)
    flen_full = len(np.asarray(sch.modulate(np.zeros(meta["frame_bits"], np.uint8))))
    P = len(sch.data_idx)

    q_by_shift = {s: [] for s in ALL_SHIFTS}        # per frame: (nd, P) int8
    evm_sum = np.zeros((P, len(ALL_SHIFTS)))
    evm_n = np.zeros((P, len(ALL_SHIFTS)))

    t0 = time.time()
    for fi, st in enumerate(sec["frame_starts"]):
        nd = sch.nsym_data(nom_bits[fi])
        total = nd + 1
        st = int(st) + align
        w_lo = max(0, st - pad_lo)
        w_hi = min(len(audio_nom), st + flen_full + pad_hi)
        y = np.asarray(audio_nom[w_lo:w_hi], np.float64)
        ds = int(hc.find_preamble(y.astype(np.float32), sch.preamble_seconds))
        y2 = _pll_warp(sch, y, ds, total) if base == "pll30" else None
        for si, s in enumerate(ALL_SHIFTS):
            if base == "pll30":
                c, dtau = _shift_pass_pll(sch, y2, ds, total, s)
            else:                                    # ema0.6
                c, dtau = _shift_pass_ema(sch, y, ds, total, 0.6, s)
            q, res = _decide_refine(sch, c, dtau)
            q_by_shift[s].append(q.astype(np.int8))
            evm_sum[:, si] += np.abs(res).sum(axis=0)
            evm_n[:, si] += res.shape[0]
    evm = evm_sum / np.maximum(evm_n, 1)

    # ---- pre-registered per-carrier argmin (truth-free) -------------------
    sidx = {s: i for i, s in enumerate(ALL_SHIFTS)}
    vec = np.zeros(P, int)
    vec[0] = DC0_GRID[int(np.argmin([evm[0, sidx[s]] for s in DC0_GRID]))]
    for j in range(1, P):
        vec[j] = OTHER_GRID[int(np.argmin([evm[j, sidx[s]] for s in OTHER_GRID]))]

    # ---- branch construction ----------------------------------------------
    branches = {}
    for S in SCALAR_S:
        bvec = np.zeros(P, int)
        bvec[0] = S
        branches[f"{base}_S{S}"] = bvec
    branches[f"{base}_argmin"] = vec

    def stitch(bvec):
        frames = []
        for fi in range(len(q_by_shift[0])):
            qs = q_by_shift[bvec[0]][fi].copy()
            for j in range(P):
                qs[:, j] = q_by_shift[int(bvec[j])][fi][:, j]
            frames.append(np.asarray(sch.quadrants_to_bits(qs.astype(int)), np.uint8))
        return frames

    branch_frames = {bn: stitch(bv) for bn, bv in branches.items()}
    if verbose:
        print(f"  [{sec['name']} base={base}] {len(sec['frame_starts'])} frames x "
              f"{len(ALL_SHIFTS)} shifts in {time.time()-t0:.1f}s; "
              f"argmin vec={vec.tolist()}", flush=True)
    return {"sch": sch, "evm": evm, "argmin_vec": vec.tolist(),
            "branches": {bn: bv.tolist() for bn, bv in branches.items()},
            "branch_frames": branch_frames, "q_by_shift": q_by_shift}


# ===========================================================================
# dc0 stream-bit -> codeword-byte mapping (for pass-2 disagreement erasures)
# ===========================================================================
def _dc0_disagree_erasures(sec, q_center, q_sel, meta, sch):
    """Byte positions per codeword whose 8 stream bits include >=1 dc0 bit on
    which center (shift 0) and the selected dc0 pass disagree."""
    fb_bits = meta["frame_bits"]
    n_cw, rs_n = meta["n_codewords"], meta["rs_n"]
    nom = _nominal_bits(meta)
    epos: dict[int, set] = {}
    for fi in range(meta["n_frames"]):
        nb = nom[fi]
        nd = sch.nsym_data(nb)
        qc = q_center[fi][:, 0]
        ql = q_sel[fi][:, 0]
        lim = min(2 * nd, nb)
        for sym in range(nd):
            if qc[sym] == ql[sym]:
                continue
            for b in (2 * sym, 2 * sym + 1):
                if b >= lim:
                    continue
                pos = fi * fb_bits + b
                sbyte = pos // 8
                if sbyte >= n_cw * rs_n:
                    continue
                cw, bytep = sbyte % n_cw, sbyte // n_cw
                epos.setdefault(cw, set()).add(int(bytep))
    return {cw: sorted(v) for cw, v in epos.items()}


# ===========================================================================
# per-carrier SER vs truth (scoring only; m9_decode._per_carrier_ser math)
# ===========================================================================
def _per_carrier_ser(rx_frames, sec, sch, expected_packed):
    from m3_codec import Rung
    meta = sec["meta"]
    rung = Rung(name=meta["rung"], M=meta["M"], K=meta["K"], rs_n=meta["rs_n"],
                rs_k=meta["rs_k"], frame_bytes=meta["frame_bytes"])
    tx_frames, _ = codec.encode_payload(expected_packed, rung)
    P = len(sch.data_idx)
    car_err = np.zeros(P, int)
    car_tot = np.zeros(P, int)
    for fi in range(min(len(tx_frames), len(rx_frames))):
        tb = np.asarray(tx_frames[fi], np.uint8)
        rb = np.asarray(rx_frames[fi], np.uint8)
        m = min(len(tb), len(rb))
        if m == 0:
            continue
        tq = sch.bits_to_quadrants(tb[:m])
        rq = sch.bits_to_quadrants(rb[:m])
        k = min(len(tq), len(rq))
        car_err += (tq[:k] != rq[:k]).sum(axis=0)
        car_tot += k
    return [round(float(e) / max(1, t), 5) for e, t in zip(car_err, car_tot)]


# ===========================================================================
# frontier: full pipeline on tape9 m4/m5/m6/m7
# ===========================================================================
def frontier(section_filter=None):
    out = _load_out()
    audio_nom, align, manifest = _load_tape9()
    secs = {s["name"]: s for s in manifest["ws_payloads"]}
    names = [n for n in FRONTIER if section_filter is None or n in section_filter]
    for name in names:
        t0 = time.time()
        sec = secs[name]
        sch = md._scheme_from_entry(sec)
        meta = sec["meta"]
        crc = sec["crc32_codewords"]
        expected = (_HERE / sec["payload_sidecar"]).read_bytes()
        truth = _truth_msgs(expected, meta)
        n_cw = meta["n_codewords"]
        rec = {"rs_k": meta["rs_k"], "n_codewords": n_cw,
               "net_bps": sec.get("projected_net_bps"), "baseline_fe": {},
               "stitched": {}, "miscorrections_vs_truth": 0}

        # ---- 6-FE baseline ensemble (fresh re-run, union-probe order) -----
        ordered_msgs: list[tuple[str, list]] = []
        for fe_name, kw in BASELINE_FRONTENDS:
            dem = ResamplingPLLDemod(sch, **kw)
            rx_frames, _d = md._demod_section_frames(
                audio_nom, sec, align, sch, lambda w, nd, d=dem: d.demod(w, nd))
            ok, msgs, led = _per_cw_decode(_rx_mat(rx_frames, meta), meta, crc)
            _ledger_add(out, *led)
            mis = sum(1 for i in range(n_cw)
                      if msgs[i] is not None and msgs[i] != truth[i])
            rec["miscorrections_vs_truth"] += mis
            failed = [int(i) for i in np.flatnonzero(~ok)]
            rec["baseline_fe"][fe_name] = {"cw_failed": len(failed),
                                           "failed_idx": failed}
            ordered_msgs.append((fe_name, msgs))
            print(f"[{name}] {fe_name}: {len(failed)}/{n_cw} {failed}", flush=True)

        def union_of(msg_lists):
            u: list[bytes | None] = [None] * n_cw
            for _n, msgs in msg_lists:
                for i in range(n_cw):
                    if u[i] is None and msgs[i] is not None:
                        u[i] = msgs[i]
            failed = [i for i in range(n_cw) if u[i] is None]
            return u, failed

        _u, base_failed = union_of(ordered_msgs)
        rec["union_baseline"] = {"cw_failed": len(base_failed),
                                 "failed_idx": base_failed}
        print(f"[{name}] UNION-BASELINE: {len(base_failed)}/{n_cw} "
              f"{base_failed}", flush=True)

        # ---- stitched branches on both bases ------------------------------
        stitch_info = {}
        for base in BASES:
            si = run_stitched_section(audio_nom, align, sec, base)
            stitch_info[base] = si
            evm_tab = {str(s): [round(float(np.degrees(si["evm"][j, ai])), 2)
                                for j in range(si["evm"].shape[0])]
                       for ai, s in enumerate(ALL_SHIFTS)}
            rec["stitched"][base] = {"argmin_vec": si["argmin_vec"],
                                     "decision_evm_deg_by_shift": evm_tab,
                                     "branches": {}}
            for bn, bv in si["branches"].items():
                rx_frames = si["branch_frames"][bn]
                ok, msgs, led = _per_cw_decode(_rx_mat(rx_frames, meta), meta, crc)
                _ledger_add(out, *led)
                mis = sum(1 for i in range(n_cw)
                          if msgs[i] is not None and msgs[i] != truth[i])
                rec["miscorrections_vs_truth"] += mis
                failed = [int(i) for i in np.flatnonzero(~ok)]
                ser = _per_carrier_ser(rx_frames, sec, sch, expected)
                rec["stitched"][base]["branches"][bn] = {
                    "vec": bv, "cw_failed": len(failed), "failed_idx": failed,
                    "per_carrier_ser": ser, "dc0_ser": ser[0]}
                ordered_msgs.append((bn, msgs))
                print(f"[{name}] {bn} vec={bv}: {len(failed)}/{n_cw} {failed} "
                      f"dc0_ser={ser[0]:.3f}", flush=True)

        # ---- unions --------------------------------------------------------
        reg_lists = ordered_msgs[:6] + [m for m in ordered_msgs[6:]
                                        if m[0].startswith("ema0.6_")]
        _u, reg_failed = union_of(reg_lists)
        rec["union_plus_registered_ema06"] = {"cw_failed": len(reg_failed),
                                              "failed_idx": reg_failed}
        union_msgs, all_failed = union_of(ordered_msgs)
        rec["union_plus_all"] = {"cw_failed": len(all_failed),
                                 "failed_idx": all_failed}
        print(f"[{name}] UNION+ema06-stitched: {len(reg_failed)}/{n_cw} "
              f"{reg_failed} | UNION+all: {len(all_failed)}/{n_cw} {all_failed}",
              flush=True)

        # ---- pass-2: disagreement-gated dc0 erasures on still-failed cws ---
        pass2 = {"attempted": [], "recovered": []}
        if all_failed:
            for base in BASES:
                si = stitch_info[base]
                vec = si["argmin_vec"]
                if vec[0] == 0:
                    continue
                q_center = si["q_by_shift"][0]
                q_sel = si["q_by_shift"][vec[0]]
                ep = _dc0_disagree_erasures(sec, q_center, q_sel, meta, sch)
                rx_frames = si["branch_frames"][f"{base}_argmin"]
                rxm = _rx_mat(rx_frames, meta)
                still = [i for i in all_failed]
                ep_f = {i: ep.get(i, []) for i in still if ep.get(i)}
                if not ep_f:
                    continue
                oks, msgs2, led = _per_cw_decode(
                    rxm, meta, crc,
                    erase_pos_per_cw={i: ep_f.get(i, []) for i in still})
                # only count/use the still-failed rows we actually targeted
                _ledger_add(out, *led)
                for i in still:
                    pass2["attempted"].append(
                        {"cw": i, "base": base, "n_erase": len(ep_f.get(i, []))})
                    if msgs2[i] is not None and union_msgs[i] is None:
                        if msgs2[i] != truth[i]:
                            rec["miscorrections_vs_truth"] += 1
                        union_msgs[i] = msgs2[i]
                        pass2["recovered"].append({"cw": i, "base": base})
            all_failed = [i for i in range(n_cw) if union_msgs[i] is None]
        rec["pass2"] = pass2
        rec["union_final"] = {"cw_failed": len(all_failed),
                              "failed_idx": all_failed}

        # ---- assembly + orig verification ----------------------------------
        assembled = _assemble(meta, union_msgs)
        rec["byte_exact_packed"] = assembled == expected
        rec["byte_errors"] = sum(a != b for a, b in zip(assembled, expected)) \
            + abs(len(assembled) - len(expected))
        pack = sec["pack"]
        try:
            orig = unpack_payload(assembled)
            rec["orig_exact"] = (hashlib.sha256(orig).hexdigest() == pack["sha256_orig"]
                                 and len(orig) == pack["orig_len"])
        except Exception as exc:
            rec["orig_exact"] = False
            rec["unpack_error"] = str(exc)
        rec["elapsed_s"] = round(time.time() - t0, 1)
        out["sections"][name] = rec
        _save_out(out)
        print(f"[{name}] FINAL union {len(all_failed)}/{n_cw} byte_exact="
              f"{rec['byte_exact_packed']} orig_exact={rec.get('orig_exact')} "
              f"({rec['elapsed_s']}s) -> checkpointed", flush=True)


# ===========================================================================
# regression: tape9 landed rungs + m8-lossless DQPSK rung
# ===========================================================================
def _regress_dqpsk(audio_nom, align, sec, winner, out, tag):
    """Run the documented winner FE + all 10 stitched branches; union must
    stay 0 cw failed; every CRC-accepted stitched msg must equal truth."""
    sch = md._scheme_from_entry(sec)
    meta = sec["meta"]
    crc = sec["crc32_codewords"]
    expected = (_HERE / sec["payload_sidecar"]).read_bytes()
    truth = _truth_msgs(expected, meta)
    n_cw = meta["n_codewords"]
    t0 = time.time()
    kw = dict(front_end="pll", pll_bw_hz=30.0) if winner == "pll30" else \
        dict(front_end="ema", ema_alpha=float(winner.replace("ema", "")))
    dem = ResamplingPLLDemod(sch, **kw)
    rx_frames, _d = md._demod_section_frames(
        audio_nom, sec, align, sch, lambda w, nd, d=dem: d.demod(w, nd))
    ok, msgs, led = _per_cw_decode(_rx_mat(rx_frames, meta), meta, crc)
    _ledger_add(out, *led)
    base_failed = [int(i) for i in np.flatnonzero(~ok)]
    union_msgs = list(msgs)
    mis = sum(1 for i in range(n_cw) if msgs[i] is not None and msgs[i] != truth[i])
    branch_summary = {}
    for base in BASES:
        si = run_stitched_section(audio_nom, align, sec, base, verbose=False)
        for bn in si["branches"]:
            rxf = si["branch_frames"][bn]
            okb, msgsb, led = _per_cw_decode(_rx_mat(rxf, meta), meta, crc)
            _ledger_add(out, *led)
            mis += sum(1 for i in range(n_cw)
                       if msgsb[i] is not None and msgsb[i] != truth[i])
            branch_summary[bn] = {"cw_failed": int((~okb).sum()),
                                  "vec": si["branches"][bn]}
            for i in range(n_cw):
                if union_msgs[i] is None and msgsb[i] is not None:
                    union_msgs[i] = msgsb[i]
    failed = [i for i in range(n_cw) if union_msgs[i] is None]
    assembled = _assemble(meta, union_msgs)
    rec = {"winner_fe": winner, "winner_cw_failed": len(base_failed),
           "union_cw_failed": len(failed),
           "byte_exact_packed": assembled == expected,
           "miscorrections_vs_truth": int(mis),
           "stitched_branches": branch_summary,
           "elapsed_s": round(time.time() - t0, 1)}
    out["regression"].setdefault(tag, {})[sec["name"]] = rec
    _save_out(out)
    print(f"[regress {tag}/{sec['name']}] winner {len(base_failed)} failed, "
          f"union {len(failed)} failed, byte_exact={rec['byte_exact_packed']}, "
          f"mis={mis} ({rec['elapsed_s']}s)", flush=True)


def regress_tape9(only=None):
    out = _load_out()
    audio_nom, align, manifest = _load_tape9()
    secs = {s["name"]: s for s in manifest["ws_payloads"]}
    for name, winner in TAPE9_LANDED:
        if only and name not in only:
            continue
        _regress_dqpsk(audio_nom, align, secs[name], winner, out, "tape9")


def regress_m8():
    out = _load_out()
    audio_nom, align, manifest = _load_m8_lossless()
    secs = {s["name"]: s for s in manifest["ws_payloads"]}
    sec = secs["m8_dq_p10n512_rs127"]
    # documented landed decode (m8_results_m8_tape_mono_lossless.json: 0 cw
    # failed via the m8-era h4 EMA0.5 chain) -> winner = ema0.5
    _regress_dqpsk(audio_nom, align, sec, "ema0.5", out, "m8_tape_mono_lossless")


def regress_ws():
    """tape7/tape4 widespace rungs: the late-window branch only exists for
    DQPSK sections, so these decode paths are UNTOUCHED by construction; this
    re-runs the existing decoders unchanged as a determinism confirmation."""
    out = _load_out()
    import m7_decode
    import m4_decode
    t0 = time.time()
    r7 = m7_decode.decode(str(_HERE / "captures" / "tape7_run1.wav"),
                          out_tag="x10_lw_regress_tape7", verbose=False)
    keep7 = {p["name"]: {"cw_failed": p.get("rs_codewords_failed"),
                         "byte_exact": p.get("byte_exact")}
             for p in r7["payloads"]
             if p["name"] in ("m16_rs111_8k", "m16_rs191_8k", "m32_rs95_4k")}
    print(f"[regress tape7] {keep7} ({time.time()-t0:.0f}s)", flush=True)
    t0 = time.time()
    r4 = m4_decode.decode(str(_HERE / "captures" / "tape4_run1.wav"),
                          out_tag="x10_lw_regress_tape4", verbose=False)
    keep4 = {p["name"]: {"cw_failed": p.get("rs_codewords_failed"),
                         "byte_exact": p.get("byte_exact")}
             for p in r4["payloads"] if p["name"] in ("ws_test2k", "ws_llm24k")}
    print(f"[regress tape4] {keep4} ({time.time()-t0:.0f}s)", flush=True)
    out["regression"]["tape7"] = keep7
    out["regression"]["tape4"] = keep4
    _save_out(out)


# ===========================================================================
def summarize():
    out = _load_out()
    base = {"m9_m5_n256_rs179": 0, "m9_m6_n256_rs191": 10,
            "m9_m7_n256_p11_9000": 4, "m9_m4_n256_rs159": 0}
    verdict = {"x10_union_baseline_cw_failed": base}
    for name, rec in out.get("sections", {}).items():
        verdict[name] = {
            "union_baseline": rec["union_baseline"]["cw_failed"],
            "union_final": rec["union_final"]["cw_failed"],
            "byte_exact": rec["byte_exact_packed"],
            "orig_exact": rec.get("orig_exact"),
            "dc0_ser_argmin": {b: rec["stitched"][b]["branches"]
                               [f"{b}_argmin"]["dc0_ser"] for b in BASES},
            "miscorrections": rec["miscorrections_vs_truth"]}
    reg_fail = []
    for tag, secs in out.get("regression", {}).items():
        for sname, r in secs.items():
            cwf = r.get("union_cw_failed", r.get("cw_failed"))
            if cwf != 0:
                reg_fail.append(f"{tag}/{sname}={cwf}")
            if r.get("miscorrections_vs_truth"):
                reg_fail.append(f"{tag}/{sname} MISCORR")
    verdict["regressions"] = reg_fail
    verdict["trial_ledger"] = out["trial_ledger"]
    led = out["trial_ledger"]
    verdict["false_accept_bound"] = led["crc_checks"] * 2.0 ** -32
    out["verdict"] = verdict
    _save_out(out)
    print(json.dumps(verdict, indent=2, default=float))


if __name__ == "__main__":
    import warnings
    warnings.filterwarnings("ignore")
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("frontier")
    f.add_argument("--only", default="")
    r9 = sub.add_parser("regress-tape9")
    r9.add_argument("--only", default="")
    sub.add_parser("regress-m8")
    sub.add_parser("regress-ws")
    sub.add_parser("summarize")
    args = ap.parse_args()
    if args.cmd == "frontier":
        frontier([x for x in args.only.split(",") if x] or None)
    elif args.cmd == "regress-tape9":
        regress_tape9([x for x in args.only.split(",") if x] or None)
    elif args.cmd == "regress-m8":
        regress_m8()
    elif args.cmd == "regress-ws":
        regress_ws()
    elif args.cmd == "summarize":
        summarize()
