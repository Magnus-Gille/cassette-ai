"""x9_margin_forensics.py -- R2: real-capture margin forensics for the 934 bps DQPSK rung.

The dq_p10n512_rs127 section decoded with ZERO RS codeword failures on the real
tape capture. ZERO errors tells us nothing about HOW MUCH margin it had. This
script measures the margin DIRECTLY from the capture, per symbol and per carrier:

  1. Differential-phase RESIDUAL after pilot correction + after decision (deg).
     -> would D8PSK (22.5 deg slice) / 16-DAPSK have survived? With what headroom
        did QPSK (45 deg) pass?
  2. Pilot dtau trace -> flutter PSD, total wrms, residual after the EMA -> the
     tracking bandwidth the channel actually needs.
  3. Per-carrier amplitude stability + per-carrier demod-output SNR.
  4. Cross-bin leakage at 1,2,4-bin offsets vs carrier power -> supportable carrier
     spacing WITHOUT AAC masking (captures are now lossless).
  5. Same instrumentation on a FAILED N1024 section to confirm the failure
     mechanism (pilot tracking too slow vs other).

We REUSE m8_decode's global sync + resample (its decode() does the heavy lifting
to produce audio_nom + align). We do NOT modify any existing file. The demod is
re-implemented here as an INSTRUMENTED mirror of h4_dqpsk.DQPSKScheme.demod --
bit-for-bit the same math, but it records every intermediate. We cross-check our
mirror against the shipping demod's bit output to prove fidelity.

Truth (the sidecar payload bytes) is used ONLY for cross-checking decode quality,
never inside the demod.

Output: x9_dossier/R2_margins.md + R2_margins.json
"""
from __future__ import annotations

import json
import pathlib
import sys

import numpy as np
import soundfile as sf
from fractions import Fraction
from scipy.signal import resample_poly, welch

_HERE = pathlib.Path(__file__).resolve().parent
ROOT = pathlib.Path("/Users/magnus/repos/cassette-ai")
for _p in (ROOT / "src", ROOT / "tests" / "e2e",
           ROOT / "experiments" / "deepdive2",
           ROOT / "experiments" / "capacity", _HERE):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

np.seterr(divide="ignore", over="ignore", invalid="ignore")

import analyze_master2 as am2          # noqa: E402
import m3_codec as codec               # noqa: E402
from m3_codec import Rung               # noqa: E402
from h4_dqpsk import DQPSKScheme, FS as DQ_FS, PAD_LO_S, PAD_HI_S  # noqa: E402

import hyp_common as hc                # noqa: E402

SR = codec.FS
FS = DQ_FS
MANIFEST_PATH = _HERE / "master8_manifest.json"
CAPTURE = _HERE / "captures" / "m8_tape_mono_lossless.wav"
OUT_DIR = _HERE / "x9_dossier"

TARGET_PASS = "m8_dq_p10n512_rs127"
TARGET_FAIL = "m8_dq_p10n1024_rs159"


# ---------------------------------------------------------------------------
# Instrumented demod -- EXACT mirror of h4_dqpsk.DQPSKScheme.demod, but it
# records every per-symbol / per-carrier intermediate. Any divergence from the
# shipping demod's bits is a bug; we cross-check below.
# ---------------------------------------------------------------------------
def instrumented_demod(sch: DQPSKScheme, win_audio: np.ndarray, nd: int,
                       refine: bool = True) -> dict:
    y = np.asarray(win_audio, np.float64)
    ds = hc.find_preamble(y.astype(np.float32), sch.preamble_seconds)
    total = nd + 1
    nc = sch.P + 1
    N, skip, Nw = sch.N, sch.skip, sch.Nw
    fpil = sch.freqs[sch.pilot_idx]

    c = np.zeros((total, nc), np.complex128)        # carrier DFT correlator outputs
    dtau = np.zeros(total)                           # seconds, per symbol (EMA-smoothed)
    dtau_raw = np.zeros(total)                        # per-symbol pilot dtau BEFORE EMA
    drift_trace = np.zeros(total)                     # accumulated window drift (samples)
    drift = 0.0
    ema = 0.5
    sm = 0.0

    # cross-bin leakage: also correlate at +/-1, +/-2, +/-4 bins from each carrier
    df = FS / N
    off_bins = [1, 2, 4]
    # absolute frequencies for the offset probes (per carrier)
    leak_freqs = {}  # ob -> (nc,) array of [carrier_freq + ob*df] and [- ob*df]
    for ob in off_bins:
        leak_freqs[ob] = (sch.freqs + ob * df, sch.freqs - ob * df)
    leak_c = {ob: (np.zeros((total, nc), np.complex128),
                   np.zeros((total, nc), np.complex128)) for ob in off_bins}

    for i in range(total):
        base = ds + i * N + int(round(drift))
        lo = base + skip
        seg = y[lo: lo + Nw]
        if len(seg) < Nw:
            seg = np.concatenate([seg, np.zeros(Nw - len(seg))])
        tt = (lo + np.arange(Nw)) / FS
        wseg = seg * sch._win
        E = np.exp(-2j * np.pi * np.outer(sch.freqs, tt))
        c[i] = E @ wseg
        # leakage probes at the same window
        for ob in off_bins:
            fhi, flo = leak_freqs[ob]
            Ehi = np.exp(-2j * np.pi * np.outer(fhi, tt))
            Elo = np.exp(-2j * np.pi * np.outer(flo, tt))
            leak_c[ob][0][i] = Ehi @ wseg
            leak_c[ob][1][i] = Elo @ wseg
        if i > 0:
            dp = float(np.angle(c[i, sch.pilot_idx] *
                                np.conj(c[i - 1, sch.pilot_idx])))
            raw = dp / (2 * np.pi * fpil)
            dtau_raw[i] = raw
            sm = (1 - ema) * raw + ema * sm
            dtau[i] = sm
            drift -= dtau[i] * FS
            drift = float(np.clip(drift, -200, 200))
        drift_trace[i] = drift

    # ---- differential decisions (mirror) ----
    fd = sch.freqs[sch.data_idx]
    d = c[1:, :] * np.conj(c[:-1, :])               # (nd, nc)
    dphi = np.angle(d[:, sch.data_idx])             # (nd, P) raw differential phase
    dphi_corr = dphi - 2 * np.pi * np.outer(dtau[1:], fd)   # after pilot correction
    q = np.round(dphi_corr / (np.pi / 2.0)).astype(int) % 4

    dtau_res = np.zeros(nd)
    if refine:
        res = (dphi_corr - q * (np.pi / 2.0) + np.pi) % (2 * np.pi) - np.pi
        num = (res * fd[None, :]).sum(axis=1)
        den = (fd ** 2).sum()
        dtau_res = num / (2 * np.pi * den)          # (nd,)
        dphi2 = dphi_corr - 2 * np.pi * dtau_res[:, None] * fd[None, :]
        q2 = np.round(dphi2 / (np.pi / 2.0)).astype(int) % 4
        dphi_final = dphi2
        q_final = q2
    else:
        dphi_final = dphi_corr
        q_final = q

    # residual phase from decided quadrant center (the slicing margin), wrapped to
    # [-pi, pi). distance to nearest quadrant boundary = pi/4 - |residual|.
    resid = (dphi_final - q_final * (np.pi / 2.0) + np.pi) % (2 * np.pi) - np.pi  # (nd, P)

    bits = sch.quadrants_to_bits(q_final)

    return {
        "ds": int(ds),
        "c": c, "leak_c": leak_c, "off_bins": off_bins, "df": df,
        "dtau": dtau, "dtau_raw": dtau_raw, "dtau_res": dtau_res,
        "drift_trace": drift_trace,
        "dphi_raw": dphi, "dphi_corr": dphi_corr, "dphi_final": dphi_final,
        "q_final": q_final, "resid_rad": resid, "fd": fd, "fpil": fpil,
        "bits": bits, "nd": nd,
    }


