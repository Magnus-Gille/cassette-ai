"""x10_headroom.py -- BET B FORENSICS: unexploited capacity of the tape9 capture.

Measures (no proposals, numbers only):
  1. Per-bin SNR vs frequency from the front sounder (64-tone Schroeder multitone,
     300-11000 Hz) against BOTH the silence noise floor and the *loaded* floor
     (off-tone bins during the multitone = IMD + flutter sidebands).
  2. Per-carrier in-situ SNR from decoded-section residuals (EVM through the
     EXACT winning m9 receiver chain, truth used for scoring only).
  3. Flutter / jitter PSD from the 12 s steady 3 kHz sounder tone and from the
     per-symbol pilot dtau of the data sections.
  4. IMD floor vs tone spacing: multitone gap floors (pure-tone IMD, log-spaced
     17.6 -> 600 Hz gaps) + data-section mid-gap floors at 375 Hz (m8) and
     750 Hz (m1) spacing (modulation sidelobes + IMD; labeled as such).
  5. Usable-band edges at multiple SNR thresholds.
  6. Waterfilling capacity of THIS capture vs the achieved 2572 net bps, with a
     headroom decomposition (bandwidth / constellation / coding / overhead).

Receiver-chain fidelity: the EVM front-ends replicate x9_resampling_pll
byte-for-byte by importing its _ema_dft/_pll_resampled_dft helpers and
re-running the published decision math (incl. the one-shot DD refinement and
the no-truth PLL-vs-EMA selector). The winning front-end per rung is read from
results/m9_results_tape9_run1.json.

Stages (each checkpointed into results/x10_headroom.json):
    python3 experiments/tape_v2/x10_headroom.py --stage sync
    python3 experiments/tape_v2/x10_headroom.py --stage sounder,flutter,evm,imd,capacity
Seeds: fully deterministic (no RNG used); SEED=0 logged for protocol compliance.
"""
from __future__ import annotations

import argparse
import json
import math
import pathlib
import sys
import time

import numpy as np
import soundfile as sf
from scipy.signal import welch, periodogram, firwin, lfilter, resample_poly
from fractions import Fraction

np.seterr(divide="ignore", over="ignore", invalid="ignore")

_HERE = pathlib.Path(__file__).resolve().parent
ROOT = pathlib.Path("/Users/magnus/repos/cassette-ai")
for _p in (ROOT / "src", ROOT / "tests" / "e2e", ROOT / "experiments" / "capacity", _HERE):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import analyze_master2 as am2            # noqa: E402
import hyp_common as hc                  # noqa: E402
import m3_codec as codec                 # noqa: E402
from m3_codec import Rung                # noqa: E402
from h4_dqpsk import DQPSKScheme, FS as DQ_FS, PAD_LO_S, PAD_HI_S  # noqa: E402
from m9_master import DropNullDQPSK      # noqa: E402
from x9_resampling_pll import (          # noqa: E402
    ResamplingPLLDemod, _ema_dft, _pll_resampled_dft, residual_stats)

SR = 48_000
SEED = 0                                  # deterministic; logged for protocol
MANIFEST_PATH = _HERE / "master9_manifest.json"
RESULTS_DIR = _HERE / "results"
OUT_PATH = RESULTS_DIR / "x10_headroom.json"
M9_RESULTS = RESULTS_DIR / "m9_results_tape9_run1.json"
CAPTURE_DEFAULT = _HERE / "captures" / "tape9_run1.wav"
AUDIO_NOM_CACHE = _HERE / "captures" / "x10_audio_nom_tape9_run1.npy"

BAND_LO, BAND_HI = 300.0, 11_500.0        # integration band for power ratios
ACHIEVED_NET_BPS = 2572.0                 # m8_dense375, the record this capture banked
ACHIEVED_GROSS_BPS = 4125.0               # 2*22*93.75


# ===========================================================================
# JSON checkpointing
# ===========================================================================
def _load_out() -> dict:
    if OUT_PATH.exists():
        try:
            return json.loads(OUT_PATH.read_text())
        except Exception:
            return {}
    return {}


def _save_out(out: dict):
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(out, indent=2, default=float))


def _f(x):
    return None if x is None else float(x)


# ===========================================================================
# Scheme reconstruction (mirror of m9_decode._scheme_from_entry, dqpsk only)
# ===========================================================================
def _scheme_from_entry(sec: dict):
    kind = sec["kind"]
    if kind == "freqdiff":
        return None
    p = sec["dqpsk_params"]
    if kind == "dqpsk_dropnull":
        return DropNullDQPSK(p["P"], p["N"], p["spacing"], p["drop_freqs_hz"],
                             pilot_hz=p["pilot_hz"])
    return DQPSKScheme(p["P"], p["N"], p["spacing"],
                       min_spacing_hz=p.get("min_spacing_hz", 562.0))


def _nominal_frame_bits(meta: dict) -> list[int]:
    fb = meta["frame_bits"]
    n = meta["n_frames"]
    return [fb] * (n - 1) + [meta["stream_bits"] - fb * (n - 1)]


