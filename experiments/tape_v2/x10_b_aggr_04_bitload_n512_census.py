"""x10_b_aggr_04_bitload_n512_census.py -- PHASE A census for candidate
B-aggr-04-bitload-n512 (per-carrier D-MPSK bit-loading at the proven m8
N512/375 Hz geometry).

PRE-REGISTERED (frozen in PREREG below BEFORE any census run; gates the tape
spend; the rule may NOT be softened after seeing data):

  3-bit (D8PSK) qualification, per carrier: on BOTH real captures
  (tape9_run1.wav AND m8_tape_mono_lossless.wav), pooling all plain-DQPSK
  N512-geometry sections of that capture where the frequency is a data
  carrier, demodulated with the PRODUCTION front-end (the same tracker that
  will decode: x9_resampling_pll.ResamplingPLLDemod, pll_bw_hz=30):
    (a) the Clopper-Pearson upper 95% confidence limit on
        P(|dphi_err| > 15 deg) is < 1e-3,
    (b) the absolute max |dphi_err| stays inside the 22.5 deg D8PSK decision
        boundary,
    (c) f < 5000 Hz.
  dphi_err = post-DD-refine differential phase error vs the manifest-sidecar
  truth (truth used for SCORING ONLY, never inside the demod).
  Carriers with no data-carrier evidence on a capture FAIL the both-captures
  requirement (conservative intersection loading).

  1-bit (DBPSK) derate: carriers with in-situ snr_eff_db < 12 dB from the
  pre-existing calibration artifact results/x10_headroom.json (m9_m8_dense375
  EVM through the winning front-end): frozen set {4500, 5625, 7875, 9000} Hz.

  2-bit (DQPSK): every remaining carrier (the proven m8 modulation).
  Amplitude rings: excluded entirely (pre-registered).

  GATE: nq = #qualifying 3-bit carriers.
    nq >= 8           -> GO full load (plan ship target 3040 net bps)
    4 <= nq <= 7      -> DERATE: design_net_banker = (40 + nq) * 93.75 * 159/255
                         frozen PRE-TAPE as the derated rung's own ship
                         threshold; requires design_net_banker > 2572 else KILL
    nq < 4 OR design <= 2572 -> KILL before tape.

FIDELITY: the instrumented DFT pass replicates the exact production loops
(x10_forensics_errors pattern) and is verified per frame against the
production quadrant decisions (q_mismatch must be 0). Each census section
also re-runs the authoritative CRC-guarded RS merge and must reproduce the
recorded m9/m8 results (byte_exact / cw_failed) for its capture.

Usage (each run well under 8 min; checkpoints results/x10_bitload_census.json):
    python3 x10_b_aggr_04_bitload_n512_census.py prepare-m8
    python3 x10_b_aggr_04_bitload_n512_census.py census --capture tape9 --section m9_m0_reprove934
    ... (one per section) ...
    python3 x10_b_aggr_04_bitload_n512_census.py adjudicate

Deterministic (no RNG; seeds N/A -- real-capture re-decode only).
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys
import time

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
from h4_dqpsk import DQPSKScheme, FS, PAD_LO_S, PAD_HI_S   # noqa: E402
import m9_decode as m9d                              # noqa: E402
from x9_resampling_pll import (ResamplingPLLDemod,   # noqa: E402
                               _pi_loop_gains)

SR = codec.FS
CAP_DIR = _HERE / "captures"
RES_DIR = _HERE / "results"
OUT_JSON = RES_DIR / "x10_bitload_census.json"

CAPTURES = {
    "tape9": {
        "wav": CAP_DIR / "tape9_run1.wav",
        "manifest": _HERE / "master9_manifest.json",
        "cache_npy": CAP_DIR / "x10_audio_nom_tape9_run1.npy",   # forensics cache
        "sync_json": RES_DIR / "x10_forensics_sync.json",        # forensics sync
        "recorded_results": RES_DIR / "m9_results_tape9_run1.json",
        "sections": ["m9_m0_reprove934", "m9_m1_thin159", "m9_m2_thin191",
                     "m9_m8_dense375"],
    },
    "m8": {
        "wav": CAP_DIR / "m8_tape_mono_lossless.wav",
        "manifest": _HERE / "master8_manifest.json",
        "cache_npy": CAP_DIR / "x10_bitload_audio_nom_m8_tape.npy",
        "sync_json": RES_DIR / "x10_bitload_sync_m8.json",
        "recorded_results": RES_DIR / "m8_results_m8_tape_mono_lossless.json",
        "sections": ["m8_dq_p10n512_rs127"],
    },
}

# ---------------------------------------------------------------------------
# PRE-REGISTRATION (frozen before any census computation -- see module doc).
# ---------------------------------------------------------------------------
PREREG = {
    "candidate": "B-aggr-04-bitload-n512",
    "geometry": {"P": 22, "N": 512, "spacing": 4, "min_spacing_hz": 375.0,
                 "pilot_hz": 4875.0, "sym_rate_hz": 93.75},
    "production_front_end": "ResamplingPLLDemod(pll_bw_hz=30, front_end='pll', ema_alpha=0.5)",
    "rule_3bit": ("(a) Clopper-Pearson upper 95% CL on P(|dphi_err|>15deg) < 1e-3 "
                  "per carrier per capture (pooled over that capture's plain-DQPSK "
                  "N512 sections where the freq is a data carrier), AND "
                  "(b) max |dphi_err| < 22.5 deg on BOTH captures, AND "
                  "(c) f < 5000 Hz. dphi_err = post-DD-refine phase error vs "
                  "sidecar truth. No evidence on a capture = FAIL (intersection)."),
    "rule_1bit_dbpsk_hz": [4500.0, 5625.0, 7875.0, 9000.0],
    "rule_1bit_provenance": ("results/x10_headroom.json evm.m9_m8_dense375.snr_eff_db "
                             "< 12 dB (pre-existing artifact: 4500=11.07, 5625=9.71, "
                             "7875=11.60, 9000=11.24)"),
    "rule_2bit": "all remaining carriers keep DQPSK (proven m8 modulation)",
    "amplitude_rings": "excluded entirely",
    "rs_banker_k": 159, "rs_stretch_k": 179,
    "design_net_formula": "sum(bits_per_carrier) * 93.75 * rs_k / 255",
    "gate": {"go_full_min_nq": 8, "ship_target_full_net_bps": 3040,
             "derate_nq_range": [4, 7],
             "derate_requires_design_net_banker_gt": 2572,
             "kill_below_nq": 4},
    "record_to_beat_net_bps": 2572.0588235294117,
    "sections_used": {k: v["sections"] for k, v in CAPTURES.items()},
    "pooling": ("per (capture, frequency): exceedance counts and max pooled over "
                "the listed sections of that capture in which the frequency is a "
                "data carrier; sections at 750 Hz spacing (sp8) and 375 Hz spacing "
                "(sp4) both count as m8-geometry (N512) evidence"),
}

THRESH_QUAL_DEG = 15.0
BOUND_8PSK_DEG = 22.5
BOUND_QPSK_DEG = 45.0
CP_CONF = 0.95
CP_LIMIT = 1e-3
F_MAX_HZ = 5000.0
DBPSK_HZ = set(PREREG["rule_1bit_dbpsk_hz"])

# The full m8-dense375 grid (22 data carriers + pilot 4875), the master10 geometry.
M8_DATA_FREQS = [750.0, 1125.0, 1500.0, 1875.0, 2250.0, 2625.0, 3000.0, 3375.0,
                 3750.0, 4125.0, 4500.0, 5250.0, 5625.0, 6000.0, 6375.0, 6750.0,
                 7125.0, 7500.0, 7875.0, 8250.0, 8625.0, 9000.0]


# ===========================================================================
# instrumented replicas (x10_forensics_errors pattern, production-faithful)
# ===========================================================================
def _ema_dft(sch, y, ds, total, ema_alpha):
    N, skip, Nw = sch.N, sch.skip, sch.Nw
    win = sch._win
    freqs = sch.freqs
    fpil = freqs[sch.pilot_idx]
    pidx = sch.pilot_idx
    c = np.zeros((total, len(freqs)), np.complex128)
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
            dp = float(np.angle(c[i, pidx] * np.conj(c[i - 1, pidx])))
            sm = (1 - ema_alpha) * (dp / (2 * np.pi * fpil)) + ema_alpha * sm
            dtau[i] = sm
            drift -= dtau[i] * FS
            drift = float(np.clip(drift, -200, 200))
    return c, dtau


def _plain_dft(sch, y, ds, total):
    N, skip, Nw = sch.N, sch.skip, sch.Nw
    win = sch._win
    freqs = sch.freqs
    c = np.zeros((total, len(freqs)), np.complex128)
    for i in range(total):
        lo = ds + i * N + skip
        seg = y[lo: lo + Nw]
        if len(seg) < Nw:
            seg = np.concatenate([seg, np.zeros(Nw - len(seg))])
        tt = (lo + np.arange(Nw)) / FS
        E = np.exp(-2j * np.pi * np.outer(freqs, tt))
        c[i] = E @ (seg * win)
    return c


def _pll_dft(pll, y, ds, total):
    """Replicates ResamplingPLLDemod._demod_pll Pass1 + warp + Pass2."""
    sch = pll.sch
    N = sch.N
    c1, dtau_ema = _ema_dft(sch, y, ds, total, pll.ema_alpha)
    kp, ki = _pi_loop_gains(pll.pll_bw_hz, pll.t_sym, pll.zeta)
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
    c2 = _plain_dft(sch, y2, ds, total)
    fpil = sch.freqs[sch.pilot_idx]
    dtau_res = np.zeros(total)
    for i in range(1, total):
        dp = float(np.angle(c2[i, sch.pilot_idx] * np.conj(c2[i - 1, sch.pilot_idx])))
        dtau_res[i] = dp / (2 * np.pi * fpil)
    return c2, dtau_res, c1, dtau_ema


def _decide_refine(sch, c, dtau_total, refine=True):
    """Replica of x9 _decide returning the final (post-refine) dphi too."""
    fd = sch.freqs[sch.data_idx]
    d = c[1:, :] * np.conj(c[:-1, :])
    dphi = np.angle(d[:, sch.data_idx]) - 2 * np.pi * np.outer(dtau_total[1:], fd)
    q = np.round(dphi / (np.pi / 2.0)).astype(int) % 4
    if refine:
        res = (dphi - q * (np.pi / 2.0) + np.pi) % (2 * np.pi) - np.pi
        num = (res * fd[None, :]).sum(axis=1)
        den = (fd ** 2).sum()
        dtau_dd = num / (2 * np.pi * den)
        dphi = dphi - 2 * np.pi * dtau_dd[:, None] * fd[None, :]
        q = np.round(dphi / (np.pi / 2.0)).astype(int) % 4
    return q, dphi, d


# ===========================================================================
# IO helpers
# ===========================================================================
def _load_out():
    if OUT_JSON.exists():
        try:
            return json.loads(OUT_JSON.read_text())
        except Exception:
            pass
    return {"prereg": PREREG, "sections": {}}


def _save_out(out):
    out["prereg"] = PREREG
    RES_DIR.mkdir(exist_ok=True)
    OUT_JSON.write_text(json.dumps(out, indent=2, default=float))


def _get_section(manifest, name):
    for sec in manifest["ws_payloads"]:
        if sec["name"] == name:
            return sec
    raise KeyError(name)


def _load_nominal(capkey):
    cap = CAPTURES[capkey]
    audio_nom = np.load(cap["cache_npy"], mmap_mode="r")
    sync = json.loads(cap["sync_json"].read_text())
    return audio_nom, sync


def prepare_m8():
    """One-time global sync of the master8 capture -> cached nominal audio."""
    cap = CAPTURES["m8"]
    t0 = time.time()
    manifest = json.loads(cap["manifest"].read_text())
    audio, sr = sf.read(str(cap["wav"]), dtype="float32", always_2d=False)
    if audio.ndim > 1:
        audio = audio.mean(axis=1)
    assert sr == SR, f"capture sr {sr} != {SR}"
    sync = am2.global_sync_and_resample(audio, manifest)
    audio_nom = sync["audio_nominal"]
    np.save(cap["cache_npy"], audio_nom.astype(np.float32))
    meta = {k: (int(v) if isinstance(v, (int, np.integer)) else float(v))
            for k, v in sync.items() if k != "audio_nominal"}
    meta["align"] = int(sync["chirp0_nominal"]) - int(manifest["tx_chirp0"])
    meta["n_samples_nominal"] = int(len(audio_nom))
    cap["sync_json"].write_text(json.dumps(meta, indent=2, default=float))
    # cross-check vs the recorded m8 decode sync
    rec = json.loads(cap["recorded_results"].read_text())["sync"]
    ok = abs(rec["clock_ratio"] - meta["clock_ratio"]) < 1e-9
    print(f"[prepare-m8] clock {meta['clock_ratio']:.7f} "
          f"(recorded {rec['clock_ratio']:.7f}, match={ok}), align {meta['align']:+d}, "
          f"{time.time()-t0:.0f}s")


# ===========================================================================
# census of one section
# ===========================================================================
def census_section(capkey: str, secname: str):
    t0 = time.time()
    cap = CAPTURES[capkey]
    manifest = json.loads(cap["manifest"].read_text())
    sec = _get_section(manifest, secname)
    meta = sec["meta"]
    p = sec["dqpsk_params"]
    sch = DQPSKScheme(p["P"], p["N"], p["spacing"],
                      min_spacing_hz=p.get("min_spacing_hz", 562.0))
    assert sec["kind"] == "dqpsk", "census covers plain-DQPSK N512 sections only"
    assert sch.N == 512

    audio_nom, sync = _load_nominal(capkey)
    align = int(sync["align"])
    expected_packed = (_HERE / sec["payload_sidecar"]).read_bytes()
    rung = Rung(name=meta["rung"], M=meta["M"], K=meta["K"], rs_n=meta["rs_n"],
                rs_k=meta["rs_k"], frame_bytes=meta["frame_bytes"])
    tx_frames, _m2 = codec.encode_payload(expected_packed, rung)

    dem = ResamplingPLLDemod(sch, pll_bw_hz=30.0, front_end="pll")
    nom_bits = m9d._nominal_frame_bits(meta)
    pad_lo, pad_hi = int(PAD_LO_S * SR), int(PAD_HI_S * SR)
    flen_full = len(np.asarray(sch.modulate(np.zeros(meta["frame_bits"], np.uint8))))

    P = sch.P
    fd = sch.freqs[sch.data_idx]
    err_deg_per_carrier = [[] for _ in range(P)]   # |dphi_err| in degrees
    amp_ratio_per_carrier = [[] for _ in range(P)]  # |c_i|/|c_{i-1}|
    q_mismatch_total = 0
    fe_per_frame = {"pll": 0, "ema": 0}
    rx_frames = []
    ser_err = np.zeros(P, int)
    ser_tot = np.zeros(P, int)

    for fi, st in enumerate(sec["frame_starts"]):
        nd = sch.nsym_data(nom_bits[fi])
        st = int(st) + align
        w_lo = max(0, int(st - pad_lo))
        w_hi = min(len(audio_nom), int(st + flen_full + pad_hi))
        win = np.asarray(audio_nom[w_lo:w_hi], np.float64)

        # ---- production decision (unmodified module) ----
        bits, diag = dem.demod(win, nd)
        rx_frames.append(np.asarray(bits, np.uint8))
        used = diag.get("front_end", "pll")
        fe_per_frame[used] = fe_per_frame.get(used, 0) + 1

        # ---- instrumented replica of the SAME path ----
        ds = diag["preamble_at"]
        total = nd + 1
        if used == "pll":
            c, dtau_res, _c1, _dtau_ema = _pll_dft(dem, win, ds, total)
            dtau_total = np.concatenate([[0.0], np.asarray(diag["dtau"])])
            # sanity: replica pilot residual must match the production dtau
            assert np.allclose(dtau_res[1:], diag["dtau"], atol=1e-12), "dtau mismatch"
        else:
            c, dtau_ema = _ema_dft(sch, win, ds, total, dem.ema_alpha)
            dtau_total = np.concatenate([[0.0], np.asarray(diag["dtau"])])
            assert np.allclose(dtau_ema[1:], diag["dtau"], atol=1e-12), "dtau mismatch"
        q, dphi, d = _decide_refine(sch, c, dtau_total)
        qm = int(np.count_nonzero(q != diag["quadrants"]))
        q_mismatch_total += qm

        # ---- truth (scoring only) ----
        tb = np.asarray(tx_frames[fi], np.uint8)
        tq = sch.bits_to_quadrants(tb)            # (nd, P) incl. any pad symbols
        k = min(len(tq), len(q))
        gerr = (dphi[:k] - tq[:k] * (np.pi / 2.0) + np.pi) % (2 * np.pi) - np.pi
        ser_err += (q[:k] != tq[:k]).sum(axis=0)
        ser_tot += k
        amp = np.abs(d)                            # (nd, nc) diff products
        camp = np.abs(c)                           # (total, nc)
        for j in range(P):
            err_deg_per_carrier[j].append(np.degrees(np.abs(gerr[:, j])).astype(np.float32))
            ci = camp[1:, sch.data_idx[j]]
            cim1 = camp[:-1, sch.data_idx[j]]
            amp_ratio_per_carrier[j].append((ci / np.maximum(cim1, 1e-12)).astype(np.float32))

    # ---- authoritative RS reproduction (validation vs recorded results) ----
    out_packed, cwf, misc, _ = m9d._rs_merge_guarded(
        rx_frames, meta, sec["crc32_codewords"], erase_frac=0.0, rel_cw=None)
    byte_exact = out_packed == expected_packed
    byte_err = sum(a != b for a, b in zip(out_packed, expected_packed)) + abs(
        len(out_packed) - len(expected_packed))

    rec_cmp = None
    try:
        rec = json.loads(cap["recorded_results"].read_text())
        for rp in rec["payloads"]:
            if rp.get("name") == secname:
                rec_cmp = {"recorded_cw_failed": rp.get("rs_codewords_failed"),
                           "recorded_byte_exact": rp.get("byte_exact"),
                           "recorded_front_end": rp.get("front_end_used"),
                           "reproduced": (bool(rp.get("byte_exact")) == bool(byte_exact)
                                          and (rp.get("rs_codewords_failed") == cwf
                                               or rp.get("front_end_used") is None))}
    except Exception as exc:
        rec_cmp = {"error": str(exc)}

    # ---- per-carrier summaries + raw |err| cache for pooled adjudication ----
    carriers = []
    npz_payload = {}
    for j in range(P):
        e = np.concatenate(err_deg_per_carrier[j])
        a = np.concatenate(amp_ratio_per_carrier[j])
        es = np.sort(e)
        n = len(es)
        carriers.append({
            "freq_hz": float(fd[j]),
            "n_sym": int(n),
            "rms_deg": float(np.sqrt(np.mean(es ** 2))),
            "p50_deg": float(es[int(0.50 * (n - 1))]),
            "p90_deg": float(es[int(0.90 * (n - 1))]),
            "p99_deg": float(es[int(0.99 * (n - 1))]),
            "p999_deg": float(es[min(n - 1, int(0.999 * (n - 1)))]),
            "max_deg": float(es[-1]),
            "n_gt15": int(np.count_nonzero(es > THRESH_QUAL_DEG)),
            "n_gt22p5": int(np.count_nonzero(es > BOUND_8PSK_DEG)),
            "n_gt45": int(np.count_nonzero(es > BOUND_QPSK_DEG)),
            "ser": float(ser_err[j] / max(1, ser_tot[j])),
            "amp_ratio_mean": float(np.mean(a)),
            "amp_ratio_std": float(np.std(a)),
            "amp_ratio_p1": float(np.percentile(a, 1)),
            "amp_ratio_p99": float(np.percentile(a, 99)),
        })
        npz_payload[f"err_{int(fd[j])}"] = e
    npz_path = CAP_DIR / f"x10_bitload_errs_{capkey}_{secname}.npz"
    np.savez_compressed(npz_path, **npz_payload)

    res = {
        "capture": capkey, "section": secname, "phy": sec["phy"],
        "pilot_hz": float(sch.freqs[sch.pilot_idx]),
        "n_frames": meta["n_frames"],
        "front_end_per_frame": fe_per_frame,
        "q_mismatch_total": int(q_mismatch_total),
        "rs_reproduction": {"cw_failed": int(cwf), "miscorrected": int(misc),
                            "byte_exact": bool(byte_exact), "byte_errors": int(byte_err),
                            **(rec_cmp or {})},
        "carriers": carriers,
        "err_cache_npz": str(npz_path.name),
        "wall_s": round(time.time() - t0, 1),
    }
    out = _load_out()
    out["sections"][f"{capkey}/{secname}"] = res
    _save_out(out)
    print(f"[census {capkey}/{secname}] frames={meta['n_frames']} "
          f"q_mismatch={q_mismatch_total} rs: cw={cwf} exact={byte_exact} "
          f"repro={rec_cmp and rec_cmp.get('reproduced')} ({res['wall_s']}s)")
    for cinfo in carriers:
        print(f"    {cinfo['freq_hz']:6.0f} Hz n={cinfo['n_sym']:5d} "
              f"rms={cinfo['rms_deg']:5.2f} max={cinfo['max_deg']:6.2f} "
              f">15deg:{cinfo['n_gt15']:4d} >22.5:{cinfo['n_gt22p5']:4d} "
              f"ser={cinfo['ser']:.5f}")
    return res


# ===========================================================================
# adjudication: pool per (capture, freq), apply the frozen rule
# ===========================================================================
def _cp_upper(k: int, n: int, conf: float = CP_CONF) -> float:
    """Clopper-Pearson upper confidence limit for k successes in n trials."""
    from scipy.stats import beta as _beta
    if n <= 0:
        return 1.0
    if k >= n:
        return 1.0
    return float(_beta.ppf(conf, k + 1, n - k))


def adjudicate():
    out = _load_out()
    secs = out.get("sections", {})
    needed = [f"{ck}/{sn}" for ck, cv in CAPTURES.items() for sn in cv["sections"]]
    missing = [s for s in needed if s not in secs]
    if missing:
        print(f"[adjudicate] MISSING sections: {missing}")
        sys.exit(1)
    # fidelity gates: every section must have q_mismatch 0 and reproduce its
    # recorded decode
    for key in needed:
        s = secs[key]
        assert s["q_mismatch_total"] == 0, f"{key}: q_mismatch != 0"
        assert s["rs_reproduction"]["byte_exact"], f"{key}: RS reproduction not byte-exact"

    per_freq = {}
    for f in M8_DATA_FREQS:
        row = {"freq_hz": f, "per_capture": {}}
        for capkey, cv in CAPTURES.items():
            n = k15 = k225 = k45 = 0
            mx = 0.0
            rms_num = 0.0
            sec_list = []
            for sn in cv["sections"]:
                s = secs[f"{capkey}/{sn}"]
                for cinfo in s["carriers"]:
                    if abs(cinfo["freq_hz"] - f) < 0.5:
                        n += cinfo["n_sym"]
                        k15 += cinfo["n_gt15"]
                        k225 += cinfo["n_gt22p5"]
                        k45 += cinfo["n_gt45"]
                        mx = max(mx, cinfo["max_deg"])
                        rms_num += (cinfo["rms_deg"] ** 2) * cinfo["n_sym"]
                        sec_list.append({"section": sn, "n": cinfo["n_sym"],
                                         "n_gt15": cinfo["n_gt15"],
                                         "max_deg": cinfo["max_deg"],
                                         "rms_deg": cinfo["rms_deg"],
                                         "ser": cinfo["ser"]})
            cp = _cp_upper(k15, n) if n else 1.0
            row["per_capture"][capkey] = {
                "n": n, "n_gt15": k15, "n_gt22p5": k225, "n_gt45": k45,
                "max_deg": mx, "rms_deg_pooled": (rms_num / n) ** 0.5 if n else None,
                "cp_upper95_p_gt15": cp,
                "pass_a_cp": bool(n > 0 and cp < CP_LIMIT),
                "pass_b_max": bool(n > 0 and mx < BOUND_8PSK_DEG),
                "sections": sec_list,
            }
        pa = all(row["per_capture"][c]["pass_a_cp"] for c in CAPTURES)
        pb = all(row["per_capture"][c]["pass_b_max"] for c in CAPTURES)
        pc = f < F_MAX_HZ
        evid = all(row["per_capture"][c]["n"] > 0 for c in CAPTURES)
        row["pass_a"] = pa
        row["pass_b"] = pb
        row["pass_c_f_lt_5k"] = pc
        row["evidence_both_captures"] = evid
        row["qualifies_3bit"] = bool(pa and pb and pc and evid)
        row["dbpsk_derate"] = f in DBPSK_HZ
        per_freq[str(int(f))] = row

    qual = [f for f in M8_DATA_FREQS if per_freq[str(int(f))]["qualifies_3bit"]
            and f not in DBPSK_HZ]
    nq = len(qual)
    load_table = {}
    for f in M8_DATA_FREQS:
        if f in DBPSK_HZ:
            load_table[str(int(f))] = 1
        elif f in qual:
            load_table[str(int(f))] = 3
        else:
            load_table[str(int(f))] = 2
    bits_sum = sum(load_table.values())
    sym_rate = PREREG["geometry"]["sym_rate_hz"]
    design_net_banker = bits_sum * sym_rate * PREREG["rs_banker_k"] / 255.0
    design_net_stretch = bits_sum * sym_rate * PREREG["rs_stretch_k"] / 255.0
    record = PREREG["record_to_beat_net_bps"]

    if nq >= PREREG["gate"]["go_full_min_nq"]:
        verdict = "GO-FULL"
        ship_threshold = float(PREREG["gate"]["ship_target_full_net_bps"])
    elif PREREG["gate"]["derate_nq_range"][0] <= nq <= PREREG["gate"]["derate_nq_range"][1]:
        if design_net_banker > record:
            verdict = "GO-DERATED"
            ship_threshold = design_net_banker
        else:
            verdict = "KILL"
            ship_threshold = None
    else:
        verdict = "KILL"
        ship_threshold = None

    out["adjudication"] = {
        "per_freq": per_freq,
        "qualifying_3bit_hz": qual,
        "n_qualifying": nq,
        "dbpsk_hz": sorted(DBPSK_HZ),
        "load_table_bits": load_table,
        "bits_per_symbol": bits_sum,
        "design_net_bps_banker_rs159": design_net_banker,
        "design_net_bps_stretch_rs179": design_net_stretch,
        "record_to_beat": record,
        "verdict": verdict,
        "ship_threshold_net_bps": ship_threshold,
        "note_max_possible": ("max possible under f<5kHz cap: 10 qualifying -> "
                              "50 bits/sym -> 2922.8 net (banker), i.e. the plan's "
                              "full-load ship target 3040 is unreachable under the "
                              "pre-registered f<5kHz constraint"),
    }
    _save_out(out)
    print(f"[adjudicate] qualifying={nq} {[int(f) for f in qual]}")
    print(f"  load table bits/sym = {bits_sum} "
          f"-> banker net {design_net_banker:.1f} bps, stretch {design_net_stretch:.1f} bps")
    print(f"  VERDICT: {verdict}" + (f" (ship threshold {ship_threshold:.1f})" if ship_threshold else ""))
    for f in M8_DATA_FREQS:
        r = per_freq[str(int(f))]
        t9 = r["per_capture"]["tape9"]
        m8 = r["per_capture"]["m8"]
        print(f"    {f:6.0f} Hz bits={load_table[str(int(f))]} "
              f"q3={'Y' if r['qualifies_3bit'] else 'n'} "
              f"t9[n={t9['n']:5d} k15={t9['n_gt15']:4d} cp={t9['cp_upper95_p_gt15']:.2e} "
              f"max={t9['max_deg']:5.1f}] "
              f"m8[n={m8['n']:5d} k15={m8['n_gt15']:4d} cp={m8['cp_upper95_p_gt15']:.2e} "
              f"max={m8['max_deg']:5.1f}]")
    return out["adjudication"]


# ===========================================================================
# POST-HOC INFORMATIONAL ONLY (computed AFTER the frozen adjudication; clearly
# NOT part of the pre-registered gate and confers NO tape authorization).
# Quantifies what an RS-tolerant tail rule would have seen, for the campaign
# ledger / next-candidate design.
# ===========================================================================
def informational():
    out = _load_out()
    adj = out.get("adjudication")
    assert adj is not None, "run adjudicate first"
    per_freq = adj["per_freq"]
    sym_rate = PREREG["geometry"]["sym_rate_hz"]

    def design(loads, k):
        return sum(loads.values()) * sym_rate * k / 255.0

    variants = {}
    # hypothetical rule H1: 3-bit iff pooled P(>22.5deg) < 1% on BOTH captures,
    # f<5kHz, not in the DBPSK set (D8PSK boundary-exceedance proxy <= RS budget)
    for tag, lim in (("H1_p22p5_lt_1pct_pooled", 0.01),
                     ("H2_p22p5_lt_0p5pct_pooled", 0.005)):
        qual = []
        for f in M8_DATA_FREQS:
            r = per_freq[str(int(f))]
            if f >= F_MAX_HZ or f in DBPSK_HZ:
                continue
            ok = True
            for ck in CAPTURES:
                pc_ = r["per_capture"][ck]
                if pc_["n"] == 0 or pc_["n_gt22p5"] / pc_["n"] >= lim:
                    ok = False
            if ok:
                qual.append(f)
        loads = {str(int(f)): (1 if f in DBPSK_HZ else (3 if f in qual else 2))
                 for f in M8_DATA_FREQS}
        variants[tag] = {
            "rule": f"3-bit iff pooled P(|err|>22.5deg) < {lim} on both captures, "
                    f"f<5kHz, not DBPSK-derated; both-captures evidence required",
            "qualifying_hz": qual, "n_qualifying": len(qual),
            "bits_per_symbol": sum(loads.values()),
            "design_net_bps_banker_rs159": design(loads, 159),
            "design_net_bps_stretch_rs179": design(loads, 179),
        }
    # hypothetical rule H3: tape9 m8dense-section-only evidence (the exact
    # master10 geometry, single capture -- weakest evidence, widest table)
    sec = out["sections"]["tape9/m9_m8_dense375"]
    qual = [c["freq_hz"] for c in sec["carriers"]
            if c["freq_hz"] < F_MAX_HZ and c["freq_hz"] not in DBPSK_HZ
            and c["n_gt22p5"] / c["n_sym"] < 0.01]
    loads = {str(int(f)): (1 if f in DBPSK_HZ else (3 if f in qual else 2))
             for f in M8_DATA_FREQS}
    variants["H3_m8dense_only_p22p5_lt_1pct"] = {
        "rule": "3-bit iff m8dense-section P(|err|>22.5deg) < 1% (tape9 only, "
                "exact master10 geometry; NO cross-tape confirmation)",
        "qualifying_hz": qual, "n_qualifying": len(qual),
        "bits_per_symbol": sum(loads.values()),
        "design_net_bps_banker_rs159": design(loads, 159),
        "design_net_bps_stretch_rs179": design(loads, 179),
    }
    out["post_hoc_informational"] = {
        "WARNING": ("NOT pre-registered, computed after the gate verdict; for "
                    "next-candidate design only. The frozen gate verdict stands: "
                    + adj["verdict"]),
        "variants": variants,
    }
    _save_out(out)
    for tag, v in variants.items():
        print(f"[info {tag}] nq={v['n_qualifying']} {sorted(int(f) for f in v['qualifying_hz'])} "
              f"bits={v['bits_per_symbol']} banker={v['design_net_bps_banker_rs159']:.1f} "
              f"stretch={v['design_net_bps_stretch_rs179']:.1f}")


if __name__ == "__main__":
    import warnings
    warnings.filterwarnings("ignore")
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("prepare-m8")
    pc = sub.add_parser("census")
    pc.add_argument("--capture", required=True, choices=list(CAPTURES))
    pc.add_argument("--section", required=True)
    sub.add_parser("adjudicate")
    sub.add_parser("informational")
    args = ap.parse_args()
    if args.cmd == "prepare-m8":
        prepare_m8()
    elif args.cmd == "census":
        census_section(args.capture, args.section)
    elif args.cmd == "adjudicate":
        adjudicate()
    elif args.cmd == "informational":
        informational()