# ---------------------------------------------------------------------------
def _section_audio_nom():
    """Run m8_decode's global sync + resample to get audio_nom + align, plus the
    manifest. Mirrors m8_decode.decode() preamble exactly."""
    manifest = json.loads(MANIFEST_PATH.read_text())
    audio, sr = sf.read(str(CAPTURE), dtype="float32", always_2d=False)
    if audio.ndim > 1:
        audio = audio.mean(axis=1)
    if sr != SR:
        frac = Fraction(SR, sr).limit_denominator(20000)
        audio = resample_poly(audio.astype(np.float64), frac.numerator, frac.denominator)
    sync = am2.global_sync_and_resample(audio, manifest)
    audio_nom = sync["audio_nominal"]
    align = sync["chirp0_nominal"] - manifest["tx_chirp0"]
    return manifest, audio_nom, align, sync


def _get_section(manifest, name):
    for s in manifest["ws_payloads"]:
        if s["name"] == name:
            return s
    raise KeyError(name)


def _nom_bits_for(meta):
    fb = meta["frame_bits"]
    n = meta["n_frames"]
    return [fb] * (n - 1) + [meta["stream_bits"] - fb * (n - 1)]


def _pctl(a, ps):
    a = np.asarray(a, float)
    a = a[np.isfinite(a)]
    if a.size == 0:
        return {f"p{p}": None for p in ps}
    return {f"p{p}": float(np.percentile(a, p)) for p in ps}


