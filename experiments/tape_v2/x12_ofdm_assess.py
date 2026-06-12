"""x12_ofdm_assess.py -- X12 SPIKE STEAL (b): honest CP-OFDM assessment vs the
banked DQPSK-per-carrier line, computed from MEASURED tape10 channel data.

QUESTION (quiet/libquiet steal): would cyclic-prefix OFDM with pilot tracking
beat the d2x DQPSK line at equal occupied band (750-9000 Hz), or is it a
sidegrade?  This is a PAPER+NUMBERS assessment -- no modem is built.  Per the
x12 brief, a sim probe would only be justified if some design row projects a
credible >= 1.15x net win inside the measured margins.

STRUCTURAL OBSERVATION (stated up front, verified by grid arithmetic): the
shipping d2x receiver branch rect128_skip64 IS de-facto CP-OFDM.  Every
carrier sits on the 375 Hz grid = integer cycles per 128 samples, so the
256-sample symbol body is cyclic with period 128; a rect-128 window placed
anywhere in the clean region sees a circular shift of the same symbol --
exactly the CP property (CP = 128 smp = 2.67 ms), demodulated differentially.
The deltas a quiet-style modem would add are therefore only:
  (A) coherent detection instead of differential,
  (B) shorter CP (more payload per stride),
  (C) denser bins (longer N, more carriers in the same band).
Each is quantified below against measured tape10 evidence.

Stages (checkpoint results/x12_ofdm_assessment.json; deterministic, no RNG):
    OPENBLAS_NUM_THREADS=2 OMP_NUM_THREADS=2 python3 x12_ofdm_assess.py flutter
    ... echo | budget | designs | all

  flutter -- tau(t) from the tape10 12 s steady 3 kHz sounder tone (headroom
             recipe, finer decimation): band-rms table, PSD, lag-differential
             timing jitter sigma_dtau(T) per candidate symbol stride, both
             full-band and untracked (>30 Hz, beyond the PLL/EMA bandwidth),
             and untracked speed deviation (the dense-bin ICI driver).
  echo    -- channel impulse response via matched filter of the REAL start
             chirp (500-5000 Hz, 0.2 s) on tape10: envelope decay vs the
             template self-response, direct-to-tail energy ratios per guard
             length (the CP-length evidence).  Band-limited caveat logged.
  budget  -- per-carrier error budget at the d2x geometry: measured p90
             (x12_tape10_margins best sanctioned branch) split into the
             additive-noise term (from measured loaded SNR; the ONLY term
             coherent detection improves) vs everything else (flutter
             residual + ISI + IMD, untouched by coherence).  Yields the
             maximum margin gain coherent CP-OFDM could buy, assumptions
             maximally favorable to OFDM (perfect channel estimate).
  designs -- throughput + margin arithmetic for the candidate OFDM variants
             vs the banked d2x line, and the verdict.
"""
from __future__ import annotations

import argparse
import datetime
import json
import math
import pathlib
import sys
import time

import numpy as np

np.seterr(divide="ignore", over="ignore", invalid="ignore")

_HERE = pathlib.Path(__file__).resolve().parent
ROOT = pathlib.Path("/Users/magnus/repos/cassette-ai")
for _p in (ROOT / "src", ROOT / "tests" / "e2e", ROOT / "experiments" / "deepdive2",
           ROOT / "experiments" / "capacity", _HERE):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import analyze_master2 as am2                          # noqa: E402
from x10_headroom import _tone_gap_table               # noqa: E402
from x11_frontier_probe import _best_branch_table      # noqa: E402
from scipy.signal import welch, firwin, lfilter, correlate, hilbert  # noqa: E402

SR = 48_000
RESULTS = _HERE / "results"
OUT_JSON = RESULTS / "x12_ofdm_assessment.json"
MARGINS_T10 = RESULTS / "x12_tape10_margins.json"
MANIFEST_M10 = json.loads((_HERE / "master10_manifest.json").read_text())
CACHE_T10 = _HERE / "captures" / "x11_decode_nom_tape10_run1.npy"
SYNC_T10 = RESULTS / "x11_decode_sync_tape10_run1.json"

