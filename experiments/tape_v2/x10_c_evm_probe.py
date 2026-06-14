"""x10_c_evm_probe.py -- BET C first-principles channel evidence probe.

Measures, on REAL capture tape9_run1.wav (no truth used for tracking; truth used
only for SCORING, same as m9_decode's per-carrier SER):

  1. Per-carrier truth-referenced phase-error distribution (deg RMS, tail
     fractions beyond 45/22.5/11.25 deg) for m8_dense375 (the record, N512 P22)
     and the N256 near-misses m5/m7  -> direct bit-loading evidence.
  2. Decomposition err_rms^2(f) = (2*pi*f*sigma_tau)^2 + sigma_0^2 on clean
     carriers -> how much of the phase noise is residual TIMING (scales with f)
     vs additive floor (flat). Adjudicates coherent/MSDD vs better tracking.
  3. Per-carrier amplitude-ratio stability (dB std of |c[i+1]|/|c[i]|)
     -> viability of adding amplitude rings (DAPSK / star-QAM).
  4. Sounder per-tone SNR -> AWGN waterfilling capacity bound for context.
  5. x9 residual_stats (raw/EMA/PLL timing residual, us) on m8 frames.

Seed: none needed (pure measurement, deterministic given the capture).
Output: results/x10_c_evm_probe.json + bounded stdout summary.

Usage:
    OPENBLAS_NUM_THREADS=2 OMP_NUM_THREADS=2 python3 \
        experiments/tape_v2/x10_c_evm_probe.py [capture.wav]
"""
from __future__ import annotations

import json
import pathlib
import sys
from fractions import Fraction

import numpy as np
import soundfile as sf
from scipy.signal import resample_poly

_HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))

import m9_decode as m9d                      # noqa: E402  (reuse, don't copy)
import m3_codec as codec                     # noqa: E402
from m3_codec import Rung                    # noqa: E402
from h4_dqpsk import FS, PAD_LO_S, PAD_HI_S  # noqa: E402
import hyp_common as hc                      # noqa: E402
from x9_resampling_pll import residual_stats  # noqa: E402

am2 = m9d.am2
SR = codec.FS

# sections to probe: name -> EMA alpha that won (or coincided with winner) on tape9
TARGETS = {
    "m9_m8_dense375": 0.5,    # record rung; PLL won but PLL~EMA on clean frames
    "m9_m5_n256_rs179": 0.6,  # nearest miss 2632 (2 cw)
    "m9_m7_n256_p11_9000": 0.5,  # 2896 miss (5 cw); pll coincides ~ema0.5 on N256
}


def _ema_demod_soft(sch, y, nd, alpha):
    """h4 EMA-integer-drift loop (mirrors x9 _demod_ema) returning the raw
    per-symbol complex DFT c[(nd+1), nc] and the EMA dtau -- soft outputs the
    frozen modules don't expose. Tracking is truth-free."""
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


def _wrap(x):
    return (x + np.pi) % (2 * np.pi) - np.pi