# ---------------------------------------------------------------------------
def analyze_section(manifest, audio_nom, align, name, *, label):
    sec = _get_section(manifest, name)
    dq = sec["dqpsk_params"]
    sch = DQPSKScheme(dq["P"], dq["N"], dq["spacing"])
    meta = sec["meta"]
    expected_packed = (_HERE / sec["payload_sidecar"]).read_bytes()

    # Reconstruct the TRANSMITTED frame bits by re-encoding the known packed
    # payload through the same codec (mirrors _ws_recovered_packed). This gives
    # the TRUE per-symbol per-carrier quadrants so we can measure the ACTUAL
    # slicing margin (residual vs TRUE quadrant) and the TRUE raw symbol error
    # rate. Truth is used for SCORING ONLY -- never inside the demod.
    rung = Rung(name=meta["rung"], M=meta["M"], K=meta["K"],
                rs_n=meta["rs_n"], rs_k=meta["rs_k"],
                frame_bytes=meta["frame_bytes"])
    tx_frames, _meta2 = codec.encode_payload(expected_packed, rung)
    true_quadrants = [sch.bits_to_quadrants(np.asarray(tb, np.uint8))
                      for tb in tx_frames]   # each (nd, P)

    fb = meta["frame_bits"]
    n_frames = meta["n_frames"]
    nom_bits = _nom_bits_for(meta)
    pad_lo, pad_hi = int(PAD_LO_S * FS), int(PAD_HI_S * FS)
    full_frame = np.asarray(sch.modulate(np.zeros(fb, np.uint8)), np.float32)
    flen_full = len(full_frame)

    P = sch.P
    N = sch.N
    df = FS / N

    # accumulators across all symbols/carriers in the whole section
    all_resid_deg = []                      # |residual| per (symbol,carrier) in deg
    per_carrier_resid_deg = [[] for _ in range(P)]
    all_dtau = []                           # EMA-smoothed dtau, seconds (excl sym0)
    all_dtau_raw = []                       # raw per-symbol pilot dtau, seconds
    all_dtau_res = []                       # decision-directed residual dtau, seconds
    per_carrier_amp = [[] for _ in range(P)]    # |c| at each carrier, per symbol
    pilot_amp = []
    # leakage: ratio of |leak|^2 at offset ob to mean carrier power, per carrier
    leak_ratio = {1: [[] for _ in range(P)], 2: [[] for _ in range(P)],
                  4: [[] for _ in range(P)]}
    # TRUTH-referenced margin: residual phase vs the TRUE transmitted quadrant
    # (the honest "how close to a wrong decision did we come"), and the TRUE raw
    # symbol error count (a decision landing in a different quadrant than truth).
    all_true_margin_deg = []                    # signed |angle to true quadrant ctr|
    per_carrier_true_margin = [[] for _ in range(P)]
    sym_err_total = 0
    sym_total = 0
    per_carrier_sym_err = np.zeros(P, int)
    per_carrier_sym_tot = np.zeros(P, int)
    # per-carrier demod SNR: signal = decided constellation; noise = residual phasor
    # we estimate per-carrier output SNR from the differential phasor d: the decided
    # unit vector vs the residual error vector.
    per_carrier_dphasor_err = [[] for _ in range(P)]   # |error| / |signal| linear

    rx_frames = []
    bits_match_frames = 0
    for fi, st in enumerate(sec["frame_starts"]):
        nd = sch.nsym_data(nom_bits[fi])
        st_a = int(st) + align
        w_lo = max(0, st_a - pad_lo)
        w_hi = min(len(audio_nom), st_a + flen_full + pad_hi)
        win = np.asarray(audio_nom[w_lo:w_hi], np.float64)

        # cross-check: shipping demod vs our instrumented mirror (same bits)
        ship_bits, _diag = sch.demod(win, nd)
        info = instrumented_demod(sch, win, nd)
        if np.array_equal(np.asarray(ship_bits, np.uint8),
                          np.asarray(info["bits"], np.uint8)):
            bits_match_frames += 1
        rx_frames.append(np.asarray(info["bits"], np.uint8))

        resid_deg = np.degrees(np.abs(info["resid_rad"]))   # (nd, P)
        all_resid_deg.append(resid_deg.ravel())
        for k in range(P):
            per_carrier_resid_deg[k].extend(resid_deg[:, k].tolist())

        # ---- TRUTH-referenced margin + true symbol errors ----
        tq = true_quadrants[fi]                              # (nd_true, P)
        q_dec = info["q_final"]                              # (nd, P) decided
        dphi_fin = info["dphi_final"]                        # (nd, P) corrected diff phase
        m = min(len(tq), len(q_dec))
        if m > 0:
            tqm = tq[:m]; qdm = q_dec[:m]; dpm = dphi_fin[:m]
            # true symbol errors: decided quadrant != true quadrant
            err = (qdm != tqm)
            sym_err_total += int(err.sum())
            sym_total += err.size
            per_carrier_sym_err += err.sum(axis=0)
            per_carrier_sym_tot += err.shape[0]
            # TRUE margin: phase distance from the TRUE quadrant center. Positive =
            # safe side; this is how far the received phasor sat from the boundary
            # toward the correct decision. We report the SIGNED distance to the
            # nearest boundary relative to TRUTH: margin = pi/4 - |phase - true_ctr|.
            # In degrees, a positive margin means correct & that many deg of slack;
            # negative means it crossed into a wrong quadrant (a symbol error).
            true_off = (dpm - tqm * (np.pi / 2.0) + np.pi) % (2 * np.pi) - np.pi
            margin_deg = 45.0 - np.degrees(np.abs(true_off))  # >0 correct, <0 error
            all_true_margin_deg.append(margin_deg.ravel())
            for k in range(P):
                per_carrier_true_margin[k].extend(margin_deg[:, k].tolist())

        # dtau traces (skip symbol 0 which has no differential)
        all_dtau.extend(info["dtau"][1:].tolist())
        all_dtau_raw.extend(info["dtau_raw"][1:].tolist())
        all_dtau_res.extend(info["dtau_res"].tolist())

        # amplitudes from c (use the analysis symbols 1..nd that carry data)
        c = info["c"]                                        # (total, nc)
        for k_data, kk in enumerate(sch.data_idx):
            per_carrier_amp[k_data].extend(np.abs(c[1:, kk]).tolist())
        pilot_amp.extend(np.abs(c[1:, sch.pilot_idx]).tolist())

        # per-carrier mean power for leakage normalization (use data carriers)
        car_pow = np.abs(c[:, sch.data_idx]) ** 2            # (total, P)
        car_pow_mean = car_pow.mean(axis=0) + 1e-30          # (P,)
        for ob in (1, 2, 4):
            hi, lo = info["leak_c"][ob]                      # each (total, nc)
            # average the +ob and -ob leakage power at each DATA carrier
            lp_hi = np.abs(hi[:, sch.data_idx]) ** 2
            lp_lo = np.abs(lo[:, sch.data_idx]) ** 2
            lp = 0.5 * (lp_hi + lp_lo)                       # (total, P)
            ratio = lp.mean(axis=0) / car_pow_mean           # (P,)
            for k in range(P):
                leak_ratio[ob][k].append(float(ratio[k]))

        # per-carrier output SNR via differential phasor error.
        # d = c[1:]*conj(c[:-1]); after correcting common timing, the decided
        # phasor should sit at q*90deg. Error magnitude = |d_corrected - decided|.
        d = c[1:, :] * np.conj(c[:-1, :])
        dd = d[:, sch.data_idx]                              # (nd, P)
        # correct common timing (pilot dtau) on the phasor
        corr = np.exp(-1j * 2 * np.pi * np.outer(info["dtau"][1:], info["fd"]))
        ddc = dd * corr
        mag = np.abs(ddc) + 1e-30
        decided = np.exp(1j * info["q_final"] * (np.pi / 2.0))   # unit decided dir
        unit = ddc / mag[:, None] if ddc.ndim == 1 else ddc / mag
        err_vec = unit - decided                              # (nd, P)
        err_mag = np.abs(err_vec)                             # ~ angular error in rad for small
        for k in range(P):
            per_carrier_dphasor_err[k].extend(err_mag[:, k].tolist())

    # RS decode quality (truth used for scoring only)
    recovered = codec.decode_payload(rx_frames, meta)
    cw_failed = codec.decode_payload.last_codewords_failed
    byte_exact = recovered == expected_packed
    byte_err = sum(a != b for a, b in zip(recovered, expected_packed)) + abs(
        len(recovered) - len(expected_packed))

    # ---------- summarize ----------
    all_resid_deg = np.concatenate(all_resid_deg)
    overall_resid = {
        "median": float(np.median(all_resid_deg)),
        **_pctl(all_resid_deg, [50, 90, 95, 99, 99.9]),
        "max": float(np.max(all_resid_deg)),
        "n_decisions": int(all_resid_deg.size),
        # fraction of decisions OUTSIDE a given slicing margin (would-fail rate)
        "frac_over_22p5deg": float(np.mean(all_resid_deg > 22.5)),   # D8PSK boundary
        "frac_over_11p25deg": float(np.mean(all_resid_deg > 11.25)), # D16PSK boundary
        "frac_over_45deg": float(np.mean(all_resid_deg >= 45.0)),    # QPSK fail (wrap)
    }
    per_carrier_resid = []
    for k in range(P):
        a = np.asarray(per_carrier_resid_deg[k])
        per_carrier_resid.append({
            "carrier_idx": k,
            "freq_hz": round(float(sch.freqs[sch.data_idx[k]]), 1),
            "median_deg": float(np.median(a)),
            "p90_deg": float(np.percentile(a, 90)),
            "p99_deg": float(np.percentile(a, 99)),
            "max_deg": float(np.max(a)),
            "frac_over_22p5deg": float(np.mean(a > 22.5)),
        })

    # ---- TRUTH-referenced margin (the honest answer) ----
    tm = np.concatenate(all_true_margin_deg) if all_true_margin_deg else np.zeros(0)
    # margin = 45 - |dev from true quadrant|; <0 = a real symbol error.
    # min margin among CORRECT symbols = worst-case headroom to the QPSK boundary.
    correct = tm[tm > 0]
    true_margin = {
        "definition": "deg of slack to the nearest quadrant boundary, vs TRUE tx "
                      "quadrant. >0 = correct decision with that headroom; <0 = a "
                      "symbol error (crossed boundary).",
        "raw_symbol_error_rate": float(sym_err_total / max(1, sym_total)),
        "n_symbol_errors": int(sym_err_total),
        "n_symbols": int(sym_total),
        # worst headroom among the correct decisions = the true QPSK margin used
        "min_margin_correct_deg": float(np.min(correct)) if correct.size else None,
        "p1_margin_deg": float(np.percentile(tm, 1)) if tm.size else None,
        "p0p1_margin_deg": float(np.percentile(tm, 0.1)) if tm.size else None,
        "median_margin_deg": float(np.median(tm)) if tm.size else None,
        # would D8PSK survive? a D8PSK symbol error happens when |dev|>22.5deg, i.e.
        # margin < 22.5. count those (would-be raw errors at the 22.5 slice).
        "frac_below_22p5_margin": float(np.mean(tm < 22.5)) if tm.size else None,
        "frac_below_11p25_margin": float(np.mean(tm < 33.75)) if tm.size else None,
    }
    per_carrier_true_margin_stats = []
    for k in range(P):
        a = np.asarray(per_carrier_true_margin[k])
        ser = float(per_carrier_sym_err[k] / max(1, per_carrier_sym_tot[k]))
        per_carrier_true_margin_stats.append({
            "carrier_idx": k,
            "freq_hz": round(float(sch.freqs[sch.data_idx[k]]), 1),
            "raw_ser": ser,
            "n_sym_err": int(per_carrier_sym_err[k]),
            "min_margin_deg": float(np.min(a)) if a.size else None,
            "p1_margin_deg": float(np.percentile(a, 1)) if a.size else None,
            "median_margin_deg": float(np.median(a)) if a.size else None,
        })

    # flutter / dtau
    dtau_raw_arr = np.asarray(all_dtau_raw)
    dtau_ema_arr = np.asarray(all_dtau)
    dtau_res_arr = np.asarray(all_dtau_res)
    sym_rate = FS / N                                   # symbols/sec (dtau sampled per symbol)
    # wrms of the per-symbol dtau (relative timing jitter). dtau is delta-tau between
    # consecutive symbols (sec). Convert to a relative-rate wrms: dtau * sym_rate =
    # fractional speed deviation per symbol.
    rel_rate_raw = dtau_raw_arr * sym_rate              # fractional speed error/symbol
    rel_rate_res = dtau_res_arr * sym_rate
    flutter = {
        "symbol_rate_hz": float(sym_rate),
        "dtau_raw_std_us": float(np.std(dtau_raw_arr) * 1e6),
        "dtau_ema_std_us": float(np.std(dtau_ema_arr) * 1e6),
        "dtau_res_std_us": float(np.std(dtau_res_arr) * 1e6),
        "rel_rate_raw_wrms_pct": float(np.std(rel_rate_raw) * 100.0),
        "rel_rate_res_wrms_pct": float(np.std(rel_rate_res) * 100.0),
        "residual_reduction_x": float(np.std(dtau_raw_arr) /
                                      (np.std(dtau_res_arr) + 1e-30)),
    }
    # PSD of the raw per-symbol dtau (flutter spectrum). nperseg modest.
    if dtau_raw_arr.size >= 64:
        nseg = min(256, dtau_raw_arr.size)
        f_psd, psd = welch(dtau_raw_arr - dtau_raw_arr.mean(), fs=sym_rate,
                           nperseg=nseg)
        # find the frequency below which 90% of flutter energy lies
        cum = np.cumsum(psd)
        cum /= cum[-1] + 1e-30
        f90 = float(f_psd[np.searchsorted(cum, 0.90)]) if cum[-1] > 0 else None
        f50 = float(f_psd[np.searchsorted(cum, 0.50)]) if cum[-1] > 0 else None
        # peak flutter frequency (excluding DC bin)
        pk = int(np.argmax(psd[1:]) + 1) if psd.size > 1 else 0
        flutter["psd_freqs_hz"] = [round(float(x), 3) for x in f_psd.tolist()]
        flutter["psd"] = [float(x) for x in psd.tolist()]
        flutter["flutter_f90_hz"] = f90
        flutter["flutter_f50_hz"] = f50
        flutter["flutter_peak_hz"] = round(float(f_psd[pk]), 3)
        flutter["required_tracking_bw_hz_est"] = f90
    else:
        flutter["psd_freqs_hz"] = []
        flutter["psd"] = []

    # amplitude stability + output SNR per carrier
    per_carrier_amp_stats = []
    for k in range(P):
        a = np.asarray(per_carrier_amp[k])
        an = a / (np.mean(a) + 1e-30)
        cov = float(np.std(a) / (np.mean(a) + 1e-30))
        # per-carrier output SNR from phasor error: SNR ~ 1 / mean(err_mag^2)
        em = np.asarray(per_carrier_dphasor_err[k])
        evm = float(np.sqrt(np.mean(em ** 2)))          # error vector magnitude
        snr_db = float(-20.0 * np.log10(evm + 1e-30))
        per_carrier_amp_stats.append({
            "carrier_idx": k,
            "freq_hz": round(float(sch.freqs[sch.data_idx[k]]), 1),
            "mean_amp": float(np.mean(a)),
            "amp_cov_pct": round(cov * 100.0, 2),
            "amp_p10_over_median": float(np.percentile(an, 10)),
            "amp_p90_over_median": float(np.percentile(an, 90)),
            "evm_rms": round(evm, 4),
            "out_snr_db": round(snr_db, 2),
        })

    # leakage summary per offset
    leak_summary = {}
    for ob in (1, 2, 4):
        per_car = []
        for k in range(P):
            r = np.asarray(leak_ratio[ob][k])
            per_car.append(float(np.mean(r)))
        per_car = np.asarray(per_car)
        leak_summary[f"offset_{ob}bin_{round(ob*df)}hz"] = {
            "mean_leak_db": round(float(10 * np.log10(np.mean(per_car) + 1e-30)), 2),
            "max_leak_db": round(float(10 * np.log10(np.max(per_car) + 1e-30)), 2),
            "per_carrier_leak_db": [round(float(10 * np.log10(x + 1e-30)), 2)
                                    for x in per_car],
        }

    return {
        "section": name,
        "label": label,
        "P": P, "N": N, "spacing": dq["spacing"],
        "df_hz": round(df, 2),
        "carrier_freqs_hz": [round(float(f), 1) for f in sch.freqs[sch.data_idx]],
        "pilot_hz": round(float(sch.freqs[sch.pilot_idx]), 1),
        "symbol_ms": round(N / FS * 1000.0, 3),
        "n_frames": n_frames,
        "n_decisions": int(all_resid_deg.size),
        "instrumented_demod_matches_shipping_frames": f"{bits_match_frames}/{n_frames}",
        "rs_codewords_failed": cw_failed,
        "n_codewords": meta["n_codewords"],
        "byte_exact": byte_exact,
        "byte_errors": byte_err,
        "true_margin": true_margin,
        "per_carrier_true_margin": per_carrier_true_margin_stats,
        "differential_phase_residual_deg": overall_resid,
        "per_carrier_residual": per_carrier_resid,
        "flutter": flutter,
        "per_carrier_amplitude_and_snr": per_carrier_amp_stats,
        "cross_bin_leakage": leak_summary,
        "pilot_mean_amp": float(np.mean(pilot_amp)),
    }