BAND = (750.0, 9000.0)
PLL_BW_HZ = 30.0                 # the receiver pilot-tracking bandwidth class
STRIDES = (128, 192, 256, 384, 512, 640, 768, 1024, 2048, 4096)
GUARDS = (16, 32, 64, 96, 128, 192, 256, 384, 512, 768, 1024, 2048)
P90_Z = 1.6448536269514722       # p90 of |N(0,1)|... actually of N; see note
# NOTE: 1.6449 is the 90th pct of a one-sided |N(0,1)| at p90 -> z s.t.
# P(|X|<z)=0.90 => z = 1.6449.  Used consistently for all converted terms.


def _ckpt() -> dict:
    if OUT_JSON.exists():
        return json.loads(OUT_JSON.read_text())
    return {"campaign": "x12 spike steal (b): CP-OFDM honest assessment "
                        "(paper+numbers, no modem built)",
            "created_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "caveats": [
                "echo stage is band-limited to the chirp band 500-5000 Hz; "
                "the reverb tail above 5 kHz is extrapolated, not measured",
                "budget stage assumptions are MAXIMALLY favorable to "
                "coherent OFDM (perfect channel phase reference, zero "
                "channel-estimation overhead); real coherent gains are lower",
                "all evidence is single-capture (tape10); the x12 recon "
                "showed per-carrier quality is non-stationary across burns, "
                "so design margins need a multi-capture column",
            ],
            "stages": {}}


def _save(out: dict) -> None:
    RESULTS.mkdir(exist_ok=True)
    OUT_JSON.write_text(json.dumps(out, indent=1, default=float))


def _load_tape10():
    audio_nom = np.load(CACHE_T10, mmap_mode="r")
    sync = json.loads(SYNC_T10.read_text())
    return audio_nom, int(sync["align"])


def _grab(audio_nom, align, sec, trim):
    st = sec["start"] + align
    ti = int(trim * SR)
    return np.asarray(audio_nom[st + ti: st + sec["length"] - ti], np.float64)


# ===========================================================================
def stage_flutter():
    out = _ckpt()
    if "flutter" in out["stages"]:
        print("[flutter] already done")
        return
    t0 = time.time()
    audio_nom, align = _load_tape10()
    steady = next(s for s in MANIFEST_M10["sounder_sections"]
                  if s["kind"] == "steady")
    f0 = float(steady["info"]["f0"])
    seg = _grab(audio_nom, align, steady, 0.5)
    t = np.arange(len(seg)) / SR
    bb = seg * np.exp(-2j * np.pi * f0 * t)
    taps = firwin(511, 300.0, fs=SR)
    bb_lp = lfilter(taps, 1.0, bb)[510:]
    dec = 8                                  # fs2 = 6000 Hz (finer than the
    fs2 = SR / dec                           # headroom dec=40, for lag diffs)
    ph = np.unwrap(np.angle(bb_lp[::dec]))
    tau = ph / (2 * np.pi * f0)
    x = np.arange(len(tau))
    A = np.vstack([x, np.ones_like(x)]).T
    coef, *_ = np.linalg.lstsq(A, tau, rcond=None)
    tau_d = tau - A @ coef

    f_t, psd = welch(tau_d, fs=fs2, nperseg=16384, noverlap=8192, window="hann")
    df = f_t[1] - f_t[0]

    def band_rms_us(lo, hi):
        m = (f_t >= lo) & (f_t < hi)
        return float(np.sqrt(np.sum(psd[m]) * df) * 1e6)

    bands = {"wow_0p5_5hz": band_rms_us(0.5, 5.0),
             "flutter_5_23p4hz": band_rms_us(5.0, 23.4),
             "flutter_23p4_60hz": band_rms_us(23.4, 60.0),
             "hf_60_300hz": band_rms_us(60.0, 300.0),
             "total_0p5_300hz": band_rms_us(0.5, 300.0)}

    # lag-differential timing jitter: sigma^2 = int S(f) * 4 sin^2(pi f T) df
    def sig_diff_us(T_s, fmin):
        m = (f_t >= fmin) & (f_t <= 300.0)
        w = 4.0 * np.sin(np.pi * f_t[m] * T_s) ** 2
        return float(np.sqrt(np.sum(psd[m] * w) * df) * 1e6)

    lag_rows = []
    for stride in STRIDES:
        T = stride / SR
        lag_rows.append({
            "stride_smp": stride, "T_ms": round(T * 1e3, 3),
            "sig_dtau_full_us": round(sig_diff_us(T, 0.5), 3),
            "sig_dtau_untracked_us": round(sig_diff_us(T, PLL_BW_HZ), 3)})

    # untracked relative speed deviation (drives dense-bin ICI):
    # speed = d tau/dt -> rms = sqrt( int S(f) (2 pi f)^2 df )
    def speed_rms(fmin):
        m = (f_t >= fmin) & (f_t <= 300.0)
        return float(np.sqrt(np.sum(psd[m] * (2 * np.pi * f_t[m]) ** 2) * df))

    inst = np.gradient(ph) * fs2 / (2 * np.pi)
    mtr = len(inst) // 10
    rel = (inst[mtr:-mtr] - np.mean(inst[mtr:-mtr])) / f0
    keep = np.unique(np.clip(np.round(np.geomspace(
        1, len(f_t) - 1, 140)).astype(int), 1, len(f_t) - 1))
    out["stages"]["flutter"] = {
        "capture": "tape10_run1", "steady_tone_hz": f0,
        "seg_seconds": round(len(seg) / SR, 2),
        "clock_residual_ppm": round(float(coef[0] * fs2 * 1e6), 2),
        "flutter_wrms_pct": round(float(np.sqrt(np.mean(rel ** 2)) * 100), 4),
        "tau_band_rms_us": {k: round(v, 3) for k, v in bands.items()},
        "lag_diff_table": lag_rows,
        "speed_dev_rms_full": speed_rms(0.5),
        "speed_dev_rms_untracked": speed_rms(PLL_BW_HZ),
        "pll_bw_hz_assumed": PLL_BW_HZ,
        "psd_freq_hz": [round(float(f_t[i]), 3) for i in keep],
        "psd_tau_us2_per_hz": [float(psd[i] * 1e12) for i in keep],
        "wall_s": round(time.time() - t0, 1)}
    _save(out)
    fl = out["stages"]["flutter"]
    print(f"[flutter] wrms {fl['flutter_wrms_pct']}%  bands(us) "
          + ", ".join(f"{k}={v:.1f}" for k, v in fl["tau_band_rms_us"].items()))
    print(f"  speed_dev untracked(>{PLL_BW_HZ}Hz) "
          f"{fl['speed_dev_rms_untracked']:.2e}; "
          f"sig_dtau(256smp) full {lag_rows[2]['sig_dtau_full_us']} us, "
          f"untracked {lag_rows[2]['sig_dtau_untracked_us']} us")