# ===========================================================================
# stage: sync -- global chirp sync + clock resample, cache audio_nominal
# ===========================================================================
def stage_sync(capture: pathlib.Path, out: dict, force: bool = False):
    if AUDIO_NOM_CACHE.exists() and out.get("sync") and not force:
        print("[sync] cache present, skipping")
        return
    t0 = time.time()
    manifest = json.loads(MANIFEST_PATH.read_text())
    audio, sr = sf.read(str(capture), dtype="float32", always_2d=False)
    if audio.ndim > 1:
        audio = audio.mean(axis=1)
    if sr != SR:
        frac = Fraction(SR, sr).limit_denominator(20000)
        audio = resample_poly(audio.astype(np.float64), frac.numerator, frac.denominator)
    sync = am2.global_sync_and_resample(audio, manifest)
    np.save(AUDIO_NOM_CACHE, sync["audio_nominal"].astype(np.float32))
    out["capture"] = str(capture)
    out["seed"] = SEED
    out["sync"] = {k: v for k, v in sync.items() if k != "audio_nominal"}
    out["sync"]["wall_s"] = round(time.time() - t0, 1)
    _save_out(out)
    print(f"[sync] clock {sync['clock_ratio']:.6f}, chirp0_nom {sync['chirp0_nominal']}, "
          f"{out['sync']['wall_s']}s")


def _get_audio(out: dict) -> tuple[np.ndarray, int]:
    audio_nom = np.load(AUDIO_NOM_CACHE)
    manifest = json.loads(MANIFEST_PATH.read_text())
    align = out["sync"]["chirp0_nominal"] - manifest["tx_chirp0"]
    return audio_nom.astype(np.float64), int(align)


# ===========================================================================
# stage: sounder -- per-tone SNR table, loaded (IMD) floor, band edges
# ===========================================================================
def _tone_gap_table(seg: np.ndarray, freqs: np.ndarray, flutter_frac: float = 0.0045):
    """One multitone rep -> per-tone integrated power + per-gap loaded floor.
    Tone power = integral of periodogram PSD over a +-w window (w grows with f
    to swallow flutter FM sidebands, capped at 0.35x the local gap).
    Gap floor = median PSD over bins safely away from both bounding tones."""
    f_ax, psd = periodogram(seg, fs=SR, window="hann", detrend="constant",
                            scaling="density")
    df = f_ax[1] - f_ax[0]
    n_t = len(freqs)
    gaps = np.diff(freqs)
    tone_p = np.zeros(n_t)
    for k, f in enumerate(freqs):
        gap_min = gaps[k - 1] if k == n_t - 1 else (
            gaps[0] if k == 0 else min(gaps[k - 1], gaps[k]))
        w = max(4.0, 3.0 * flutter_frac * f)
        w = min(w, 0.35 * gap_min)
        lo = np.searchsorted(f_ax, f - w)
        hi = max(np.searchsorted(f_ax, f + w), lo + 1)
        tone_p[k] = float(np.sum(psd[lo:hi]) * df)
    gap_centers, gap_floor = [], []
    for k in range(n_t - 1):
        f0, f1 = freqs[k], freqs[k + 1]
        e0 = max(5.0, 3.0 * flutter_frac * f0)
        e1 = max(5.0, 3.0 * flutter_frac * f1)
        lo_f, hi_f = f0 + e0, f1 - e1
        if hi_f - lo_f < 3 * df:        # gap fully eaten by exclusion zones
            gap_centers.append(0.5 * (f0 + f1))
            gap_floor.append(None)
            continue
        lo = np.searchsorted(f_ax, lo_f)
        hi = max(np.searchsorted(f_ax, hi_f), lo + 1)
        gap_centers.append(0.5 * (f0 + f1))
        # median of a chi2(2dof) periodogram underestimates the mean PSD by
        # ln(2) (-1.59 dB); correct so floors are mean-equivalent.
        gap_floor.append(float(np.median(psd[lo:hi]) / math.log(2)))
    # in-band total power (for the data/multitone drive ratio)
    blo = np.searchsorted(f_ax, BAND_LO)
    bhi = np.searchsorted(f_ax, BAND_HI)
    p_inband = float(np.sum(psd[blo:bhi]) * df)
    return tone_p, np.asarray(gap_centers), gap_floor, p_inband