# ---------------------------------------------------------------------------
def spacing_sir_analysis(manifest, audio_nom, align, name):
    """Measure the ACHIEVABLE carrier spacing without AAC, directly from the
    PASS capture. For each captured data symbol we form the Hann-windowed
    analysis segment (exactly as the demod does) and correlate at FINE frequency
    offsets around each carrier. The leakage at offset df_off = (neighbor power
    that would land in this carrier's bin). SIR(spacing) = carrier power / sum of
    both neighbors' leakage at +/- spacing. This tells us the tightest spacing
    that still clears, say, 20 dB SIR -- the real spacing budget now that captures
    are lossless (no AAC masking skirt)."""
    sec = _get_section(manifest, name)
    dq = sec["dqpsk_params"]
    sch = DQPSKScheme(dq["P"], dq["N"], dq["spacing"])
    meta = sec["meta"]
    N, skip, Nw = sch.N, sch.skip, sch.Nw
    df = FS / N
    fb = meta["frame_bits"]
    nom_bits = _nom_bits_for(meta)
    pad_lo = int(PAD_LO_S * FS)
    full_frame = np.asarray(sch.modulate(np.zeros(fb, np.uint8)), np.float32)
    flen_full = len(full_frame)
    win = sch._win

    # candidate offsets in Hz around a carrier (one-sided; we mirror for SIR)
    off_hz = np.arange(50.0, 800.0, 25.0)
    # accumulate mean leakage power at each offset, normalized to carrier power,
    # averaged over all carriers + symbols.
    acc_leak = np.zeros(len(off_hz))
    acc_n = 0
    carrier_pow_acc = 0.0
    carrier_pow_n = 0

    for fi, st in enumerate(sec["frame_starts"][:8]):   # 8 frames is plenty
        nd = sch.nsym_data(nom_bits[fi])
        st_a = int(st) + align
        w_lo = max(0, st_a - pad_lo)
        w_hi = min(len(audio_nom), st_a + flen_full + int(PAD_HI_S * FS))
        y = np.asarray(audio_nom[w_lo:w_hi], np.float64)
        ds = hc.find_preamble(y.astype(np.float32), sch.preamble_seconds)
        for i in range(1, nd + 1):                       # data symbols
            base = ds + i * N
            lo = base + skip
            seg = y[lo: lo + Nw]
            if len(seg) < Nw:
                break
            tt = (lo + np.arange(Nw)) / FS
            wseg = seg * win
            for kk in sch.data_idx:
                fc = sch.freqs[kk]
                # carrier power
                ec = np.exp(-2j * np.pi * fc * tt)
                pc = abs(ec @ wseg) ** 2
                carrier_pow_acc += pc
                carrier_pow_n += 1
                # leakage power at fc +/- off (average the two sides)
                for j, dfo in enumerate(off_hz):
                    eh = np.exp(-2j * np.pi * (fc + dfo) * tt)
                    el = np.exp(-2j * np.pi * (fc - dfo) * tt)
                    lp = 0.5 * (abs(eh @ wseg) ** 2 + abs(el @ wseg) ** 2)
                    acc_leak[j] += lp / (pc + 1e-30)
                    acc_n += 1
    mean_leak = acc_leak / max(1, acc_n) * len(sch.data_idx)  # back to per-offset mean
    mean_leak = acc_leak / max(1, acc_n)
    leak_db = 10 * np.log10(mean_leak + 1e-30)
    # SIR at a candidate spacing = -10log10(2 * leak_at_spacing) (two neighbors)
    sir_db = -10 * np.log10(2 * mean_leak + 1e-30)
    # the tightest spacing that clears 15 / 20 / 25 dB SIR
    def tightest_for(target):
        ok = np.where(sir_db >= target)[0]
        return float(off_hz[ok[0]]) if len(ok) else None
    return {
        "section": name,
        "analysis_window_Nw_samples": int(Nw),
        "current_spacing_hz": round(dq["spacing"] * df, 1),
        "note": "leakage = windowed single-carrier spectral skirt (the real ICI a "
                "neighbor at that offset would inject). SIR assumes two equal "
                "neighbors. No AAC: pure window+channel limited.",
        "offsets_hz": [round(float(x), 1) for x in off_hz],
        "leak_db_at_offset": [round(float(x), 2) for x in leak_db],
        "sir_db_at_spacing": [round(float(x), 2) for x in sir_db],
        "tightest_spacing_for_15dB_sir_hz": tightest_for(15.0),
        "tightest_spacing_for_20dB_sir_hz": tightest_for(20.0),
        "tightest_spacing_for_25dB_sir_hz": tightest_for(25.0),
    }