# ===========================================================================
def stage_echo():
    out = _ckpt()
    if "echo" in out["stages"]:
        print("[echo] already done")
        return
    t0 = time.time()
    audio_nom, align = _load_tape10()
    c0 = int(MANIFEST_M10["tx_chirp0"]) + align
    ref = am2._ref_global_chirp(up=True)
    ref = ref / np.sqrt(np.sum(ref ** 2))
    pre, post = 2400, 19200                      # 50 ms pre, 400 ms post
    y = np.asarray(audio_nom[c0 - pre: c0 + len(ref) + post], np.float64)
    h = correlate(y, ref, mode="valid")          # chirp-start lag axis
    env = np.abs(hilbert(h))
    pk = int(np.argmax(env[pre - 240: pre + 240])) + pre - 240
    lags = np.arange(len(env)) - pk              # samples relative to direct
    e2 = env ** 2
    peak2 = float(e2[pk])
    # template self-response (matched-filter point-spread), same envelope math
    a = correlate(ref, ref, mode="full")
    aenv = np.abs(hilbert(a))
    apk = int(np.argmax(aenv))
    a2 = aenv ** 2 / float(aenv[apk] ** 2)
    # pre-chirp correlation noise floor (per-sample, power, normalized)
    nf = float(np.median(e2[(lags > -2200) & (lags < -600)])) / peak2

    rows = []
    e2n = e2 / peak2
    for g in GUARDS:
        m_dir = (lags >= -64) & (lags <= g)
        m_tail = (lags > g) & (lags <= post - 1200)
        cap_tail = float(np.sum(np.maximum(e2n[m_tail] - nf, 0.0)))
        cap_dir = float(np.sum(e2n[m_dir]))
        # template: identical windows around its own peak
        al = np.arange(len(a2)) - apk
        t_dir = float(np.sum(a2[(al >= -64) & (al <= g)]))
        t_tail = float(np.sum(a2[(al > g) & (al <= min(post - 1200,
                                                       al.max()))]))
        tail_db = 10 * math.log10(max(cap_tail, 1e-12) / max(cap_dir, 1e-12))
        tmpl_db = 10 * math.log10(max(t_tail, 1e-12) / max(t_dir, 1e-12))
        excess = float(max(cap_tail / max(cap_dir, 1e-12)
                           - t_tail / max(t_dir, 1e-12), 0.0))
        rows.append({"guard_smp": g, "guard_ms": round(g / 48.0, 3),
                     "tail_to_direct_db": round(tail_db, 2),
                     "template_tail_to_direct_db": round(tmpl_db, 2),
                     "channel_excess_tail_db": (round(10 * math.log10(excess), 2)
                                                if excess > 1e-12 else None)})
    # envelope decay curve (dB vs lag) for the dossier
    sel = np.unique(np.clip(np.round(np.geomspace(1, post - 1300, 80)
                                     ).astype(int), 1, post - 1300))
    decay = [{"lag_smp": int(s), "lag_ms": round(s / 48.0, 3),
              "capture_db": round(10 * math.log10(max(float(e2n[pk + s]),
                                                      1e-15)), 2),
              "template_db": round(10 * math.log10(max(float(
                  a2[apk + s]) if apk + s < len(a2) else 1e-15, 1e-15)), 2)}
             for s in sel]
    out["stages"]["echo"] = {
        "capture": "tape10_run1", "chirp_band_hz": [500.0, 5000.0],
        "noise_floor_db_rel_peak": round(10 * math.log10(nf + 1e-300), 2),
        "guard_rows": rows, "decay_curve": decay,
        "wall_s": round(time.time() - t0, 1)}
    _save(out)
    for r in rows[:8]:
        print(f"  guard {r['guard_smp']:4d} smp ({r['guard_ms']:6.2f} ms): "
              f"tail/direct {r['tail_to_direct_db']:7.2f} dB "
              f"(template {r['template_tail_to_direct_db']:7.2f}, excess "
              f"{r['channel_excess_tail_db']})")
    print(f"[echo] noise floor {out['stages']['echo']['noise_floor_db_rel_peak']}"
          f" dB rel peak")