def stage_sounder(out: dict):
    t0 = time.time()
    manifest = json.loads(MANIFEST_PATH.read_text())
    audio_nom, align = _get_audio(out)
    multitone = [s for s in manifest["sounder_sections"] if s["kind"] == "multitone"]
    noise = next(s for s in manifest["sounder_sections"] if s["kind"] == "noisefloor")
    freqs = np.asarray(multitone[0]["info"]["freqs"], float)

    def grab(sec, trim):
        st = sec["start"] + align
        ti = int(trim * SR)
        return audio_nom[st + ti: st + sec["length"] - ti]

    # ---- silence noise PSD (Welch, 2.93 Hz res) ----
    nseg = grab(noise, 0.4)
    f_n, n_psd = welch(nseg, fs=SR, nperseg=16384, noverlap=8192, window="hann")
    nf_rms = float(np.sqrt(np.mean(nseg ** 2)))

    # ---- multitone reps: tone powers + gap (loaded) floors ----
    tone_acc = np.zeros(len(freqs))
    gap_acc = None
    gap_cnt = None
    p_mt_inband = 0.0
    for mt in multitone:
        seg = grab(mt, 0.3)
        tp, gc, gf, pib = _tone_gap_table(seg, freqs)
        tone_acc += tp
        p_mt_inband += pib
        if gap_acc is None:
            gap_acc = np.zeros(len(gc))
            gap_cnt = np.zeros(len(gc))
        for i, v in enumerate(gf):
            if v is not None:
                gap_acc[i] += v
                gap_cnt[i] += 1
    tone_p = tone_acc / len(multitone)
    p_mt_inband /= len(multitone)
    gap_centers = gc
    gap_floor = np.where(gap_cnt > 0, gap_acc / np.maximum(gap_cnt, 1), np.nan)

    # noise PSD + loaded floor at each tone / gap frequency
    n_at = np.interp(freqs, f_n, n_psd)
    n_at_gap = np.interp(gap_centers, f_n, n_psd)
    loaded_at_tone = np.interp(freqs, gap_centers[~np.isnan(gap_floor)],
                               gap_floor[~np.isnan(gap_floor)])
    bloom_db = 10 * np.log10(gap_floor / n_at_gap)

    snr_1hz = 10 * np.log10(tone_p / n_at)                  # tone power vs 1 Hz floor
    snr_375 = 10 * np.log10(tone_p / (n_at * 375.0))        # vs noise in a 375 Hz carrier band
    snr_375_loaded = 10 * np.log10(tone_p / (loaded_at_tone * 375.0))
    H_db = 10 * np.log10(tone_p / np.max(tone_p))

    # ---- usable-band edges at thresholds (on snr_375, largest contiguous run) ----
    edges = {}
    for thr in (30.0, 25.0, 20.0, 15.0, 10.0):
        ok = snr_375 >= thr
        best = (None, None, 0)
        i = 0
        while i < len(ok):
            if ok[i]:
                j = i
                while j + 1 < len(ok) and ok[j + 1]:
                    j += 1
                if j - i + 1 > best[2]:
                    best = (float(freqs[i]), float(freqs[j]), j - i + 1)
                i = j + 1
            else:
                i += 1
        edges[f"{thr:.0f}dB"] = {"lo_hz": best[0], "hi_hz": best[1], "n_tones": best[2]}

    out["sounder"] = {
        "n_multitone_reps": len(multitone),
        "noise_floor_rms": nf_rms,
        "noise_floor_dbfs": 20 * math.log10(nf_rms),
        "p_multitone_inband": p_mt_inband,
        "table": [
            {"f_hz": _f(freqs[k]), "H_db": _f(H_db[k]),
             "tone_p_db": _f(10 * np.log10(tone_p[k])),
             "noise_psd_dbhz": _f(10 * np.log10(n_at[k])),
             "loaded_psd_dbhz": _f(10 * np.log10(loaded_at_tone[k])),
             "snr_1hz_db": _f(snr_1hz[k]), "snr_375_db": _f(snr_375[k]),
             "snr_375_loaded_db": _f(snr_375_loaded[k])}
            for k in range(len(freqs))
        ],
        "gap_floor": [
            {"f_hz": _f(gap_centers[i]), "gap_hz": _f(freqs[i + 1] - freqs[i]),
             "loaded_psd_dbhz": (None if np.isnan(gap_floor[i])
                                 else _f(10 * np.log10(gap_floor[i]))),
             "bloom_above_silence_db": (None if np.isnan(gap_floor[i])
                                        else _f(bloom_db[i]))}
            for i in range(len(gap_centers))
        ],
        "snr_375_median_db": _f(np.median(snr_375)),
        "snr_375_p10_db": _f(np.percentile(snr_375, 10)),
        "band_edges_snr375": edges,
        "wall_s": round(time.time() - t0, 1),
    }
    _save_out(out)
    print(f"[sounder] median SNR375 {np.median(snr_375):.1f} dB, "
          f"nf {20*math.log10(nf_rms):.1f} dBFS, edges@15dB "
          f"{edges['15dB']['lo_hz']}-{edges['15dB']['hi_hz']} Hz "
          f"({out['sounder']['wall_s']}s)")