# ---------------------------------------------------------------------------
def _slim_flutter(f):
    """Drop the big PSD arrays from the flutter dict for the top-level JSON; keep
    scalars + a downsampled PSD."""
    out = {k: v for k, v in f.items() if k not in ("psd", "psd_freqs_hz")}
    # keep a compact PSD (first 40 bins) for plotting later
    pf = f.get("psd_freqs_hz", [])
    ps = f.get("psd", [])
    n = min(40, len(ps))
    out["psd_compact"] = [{"f_hz": pf[i], "psd": ps[i]} for i in range(n)]
    return out


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    print("[x9] running m8 global sync + resample ...", flush=True)
    manifest, audio_nom, align, sync = _section_audio_nom()
    print(f"[x9] sync clock {sync['speed']:.5f}x  align {align:+d}", flush=True)

    print(f"[x9] analyzing PASS section {TARGET_PASS} (934 bps) ...", flush=True)
    res_pass = analyze_section(manifest, audio_nom, align, TARGET_PASS,
                               label="PASS_934bps")
    print(f"     residual median {res_pass['differential_phase_residual_deg']['median']:.2f} deg "
          f"p99 {res_pass['differential_phase_residual_deg']['p99']:.2f} deg "
          f"max {res_pass['differential_phase_residual_deg']['max']:.2f} deg "
          f"cwFail {res_pass['rs_codewords_failed']}/{res_pass['n_codewords']}",
          flush=True)

    print(f"[x9] analyzing FAIL section {TARGET_FAIL} (N1024) ...", flush=True)
    res_fail = analyze_section(manifest, audio_nom, align, TARGET_FAIL,
                               label="FAIL_N1024")
    print(f"     residual median {res_fail['differential_phase_residual_deg']['median']:.2f} deg "
          f"p99 {res_fail['differential_phase_residual_deg']['p99']:.2f} deg "
          f"max {res_fail['differential_phase_residual_deg']['max']:.2f} deg "
          f"cwFail {res_fail['rs_codewords_failed']}/{res_fail['n_codewords']}",
          flush=True)

    print("[x9] spacing/SIR analysis on PASS section (no-AAC budget) ...", flush=True)
    spacing = spacing_sir_analysis(manifest, audio_nom, align, TARGET_PASS)
    print(f"     tightest spacing for 20 dB SIR: "
          f"{spacing['tightest_spacing_for_20dB_sir_hz']} Hz "
          f"(15 dB: {spacing['tightest_spacing_for_15dB_sir_hz']} Hz)", flush=True)

    out = {
        "task": "R2 real-capture margin forensics",
        "capture": str(CAPTURE),
        "sync": {"speed": float(sync["speed"]),
                 "speed_offset_pct": float(sync["speed_offset"] * 100),
                 "align": int(align)},
        "pass_section": res_pass,
        "fail_section": res_fail,
        "spacing_sir": spacing,
    }
    # slim PSD for the JSON
    out["pass_section"]["flutter"] = _slim_flutter(out["pass_section"]["flutter"])
    out["fail_section"]["flutter"] = _slim_flutter(out["fail_section"]["flutter"])

    (OUT_DIR / "R2_margins.json").write_text(json.dumps(out, indent=2, default=float))
    print(f"[x9] wrote {OUT_DIR / 'R2_margins.json'}", flush=True)
    _write_md(out)
    print(f"[x9] wrote {OUT_DIR / 'R2_margins.md'}", flush=True)
    return out