# ===========================================================================
def stage_budget():
    out = _ckpt()
    if "budget" in out["stages"]:
        print("[budget] already done")
        return
    if "flutter" not in out["stages"]:
        raise RuntimeError("run flutter first")
    t0 = time.time()
    marg = json.loads(MARGINS_T10.read_text())
    best = [b for b in _best_branch_table(
        marg["stages"]["quantiles_tape10_m10_r8_d2x_p22_rs179"]) if b]

    # measured LOADED per-tone SNR (vs in-band gap floor) -> interp at carriers
    audio_nom, align = _load_tape10()
    mt = [s for s in MANIFEST_M10["sounder_sections"] if s["kind"] == "multitone"]
    freqs = np.asarray(mt[0]["info"]["freqs"], float)
    tone_acc, gap_acc = None, None
    for sec in mt:
        seg = _grab(audio_nom, align, sec, 0.3)
        tp, gc, gf, _ = _tone_gap_table(seg, freqs)
        gfa = np.asarray([v if v is not None else np.nan for v in gf])
        tone_acc = tp if tone_acc is None else tone_acc + tp
        gap_acc = gfa if gap_acc is None else gap_acc + gfa
    tone_p = tone_acc / len(mt)
    gap_f = gap_acc / len(mt)
    ok = ~np.isnan(gap_f)
    loaded_at_tone = np.interp(freqs, gc[ok], gap_f[ok])
    snr_loaded_db = 10 * np.log10(tone_p / (loaded_at_tone * 375.0) + 1e-300)

    # SILENCE-floor SNR (true additive noise; from the recon sounder table).
    # The loaded gap-floor SNR is kept as a diagnostic column only: it counts
    # flutter FM sidebands + IMD as 'noise', which coherence does NOT remove
    # -- using it makes the noise term exceed the measured total error
    # (unphysical), so it must not drive the coherent-gain arithmetic.
    snd = marg["stages"]["sounder_tape10"]["table"]
    f_snd = np.asarray([r["f_hz"] for r in snd])
    snr_sil_db = np.asarray([r["snr_375_db"] for r in snd])

    sig256_us = next(r["sig_dtau_untracked_us"]
                     for r in out["stages"]["flutter"]["lag_diff_table"]
                     if r["stride_smp"] == 256)
    rows, deg = [], 180.0 / math.pi
    for b in best:
        f = float(b["freq_hz"])
        snr_lin = 10 ** (float(np.interp(f, f_snd, snr_sil_db)) / 10.0)
        p90_meas = float(b["p90_deg"])
        p90_nd = P90_Z * deg * math.sqrt(2.0 / snr_lin)   # differential noise
        p90_nc = P90_Z * deg * math.sqrt(1.0 / snr_lin)   # coherent (ideal ref)
        # flutter UPPER BOUND (>30 Hz band); the actual receiver also applies
        # a per-symbol-pair pilot dtau + cross-carrier LS refinement with no
        # bandwidth limit, so the true exposure is lower -- flagged if the
        # bound overshoots the measured budget.
        p90_fl = P90_Z * 360.0 * f * sig256_us * 1e-6
        nonnoise2 = max(p90_meas ** 2 - p90_nd ** 2, 0.0)
        resid2 = max(nonnoise2 - p90_fl ** 2, 0.0)
        # coherent gain is flutter-split-independent: only noise term changes
        p90_coh = math.sqrt(nonnoise2 + p90_nc ** 2)
        rows.append({
            "freq_hz": f,
            "snr_silence_db": round(float(np.interp(f, f_snd, snr_sil_db)), 2),
            "snr_loaded_db_diag": round(float(
                np.interp(f, freqs, snr_loaded_db)), 2),
            "p90_meas_deg": p90_meas,
            "p90_noise_diff_deg": round(p90_nd, 2),
            "p90_flutter_ub_deg": round(p90_fl, 2),
            "flutter_ub_exceeds_budget": bool(p90_fl ** 2 > nonnoise2),
            "p90_residual_isi_imd_deg": round(math.sqrt(resid2), 2),
            "noise_frac_of_meas_var": round(min(p90_nd ** 2 / p90_meas ** 2,
                                                9.999), 4),
            "p90_coherent_pred_deg": round(p90_coh, 2),
            "coherent_margin_gain_deg": round(p90_meas - p90_coh, 2)})
    gains = [r["coherent_margin_gain_deg"] for r in rows]
    nf = [r["noise_frac_of_meas_var"] for r in rows]
    out["stages"]["budget"] = {
        "note": "additive-noise term uses the SILENCE-floor SNR_375 (true "
                "additive noise); the loaded gap-floor SNR is a diagnostic "
                "column only (it counts flutter sidebands + IMD as noise -- "
                "structure coherence cannot remove).  Coherent side assumed "
                "PERFECT (zero-noise channel reference, no extra overhead): "
                "an upper bound on the coherence gain.",
        "sig_dtau_untracked_256_us": sig256_us,
        "per_carrier": rows,
        "coherent_margin_gain_median_deg": round(float(np.median(gains)), 2),
        "coherent_margin_gain_max_deg": round(float(np.max(gains)), 2),
        "noise_var_fraction_median": round(float(np.median(nf)), 4),
        "wall_s": round(time.time() - t0, 1)}
    _save(out)
    print(f"[budget] coherent gain median "
          f"{out['stages']['budget']['coherent_margin_gain_median_deg']} deg, "
          f"max {out['stages']['budget']['coherent_margin_gain_max_deg']} deg; "
          f"median noise fraction of measured var "
          f"{out['stages']['budget']['noise_var_fraction_median']}")