# ===========================================================================
# stage: flutter -- jitter PSD from the 12 s steady 3 kHz tone
# ===========================================================================
def stage_flutter(out: dict):
    t0 = time.time()
    manifest = json.loads(MANIFEST_PATH.read_text())
    audio_nom, align = _get_audio(out)
    steady = next(s for s in manifest["sounder_sections"] if s["kind"] == "steady")
    f0 = float(steady["info"]["f0"])
    st = steady["start"] + align
    ti = int(0.5 * SR)
    seg = audio_nom[st + ti: st + steady["length"] - ti]

    t = np.arange(len(seg)) / SR
    bb = seg * np.exp(-2j * np.pi * f0 * t)
    taps = firwin(511, 300.0, fs=SR)
    bb_lp = lfilter(taps, 1.0, bb)[510:]            # drop filter transient
    dec = 40                                        # -> fs2 = 1200 Hz
    bb_d = bb_lp[::dec]
    fs2 = SR / dec
    ph = np.unwrap(np.angle(bb_d))
    tau = ph / (2 * np.pi * f0)                     # seconds of timing offset
    # remove linear trend = residual static clock offset
    x = np.arange(len(tau))
    A = np.vstack([x, np.ones_like(x)]).T
    coef, *_ = np.linalg.lstsq(A, tau, rcond=None)
    tau_d = tau - A @ coef
    clock_resid_ppm = float(coef[0] * fs2 * 1e6)

    f_t, psd_tau = welch(tau_d, fs=fs2, nperseg=4096, noverlap=2048, window="hann")
    df = f_t[1] - f_t[0]

    def band_rms_us(lo, hi):
        m = (f_t >= lo) & (f_t < hi)
        return float(np.sqrt(np.sum(psd_tau[m]) * df) * 1e6)

    bands = {"wow_0p5_5hz": band_rms_us(0.5, 5.0),
             "flutter_5_23p4hz": band_rms_us(5.0, 23.4),
             "flutter_23p4_60hz": band_rms_us(23.4, 60.0),
             "hf_60_300hz": band_rms_us(60.0, 300.0),
             "total_0p5_300hz": band_rms_us(0.5, 300.0)}

    inst_f = f0 + np.gradient(ph) * fs2 / (2 * np.pi)
    m = len(inst_f) // 10
    rel = (inst_f[m:-m] - np.mean(inst_f[m:-m])) / f0
    flutter_pct = float(np.sqrt(np.mean(rel ** 2)) * 100)

    # decimate PSD curve for JSON (~160 points, log-ish)
    keep = np.unique(np.clip(np.round(
        np.geomspace(1, len(f_t) - 1, 160)).astype(int), 1, len(f_t) - 1))
    out["flutter"] = {
        "steady_tone_hz": f0, "seg_seconds": len(seg) / SR,
        "clock_residual_ppm": clock_resid_ppm,
        "flutter_wrms_pct": flutter_pct,
        "tau_band_rms_us": bands,
        "psd_freq_hz": [_f(f_t[i]) for i in keep],
        "psd_tau_us2_per_hz": [_f(psd_tau[i] * 1e12) for i in keep],
        "wall_s": round(time.time() - t0, 1),
    }
    _save_out(out)
    print(f"[flutter] {flutter_pct:.3f}% wrms; band rms us: "
          + ", ".join(f"{k}={v:.1f}" for k, v in bands.items())
          + f" ({out['flutter']['wall_s']}s)")


# ===========================================================================
# EVM machinery -- replicate the x9 receiver chain, expose c-matrices
# ===========================================================================
def _decide_full(sch, c, dtau):
    """x9_resampling_pll._decide with refine=True, verbatim math; returns
    (q, dphi_refined, quality, d)."""
    fd = sch.freqs[sch.data_idx]
    d = c[1:, :] * np.conj(c[:-1, :])
    dphi = np.angle(d[:, sch.data_idx]) - 2 * np.pi * np.outer(dtau[1:], fd)
    q = np.round(dphi / (np.pi / 2.0)).astype(int) % 4
    res = (dphi - q * (np.pi / 2.0) + np.pi) % (2 * np.pi) - np.pi
    num = (res * fd[None, :]).sum(axis=1)
    den = (fd ** 2).sum()
    dtau_res = num / (2 * np.pi * den)
    dphi2 = dphi - 2 * np.pi * dtau_res[:, None] * fd[None, :]
    q2 = np.round(dphi2 / (np.pi / 2.0)).astype(int) % 4
    resd = (dphi2 - q2 * (np.pi / 2.0) + np.pi) % (2 * np.pi) - np.pi
    quality = float(np.sqrt(np.mean(resd ** 2)))
    return q2, dphi2, quality, d


def _frontend_c(sch, win, nd, fe_name):
    """Replicates the winning m9 front-end, returning the symbol c-matrix and
    common-timing trace actually used by the decisions, plus the raw per-symbol
    pilot dtau (for jitter stats). fe_name: 'resampling_pll' or 'emaX.Y'."""
    alpha = float(fe_name[3:]) if fe_name.startswith("ema") else 0.5
    pll = ResamplingPLLDemod(sch, pll_bw_hz=30.0, front_end="pll", ema_alpha=alpha)
    y = np.asarray(win, np.float64)
    ds = hc.find_preamble(y.astype(np.float32), sch.preamble_seconds)
    total = nd + 1
    fpil = sch.freqs[sch.pilot_idx]
    c1 = _ema_dft(pll, y, ds, total)
    dpil = np.zeros(total)
    dtau_ema = np.zeros(total)
    sm = 0.0
    for i in range(1, total):
        dp = float(np.angle(c1[i, sch.pilot_idx] * np.conj(c1[i - 1, sch.pilot_idx])))
        dpil[i] = dp / (2 * np.pi * fpil)
        sm = (1 - alpha) * dpil[i] + alpha * sm
        dtau_ema[i] = sm
    if fe_name.startswith("ema"):
        return c1, dtau_ema, dpil[1:], "ema"
    c2 = _pll_resampled_dft(pll, y, ds, total)
    dtau_res = np.zeros(total)
    for i in range(1, total):
        dp = float(np.angle(c2[i, sch.pilot_idx] * np.conj(c2[i - 1, sch.pilot_idx])))
        dtau_res[i] = dp / (2 * np.pi * fpil)
    _, _, qual_p, _ = _decide_full(sch, c2, dtau_res)
    _, _, qual_e, _ = _decide_full(sch, c1, dtau_ema)
    if qual_p <= qual_e:
        return c2, dtau_res, dpil[1:], "pll"
    return c1, dtau_ema, dpil[1:], "ema-sel"