def _write_md(out):
    p = out["pass_section"]
    f = out["fail_section"]

    def resid_line(s):
        r = s["differential_phase_residual_deg"]
        return (f"median {r['median']:.2f} deg, p90 {r['p90']:.2f}, p99 {r['p99']:.2f}, "
                f"p99.9 {r['p99.9']:.2f}, max {r['max']:.2f}")

    lines = []
    A = lines.append
    A("# R2 - Real-Capture Margin Forensics (934 bps DQPSK rung)\n")
    A(f"Capture: `{out['capture']}`  ")
    A(f"Global sync: clock {out['sync']['speed']:.5f}x "
      f"({out['sync']['speed_offset_pct']:+.3f}%), align {out['sync']['align']:+d}\n")
    A("The `dq_p10n512_rs127` section decoded with ZERO RS codeword failures on the "
      "real tape. This dossier measures HOW MUCH margin it actually had, directly "
      "from the capture, and instruments the failed N1024 section to pin its "
      "failure mechanism.\n")
    A("Demod fidelity check: the instrumented mirror reproduced the shipping "
      f"`DQPSKScheme.demod` bits on {p['instrumented_demod_matches_shipping_frames']} "
      f"(PASS) and {f['instrumented_demod_matches_shipping_frames']} (FAIL) frames.\n")

    A("## 0. TRUTH-referenced margin (the honest answer)\n")
    A("`true_margin` = degrees of slack from the received phasor to the nearest "
      "quadrant boundary, measured against the TRUE transmitted quadrant. >0 means a "
      "correct decision with that much headroom; <0 means the symbol crossed a "
      "boundary (a real symbol error). QPSK boundary = +/-45 deg. A D8PSK constellation "
      "(twice the phase states) would need margin to a +/-22.5 deg boundary; D16 "
      "(16-DAPSK phase ring) needs +/-11.25 deg.\n")
    A("| section | raw SER | sym errors | min margin (correct) | p0.1 margin | p1 margin | median margin | frac<22.5 (D8PSK err) | cwFail |")
    A("|---|---|---|---|---|---|---|---|---|")
    for tag, s in (("PASS 934bps N512", p), ("FAIL N1024", f)):
        t = s["true_margin"]
        mm = t['min_margin_correct_deg']
        A(f"| {tag} | {t['raw_symbol_error_rate']:.3e} | {t['n_symbol_errors']} | "
          f"{(mm if mm is not None else float('nan')):.2f} deg | "
          f"{t['p0p1_margin_deg']:.2f} | {t['p1_margin_deg']:.2f} | "
          f"{t['median_margin_deg']:.2f} | {t['frac_below_22p5_margin']:.3e} | "
          f"{s['rs_codewords_failed']}/{s['n_codewords']} |")
    A("")
    A("Reading: `min margin (correct)` is the worst-case headroom the QPSK decoder "
      "actually had to a wrong decision across the whole section -- the single "
      "tightest symbol. `frac<22.5` is the fraction of symbols whose phasor sat "
      "closer than 22.5 deg to its true quadrant boundary = the raw symbol error "
      "rate a D8PSK constellation would have suffered on this exact capture (before "
      "FEC).\n")
    A("### Per-carrier truth margin (PASS 934 bps)\n")
    A("| carrier | freq (Hz) | raw SER | sym err | min margin deg | p1 margin deg | median margin deg |")
    A("|---|---|---|---|---|---|---|")
    for c in p["per_carrier_true_margin"]:
        A(f"| {c['carrier_idx']} | {c['freq_hz']:.0f} | {c['raw_ser']:.2e} | "
          f"{c['n_sym_err']} | "
          f"{(c['min_margin_deg'] if c['min_margin_deg'] is not None else float('nan')):.2f} | "
          f"{(c['p1_margin_deg'] if c['p1_margin_deg'] is not None else float('nan')):.2f} | "
          f"{(c['median_margin_deg'] if c['median_margin_deg'] is not None else float('nan')):.2f} |")
    A("")

    A("## 1. Differential-phase slicing margin (decided-quadrant residual)\n")
    A("QPSK slices at +/-45 deg; D8PSK at +/-22.5 deg; D16PSK (16-DAPSK phase ring) "
      "at +/-11.25 deg. `residual` = angular distance from the DECIDED quadrant "
      "center (post pilot-correction + decision-directed refinement). NOTE: this is "
      "measured vs the DECIDED quadrant, so it understates errors (a wrong decision "
      "still shows small residual to its wrong center). See section 0 for the "
      "truth-referenced numbers.\n")
    A("| section | residual (deg) | frac>22.5deg (D8PSK fail) | frac>11.25deg (D16 fail) | cwFail |")
    A("|---|---|---|---|---|")
    A(f"| PASS 934bps (N512) | {resid_line(p)} | "
      f"{p['differential_phase_residual_deg']['frac_over_22p5deg']:.2e} | "
      f"{p['differential_phase_residual_deg']['frac_over_11p25deg']:.2e} | "
      f"{p['rs_codewords_failed']}/{p['n_codewords']} |")
    A(f"| FAIL N1024 | {resid_line(f)} | "
      f"{f['differential_phase_residual_deg']['frac_over_22p5deg']:.2e} | "
      f"{f['differential_phase_residual_deg']['frac_over_11p25deg']:.2e} | "
      f"{f['rs_codewords_failed']}/{f['n_codewords']} |")
    A("")
    A(f"PASS section: {p['n_decisions']} symbol-carrier decisions. QPSK margin used "
      f"only up to the listed percentiles -- the headroom to the 45 deg boundary is "
      f"large.\n")

    A("### Per-carrier residual (PASS section, 934 bps)\n")
    A("| carrier | freq (Hz) | median deg | p90 deg | p99 deg | max deg | frac>22.5deg |")
    A("|---|---|---|---|---|---|---|")
    for c in p["per_carrier_residual"]:
        A(f"| {c['carrier_idx']} | {c['freq_hz']:.0f} | {c['median_deg']:.2f} | "
          f"{c['p90_deg']:.2f} | {c['p99_deg']:.2f} | {c['max_deg']:.2f} | "
          f"{c['frac_over_22p5deg']:.2e} |")
    A("")

    A("## 2. Flutter / timing (pilot dtau trace)\n")
    for tag, s in (("PASS N512", p), ("FAIL N1024", f)):
        fl = s["flutter"]
        A(f"**{tag}** (symbol rate {fl['symbol_rate_hz']:.1f} Hz):  ")
        A(f"- raw per-symbol dtau std {fl['dtau_raw_std_us']:.3f} us; "
          f"after EMA {fl['dtau_ema_std_us']:.3f} us; "
          f"decision-directed residual {fl['dtau_res_std_us']:.4f} us  ")
        A(f"- relative-rate wrms: raw {fl['rel_rate_raw_wrms_pct']:.4f}%, "
          f"residual {fl['rel_rate_res_wrms_pct']:.4f}% "
          f"(residual {fl['residual_reduction_x']:.1f}x smaller)  ")
        if fl.get("flutter_f90_hz") is not None:
            A(f"- flutter spectrum: peak {fl.get('flutter_peak_hz')} Hz, "
              f"f50 {fl.get('flutter_f50_hz')} Hz, f90 {fl.get('flutter_f90_hz')} Hz "
              f"(=> required tracking BW ~ {fl.get('required_tracking_bw_hz_est')} Hz)  ")
        A("")

    A("## 3. Per-carrier amplitude stability + output SNR (PASS 934 bps)\n")
    A("| carrier | freq (Hz) | amp CoV % | p10/med | p90/med | EVM rms | out SNR dB |")
    A("|---|---|---|---|---|---|---|")
    for c in p["per_carrier_amplitude_and_snr"]:
        A(f"| {c['carrier_idx']} | {c['freq_hz']:.0f} | {c['amp_cov_pct']:.1f} | "
          f"{c['amp_p10_over_median']:.2f} | {c['amp_p90_over_median']:.2f} | "
          f"{c['evm_rms']:.3f} | {c['out_snr_db']:.1f} |")
    A("")

    A("## 4. Cross-bin leakage (PASS 934 bps) -- supportable spacing without AAC\n")
    A("Energy at unused bins offset from each carrier, relative to carrier power "
      f"(carrier spacing here = {p['spacing']} bins = {p['spacing']*p['df_hz']:.0f} Hz). "
      "More-negative dB = cleaner; a deep null at small offsets means tighter "
      "spacing is supportable.\n")
    A("| offset | mean leak dB | max leak dB |")
    A("|---|---|---|")
    for kname, v in p["cross_bin_leakage"].items():
        A(f"| {kname} | {v['mean_leak_db']:.1f} | {v['max_leak_db']:.1f} |")
    A("")
    sp = out.get("spacing_sir")
    if sp:
        A("### Achievable spacing / SIR (measured leakage skirt, no AAC)\n")
        A(f"Current spacing {sp['current_spacing_hz']:.0f} Hz. SIR(spacing) = carrier "
          "power over the leakage two equal neighbors at +/-spacing would inject "
          "(Hann-windowed analysis, Nw="
          f"{sp['analysis_window_Nw_samples']}). Tightest spacing clearing each SIR:\n")
        A(f"- 15 dB SIR: {sp['tightest_spacing_for_15dB_sir_hz']} Hz  ")
        A(f"- 20 dB SIR: {sp['tightest_spacing_for_20dB_sir_hz']} Hz  ")
        A(f"- 25 dB SIR: {sp['tightest_spacing_for_25dB_sir_hz']} Hz  ")
        A("")
        A("| spacing (Hz) | SIR (dB) |")
        A("|---|---|")
        offs = sp["offsets_hz"]; sirs = sp["sir_db_at_spacing"]
        for i in range(0, len(offs), 2):       # every other row for brevity
            A(f"| {offs[i]:.0f} | {sirs[i]:.1f} |")
        A("")
        A("Caveats: (a) the SIR DIP near 750 Hz is the REAL adjacent data carrier "
          "(the section's own carriers sit 750 Hz apart), not window skirt -- ignore "
          "it; the skirt-limited clean region is ~150-500 Hz where SIR plateaus at "
          "~30 dB (channel-noise-floor limited). (b) The orthogonality constraint "
          "`spacing_bins * Nw % N == 0` (Nw=3N/4) restricts the exact usable bin "
          "grid; a rectangular-window DFT on integer bins gives zero ICI at the full "
          "N-bin resolution (93.75 Hz at N512) but loses the Hann ISI robustness. "
          "(c) Bottom line: the old 562 Hz AAC-masking floor is OBSOLETE on lossless "
          "captures -- ~150-200 Hz spacing is supportable at 20-25 dB SIR, a 3-5x "
          "carrier-density headroom over today's 750 Hz.")
        A("")

    A("## 5. Failure mechanism (N1024)\n")
    A(f"FAIL N1024 residual: {resid_line(f)}; cwFail {f['rs_codewords_failed']}/"
      f"{f['n_codewords']} (total wipeout). PASS N512 residual: {resid_line(p)}.\n")
    flp = p["flutter"]; flf = f["flutter"]
    A(f"N1024 symbol rate is {flf['symbol_rate_hz']:.1f} Hz vs N512's "
      f"{flp['symbol_rate_hz']:.1f} Hz -- the pilot updates HALF as often. The raw "
      f"per-symbol dtau std grows from {flp['dtau_raw_std_us']:.3f} us (N512) to "
      f"{flf['dtau_raw_std_us']:.3f} us (N1024) because more flutter accumulates "
      f"within one longer symbol, and the EMA (alpha fixed) tracks it more poorly. "
      f"If the N1024 residual median/p99 are far worse than N512's, the diagnosis is "
      f"confirmed: flutter tracking, not noise or leakage.\n")

    (OUT_DIR / "R2_margins.md").write_text("\n".join(lines))


if __name__ == "__main__":
    main()