def probe_section(audio_nom, sec, align, alpha):
    sch = m9d._scheme_from_entry(sec)
    meta = sec["meta"]
    expected_packed = (_HERE / sec["payload_sidecar"]).read_bytes()
    rung = Rung(name=meta["rung"], M=meta["M"], K=meta["K"], rs_n=meta["rs_n"],
                rs_k=meta["rs_k"], frame_bytes=meta["frame_bytes"])
    tx_frames, _ = codec.encode_payload(expected_packed, rung)
    nom_bits = m9d._nominal_frame_bits(meta)
    pad_lo, pad_hi = int(PAD_LO_S * SR), int(PAD_HI_S * SR)
    flen_full = len(np.asarray(sch.modulate(np.zeros(meta["frame_bits"], np.uint8))))

    fd = sch.freqs[sch.data_idx]
    P = sch.P
    errs = [[] for _ in range(P)]      # truth-referenced phase error (rad)
    aratio = [[] for _ in range(P)]    # log-amp ratio between consecutive syms
    pil_snr = []

    for fi, st in enumerate(sec["frame_starts"]):
        nd = sch.nsym_data(nom_bits[fi])
        st = int(st) + align
        w_lo = max(0, st - pad_lo)
        w_hi = min(len(audio_nom), st + flen_full + pad_hi)
        y = np.asarray(audio_nom[w_lo:w_hi], np.float64)
        c, dtau = _ema_demod_soft(sch, y, nd, alpha)

        tb = np.asarray(tx_frames[fi], np.uint8)
        q_true = sch.bits_to_quadrants(tb)          # (nd, P) differential quadrants
        n = min(nd, q_true.shape[0])

        d = c[1:, :] * np.conj(c[:-1, :])
        dphi = np.angle(d[:, sch.data_idx]) - 2 * np.pi * np.outer(dtau[1:], fd)
        # truth-aided common-mode refine (same math as _decide's DD refine,
        # but with the TRUE quadrants so refine never chases bad decisions)
        res = _wrap(dphi[:n] - q_true[:n] * (np.pi / 2.0))
        dtau_res = (res * fd[None, :]).sum(axis=1) / (2 * np.pi * (fd ** 2).sum())
        dphi2 = dphi[:n] - 2 * np.pi * dtau_res[:, None] * fd[None, :]
        E = _wrap(dphi2 - q_true[:n] * (np.pi / 2.0))
        for k in range(P):
            errs[k].append(E[:, k])
        A = np.abs(c[:, sch.data_idx])
        lr = np.log(np.maximum(A[1:n + 1], 1e-12) / np.maximum(A[:n], 1e-12))
        for k in range(P):
            aratio[k].append(lr[:, k])
        # pilot tone CNR proxy: |c_pilot| vs RMS of off-grid bins is overkill;
        # store pilot amplitude stability instead
        ap = np.abs(c[:, sch.pilot_idx])
        pil_snr.append(float(np.std(np.log(np.maximum(ap, 1e-12)))) * 8.686)

    per_car = []
    for k in range(P):
        e = np.concatenate(errs[k])
        a = np.concatenate(aratio[k])
        deg = np.degrees(e)
        # lag-1 autocorrelation of the differential phase error, per frame then
        # pooled: rho ~ -0.5 => absolute phase noise is WHITE (differential
        # doubles it; coherent/MSDD recovers up to 3 dB). rho ~ 0 => random-walk
        # phase (differential near-optimal).
        acs = []
        for ef in errs[k]:
            if len(ef) > 8 and np.std(ef) > 1e-9:
                x = ef - np.mean(ef)
                acs.append(float(np.dot(x[1:], x[:-1]) / np.dot(x, x)))
        per_car.append({
            "f_hz": float(fd[k]),
            "n": int(len(e)),
            "rms_deg": round(float(np.sqrt(np.mean(deg ** 2))), 2),
            "p99_deg": round(float(np.percentile(np.abs(deg), 99)), 2),
            "frac_gt45": round(float(np.mean(np.abs(deg) > 45.0)), 5),
            "frac_gt22p5": round(float(np.mean(np.abs(deg) > 22.5)), 5),
            "frac_gt11p25": round(float(np.mean(np.abs(deg) > 11.25)), 5),
            "amp_ratio_db_std": round(float(np.std(a)) * 8.686, 3),
            "lag1_rho": round(float(np.median(acs)), 3) if acs else None,
        })

    # ---- timing-vs-floor decomposition on carriers with rms < 20 deg -------
    f_fit, v_fit = [], []
    for pc in per_car:
        if pc["rms_deg"] < 20.0:
            f_fit.append(pc["f_hz"])
            v_fit.append(np.radians(pc["rms_deg"]) ** 2)
    decomp = None
    if len(f_fit) >= 4:
        F = np.asarray(f_fit); V = np.asarray(v_fit)
        # LSQ V = a + b F^2, a,b >= 0
        A_ = np.stack([np.ones_like(F), F ** 2], axis=1)
        coef, *_ = np.linalg.lstsq(A_, V, rcond=None)
        a_, b_ = max(coef[0], 0.0), max(coef[1], 0.0)
        decomp = {
            "sigma0_deg": round(float(np.degrees(np.sqrt(a_))), 2),
            "sigma_tau_us": round(float(np.sqrt(b_) / (2 * np.pi) * 1e6), 2),
            "n_carriers_fit": len(f_fit),
            "share_timing_at_4khz": round(float(
                (b_ * 4000 ** 2) / max(a_ + b_ * 4000 ** 2, 1e-12)), 3),
            "share_timing_at_8khz": round(float(
                (b_ * 8000 ** 2) / max(a_ + b_ * 8000 ** 2, 1e-12)), 3),
        }
    return {
        "section": sec["name"], "phy": sec["phy"], "alpha": alpha,
        "pilot_amp_db_std_median": round(float(np.median(pil_snr)), 2),
        "per_carrier": per_car, "timing_floor_decomp": decomp,
    }


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

    # ---- sounder -> waterfilling bound ------------------------------------
    sounder = am2.analyze_sounder(audio_nom, manifest, sync)
    wf = None
    try:
        fr = np.asarray(sounder["sounder_freqs"], float)
        snr_db = np.asarray(sounder["snr_db_per_tone"], float)
        ok = np.isfinite(snr_db)
        fr, snr_db = fr[ok], snr_db[ok]
        dfs = np.diff(fr)
        bw = np.concatenate([[dfs[0]], (dfs[:-1] + dfs[1:]) / 2, [dfs[-1]]])
        cap_bps = float(np.sum(bw * np.log2(1 + 10 ** (snr_db / 10))))
        wf = {"n_tones": int(len(fr)), "f_lo": float(fr[0]), "f_hi": float(fr[-1]),
              "snr_db_median": round(float(np.median(snr_db)), 1),
              "snr_db_p10": round(float(np.percentile(snr_db, 10)), 1),
              "awgn_waterfill_bps": round(cap_bps)}
        # attribution check: does the LINEAR channel (sounder H, SNR) dip at the
        # dirty OFDM carriers? flat there => dirt is nonlinear self-noise (IMD).
        H = np.asarray(sounder.get("H_db", []), float)
        if H.size == len(fr):
            chk = {}
            for f0 in (1500, 2250, 3375, 4500, 5250, 5625, 6750, 7125, 7875):
                i = int(np.argmin(np.abs(fr - f0)))
                chk[str(f0)] = {"sounder_f": float(fr[i]),
                                "H_db": round(float(H[i]), 1),
                                "snr_db": round(float(snr_db[i]), 1)}
            wf["dirty_vs_clean_freqs"] = chk
    except Exception as exc:
        wf = {"error": f"{type(exc).__name__}: {exc}",
              "sounder_keys": sorted(sounder.keys())}

    out = {"capture": cap, "clock_ratio": sync.get("clock_ratio"),
           "waterfilling": wf, "sections": []}

    # ---- per-section soft probes ------------------------------------------
    for sec in manifest["ws_payloads"]:
        if sec["name"] in TARGETS and not sec.get("skipped"):
            r = probe_section(audio_nom, sec, align, TARGETS[sec["name"]])
            out["sections"].append(r)
            print(f"== {r['section']} (alpha={r['alpha']}) "
                  f"pilot_amp_db_std={r['pilot_amp_db_std_median']}")
            for pc in r["per_carrier"]:
                print(f"  f={pc['f_hz']:7.1f}  rms={pc['rms_deg']:6.2f}d "
                      f"p99={pc['p99_deg']:6.2f}d  >45:{pc['frac_gt45']:.4f} "
                      f">22.5:{pc['frac_gt22p5']:.4f} >11.25:{pc['frac_gt11p25']:.4f} "
                      f"ampdb={pc['amp_ratio_db_std']:.2f} rho1={pc['lag1_rho']}")
            print(f"  decomp: {r['timing_floor_decomp']}")

    # ---- x9 residual stats on a few m8 frames ------------------------------
    sec8 = next(s for s in manifest["ws_payloads"] if s["name"] == "m9_m8_dense375")
    sch8 = m9d._scheme_from_entry(sec8)
    meta8 = sec8["meta"]
    nb8 = m9d._nominal_frame_bits(meta8)
    pad_lo, pad_hi = int(PAD_LO_S * SR), int(PAD_HI_S * SR)
    flen8 = len(np.asarray(sch8.modulate(np.zeros(meta8["frame_bits"], np.uint8))))
    rs_list = []
    for fi in (0, 8, 16, 24):
        st = int(sec8["frame_starts"][fi]) + align
        y = np.asarray(audio_nom[max(0, st - pad_lo):
                                 min(len(audio_nom), st + flen8 + pad_hi)], np.float64)
        rs = residual_stats(sch8, y, sch8.nsym_data(nb8[fi]))
        rs_list.append({k: (round(float(v), 3) if isinstance(v, (int, float)) else v)
                        for k, v in rs.items() if isinstance(v, (int, float))})
    out["m8_residual_stats_frames_0_8_16_24"] = rs_list
    print("m8 residual_stats:", json.dumps(rs_list)[:400])
    print("waterfilling:", json.dumps(wf))

    rp = _HERE / "results" / "x10_c_evm_probe.json"
    rp.write_text(json.dumps(out, indent=2, default=float))
    print(f"[x10_c_evm_probe] wrote {rp}")


if __name__ == "__main__":
    main()