def stage_evm(out: dict, only: set[str] | None = None):
    manifest = json.loads(MANIFEST_PATH.read_text())
    audio_nom, align = _get_audio(out)
    m9 = json.loads(M9_RESULTS.read_text())
    fe_by_name = {p["name"]: (p.get("front_end_used") or "resampling_pll")
                  for p in m9["payloads"] if not p.get("skipped")}
    pad_lo, pad_hi = int(PAD_LO_S * SR), int(PAD_HI_S * SR)
    evm = out.setdefault("evm", {})

    for sec in manifest["ws_payloads"]:
        name = sec["name"]
        if sec.get("skipped") or sec["kind"] == "freqdiff":
            continue
        if only and name not in only:
            continue
        if name in evm and not only:
            continue                                    # checkpointed already
        t0 = time.time()
        sch = _scheme_from_entry(sec)
        meta = sec["meta"]
        fe_name = fe_by_name.get(name, "resampling_pll")
        expected_packed = (_HERE / sec["payload_sidecar"]).read_bytes()
        rung = Rung(name=meta["rung"], M=meta["M"], K=meta["K"], rs_n=meta["rs_n"],
                    rs_k=meta["rs_k"], frame_bytes=meta["frame_bytes"])
        tx_frames, _m = codec.encode_payload(expected_packed, rung)
        nom_bits = _nominal_frame_bits(meta)
        flen_full = len(sch._preamble) + (sch.nsym_data(meta["frame_bits"]) + 1) * sch.N

        P = sch.P
        sum_r2 = np.zeros(P); sum_r2_ok = np.zeros(P)
        n_all = np.zeros(P); n_ok = np.zeros(P); n_err = np.zeros(P)
        amp_s = np.zeros(P); amp_s2 = np.zeros(P)
        pil_jitter: list[np.ndarray] = []
        fe_used_counts: dict[str, int] = {}

        for fi, st in enumerate(sec["frame_starts"]):
            nd = sch.nsym_data(nom_bits[fi])
            st = int(st) + align
            w_lo = max(0, st - pad_lo)
            w_hi = min(len(audio_nom), st + flen_full + pad_hi)
            win = audio_nom[w_lo:w_hi]
            c, dtau, dpil_raw, used = _frontend_c(sch, win, nd, fe_name)
            fe_used_counts[used] = fe_used_counts.get(used, 0) + 1
            pil_jitter.append(dpil_raw)
            q2, dphi2, _qual, d = _decide_full(sch, c, dtau)
            tq = sch.bits_to_quadrants(np.asarray(tx_frames[fi], np.uint8))
            k = min(len(tq), len(q2))
            resid = (dphi2[:k] - tq[:k] * (np.pi / 2.0) + np.pi) % (2 * np.pi) - np.pi
            errs = (q2[:k] != tq[:k])
            okm = ~errs
            sum_r2 += (resid ** 2).sum(axis=0)
            sum_r2_ok += np.where(okm, resid ** 2, 0.0).sum(axis=0)
            n_all += k; n_ok += okm.sum(axis=0); n_err += errs.sum(axis=0)
            amp = np.abs(c[1:k + 1, :])[:, sch.data_idx]
            amp_s += amp.sum(axis=0); amp_s2 += (amp ** 2).sum(axis=0)

        var_all = sum_r2 / np.maximum(n_all, 1)
        var_ok = sum_r2_ok / np.maximum(n_ok, 1)
        ser = n_err / np.maximum(n_all, 1)
        snr_all_db = -10 * np.log10(var_all)            # gamma ~ 1/var(dphi_resid)
        snr_ok_db = -10 * np.log10(var_ok)
        amp_mean = amp_s / np.maximum(n_all, 1)
        amp_var = amp_s2 / np.maximum(n_all, 1) - amp_mean ** 2
        amp_snr_db = 10 * np.log10(amp_mean ** 2 / np.maximum(amp_var, 1e-30))
        sym_rate = SR / sch.N
        gamma = 10 ** (snr_all_db / 10)
        bits_cap = np.log2(1 + gamma)
        cap_geom = float(sym_rate * bits_cap.sum())
        # practical D-MPSK order per carrier: boundary pi/M > z*sigma, z=2.6
        sigma = np.sqrt(var_all)
        m_max = np.maximum(np.pi / (2.6 * np.maximum(sigma, 1e-9)), 1.0)
        bits_dmpsk = np.clip(np.floor(np.log2(m_max)), 0, 6)
        cap_dmpsk_gross = float(sym_rate * bits_dmpsk.sum())

        # per-symbol pilot jitter PSD (raw dtau, fs = symbol rate)
        L = min(len(a) for a in pil_jitter)
        stack = np.vstack([a[:L] for a in pil_jitter])
        f_p, psd_p = periodogram(stack - stack.mean(axis=1, keepdims=True),
                                 fs=sym_rate, window="hann", axis=1,
                                 scaling="density")
        psd_pm = psd_p.mean(axis=0)
        raw_dtau_us = float(np.sqrt(np.mean(stack ** 2)) * 1e6)

        evm[name] = {
            "phy": sec["phy"], "front_end": fe_name,
            "front_end_per_frame": fe_used_counts,
            "rs_k": meta["rs_k"], "n_frames": meta["n_frames"],
            "sym_rate_hz": sym_rate,
            "net_bps": _f(sec.get("projected_net_bps")),
            "carrier_freqs_hz": [_f(f) for f in sch.freqs[sch.data_idx]],
            "pilot_hz": _f(sch.freqs[sch.pilot_idx]),
            "ser": [_f(s) for s in ser],
            "resid_rms_deg": [_f(np.degrees(np.sqrt(v))) for v in var_all],
            "resid_rms_deg_correct_only": [_f(np.degrees(np.sqrt(v))) for v in var_ok],
            "snr_eff_db": [_f(s) for s in snr_all_db],
            "snr_eff_db_correct_only": [_f(s) for s in snr_ok_db],
            "amp_snr_db": [_f(s) for s in amp_snr_db],
            "bits_capacity_per_carrier": [_f(b) for b in bits_cap],
            "bits_dmpsk_z2p6": [int(b) for b in bits_dmpsk],
            "cap_geometry_bps": cap_geom,
            "cap_dmpsk_gross_bps": cap_dmpsk_gross,
            "cap_dmpsk_net_rs_bps": cap_dmpsk_gross * meta["rs_k"] / 255.0,
            "pilot_raw_dtau_rms_us": raw_dtau_us,
            "pilot_jitter_psd_freq_hz": [_f(x) for x in f_p[1:]],
            "pilot_jitter_psd_us2_per_hz": [_f(x * 1e12) for x in psd_pm[1:]],
            "wall_s": round(time.time() - t0, 1),
        }
        _save_out(out)
        print(f"[evm] {name:24s} fe={fe_name:14s} cap_geom={cap_geom:6.0f} bps "
              f"snr_eff med {np.median(snr_all_db):5.1f} dB "
              f"({evm[name]['wall_s']}s)")

    # residual_stats spot-checks (R2-comparable timing numbers) on m8 + m5
    try:
        rs_out = out.setdefault("timing_residual_stats", {})
        for name, fidx in (("m9_m8_dense375", 0), ("m9_m8_dense375", 12),
                           ("m9_m5_n256_rs179", 0), ("m9_m5_n256_rs179", 10)):
            key = f"{name}_frame{fidx}"
            if key in rs_out:
                continue
            sec = next(s for s in manifest["ws_payloads"] if s["name"] == name)
            sch = _scheme_from_entry(sec)
            meta = sec["meta"]
            nom_bits = _nominal_frame_bits(meta)
            flen_full = len(sch._preamble) + (sch.nsym_data(meta["frame_bits"]) + 1) * sch.N
            st = int(sec["frame_starts"][fidx]) + align
            w_lo = max(0, st - pad_lo)
            w_hi = min(len(audio_nom), st + flen_full + pad_hi)
            nd = sch.nsym_data(nom_bits[fidx])
            rs_out[key] = residual_stats(sch, audio_nom[w_lo:w_hi], nd)
        _save_out(out)
        print("[evm] residual_stats:", json.dumps(rs_out, default=float)[:300])
    except Exception as exc:
        print(f"[evm] residual_stats failed: {exc}")