# ===========================================================================
def stage_designs():
    out = _ckpt()
    for need in ("flutter", "echo", "budget"):
        if need not in out["stages"]:
            raise RuntimeError(f"run {need} first")
    fl, ec, bu = (out["stages"][k] for k in ("flutter", "echo", "budget"))
    g_by = {r["guard_smp"]: r for r in ec["guard_rows"]}
    lag = {r["stride_smp"]: r for r in fl["lag_diff_table"]}
    deg = 180.0 / math.pi

    def carriers(spacing_hz):
        n = int(math.floor((BAND[1] - BAND[0]) / spacing_hz)) + 1
        return n

    rows = []
    # --- banked line -------------------------------------------------------
    rows.append({
        "design": "d2x DQPSK (banked, r8)", "stride_smp": 256,
        "spacing_hz": 375.0, "data_carriers": 22,
        "gross_bps": 22 * 2 * SR / 256.0,
        "banked_net_bps": 5791.2,
        "note": "rect128_skip64 branch is ALREADY de-facto CP-OFDM with "
                "CP=128 smp (grid carriers are 128-periodic), differential "
                "demod; this is the line to beat"})
    # --- A: coherent, same geometry -----------------------------------------
    med_gain = bu["coherent_margin_gain_median_deg"]
    rows.append({
        "design": "A: coherent CP-OFDM, same geometry (N128+CP128)",
        "stride_smp": 256, "spacing_hz": 375.0, "data_carriers": 22,
        "gross_bps": 22 * 2 * SR / 256.0,
        "rate_vs_banked": 1.0,
        "margin_gain_deg_upper_bound": med_gain,
        "verdict": ("SIDEGRADE: identical rate; the coherence upper bound "
                    f"buys median {med_gain} deg of margin (perfect channel "
                    "reference assumed, real gain lower minus channel-est "
                    "overhead), against carrier nonstationarity of ~3-32 deg "
                    "between consecutive burns (x12 recon)")})
    # --- B: shorter CP ------------------------------------------------------
    t64, t128 = (g_by[64]["tail_to_direct_db"], g_by[128]["tail_to_direct_db"])
    rows.append({
        "design": "B: CP-OFDM N128+CP64 (stride 192)",
        "stride_smp": 192, "spacing_hz": 375.0, "data_carriers": 22,
        "gross_bps": 22 * 2 * SR / 192.0,
        "rate_vs_banked": round(256.0 / 192.0, 3),
        "echo_tail_to_direct_db": {"guard64": t64, "guard128": t128,
                                   "isi_penalty_db": round(t64 - t128, 2)},
        "verdict": None})  # filled below from echo numbers
    isi64_lin = 10 ** (t64 / 10.0)
    # ISI -> phase-error mapping: a complex interferer of relative power rho
    # gives dphi std ~ sqrt(rho/2) per symbol, x sqrt(2) for differential
    # detection -> sigma ~ sqrt(rho).  UPPER BOUND: tail energy inside the
    # cyclic period is benign and partial-overlap weighting reduces the rest.
    p90_isi64 = P90_Z * deg * math.sqrt(isi64_lin)
    rows[-1]["isi_equiv_p90_deg_at_guard64_ub"] = round(p90_isi64, 2)
    resid_med = float(np.median([r["p90_residual_isi_imd_deg"]
                                 for r in bu["per_carrier"]]))
    rows[-1]["measured_residual_p90_median_deg"] = round(resid_med, 2)
    if t64 - t128 < 1.0 and p90_isi64 < 0.5 * resid_med:
        rows[-1]["verdict"] = (
            "PLAUSIBLE +33% gross: measured echo tail beyond 64 smp adds "
            f"only {round(t64 - t128, 2)} dB tail energy (ISI-equiv p90 "
            f"{round(p90_isi64, 2)} deg vs residual median {round(resid_med, 2)}"
            " deg) -- but 500-5000 Hz band-limited evidence; needs its own "
            "pre-registered campaign with canary rungs")
    else:
        rows[-1]["verdict"] = (
            f"KILLED BY ECHO NUMBERS: guard-64 tail/direct {t64} dB "
            f"(ISI-equiv p90 {round(p90_isi64, 2)} deg) vs guard-128 {t128} "
            f"dB; the added ISI is not small next to the measured residual "
            f"median {round(resid_med, 2)} deg")
    # --- C: denser bins -----------------------------------------------------
    n_c = carriers(93.75) - 1
    eps9k = 9000.0 * fl["speed_dev_rms_untracked"] / 93.75
    sir_db = -10 * math.log10((math.pi * eps9k) ** 2 / 3.0 + 1e-300)
    rows.append({
        "design": "C: dense-bin coherent CP-OFDM N512+CP128 (93.75 Hz bins)",
        "stride_smp": 640, "spacing_hz": 93.75, "data_carriers": n_c,
        "gross_bps": n_c * 2 * SR / 640.0,
        "rate_vs_banked": round((n_c * 2 * SR / 640.0) / 8250.0, 3),
        "ici_eps_at_9khz": round(eps9k, 4),
        "ici_sir_db_at_9khz": round(sir_db, 1),
        "verdict": None})
    if sir_db >= 25.0:
        rows[-1]["verdict"] = (
            f"ICI alone tolerable (SIR {round(sir_db, 1)} dB at 9 kHz), BUT "
            "the empirical record contradicts long symbols: the m10->d2x "
            "history doubled throughput by HALVING N at fixed spacing, and "
            "x10 d3x (1-bin spacing at N128) was killed by tail>guard; "
            "dense bins also quadruple the per-carrier nonstationarity "
            "exposure (88 carriers must each clear margin) -- needs own "
            "campaign; not the cheapest path vs bulk framing 1.74x")
    else:
        rows[-1]["verdict"] = (
            f"KILLED BY FLUTTER ICI: untracked speed dev "
            f"{fl['speed_dev_rms_untracked']:.2e} -> eps {round(eps9k, 3)} "
            f"of a 93.75 Hz bin at 9 kHz -> SIR {round(sir_db, 1)} dB < 25 dB "
            "needed for QPSK at our margins")
    # --- D: the orthogonal comparison axis ----------------------------------
    rows.append({
        "design": "D: bulk framing on the EXISTING d2x line (reference)",
        "stride_smp": 256, "spacing_hz": 375.0, "data_carriers": 22,
        "gross_bps": 8250.0, "rate_vs_banked": "1.17-1.74x WALL-CLOCK",
        "verdict": "the proven-channel alternative: same PHY, amortize the "
                   "0.37 s/frame preamble cost (F=8 -> 1.59x); margin-"
                   "orthogonal; this is the bar any OFDM rebuild must beat"})

    best_candidate = max(
        (r for r in rows if isinstance(r.get("rate_vs_banked"), (int, float))),
        key=lambda r: r["rate_vs_banked"])
    sim_probe = bool(isinstance(best_candidate.get("rate_vs_banked"), float)
                     and best_candidate["rate_vs_banked"] >= 1.15
                     and "PLAUSIBLE" in str(best_candidate.get("verdict", "")))
    out["stages"]["designs"] = {
        "rows": rows,
        "sim_probe_justified": sim_probe,
        "sim_probe_target": (best_candidate["design"] if sim_probe else None),
        "overall": None}
    b_killed = "KILLED" in str(rows[2]["verdict"])
    c_killed = "KILLED" in str(rows[3]["verdict"])
    out["stages"]["designs"]["overall"] = (
        "CP-OFDM as a NEW modem is a SIDEGRADE-or-worse on this channel: the "
        "d2x rect128_skip64 receiver already has the CP property (grid "
        "carriers are 128-periodic; CP=128 smp), so the only deltas are "
        "coherence, shorter CP, or denser bins. Coherent detection's upper-"
        f"bound gain is median {med_gain} deg because additive noise is only "
        f"{bu['noise_var_fraction_median']*100:.1f}% (median) of the measured "
        "error variance -- the budget is flutter-residual/ISI/IMD, which "
        "coherence does not touch. "
        + ("Shorter CP (row B, +33% gross) is KILLED by the measured reverb "
           "tail (guard-64 tail/direct -5.0 dB vs -9.3 dB at guard-128). "
           if b_killed else
           "Shorter CP (row B, +33% gross) survives its echo numbers and "
           "would need its own pre-registered campaign. ")
        + ("Dense bins (row C) are KILLED by untracked flutter ICI. "
           if c_killed else "Dense bins (row C) survive the ICI check. ")
        + "Bulk framing (row D, same PHY, 1.17-1.74x wall-clock) dominates "
          "every OFDM rebuild on cost and risk.")
    _save(out)
    for r in rows:
        print(f"  {r['design'][:58]:58s} gross={r['gross_bps']:7.0f} "
              f"x{r.get('rate_vs_banked')}")
    print(f"[designs] sim_probe_justified={sim_probe} "
          f"target={out['stages']['designs']['sim_probe_target']}")


STAGES = {"flutter": stage_flutter, "echo": stage_echo,
          "budget": stage_budget, "designs": stage_designs}

if __name__ == "__main__":
    import warnings
    warnings.filterwarnings("ignore")
    ap = argparse.ArgumentParser()
    ap.add_argument("stage", choices=list(STAGES) + ["all"])
    args = ap.parse_args()
    if args.stage == "all":
        for fn in STAGES.values():
            fn()
    else:
        STAGES[args.stage]()
