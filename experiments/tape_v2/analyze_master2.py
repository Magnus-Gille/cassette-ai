"""analyze_master2.py — Analyze a RECORDING of the tape_v2 master and report
per-config decode pass-rates, the reliable throughput frontier, and a fresh
channel sounding (H(f), SNR(f), flutter, noise floor, recovered clock).

Pipeline
--------
  (a) GLOBAL SYNC + CLOCK:
        - locate the two wide-band global chirps (500->5000 Hz, 0.2 s) by
          matched-filter correlation;
        - estimate the global clock/speed = (manifest chirp spacing) /
          (measured chirp spacing); handle 0.80..1.10;
        - DC-remove, resample the WHOLE recording to ~nominal 48k, normalize.
  (b) SOUNDER: from the (now nominal-rate) recording, measure real H(f), SNR(f),
      flutter % (from the steady 3 kHz tone), noise floor, recovered clock.
  (c) PER-SECTION DECODE: for each manifest section, coarse-locate by the scaled
      manifest offset, hand a generous window to the owning modem.demodulate
      (which does its own local find_preamble fine-sync), CRC-check, byte-compare
      to the sidecar. Aggregate a PASS-RATE table per config.
  (d) WRITE results JSON + markdown table to results/.

Usage
-----
    python3 analyze_master2.py <recording.wav> [--out-tag TAG]

The recording is assumed float/int WAV @ (nominally) 48k.  Speed offset / clock
drift is recovered automatically from the chirps.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys
from fractions import Fraction

import numpy as np
import soundfile as sf
from scipy.signal import correlate, resample_poly, chirp as _scipy_chirp

# ---------------------------------------------------------------------------
# Path bootstrap
# ---------------------------------------------------------------------------
ROOT = pathlib.Path("/Users/magnus/repos/cassette-ai")
for _p in ["src", "tests/e2e"]:
    _full = str(ROOT / _p)
    if _full not in sys.path:
        sys.path.insert(0, _full)

TAPE_V2 = ROOT / "experiments" / "tape_v2"
if str(TAPE_V2) not in sys.path:
    sys.path.insert(0, str(TAPE_V2))

import hyp_common as hc          # noqa: E402
import modems_index             # noqa: E402
import modems_combo             # noqa: E402
import modems_ofdm              # noqa: E402

SR = 48_000
MANIFEST_PATH = TAPE_V2 / "master2_manifest.json"
RESULTS_DIR = TAPE_V2 / "results"

# ---------------------------------------------------------------------------
# Modem registry: section config -> owning modem module
# ---------------------------------------------------------------------------
MODEM_REGISTRY = {
    "mfsk32":       modems_index,
    "c1_gray_m16":  modems_index,
    "c2_m32_k2":    modems_combo,
    "c2_m32_k4":    modems_combo,
    "c2_m48_k6":    modems_combo,
    "c4_bpsk":      modems_ofdm,
    "c4_qpsk":      modems_ofdm,
    "c4_realmodel": modems_ofdm,
    "c4_simloaded": modems_ofdm,
}
# Robust -> aggressive order for tables / frontier.
CONFIG_ORDER = [
    "mfsk32", "c1_gray_m16", "c2_m32_k2", "c2_m32_k4", "c2_m48_k6",
    "c4_bpsk", "c4_qpsk", "c4_realmodel", "c4_simloaded",
]

# Global chirp parameters (must match make_master2.py)
GLOBAL_CHIRP_T = 0.20
GLOBAL_CHIRP_F0 = 500.0
GLOBAL_CHIRP_F1 = 5000.0

# ---------------------------------------------------------------------------
# Sync-confidence gate — calibrated 2026-06-28 against two real UCA222 captures:
#   BAD  (inband_cassettellm_tape.wav,  truncated end chirp):
#         chirp0=86.78  chirp1=2.75  → spurious lock (speed 0.83x), 17.3% flutter
#   GOOD (inband_cassettellm_tape2.wav, full chirps):
#         chirp0=87.34  chirp1=148.38 → clock 0.9995x, 0.29% flutter (byte-exact)
# Threshold 4.5 gives >1.6x margin below bad (2.75 vs 4.5) and 33x margin
# above good (148.38 vs 4.5).
# ---------------------------------------------------------------------------
MIN_CHIRP_PROMINENCE = 4.5


# ===========================================================================
# (a) global chirp sync + clock recovery
# ===========================================================================
def _ref_global_chirp(up: bool = True) -> np.ndarray:
    n = int(GLOBAL_CHIRP_T * SR)
    t = np.arange(n, dtype=np.float64) / SR
    f0, f1 = ((GLOBAL_CHIRP_F0, GLOBAL_CHIRP_F1) if up
              else (GLOBAL_CHIRP_F1, GLOBAL_CHIRP_F0))
    return _scipy_chirp(t, f0=f0, f1=f1, t1=GLOBAL_CHIRP_T, method="linear")


def _dc_remove_normalize(x: np.ndarray) -> np.ndarray:
    x = np.asarray(x, dtype=np.float64)
    x = x - np.mean(x)
    pk = float(np.max(np.abs(x))) if x.size else 0.0
    if pk > 1e-12:
        x = x / pk
    return x


def _speed_match_ref(ref: np.ndarray, speed: float) -> np.ndarray:
    """Resample a nominal-rate chirp template to the recorded `speed` so the
    matched filter is not biased by template/signal time-scale mismatch."""
    if abs(speed - 1.0) < 1e-4:
        return ref
    frac = Fraction(speed).limit_denominator(2000)
    return resample_poly(ref, frac.numerator, frac.denominator)


def _chirp_prominence(corr: np.ndarray, peak_idx: int) -> float:
    """Return peak / 90th-percentile-of-background for a correlation array.

    Guard window = 3x the chirp duration on each side of the peak. The ratio
    measures how far the matched-filter peak stands above the noise floor: a
    genuine in-band chirp gives >> 1; a spurious peak on a missing/truncated
    chirp hovers near 1.
    """
    guard = min(len(corr) // 4, int(GLOBAL_CHIRP_T * SR * 3))
    peak_val = float(corr[peak_idx]) if peak_idx < len(corr) else 0.0
    if peak_val < 1e-12:
        return 0.0
    lo_g = max(0, peak_idx - guard)
    hi_g = min(len(corr), peak_idx + guard + 1)
    mask = np.ones(len(corr), dtype=bool)
    mask[lo_g:hi_g] = False
    bg = corr[mask]
    if bg.size < 10:
        # Fallback: use everything except the immediate peak bin
        bg = np.concatenate([corr[:peak_idx], corr[peak_idx + 1:]])
    if bg.size == 0:
        return float("inf")
    bg_level = float(np.percentile(bg, 90))
    return peak_val / max(bg_level, 1e-12)


def _locate_chirp(audio: np.ndarray, ref: np.ndarray, lo: int, hi: int) -> int:
    """Return sample index of the chirp START within [lo, hi] of `audio`,
    with parabolic sub-sample peak refinement (rounded to int)."""
    lo = max(0, lo)
    hi = min(len(audio), hi)
    seg = audio[lo:hi]
    if len(seg) < len(ref):
        return lo
    corr = np.abs(correlate(seg, ref, mode="valid"))
    peak = int(np.argmax(corr))
    # parabolic interpolation around the peak for sub-sample accuracy
    if 0 < peak < len(corr) - 1:
        y0, y1, y2 = corr[peak - 1], corr[peak], corr[peak + 1]
        denom = (y0 - 2 * y1 + y2)
        if abs(denom) > 1e-12:
            peak = peak + 0.5 * (y0 - y2) / denom
    return lo + int(round(peak))


def _locate_chirp_with_prominence(
    audio: np.ndarray, ref: np.ndarray, lo: int, hi: int
) -> tuple[int, float]:
    """Like _locate_chirp but also returns the peak prominence of the match.

    Returns (sample_index, prominence) where prominence = peak / bg_90pct.
    """
    lo = max(0, lo)
    hi = min(len(audio), hi)
    seg = audio[lo:hi]
    if len(seg) < len(ref):
        return lo, 0.0
    corr = np.abs(correlate(seg, ref, mode="valid"))
    peak_int = int(np.argmax(corr))
    prominence = _chirp_prominence(corr, peak_int)
    # parabolic sub-sample refinement
    peak: float = float(peak_int)
    if 0 < peak_int < len(corr) - 1:
        y0, y1, y2 = corr[peak_int - 1], corr[peak_int], corr[peak_int + 1]
        denom = (y0 - 2 * y1 + y2)
        if abs(denom) > 1e-12:
            peak = peak_int + 0.5 * (y0 - y2) / denom
    return lo + int(round(peak)), prominence


def global_sync_and_resample(audio: np.ndarray, manifest: dict) -> dict:
    """Find both global chirps, estimate clock, resample whole recording to nominal.

    Returns dict with keys: audio_nominal, clock_ratio, speed_offset,
    chirp0_meas, chirp1_meas, expected_spacing, measured_spacing.
    """
    audio = _dc_remove_normalize(audio)

    up = _ref_global_chirp(up=True)
    down = _ref_global_chirp(up=False)

    exp_c0 = manifest["tx_chirp0"]
    exp_c1 = manifest["tx_chirp1"]
    exp_spacing = exp_c1 - exp_c0

    # --- PASS 1: locate chirp0 in a GENEROUS lead-in window ---
    # The operator may start the recorder an arbitrary number of seconds before
    # starting the tape (real captures have seen 10+ s of lead-in), so chirp0 is
    # NOT near exp_c0. Search the whole first ~45% of the recording (chirp1 lives
    # in the back half, so chirp0 is always in front of that) and take the global
    # max: the up-chirp's matched-filter gain makes it dominate any data/noise
    # peak. A too-narrow window here silently mislocates chirp0 and shifts every
    # section offset (the classic "decodes at chance on a real capture" bug).
    head_hi = int(min(len(audio), max(0.45 * len(audio), 60.0 * SR)))
    c0, chirp0_prominence = _locate_chirp_with_prominence(audio, up, 0, head_hi)

    # --- PASS 2: locate chirp1 via a SPEED SCAN with speed-matched templates ---
    # A nominal down-chirp template correlated against a speed-compressed recorded
    # chirp gives a weak, biased peak (it can lose to spurious peaks tens of ms
    # away).  Instead scan candidate speeds, compress the template to each, and
    # keep the (speed, position) with the strongest correlation.  The recorded
    # chirp1 sits at ~speed*exp_spacing after chirp0.
    best = None       # (corr_value, speed, c1)
    best_corr = None  # the correlation array for the winning speed (for prominence)
    best_lo = 0       # the segment start for the winning speed
    for sp in np.arange(0.80, 1.1001, 0.01):
        ds = _speed_match_ref(down, float(sp))
        centre = c0 + int(sp * exp_spacing)
        win = int(0.04 * exp_spacing) + SR  # +/- ~4% spacing tolerance
        lo = max(0, centre - win)
        hi = min(len(audio), centre + win + len(ds))
        seg = audio[lo:hi]
        if len(seg) < len(ds):
            continue
        corr = np.abs(correlate(seg, ds, mode="valid"))
        pk = int(np.argmax(corr))
        val = float(corr[pk])
        if best is None or val > best[0]:
            best = (val, float(sp), lo + pk)
            best_corr = corr
            best_lo = lo
    coarse_speed = best[1] if best else 1.0

    # Compute chirp1 prominence from the winning speed's correlation array.
    if best_corr is not None and best is not None:
        c1_peak_in_corr = best[2] - best_lo
        chirp1_prominence = _chirp_prominence(best_corr, c1_peak_in_corr)
    else:
        chirp1_prominence = 0.0

    # --- PASS 3: refine both chirp positions with the winning speed template ---
    up_s = _speed_match_ref(up, coarse_speed)
    down_s = _speed_match_ref(down, coarse_speed)
    c0 = _locate_chirp(audio, up_s, max(0, c0 - SR // 2), c0 + len(up_s) + SR // 2)
    c1_centre = best[2] if best else c0 + int(coarse_speed * exp_spacing)
    c1 = _locate_chirp(audio, down_s,
                       max(0, c1_centre - SR // 2),
                       c1_centre + len(down_s) + SR // 2)

    measured_spacing = c1 - c0
    if measured_spacing <= 0:
        measured_spacing = int(round(coarse_speed * exp_spacing))  # fallback
    # The deck ran at `speed` x nominal. A deck at speed s plays the tape s x
    # faster, so the captured recording is COMPRESSED: measured_spacing =
    # s * exp_spacing.  Hence speed = measured_spacing / exp_spacing.
    # (e.g. 0.88x deck -> measured_spacing ~ 0.88 * expected.)
    speed = measured_spacing / exp_spacing
    speed_offset = speed - 1.0
    clock_ratio = speed

    # Resample whole recording back to nominal: a recording compressed by `speed`
    # must be STRETCHED by 1/speed = exp_spacing/measured_spacing to restore
    # nominal timing.  resample_poly(audio, up, down) scales length by up/down,
    # so up=exp_spacing, down=measured_spacing.
    frac = Fraction(exp_spacing, measured_spacing).limit_denominator(20000)
    if frac.numerator != frac.denominator:
        audio_nominal = resample_poly(audio, frac.numerator, frac.denominator)
    else:
        audio_nominal = audio.copy()
    audio_nominal = _dc_remove_normalize(audio_nominal)

    # Re-locate chirp0 in the resampled domain to anchor section offsets (same
    # generous lead-in window as PASS 1 — a narrow window here re-introduces the
    # mislocation bug after resampling).
    head_hi2 = int(min(len(audio_nominal), max(0.45 * len(audio_nominal), 60.0 * SR)))
    c0_nom = _locate_chirp(audio_nominal, up, 0, head_hi2)

    # ------------------------------------------------------------------
    # Sync confidence gate — detect spurious peak locks BEFORE demod.
    # Reasons for failure (any one is sufficient to flag):
    #   1. chirp0 or chirp1 prominence below threshold (spurious peak)
    #   2. chirp1 lands within <1 s of the end of the recording
    #      (end chirp likely truncated; the speed scan may lock onto
    #      any noise peak near the expected position)
    #   3. measured speed implausibly far from nominal (|speed-1|>0.2)
    # ------------------------------------------------------------------
    warnings: list[str] = []
    if chirp0_prominence < MIN_CHIRP_PROMINENCE:
        warnings.append(
            f"chirp0 prominence {chirp0_prominence:.2f} < {MIN_CHIRP_PROMINENCE} "
            f"(start chirp weak/missing)"
        )
    if chirp1_prominence < MIN_CHIRP_PROMINENCE:
        warnings.append(
            f"chirp1 prominence {chirp1_prominence:.2f} < {MIN_CHIRP_PROMINENCE} "
            f"(end chirp weak/missing or recording truncated)"
        )
    samples_remaining_after_c1 = len(audio) - c1
    if samples_remaining_after_c1 < SR:
        warnings.append(
            f"end chirp at sample {c1} with only {samples_remaining_after_c1} "
            f"samples remaining (<1 s) — recording likely truncated"
        )
    if abs(speed - 1.0) > 0.20:
        warnings.append(
            f"measured speed {speed:.4f}x deviates >20 % from nominal "
            f"— likely a spurious chirp1 lock"
        )
    sync_confident = len(warnings) == 0
    sync_warning = "; ".join(warnings)

    return {
        "audio_nominal": audio_nominal.astype(np.float32),
        "clock_ratio": float(clock_ratio),
        "speed": float(speed),
        "speed_offset": float(speed_offset),
        "chirp0_meas": int(c0),
        "chirp1_meas": int(c1),
        "chirp0_nominal": int(c0_nom),
        "expected_chirp0": int(exp_c0),
        "expected_spacing": int(exp_spacing),
        "measured_spacing": int(measured_spacing),
        "resample_num": frac.numerator,
        "resample_den": frac.denominator,
        # --- new confidence keys ---
        "chirp0_prominence": float(chirp0_prominence),
        "chirp1_prominence": float(chirp1_prominence),
        "sync_confident": bool(sync_confident),
        "sync_warning": str(sync_warning),
    }


# ===========================================================================
# (b) sounder analysis on the nominal-rate recording
# ===========================================================================
def analyze_sounder(audio_nom: np.ndarray, manifest: dict, sync: dict) -> dict:
    """Measure real H(f), SNR(f), flutter %, noise floor, recovered clock from
    the sounder sub-sections (manifest start positions shifted by the chirp0
    alignment offset between recording and tx)."""
    # Alignment offset: in the nominal domain, where did chirp0 actually land
    # vs where the manifest says it should be?
    align = sync["chirp0_nominal"] - sync["expected_chirp0"]
    out: dict = {"chirp0_align_offset": int(align)}

    multitone = [s for s in manifest["sounder_sections"] if s["kind"] == "multitone"]
    steady = next((s for s in manifest["sounder_sections"] if s["kind"] == "steady"), None)
    noise = next((s for s in manifest["sounder_sections"] if s["kind"] == "noisefloor"), None)

    def grab(sec, trim=0.2):
        st = sec["start"] + align
        ln = sec["length"]
        ti = int(trim * SR)
        a = audio_nom[max(0, st + ti): st + ln - ti]
        return np.asarray(a, dtype=np.float64)

    # --- Noise floor (RMS over the silence section) ---
    nf_rms = None
    if noise is not None:
        seg = grab(noise, trim=0.3)
        if seg.size:
            nf_rms = float(np.sqrt(np.mean(seg ** 2)))
    out["noise_floor_rms"] = nf_rms
    out["noise_floor_dbfs"] = (20.0 * np.log10(nf_rms) if nf_rms and nf_rms > 0
                               else None)

    # --- H(f) + SNR(f) from the multitone probes (averaged) ---
    if multitone:
        freqs = np.asarray(multitone[0]["info"]["freqs"], dtype=float)
        Hmag_acc = np.zeros(len(freqs))
        n_used = 0
        for mt in multitone:
            seg = grab(mt, trim=0.3)
            if seg.size < SR:
                continue
            n = len(seg)
            win = np.hanning(n)
            sp = np.fft.rfft(seg * win)
            fax = np.fft.rfftfreq(n, 1.0 / SR)
            mags = []
            for f in freqs:
                bin_lo = np.searchsorted(fax, f - 30)
                bin_hi = np.searchsorted(fax, f + 30)
                bin_hi = max(bin_hi, bin_lo + 1)
                mags.append(float(np.max(np.abs(sp[bin_lo:bin_hi]))))
            Hmag_acc += np.asarray(mags)
            n_used += 1
        Hmag = Hmag_acc / max(1, n_used)
        Hmag_norm = Hmag / (np.max(Hmag) + 1e-12)
        H_db = 20.0 * np.log10(np.maximum(Hmag_norm, 1e-6))

        # Per-tone SNR: tone energy vs local off-tone floor (mid-bin between tones)
        snr_db = []
        for mt in multitone[:1]:  # one rep is enough for SNR estimate
            seg = grab(mt, trim=0.3)
            if seg.size < SR:
                snr_db = [None] * len(freqs)
                break
            n = len(seg)
            win = np.hanning(n)
            sp = np.abs(np.fft.rfft(seg * win))
            fax = np.fft.rfftfreq(n, 1.0 / SR)
            for f in freqs:
                bl = np.searchsorted(fax, f - 30)
                bh = max(np.searchsorted(fax, f + 30), bl + 1)
                tone = float(np.max(sp[bl:bh]))
                # noise: a band offset 80-140 Hz away (between tones)
                nl = np.searchsorted(fax, f + 80)
                nh = max(np.searchsorted(fax, f + 140), nl + 1)
                nh = min(nh, len(sp))
                noise_amp = float(np.median(sp[nl:nh])) if nh > nl else 1e-9
                snr_db.append(20.0 * np.log10(max(tone, 1e-12) / max(noise_amp, 1e-12)))
            break
        snr_arr = np.asarray([s for s in snr_db if s is not None], dtype=float)
        out["sounder_freqs"] = freqs.tolist()
        out["H_db"] = H_db.tolist()
        out["snr_db_per_tone"] = [None if s is None else float(s) for s in snr_db]
        if snr_arr.size:
            out["snr_db_median"] = float(np.median(snr_arr))
            out["snr_db_p10"] = float(np.percentile(snr_arr, 10))
            out["frac_below_8db"] = float(np.mean(snr_arr < 8.0))

    # --- Flutter % from the steady 3 kHz tone (instantaneous-freq deviation) ---
    if steady is not None:
        seg = grab(steady, trim=0.5)
        f0 = float(steady["info"]["f0"])
        if seg.size > SR:
            # Hilbert-free instantaneous frequency via zero-crossing-rate is noisy;
            # use complex demod: multiply by e^{-j2pi f0 t}, lowpass, unwrap phase.
            t = np.arange(len(seg)) / SR
            bb = seg * np.exp(-1j * 2 * np.pi * f0 * t)
            # simple moving-average lowpass (~200 Hz)
            w = int(SR / 600)
            if w < 1:
                w = 1
            kern = np.ones(w) / w
            bb_lp = np.convolve(bb.real, kern, mode="same") + 1j * np.convolve(bb.imag, kern, mode="same")
            ph = np.unwrap(np.angle(bb_lp))
            inst_f = f0 + np.gradient(ph) * SR / (2 * np.pi)
            # discard edges
            m = len(inst_f) // 10
            inst_f = inst_f[m:-m] if len(inst_f) > 2 * m else inst_f
            if inst_f.size:
                rel = (inst_f - np.mean(inst_f)) / max(np.mean(inst_f), 1e-9)
                out["flutter_wrms_pct"] = float(np.sqrt(np.mean(rel ** 2)) * 100.0)
                out["recovered_clock_from_tone"] = float(np.mean(inst_f) / f0)

    return out


# ===========================================================================
# (c) per-section decode
# ===========================================================================
def _hamming_ber(tb: np.ndarray, rb: np.ndarray) -> float:
    """Compute raw BER between two bit arrays; length mismatch treated as errors."""
    n = len(tb)
    if n == 0:
        return 0.0
    m = min(n, len(rb))
    errs = int(np.count_nonzero(tb[:m] != rb[:m])) if m else 0
    errs += (n - m)  # missing tail bits count as errors
    return errs / n


def decode_sections(audio_nom: np.ndarray, manifest: dict, sync: dict,
                     window_pad: float = 0.30) -> dict:
    """Decode each section via its owning modem, byte-compare to sidecar.

    Also computes raw BER per section using tx_bits/rx_bits and aggregates
    mean raw BER per config. Projects to net_bps and P_full via hc.project_to_cassette.

    Returns per-config aggregate dict with new keys:
        raw_ber, proj_net_bps, proj_P_full, recoverable_with_FEC
    """
    align = sync["chirp0_nominal"] - sync["expected_chirp0"]
    pad = int(window_pad * SR)

    per_cfg: dict[str, dict] = {
        c: {"reps": 0, "passes": 0, "payload_bytes_total": 0,
            "payload_bytes_delivered": 0, "section_lengths": [],
            "ber_samples": []}
        for c in CONFIG_ORDER
    }

    for sec in manifest["sections"]:
        cfg = sec["config"]
        mod = MODEM_REGISTRY[cfg]
        start = sec["start_sample"] + align
        length = sec["length"]
        # Generous window: pad before (so the modem's find_preamble sees the
        # whole preamble) and after (so the last symbol + tail guard is present).
        w_lo = max(0, start - pad)
        w_hi = min(len(audio_nom), start + length + pad)
        window = audio_nom[w_lo:w_hi]
        window_f32 = np.asarray(window, dtype=np.float32)

        scar_path = TAPE_V2 / sec["payload_sidecar"]
        expected = scar_path.read_bytes()

        rx = mod.demodulate(window_f32, cfg)
        ok = (rx == expected)

        # Raw BER: compare tx_bits(expected) to rx_bits(window).
        try:
            tb = mod.tx_bits(expected, cfg)
            rb = mod.rx_bits(window_f32, cfg)
            ber = _hamming_ber(tb, rb)
        except Exception:
            ber = float("nan")

        d = per_cfg[cfg]
        d["reps"] += 1
        d["payload_bytes_total"] += len(expected)
        d["section_lengths"].append(length)
        if not np.isnan(ber):
            d["ber_samples"].append(ber)
        if ok:
            d["passes"] += 1
            d["payload_bytes_delivered"] += len(expected)

    # Compute gross bps, passrate, mean raw BER, projected net_bps / P_full.
    for cfg, d in per_cfg.items():
        d["passrate"] = d["passes"] / d["reps"] if d["reps"] else 0.0
        avg_len = (sum(d["section_lengths"]) / len(d["section_lengths"])
                   if d["section_lengths"] else 0.0)
        # gross bps = frame bits / section duration (payload+8 frame overhead)
        if avg_len > 0 and d["reps"]:
            avg_payload = d["payload_bytes_total"] / d["reps"]
            frame_bits = (avg_payload + 8) * 8
            d["gross_bps"] = frame_bits / (avg_len / SR)
        else:
            d["gross_bps"] = 0.0

        # Mean raw BER.
        ber_samples = d.pop("ber_samples", [])
        if ber_samples:
            mean_ber = float(np.mean(ber_samples))
        else:
            mean_ber = float("nan")
        d["raw_ber"] = mean_ber

        # Project to cassette using hc.project_to_cassette.
        if d["gross_bps"] > 0 and not np.isnan(mean_ber):
            proj = hc.project_to_cassette(
                raw_ber=mean_ber,
                erasure_rate=0.0,
                gross_bps=d["gross_bps"],
            )
            d["proj_net_bps"] = proj["net_bps"]
            d["proj_P_full"] = proj["P_full"]
            d["recoverable_with_FEC"] = bool(proj["P_full"] >= 0.95)
        else:
            d["proj_net_bps"] = 0.0
            d["proj_P_full"] = 0.0
            d["recoverable_with_FEC"] = False

        d.pop("section_lengths", None)

    return per_cfg


def reliable_frontier(per_cfg: dict) -> dict:
    """Highest-gross config with passrate==1.0 and the highest with >=0.8."""
    perfect = [(c, per_cfg[c]) for c in CONFIG_ORDER
               if per_cfg[c]["reps"] and per_cfg[c]["passrate"] >= 0.999]
    good = [(c, per_cfg[c]) for c in CONFIG_ORDER
            if per_cfg[c]["reps"] and per_cfg[c]["passrate"] >= 0.80]
    frontier = {"perfect": None, "good": None}
    if perfect:
        c, d = max(perfect, key=lambda cd: cd[1]["gross_bps"])
        frontier["perfect"] = {"config": c, "gross_bps": d["gross_bps"],
                               "passrate": d["passrate"]}
    if good:
        c, d = max(good, key=lambda cd: cd[1]["gross_bps"])
        frontier["good"] = {"config": c, "gross_bps": d["gross_bps"],
                            "passrate": d["passrate"]}
    return frontier


# ===========================================================================
# (d) report writers
# ===========================================================================
def _fmt_ber(v) -> str:
    """Format BER value for display."""
    if v is None or (isinstance(v, float) and (np.isnan(v) or np.isinf(v))):
        return "nan"
    return f"{v:.4f}"


def _markdown_table(per_cfg: dict, sync: dict, sounder: dict,
                    frontier: dict, source: str) -> str:
    lines = []
    lines.append(f"# tape_v2 analysis — `{source}`\n")
    lines.append(f"- Recovered global clock (speed): **{sync['speed']:.4f}x** "
                 f"(offset {sync['speed_offset']*100:+.2f}%)")
    lines.append(f"- Chirp spacing: measured {sync['measured_spacing']} vs "
                 f"expected {sync['expected_spacing']} samples")
    if sounder.get("snr_db_median") is not None:
        lines.append(f"- Sounder SNR(f): median {sounder['snr_db_median']:.1f} dB, "
                     f"p10 {sounder.get('snr_db_p10', float('nan')):.1f} dB, "
                     f"frac<8dB {sounder.get('frac_below_8db', 0)*100:.0f}%")
    if sounder.get("flutter_wrms_pct") is not None:
        lines.append(f"- Flutter (steady tone): {sounder['flutter_wrms_pct']:.2f}% WRMS")
    if sounder.get("noise_floor_dbfs") is not None:
        lines.append(f"- Noise floor: {sounder['noise_floor_dbfs']:.1f} dBFS")
    lines.append("")
    lines.append("| Config | Reps | Passes | Passrate | Gross bps | Net bytes | "
                 "Raw BER | Proj net bps | Proj P_full | FEC OK |")
    lines.append("|---|---|---|---|---|---|---|---|---|---|")
    for c in CONFIG_ORDER:
        d = per_cfg[c]
        fec_ok = "YES" if d.get("recoverable_with_FEC") else "no"
        lines.append(
            f"| {c} | {d['reps']} | {d['passes']} | "
            f"{d['passrate']:.2f} | {d['gross_bps']:.0f} | "
            f"{d['payload_bytes_delivered']} | "
            f"{_fmt_ber(d.get('raw_ber'))} | "
            f"{d.get('proj_net_bps', 0):.0f} | "
            f"{d.get('proj_P_full', 0):.2f} | "
            f"{fec_ok} |"
        )
    lines.append("")
    fp = frontier.get("perfect")
    fg = frontier.get("good")
    if fp:
        lines.append(f"**Reliable frontier (passrate=1.0):** {fp['config']} "
                     f"@ {fp['gross_bps']:.0f} gross bps")
    else:
        lines.append("**Reliable frontier (passrate=1.0):** none")
    if fg:
        lines.append(f"**Frontier (passrate>=0.8):** {fg['config']} "
                     f"@ {fg['gross_bps']:.0f} gross bps")
    else:
        lines.append("**Frontier (passrate>=0.8):** none")
    # FEC-recoverable configs summary
    fec_ok_cfgs = [c for c in CONFIG_ORDER
                   if per_cfg[c].get("recoverable_with_FEC") and per_cfg[c]["reps"] > 0]
    if fec_ok_cfgs:
        best_fec = max(fec_ok_cfgs, key=lambda c: per_cfg[c].get("proj_net_bps", 0))
        lines.append(f"**FEC-recoverable (P_full>=0.95) configs:** "
                     f"{', '.join(fec_ok_cfgs)} "
                     f"(best net bps: {per_cfg[best_fec].get('proj_net_bps',0):.0f} from {best_fec})")
    else:
        lines.append("**FEC-recoverable (P_full>=0.95) configs:** none")
    lines.append("")
    return "\n".join(lines)


def print_table(per_cfg: dict, sync: dict, sounder: dict, frontier: dict):
    print(f"  recovered clock: {sync['speed']:.4f}x "
          f"(offset {sync['speed_offset']*100:+.2f}%), "
          f"spacing {sync['measured_spacing']}/{sync['expected_spacing']}")
    if sounder.get("snr_db_median") is not None:
        print(f"  sounder: SNR med {sounder['snr_db_median']:.1f} dB, "
              f"p10 {sounder.get('snr_db_p10', float('nan')):.1f} dB, "
              f"frac<8dB {sounder.get('frac_below_8db',0)*100:.0f}%, "
              f"flutter {sounder.get('flutter_wrms_pct', float('nan')):.2f}%, "
              f"nf {sounder.get('noise_floor_dbfs', float('nan')):.1f} dBFS")
    print(f"  {'config':<14} {'reps':>4} {'pass':>5} {'rate':>5} "
          f"{'gross':>7} {'net_B':>7} {'raw_ber':>8} {'net_bps':>8} {'P_full':>7} {'FEC':>5}")
    for c in CONFIG_ORDER:
        d = per_cfg[c]
        ber_s = _fmt_ber(d.get("raw_ber"))
        fec_s = "YES" if d.get("recoverable_with_FEC") else "no"
        print(f"  {c:<14} {d['reps']:>4} {d['passes']:>5} "
              f"{d['passrate']:>5.2f} {d['gross_bps']:>7.0f} "
              f"{d['payload_bytes_delivered']:>7} "
              f"{ber_s:>8} {d.get('proj_net_bps',0):>8.0f} "
              f"{d.get('proj_P_full',0):>7.2f} {fec_s:>5}")
    fp, fg = frontier.get("perfect"), frontier.get("good")
    print(f"  frontier passrate=1.0: "
          f"{fp['config'] + ' @ ' + format(fp['gross_bps'],'.0f') + ' bps' if fp else 'none'}")
    print(f"  frontier passrate>=0.8: "
          f"{fg['config'] + ' @ ' + format(fg['gross_bps'],'.0f') + ' bps' if fg else 'none'}")
    fec_ok_cfgs = [c for c in CONFIG_ORDER
                   if per_cfg[c].get("recoverable_with_FEC") and per_cfg[c]["reps"] > 0]
    print(f"  FEC-recoverable (P_full>=0.95): "
          f"{', '.join(fec_ok_cfgs) if fec_ok_cfgs else 'none'}")


def analyze(recording_path: str, out_tag: str | None = None,
            verbose: bool = True) -> dict:
    manifest = json.loads(MANIFEST_PATH.read_text())
    audio, sr = sf.read(recording_path, dtype="float32", always_2d=False)
    if audio.ndim > 1:
        audio = audio.mean(axis=1)
    # If the recording isn't 48k, bring it there first (chirp clock recovery
    # then handles the residual tape speed offset).
    if sr != SR:
        frac = Fraction(SR, sr).limit_denominator(20000)
        audio = resample_poly(audio.astype(np.float64), frac.numerator, frac.denominator)

    sync = global_sync_and_resample(audio, manifest)
    audio_nom = sync["audio_nominal"]

    sounder = analyze_sounder(audio_nom, manifest, sync)
    per_cfg = decode_sections(audio_nom, manifest, sync)
    frontier = reliable_frontier(per_cfg)

    if verbose:
        print(f"[analyze] {recording_path}")
        print_table(per_cfg, sync, sounder, frontier)

    # Write outputs.
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    tag = out_tag or pathlib.Path(recording_path).stem
    result = {
        "recording": str(recording_path),
        "sync": {k: v for k, v in sync.items() if k != "audio_nominal"},
        "sounder": {k: v for k, v in sounder.items()
                    if k not in ("H_db", "snr_db_per_tone", "sounder_freqs")},
        "sounder_curves": {
            "freqs": sounder.get("sounder_freqs"),
            "H_db": sounder.get("H_db"),
            "snr_db_per_tone": sounder.get("snr_db_per_tone"),
        },
        "per_config": per_cfg,
        "frontier": frontier,
    }
    json_path = RESULTS_DIR / f"results_{tag}.json"
    md_path = RESULTS_DIR / f"results_{tag}.md"
    json_path.write_text(json.dumps(result, indent=2))
    md_path.write_text(_markdown_table(per_cfg, sync, sounder, frontier,
                                       source=tag))
    if verbose:
        print(f"[analyze] wrote {json_path}")
        print(f"[analyze] wrote {md_path}")
    return result


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("recording", help="path to captured tape-playback WAV")
    ap.add_argument("--out-tag", default=None)
    args = ap.parse_args()
    analyze(args.recording, out_tag=args.out_tag)