# ===========================================================================
# stage: imd -- data-section mid-gap floors (375 vs 750 Hz spacing)
# ===========================================================================
def _section_body_psd(audio_nom, align, sec, sch, meta):
    """Average Welch PSD over the body (post-preamble) of every frame."""
    nom_bits = _nominal_frame_bits(meta)
    pre = len(sch._preamble)
    acc = None
    n = 0
    p_inband = 0.0
    for fi, st in enumerate(sec["frame_starts"]):
        nd = sch.nsym_data(nom_bits[fi])
        st = int(st) + align
        body = audio_nom[st + pre + sch.N: st + pre + (nd + 1) * sch.N]
        if len(body) < 8192:
            continue
        f_ax, psd = welch(body, fs=SR, nperseg=8192, noverlap=4096, window="hann")
        acc = psd if acc is None else acc + psd
        n += 1
    psd = acc / max(1, n)
    df = f_ax[1] - f_ax[0]
    blo, bhi = np.searchsorted(f_ax, BAND_LO), np.searchsorted(f_ax, BAND_HI)
    p_inband = float(np.sum(psd[blo:bhi]) * df)
    return f_ax, psd, p_inband


def stage_imd(out: dict):
    t0 = time.time()
    manifest = json.loads(MANIFEST_PATH.read_text())
    audio_nom, align = _get_audio(out)
    noise = next(s for s in manifest["sounder_sections"] if s["kind"] == "noisefloor")
    nseg = audio_nom[noise["start"] + align + int(0.4 * SR):
                     noise["start"] + align + noise["length"] - int(0.4 * SR)]
    f_n, n_psd = welch(nseg, fs=SR, nperseg=8192, noverlap=4096, window="hann")

    imd = {}
    for name in ("m9_m8_dense375", "m9_m1_thin159"):
        sec = next(s for s in manifest["ws_payloads"] if s["name"] == name)
        sch = _scheme_from_entry(sec)
        f_ax, psd, p_inband = _section_body_psd(audio_nom, align, sec, sch, sec["meta"])
        n_at = np.interp(f_ax, f_n, n_psd)
        all_f = np.sort(sch.freqs)                       # data + pilot carriers
        rows = []
        for i in range(len(all_f) - 1):
            f0, f1 = all_f[i], all_f[i + 1]
            mid = 0.5 * (f0 + f1)
            gap = f1 - f0
            lo = np.searchsorted(f_ax, mid - 0.12 * gap)
            hi = max(np.searchsorted(f_ax, mid + 0.12 * gap), lo + 1)
            floor = float(np.median(psd[lo:hi]))   # Welch-averaged: no chi2-median bias
            nfl = float(np.median(n_at[lo:hi]))
            rows.append({"mid_hz": _f(mid), "gap_hz": _f(gap),
                         "floor_dbhz": _f(10 * np.log10(floor)),
                         "above_silence_db": _f(10 * np.log10(floor / nfl))})
        # per-carrier received narrowband power (for TX-unit budget calc)
        spacing_hz = float(np.min(np.diff(all_f)))
        car = []
        for fc in sch.freqs[sch.data_idx]:
            lo = np.searchsorted(f_ax, fc - 0.45 * spacing_hz)
            hi = max(np.searchsorted(f_ax, fc + 0.45 * spacing_hz), lo + 1)
            car.append(float(np.sum(psd[lo:hi]) * (f_ax[1] - f_ax[0])))
        imd[name] = {
            "spacing_hz": spacing_hz, "p_inband": p_inband,
            "midgap_rows": rows,
            "midgap_above_silence_db_median": _f(np.median(
                [r["above_silence_db"] for r in rows])),
            "carrier_p": car,
            "note": "data-section mid-gap floor = modulation sidelobes + IMD "
                    "+ flutter sidebands (upper bound on IMD alone)",
        }
        print(f"[imd] {name}: median mid-gap floor "
              f"{imd[name]['midgap_above_silence_db_median']:.1f} dB above silence")
    imd["multitone_gap_floor_is_pure_imd"] = (
        "see sounder.gap_floor: off-tone floor during the 64-tone probe "
        "(no modulation) = IMD + flutter sidebands only")
    imd["wall_s"] = round(time.time() - t0, 1)
    out["imd"] = imd
    _save_out(out)


# ===========================================================================
# stage: capacity -- waterfilling vs the achieved 2572
# ===========================================================================
def _waterfill(qj: np.ndarray, B: float):
    """Maximize sum(log2(1+pj*qj)) s.t. sum(pj)=B, pj>=0. Returns pj."""
    lo, hi = 0.0, B + float(np.max(1.0 / qj)) * 2.0
    for _ in range(200):
        mu = 0.5 * (lo + hi)
        pj = np.maximum(0.0, mu - 1.0 / qj)
        if pj.sum() > B:
            hi = mu
        else:
            lo = mu
    return np.maximum(0.0, 0.5 * (lo + hi) - 1.0 / qj)


def stage_capacity(out: dict):
    snd = out["sounder"]
    tab = snd["table"]
    freqs = np.array([r["f_hz"] for r in tab])
    tone_p = np.array([10 ** (r["tone_p_db"] / 10) for r in tab])     # rx power / TX tone-unit
    n_psd = np.array([10 ** (r["noise_psd_dbhz"] / 10) for r in tab])
    l_psd = np.array([10 ** (r["loaded_psd_dbhz"] / 10) for r in tab])

    # drive ratio rho: data-section in-band rx power vs multitone in-band rx power
    p_mt = snd["p_multitone_inband"]
    p_m8 = out["imd"]["m9_m8_dense375"]["p_inband"]
    rho = p_m8 / p_mt
    B_tx = 64.0 * rho                       # TX budget in multitone tone-units

    # EVM ceiling from m8 in-situ per-carrier SNR (flutter/IMD/AAC-limited)
    m8 = out["evm"]["m9_m8_dense375"]
    ceil_f = np.array(m8["carrier_freqs_hz"])
    ceil_g = np.array([10 ** (s / 10) for s in m8["snr_eff_db"]])

    def gain(f):    # rx power per TX tone-unit (linear interp in dB)
        return 10 ** (np.interp(f, freqs, 10 * np.log10(tone_p)) / 10)

    def npsd(f, loaded=False):
        src = l_psd if loaded else n_psd
        return 10 ** (np.interp(f, freqs, 10 * np.log10(src)) / 10)

    def gceil(f):
        return 10 ** (np.interp(f, ceil_f, 10 * np.log10(ceil_g)) / 10)

    def cap(flo, fhi, delta, *, loaded=False, evm_ceiling=False):
        fj = np.arange(flo + delta / 2, fhi, delta)
        if len(fj) == 0:
            return None
        gj = gain(fj)
        nj = npsd(fj, loaded) * delta
        qj = gj / nj
        # equal TX power per carrier
        p_eq = np.full(len(fj), B_tx / len(fj))
        snr_eq = p_eq * qj
        # waterfilled TX power
        p_wf = _waterfill(qj, B_tx)
        snr_wf = p_wf * qj
        if evm_ceiling:
            cl = gceil(fj)
            snr_eq = np.minimum(snr_eq, cl)
            snr_wf = np.minimum(snr_wf, cl)
        c_eq = float(delta * np.sum(np.log2(1 + snr_eq)))
        c_wf = float(delta * np.sum(np.log2(1 + snr_wf)))
        return {"band_hz": [flo, fhi], "delta_hz": delta, "n_carriers": len(fj),
                "noise": "loaded(IMD+flutter)" if loaded else "silence",
                "evm_ceiling": evm_ceiling,
                "snr_eq_med_db": _f(np.median(10 * np.log10(np.maximum(snr_eq, 1e-12)))),
                "C_equal_bps": c_eq, "C_waterfill_bps": c_wf,
                "x_vs_2572_wf": c_wf / ACHIEVED_NET_BPS}

    e15 = snd["band_edges_snr375"]["15dB"]
    e10 = snd["band_edges_snr375"]["10dB"]
    band15 = (e15["lo_hz"], e15["hi_hz"])
    band10 = (e10["lo_hz"], e10["hi_hz"])

    configs = {
        "A_m9geom_d750_band750_9000_silence": cap(750, 9000, 750.0),
        "B_m8geom_d375_band750_9000_silence": cap(750, 9000, 375.0),
        "C_m8geom_d375_band750_9000_loaded": cap(750, 9000, 375.0, loaded=True),
        "D_d375_band15dB_silence": cap(band15[0], band15[1], 375.0),
        "E_d375_band15dB_loaded": cap(band15[0], band15[1], 375.0, loaded=True),
        "F_d187_band15dB_loaded": cap(band15[0], band15[1], 187.5, loaded=True),
        "G_d375_band10dB_loaded": cap(band10[0], band10[1], 375.0, loaded=True),
        "H_shannon_d25_band10dB_silence": cap(band10[0], band10[1], 25.0),
        "I_m8geom_d375_evmceil_silence": cap(750, 9000, 375.0, evm_ceiling=True),
        "J_d375_band15dB_evmceil_loaded": cap(band15[0], band15[1], 375.0,
                                              loaded=True, evm_ceiling=True),
    }

    # ---- headroom decomposition at the m8 anchor ----
    cap_geom = m8["cap_geometry_bps"]
    cap_dmpsk_net = m8["cap_dmpsk_net_rs_bps"]
    # frame overhead at m8: preamble 0.25 s + ref sym + 0.12 s gap per ~94-sym frame
    n_sym = 94
    body_s = (n_sym + 1) * 512 / SR
    oh = body_s / (body_s + 0.25 + 0.12)
    decomp = {
        "achieved_net_bps": ACHIEVED_NET_BPS,
        "achieved_gross_bps": ACHIEVED_GROSS_BPS,
        "rs_coding_efficiency": 159 / 255,
        "frame_overhead_factor_extra": oh,
        "m8_evm_capacity_same_geometry_bps": cap_geom,
        "m8_dmpsk_practical_net_bps_z2p6_rs159": cap_dmpsk_net,
        "headroom_constellation_x": cap_geom / ACHIEVED_GROSS_BPS,
        "headroom_coding_x": 255 / 159,
        "waterfill_thermal_same_band_x": (configs["B_m8geom_d375_band750_9000_silence"]
                                          ["C_waterfill_bps"] / ACHIEVED_NET_BPS),
        "waterfill_loaded_usable_band_x": (configs["E_d375_band15dB_loaded"]
                                           ["C_waterfill_bps"] / ACHIEVED_NET_BPS),
        "evm_capped_usable_band_x": (configs["J_d375_band15dB_evmceil_loaded"]
                                     ["C_waterfill_bps"] / ACHIEVED_NET_BPS),
    }
    out["capacity"] = {
        "rho_data_vs_multitone_power": rho,
        "tx_budget_tone_units": B_tx,
        "configs": configs,
        "decomposition": decomp,
        "caveats": [
            "TX budget anchored to measured rx power ratio (m8 body vs multitone); "
            "assumes similar spectral occupancy maps rx ratio ~ tx ratio.",
            "Record-level constraint is PEAK, not average power; Schroeder-style "
            "PAPR control assumed feasible.",
            "Loaded floor measured under 64-tone loading (denser than any deployed "
            "comb at low f) -- pessimistic at low f, about right at high f.",
            "EVM ceiling extrapolated flat outside 750-9000 Hz.",
            "Shannon configs ignore sync/preamble/gap overhead (factor "
            f"~{oh:.2f}) and assume ideal coding.",
        ],
    }
    _save_out(out)
    print("[capacity] rho={:.2f}, configs:".format(rho))
    for k, v in configs.items():
        if v:
            print(f"   {k:42s} C_wf={v['C_waterfill_bps']:7.0f} bps "
                  f"(x{v['x_vs_2572_wf']:.2f})")


# ===========================================================================
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", default="all",
                    help="comma list: sync,sounder,flutter,evm,imd,capacity or all")
    ap.add_argument("--capture", default=str(CAPTURE_DEFAULT))
    ap.add_argument("--sections", default=None,
                    help="comma list of section names for evm (re-run subset)")
    ap.add_argument("--force-sync", action="store_true")
    args = ap.parse_args()
    stages = (["sync", "sounder", "flutter", "evm", "imd", "capacity"]
              if args.stage == "all" else args.stage.split(","))
    out = _load_out()
    only = set(args.sections.split(",")) if args.sections else None
    for st in stages:
        if st == "sync":
            stage_sync(pathlib.Path(args.capture), out, force=args.force_sync)
        elif st == "sounder":
            stage_sounder(out)
        elif st == "flutter":
            stage_flutter(out)
        elif st == "evm":
            stage_evm(out, only)
        elif st == "imd":
            stage_imd(out)
        elif st == "capacity":
            stage_capacity(out)
    print(f"[done] {OUT_PATH}")


if __name__ == "__main__":
    import warnings
    warnings.filterwarnings("ignore")
    main()
