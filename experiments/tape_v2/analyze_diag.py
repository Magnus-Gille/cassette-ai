#!/usr/bin/env python3
"""analyze_diag.py — CASSETTE-AI SETUP REPORT CARD (RC v1).

Produces a PASS/WARN/FAIL report card for a capture of the DIAG-1 calibration
tape (make_diag_master.py) OR for any stereo/mono capture of a cassette tape.

Dimensions graded:
  1. LEVELS / CLIPPING / DC OFFSET  — per channel
  2. L/R CHANNEL RELATIONSHIP       — correlation, polarity, best combo recommendation
  3. MAINS HUM                      — 50 Hz + harmonics (EU) and 60 Hz (US/JP)
  4. FREQUENCY RESPONSE             — per-carrier SNR, notch detection, HF rolloff
  5. CLOCK / FLUTTER                — deck speed and flutter WRMS %
  6. DISTORTION / RECORD LEVEL      — THD estimate (diag-tape mode only)
  7. DECODABILITY PROJECTION        — per-config BER -> net bps (diag-tape mode only)

Works on ANY stereo (or mono) capture — the core checks run without a manifest.
When a diag_manifest.json is provided (via --manifest), it also runs the
precise probe-window checks (dimensions 5-7) for the diag tape.

Usage:
    python3 analyze_diag.py <capture.wav> [--manifest diag_manifest.json]
                                          [--window 60] [--out-json results/]
"""
from __future__ import annotations

import argparse
import datetime
import json
import pathlib
import sys
from typing import Any

import numpy as np
import soundfile as sf
from scipy.signal import butter, hilbert, sosfiltfilt

ROOT = pathlib.Path("/Users/magnus/repos/cassette-ai")
TAPE_V2 = ROOT / "experiments" / "tape_v2"
for _p in (ROOT / "src", ROOT / "tests" / "e2e", TAPE_V2):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

SR_EXPECTED = 48_000
VERSION = "diag-rc1"

# ─── Thresholds ─────────────────────────────────────────────────────────────
CLIP_THR = 0.99          # peak ≥ this → clip
QUIET_THR = 0.005        # peak <  this → probably silent / disconnected
DC_WARN = 0.01           # |mean| > this → WARN
DC_FAIL = 0.03           # |mean| > this → FAIL
CORR_IN_PHASE_MIN = 0.5  # below this → flag polarity issue
CORR_ANTI_PHASE_MAX = -0.15  # below this (negative) → anti-phase (real-world: −0.26 seen)
HUM_WARN_DB = 8.0        # hum above this (dB relative to broad band) → WARN
HUM_FAIL_DB = 18.0       # hum above this → FAIL
HUM_FREQS = [50, 100, 150, 200, 60, 120, 180, 240]  # EU 50 Hz then US 60 Hz harmonics
NOTCH_FAIL_DB = -14.0    # per-carrier/band SNR below this → dead (notch)
NOTCH_WARN_DB = -7.0     # below this → warn
HF_ROLLOFF_WARN_DB = -8.0    # HF (> 2/3 of band) vs MF average
HF_ROLLOFF_FAIL_DB = -16.0
FLUTTER_WARN_PCT = 0.8   # WRMS %
FLUTTER_FAIL_PCT = 2.0
SPEED_WARN_PCT = 1.0     # deck speed offset %
SPEED_FAIL_PCT = 3.0


# ════════════════════════════════════════════════════════════════════════════
# Core check functions (all accept ndarray of shape (N,) or (N,C))
# ════════════════════════════════════════════════════════════════════════════

def _to_channels(audio: np.ndarray) -> tuple[np.ndarray, np.ndarray | None]:
    """Return (L, R_or_None) as 1-D float64 arrays."""
    a = np.asarray(audio, dtype=np.float64)
    if a.ndim == 1:
        return a, None
    if a.shape[1] >= 2:
        return a[:, 0], a[:, 1]
    return a[:, 0], None


def _bandpass(x: np.ndarray, f0: float, sr: int, bw: float = 80.0) -> np.ndarray:
    lo = max(20.0, f0 - bw / 2) / (sr / 2)
    hi = min(sr / 2 - 100.0, f0 + bw / 2) / (sr / 2)
    sos = butter(4, [lo, hi], btype="band", output="sos")
    return sosfiltfilt(sos, x)


def _rms(x: np.ndarray) -> float:
    return float(np.sqrt(np.mean(x ** 2)))


def _representative_window(audio: np.ndarray, sr: int, max_sec: float = 60.0,
                            start_frac: float = 0.1) -> np.ndarray:
    """Return a representative window: skip lead-in, cap at max_sec."""
    n = len(audio)
    start = int(start_frac * n)
    end = min(n, start + int(max_sec * sr))
    return audio[start:end]


def _snr_at_freq(x: np.ndarray, f0: float, sr: int, bw: float = 80.0,
                 noise_bw: float = 200.0) -> float:
    """Estimate SNR (dB) at f0: tone power vs local off-tone noise floor."""
    n = len(x)
    if n < sr // 4:
        return 0.0
    win = np.hanning(n)
    sp = np.abs(np.fft.rfft(x * win))
    fax = np.fft.rfftfreq(n, 1.0 / sr)
    # Tone bin
    bl = int(np.searchsorted(fax, f0 - bw / 2))
    bh = int(np.searchsorted(fax, f0 + bw / 2))
    bh = max(bh, bl + 1)
    tone = float(np.max(sp[bl:bh]))
    # Noise: offset above (between tones)
    nl = int(np.searchsorted(fax, f0 + bw))
    nh = int(np.searchsorted(fax, f0 + bw + noise_bw))
    nh = min(nh, len(sp))
    if nh <= nl:
        nl = max(0, bl - max(1, int(np.searchsorted(fax, noise_bw))))
        nh = max(nl + 1, bl)
    noise = float(np.median(sp[nl:nh]) + 1e-12) if nh > nl else 1e-12
    return 20.0 * np.log10(max(tone, 1e-12) / noise)


# ─── 1. Levels / Clipping / DC ───────────────────────────────────────────

def check_levels(audio: np.ndarray, sr: int) -> dict:
    """Return per-channel peak, RMS, DC, clipping info + dc_status."""
    L, R = _to_channels(audio)
    channels = {"L": L} if R is None else {"L": L, "R": R}
    result: dict[str, Any] = {}
    clip_any = False
    quiet_any = False
    dc_max = 0.0

    for ch, x in channels.items():
        peak = float(np.max(np.abs(x)))
        rms = _rms(x)
        dc = float(np.mean(x))
        clipping = peak >= CLIP_THR
        quiet = peak < QUIET_THR and peak > 0
        dbfs = 20.0 * np.log10(peak + 1e-12)
        headroom = -dbfs   # positive = headroom below 0 dBFS

        result[f"peak_{ch}"] = round(peak, 4)
        result[f"rms_{ch}"] = round(rms, 5)
        result[f"dc_{ch}"] = round(dc, 5)
        result[f"dbfs_{ch}"] = round(dbfs, 2)
        result[f"headroom_{ch}"] = round(headroom, 2)
        result[f"clipping_{ch}"] = clipping
        result[f"quiet_{ch}"] = quiet
        if clipping:
            clip_any = True
        if quiet:
            quiet_any = True
        dc_max = max(dc_max, abs(dc))

    result["dc_L"] = result.get("dc_L", 0.0)
    result["clip_any"] = clip_any
    result["quiet_any"] = quiet_any

    if dc_max >= DC_FAIL:
        result["dc_status"] = "FAIL"
    elif dc_max >= DC_WARN:
        result["dc_status"] = "WARN"
    else:
        result["dc_status"] = "PASS"

    if clip_any:
        result["level_status"] = "FAIL"
    elif quiet_any:
        result["level_status"] = "WARN"
    else:
        result["level_status"] = "PASS"

    return result


# ─── 2. L/R Channel Relationship ─────────────────────────────────────────

def check_lr_relationship(audio: np.ndarray, sr: int,
                           window_sec: float = 60.0) -> dict:
    """Measure L/R correlation, polarity, SNR for L / R / L+R / L−R.

    Works on any stereo or mono capture.  For mono returns N/A.
    """
    L, R = _to_channels(audio)
    if R is None:
        return {
            "polarity": "N/A (mono)",
            "corr": None,
            "recommended_combo": "L",
            "snr_db": {"L": None, "R": None, "LpR": None, "LmR": None},
            "status": "PASS",
            "action": None,
        }

    # Use a representative window (skip lead-in, cap duration)
    n = len(L)
    start = int(0.05 * n)
    end = min(n, start + int(window_sec * sr))
    Lw, Rw = L[start:end], R[start:end]

    # Pearson correlation
    Lc = Lw - np.mean(Lw)
    Rc = Rw - np.mean(Rw)
    denom = np.sqrt(np.mean(Lc ** 2) * np.mean(Rc ** 2)) + 1e-12
    corr = float(np.dot(Lc, Rc) / (len(Lc) * denom))

    # Polarity
    if corr > CORR_IN_PHASE_MIN:
        polarity = "in-phase"
    elif corr < CORR_ANTI_PHASE_MAX:
        polarity = "anti-phase"
    else:
        polarity = "uncertain"

    # SNR estimate for each combo at a mid-band frequency (3 kHz)
    # Use bandpass filtered signal vs broadband noise estimate
    combos = {
        "L": Lw,
        "R": Rw,
        "LpR": (Lw + Rw) * 0.5,
        "LmR": (Lw - Rw) * 0.5,
    }
    snr_db: dict[str, float | None] = {}
    for name, sig in combos.items():
        bp = _bandpass(sig, 3000.0, sr, bw=2000.0)  # 2-4 kHz band
        sig_rms = _rms(bp) + 1e-12
        # Noise floor: very low freq (below 200 Hz, mostly noise/hum not signal)
        if sr > 400:
            noise_bp = _bandpass(sig, 100.0, sr, bw=100.0)
            noise_rms = _rms(noise_bp) + 1e-12
            snr_db[name] = round(20.0 * np.log10(sig_rms / noise_rms), 1)
        else:
            snr_db[name] = None

    # Best combo: highest SNR
    valid = {k: v for k, v in snr_db.items() if v is not None}
    if valid:
        best_combo = max(valid, key=lambda k: valid[k])
    else:
        best_combo = "L"

    # Override: if anti-phase, L-R is always better than L+R (signal doubles,
    # correlated noise cancels). Trust polarity over SNR estimator here.
    if polarity == "anti-phase":
        best_combo = "LmR"
    elif polarity == "in-phase":
        # L+R averages the signal; if independent noise: +3 dB SNR
        if valid.get("LpR", -999) >= valid.get("L", -999):
            best_combo = "LpR"
        else:
            best_combo = "L"

    # Status
    if polarity == "anti-phase":
        status = "FAIL"
        action = ("channels ANTI-PHASE (corr %.2f) — decode with L−R, NOT L+R. "
                  "Fix: physically swap one RCA plug, or pass --combo LmR to decoder." % corr)
    elif polarity == "uncertain":
        status = "WARN"
        action = ("low L/R correlation (corr %.2f) — check wiring; "
                  "may indicate bad contact or extreme azimuth mismatch." % corr)
    else:
        status = "PASS"
        action = None

    return {
        "polarity": polarity,
        "corr": round(corr, 3),
        "recommended_combo": best_combo,
        "snr_db": snr_db,
        "status": status,
        "action": action,
    }


# ─── 3. Mains Hum ────────────────────────────────────────────────────────

def check_mains_hum(audio: np.ndarray, sr: int,
                    window_sec: float = 10.0) -> dict:
    """Check for 50 Hz / 60 Hz mains hum and harmonics.

    Works on any capture.  Uses signal-level estimate from a mid-band reference
    window (200–2000 Hz) as the denominator.
    """
    L, R = _to_channels(audio)
    # Average all available channels
    if R is not None:
        mono = (L + R) * 0.5
    else:
        mono = L

    # Representative quiet-ish window
    n = len(mono)
    # Prefer the first 30 s (might be lead-in / silence on diag tape); fall back to middle
    w = min(n, int(window_sec * sr))
    seg = mono[:w]

    # FFT of the whole segment
    N_fft = len(seg)
    win = np.hanning(N_fft)
    sp = np.abs(np.fft.rfft(seg * win))
    fax = np.fft.rfftfreq(N_fft, 1.0 / sr)

    def _bin_rms(f0: float, bw: float = 5.0) -> float:
        bl = int(np.searchsorted(fax, f0 - bw))
        bh = int(np.searchsorted(fax, f0 + bw))
        bh = max(bh, bl + 1)
        return float(np.sqrt(np.mean(sp[bl:bh] ** 2)))

    # Mid-band reference (250–800 Hz) — usually flat background
    ref_bl = int(np.searchsorted(fax, 250.0))
    ref_bh = int(np.searchsorted(fax, 800.0))
    ref_bh = max(ref_bh, ref_bl + 1)
    ref_floor = float(np.median(sp[ref_bl:ref_bh]) + 1e-12)

    detected_freqs: list[int] = []
    hum_results: dict[int, float] = {}

    for f in HUM_FREQS:
        if f >= sr // 2:
            continue
        amp = _bin_rms(float(f))
        db = 20.0 * np.log10(max(amp, 1e-12) / ref_floor)
        hum_results[f] = round(db, 1)
        if db > HUM_WARN_DB:
            detected_freqs.append(f)

    worst_db = max(hum_results.values()) if hum_results else -99.0
    eu_hum = max(hum_results.get(f, -99) for f in [50, 100, 150, 200])
    us_hum = max(hum_results.get(f, -99) for f in [60, 120, 180, 240])

    if worst_db >= HUM_FAIL_DB:
        status = "FAIL"
    elif worst_db >= HUM_WARN_DB:
        status = "WARN"
    else:
        status = "PASS"

    # Action hint
    if status != "PASS":
        source = "50 Hz (EU)" if eu_hum > us_hum else "60 Hz (US/JP)"
        action = (f"ground-loop mains hum at {source} (+{worst_db:.0f} dB) — "
                  "try: laptop on battery, RCA ground-lift isolator, "
                  "deck + interface on same outlet as laptop.")
    else:
        action = None

    return {
        "status": status,
        "worst_hum_db": round(worst_db, 1),
        "hum_db_per_freq": {str(f): v for f, v in hum_results.items()},
        "detected_freqs": detected_freqs,
        "eu_hum_db": round(eu_hum, 1),
        "us_hum_db": round(us_hum, 1),
        "action": action,
    }


# ─── 4. Frequency Response (tone comb) ───────────────────────────────────

def _default_carrier_freqs() -> list:
    """Default carrier grid: MFSK32 tones (400-10 kHz) + DQPSK P10 bins."""
    from hyp_h2_mfsk import MFSKScheme
    m = MFSKScheme(M=32, walsh_k=0)
    mfsk = list(float(f) for f in m.freqs)
    # DQPSK P10, N256, sp4 carriers
    dqpsk = [k * 4 * SR_EXPECTED / 256 for k in range(1, 11)]
    combined = sorted(set(int(f) for f in mfsk + dqpsk))
    return [float(f) for f in combined if 300 < f < 10200]


def check_frequency_response(audio: np.ndarray, sr: int,
                              carrier_freqs_hz: list | None = None,
                              window_sec: float = 10.0,
                              diag_tape_mode: bool = False) -> dict:
    """Per-carrier SNR (or per-band if not diag-tape), notch detection, HF rolloff.

    `carrier_freqs_hz`: explicit list of probe frequencies.  Only used in
    diag-tape mode (where the Schroeder comb guarantees signal at every probe
    freq).  On generic captures, use coarser 1/3-octave bands to avoid flagging
    DQPSK carrier gaps as "notches".

    `diag_tape_mode=True` when the capture is a diag tape (tone comb section
    present) → per-carrier analysis at MFSK32 bins.  Otherwise: per-third-octave.
    """
    if carrier_freqs_hz is not None:
        diag_tape_mode = True   # explicit freq list → treat as diag tape
    elif diag_tape_mode:
        if carrier_freqs_hz is None:
            try:
                carrier_freqs_hz = _default_carrier_freqs()
            except Exception:
                carrier_freqs_hz = [float(f) for f in range(500, 10001, 500)]
    else:
        # Generic capture: use 1/3-octave centres ~500 Hz to 9 kHz
        # (broad enough to avoid carrier-gap false positives)
        carrier_freqs_hz = [
            500, 630, 800, 1000, 1250, 1600, 2000, 2500, 3150,
            4000, 5000, 6300, 8000, 9000,
        ]

    L, R = _to_channels(audio)
    mono = (L + R) * 0.5 if R is not None else L

    n = len(mono)
    start = int(0.05 * n)
    end = min(n, start + int(window_sec * sr))
    seg = mono[start:end]

    freqs = sorted(carrier_freqs_hz)
    # Bandwidth for tone/band probing: narrow for diag-tape (sharp comb tones),
    # wide for generic (covers a 1/3-octave band so inter-carrier gaps don't show)
    probe_bw = 60.0 if diag_tape_mode else 200.0
    noise_bw = 150.0 if diag_tape_mode else 400.0

    # Pre-compute FFT once for the whole segment
    N_seg = len(seg)
    win_fft = np.hanning(N_seg)
    sp_full = np.abs(np.fft.rfft(seg * win_fft))
    fax_full = np.fft.rfftfreq(N_seg, 1.0 / sr)

    def _amp_at(f0: float, bw: float = probe_bw) -> float:
        bl = int(np.searchsorted(fax_full, f0 - bw / 2))
        bh = int(np.searchsorted(fax_full, f0 + bw / 2))
        bh = max(bh, bl + 1)
        return float(np.max(sp_full[bl:bh]))

    snr_per_freq: dict[float, float] = {}
    amp_per_freq: dict[float, float] = {}
    for f in freqs:
        if f <= 0 or f >= sr / 2:
            continue
        snr_per_freq[f] = _snr_at_freq(seg, f, sr, bw=probe_bw, noise_bw=noise_bw)
        amp_per_freq[f] = _amp_at(f)

    if not snr_per_freq:
        return {"status": "PASS", "snr_per_freq": {}, "notch_freqs_hz": [],
                "hf_rolloff_db": 0.0}

    freqs_sorted = sorted(snr_per_freq.keys())
    snr_vals = [snr_per_freq[f] for f in freqs_sorted]

    # Relative normalisation: subtract per-bin median to measure drops
    median_snr = float(np.median(snr_vals))
    rel = {f: snr_per_freq[f] - median_snr for f in freqs_sorted}

    # Notch detection: relative drop below NOTCH_FAIL_DB
    notch_fail = [f for f in freqs_sorted if rel[f] < NOTCH_FAIL_DB]
    notch_warn = [f for f in freqs_sorted
                  if NOTCH_WARN_DB <= rel[f] < NOTCH_FAIL_DB]

    # HF rolloff: use raw amplitude H(f) rather than SNR so it measures the
    # actual frequency response even when the noise floor is uniformly low.
    amp_vals = [amp_per_freq[f] for f in freqs_sorted]
    amp_db = [20.0 * np.log10(a + 1e-12) for a in amp_vals]
    amp_db_arr = np.asarray(amp_db)
    # Normalise to median of the lower two-thirds (the "flat" reference region)
    n_ref = max(1, int(len(freqs_sorted) * 2 / 3))
    ref_db = float(np.median(amp_db_arr[:n_ref]))
    amp_db_norm = amp_db_arr - ref_db

    n_lo = max(1, len(freqs_sorted) // 3)
    n_hi = max(1, len(freqs_sorted) - len(freqs_sorted) // 3)
    lo_amp = float(np.mean(amp_db_norm[:n_lo]))
    hi_amp = float(np.mean(amp_db_norm[n_hi:]))
    hf_rolloff_db = round(hi_amp - lo_amp, 1)

    # Status
    if notch_fail or hf_rolloff_db < HF_ROLLOFF_FAIL_DB:
        status = "FAIL"
    elif notch_warn or hf_rolloff_db < HF_ROLLOFF_WARN_DB:
        status = "WARN"
    else:
        status = "PASS"

    # Build action string
    actions = []
    if notch_fail:
        bands = ", ".join(f"{f/1000:.2g} kHz" for f in notch_fail[:5])
        actions.append(f"dead carriers at {bands} — clean tape head; check azimuth")
    if hf_rolloff_db < HF_ROLLOFF_WARN_DB:
        actions.append(f"HF rolloff {hf_rolloff_db:+.0f} dB — check azimuth alignment "
                       "(rotate head until HF tones recover)")
    action = "; ".join(actions) if actions else None

    return {
        "status": status,
        "snr_per_freq": {str(int(f)): round(v, 1) for f, v in snr_per_freq.items()},
        "rel_snr_per_freq": {str(int(f)): round(rel[f], 1) for f in freqs_sorted},
        "notch_freqs_hz": notch_fail,
        "notch_warn_freqs_hz": notch_warn,
        "hf_rolloff_db": hf_rolloff_db,
        "median_snr_db": round(median_snr, 1),
        "action": action,
    }


# ─── 5. Clock / Flutter ──────────────────────────────────────────────────

def check_clock_flutter(audio: np.ndarray, sr: int,
                         manifest: dict | None = None) -> dict:
    """Estimate deck speed (from chirp pair if manifest provided) and flutter.

    Flutter is measured by complex demodulation of any strong steady tone
    found in the signal (or the diag tape's dedicated flutter-tone section).
    """
    L, R = _to_channels(audio)
    mono = (L + R) * 0.5 if R is not None else L

    result: dict[str, Any] = {}

    # Speed from manifest (diag tape has known chirp spacing)
    if manifest and manifest.get("tx_chirp0") and manifest.get("tx_chirp1"):
        try:
            import analyze_master2 as am2
            sync = am2.global_sync_and_resample(mono.astype(np.float32), manifest)
            result["speed"] = round(sync["speed"], 5)
            result["speed_offset_pct"] = round(sync["speed_offset"] * 100, 3)
            if abs(sync["speed_offset"]) > SPEED_FAIL_PCT / 100:
                result["speed_status"] = "FAIL"
            elif abs(sync["speed_offset"]) > SPEED_WARN_PCT / 100:
                result["speed_status"] = "WARN"
            else:
                result["speed_status"] = "PASS"
        except Exception as e:
            result["speed"] = None
            result["speed_status"] = "SKIP"
            result["speed_note"] = str(e)
    else:
        result["speed"] = None
        result["speed_status"] = "SKIP"
        result["speed_note"] = "no manifest — chirp-based speed not available"

    # Flutter: complex demodulation at a strong STEADY tone.
    # For a diag tape, we use the dedicated flutter-tone section (3000 Hz, 10 s).
    # For a generic data capture, we search for the strongest narrow-band tone;
    # if none is dominant (wideband data signal), we skip — flutter from DQPSK
    # data would give a meaningless >40% reading.
    n = len(mono)
    flutter_pct = None
    flutter_tone_hz = None
    flutter_note = None

    if manifest and manifest.get("flutter_probe"):
        # Diag tape: use the known dedicated flutter-tone section
        fp = manifest["flutter_probe"]
        fs_hz = fp.get("freq_hz", FLUTTER_TONE_HZ)
        seg_start = fp.get("start_frame", 0)
        seg_end = fp.get("end_frame", seg_start + int(10 * sr))
        seg = mono[max(0, seg_start): min(len(mono), seg_end)].astype(np.float64)
        flutter_pct = _measure_flutter(seg, fs_hz, sr)
        flutter_tone_hz = fs_hz
    else:
        # Generic capture: flutter measurement requires a steady sinusoidal tone.
        # DQPSK data carriers look like dominant tones in a long FFT but their
        # instantaneous frequency is modulated by data → measured "flutter" is
        # noise.  Skip with a clear note.
        flutter_note = ("flutter measurement skipped — no dedicated flutter-tone section "
                        "in this capture. Record the DIAG tape and re-run with "
                        "--manifest diag_manifest.json for a valid flutter reading.")

    result["flutter_wrms_pct"] = round(flutter_pct, 3) if flutter_pct is not None else None
    result["flutter_tone_hz"] = flutter_tone_hz
    if flutter_note:
        result["flutter_note"] = flutter_note

    if flutter_pct is None:
        result["flutter_status"] = "SKIP"
    elif flutter_pct > FLUTTER_FAIL_PCT:
        result["flutter_status"] = "FAIL"
    elif flutter_pct > FLUTTER_WARN_PCT:
        result["flutter_status"] = "WARN"
    else:
        result["flutter_status"] = "PASS"

    if result.get("flutter_status") in ("WARN", "FAIL"):
        result["action"] = (f"flutter {flutter_pct:.2f}% WRMS (>{FLUTTER_WARN_PCT}%) — "
                            "check pinch roller / capstan; try demagnetizing the deck")
    else:
        result["action"] = None

    return result


def _find_dominant_tone(seg: np.ndarray, sr: int,
                        f_lo: float = 500.0, f_hi: float = 8000.0
                        ) -> tuple[float | None, float]:
    """Find the most dominant narrow-band tone in `seg` between f_lo and f_hi.

    Returns (freq_hz, dominance_dB) where dominance_dB is how many dB the tone
    peak exceeds the local spectral median.  Returns (None, 0.0) if nothing found.
    """
    n = len(seg)
    if n < sr // 4:
        return None, 0.0
    win = np.hanning(n)
    sp = np.abs(np.fft.rfft(seg * win))
    fax = np.fft.rfftfreq(n, 1.0 / sr)
    lo_bin = int(np.searchsorted(fax, f_lo))
    hi_bin = int(np.searchsorted(fax, f_hi))
    hi_bin = min(hi_bin, len(sp) - 1)
    if hi_bin <= lo_bin:
        return None, 0.0
    sp_band = sp[lo_bin:hi_bin]
    pk_idx = int(np.argmax(sp_band))
    pk_val = float(sp_band[pk_idx])
    # Local median: exclude ±5% of peak freq
    excl = max(1, int(0.05 * len(sp_band)))
    mask = np.ones(len(sp_band), dtype=bool)
    mask[max(0, pk_idx - excl): min(len(sp_band), pk_idx + excl + 1)] = False
    if mask.any():
        local_med = float(np.median(sp_band[mask]))
    else:
        local_med = float(np.median(sp_band))
    if local_med < 1e-12:
        return None, 0.0
    dominance = 20.0 * np.log10(pk_val / local_med)
    tone_freq = float(fax[lo_bin + pk_idx])
    return tone_freq, dominance


def _measure_flutter(seg: np.ndarray, f0: float, sr: int) -> float | None:
    """Measure flutter at f0 via complex demodulation. Returns WRMS %."""
    if len(seg) < sr:
        return None
    t = np.arange(len(seg)) / sr
    bb = seg * np.exp(-1j * 2 * np.pi * f0 * t)
    # Lowpass ~200 Hz
    w = max(1, int(sr / 400))
    kern = np.ones(w) / w
    bb_lp = (np.convolve(bb.real, kern, mode="same")
             + 1j * np.convolve(bb.imag, kern, mode="same"))
    ph = np.unwrap(np.angle(bb_lp))
    inst_f = f0 + np.gradient(ph) * sr / (2 * np.pi)
    m = len(inst_f) // 10
    inst_f = inst_f[m:-m] if len(inst_f) > 2 * m else inst_f
    if inst_f.size < 10:
        return None
    mean_f = float(np.mean(inst_f))
    if mean_f < 100:
        return None
    rel = (inst_f - mean_f) / mean_f
    return float(np.sqrt(np.mean(rel ** 2)) * 100.0)


# ─── 6. Distortion / THD estimate ────────────────────────────────────────

def check_distortion(audio: np.ndarray, sr: int,
                     imd_freqs_hz: tuple = (1000.0, 1500.0, 2500.0),
                     window_sec: float = 5.0,
                     manifest: dict | None = None) -> dict:
    """Estimate THD and IMD from a segment containing known probe tones.

    For IMD, f1=1000, f2=1500 → look for 2f1-f2=500 Hz and 2f2-f1=2000 Hz products.

    On a generic (non-diag) data capture, the probe tones are not present and the
    measurement would be meaningless.  In that case, we check whether the probe
    frequencies are dominant in the spectrum; if not, we return SKIP with a note.
    """
    L, R = _to_channels(audio)
    mono = (L + R) * 0.5 if R is not None else L

    # If manifest present, use dedicated IMD probe window
    if manifest and manifest.get("imd_probe"):
        ip = manifest["imd_probe"]
        seg_start = ip.get("start_frame", 0)
        seg_end = ip.get("end_frame", seg_start + int(window_sec * sr))
        seg = mono[max(0, seg_start): min(len(mono), seg_end)].astype(np.float64)
        imd_freqs_hz = tuple(ip.get("freqs_hz", imd_freqs_hz))
    else:
        n = len(mono)
        start = int(0.05 * n)
        end = min(n, start + int(window_sec * sr))
        seg = mono[start:end].astype(np.float64)

    N_fft = len(seg)
    if N_fft < sr // 8:
        return {"status": "SKIP", "thd_pct": None, "imd_dbr": None,
                "note": "segment too short"}

    win = np.hanning(N_fft)
    sp = np.abs(np.fft.rfft(seg * win))
    fax = np.fft.rfftfreq(N_fft, 1.0 / sr)

    def _bin(f: float, bw: float = 40.0) -> float:
        bl = int(np.searchsorted(fax, f - bw))
        bh = int(np.searchsorted(fax, f + bw))
        bh = max(bh, bl + 1)
        return float(np.max(sp[bl:bh]))

    f1 = imd_freqs_hz[0]
    f2 = imd_freqs_hz[1] if len(imd_freqs_hz) > 1 else imd_freqs_hz[0]
    fund_f1 = _bin(f1)
    fund_f2 = _bin(f2)
    fund = max(fund_f1, fund_f2, 1e-12)

    # Guard: THD/IMD requires a known-level multi-tone probe section.
    # On a generic capture (no manifest/imd_probe), the broadband DQPSK data
    # makes harmonic products indistinguishable from data carriers → skip.
    if manifest is None or "imd_probe" not in manifest:
        return {
            "status": "SKIP",
            "thd_pct": None,
            "imd_dbr": None,
            "action": None,
            "note": ("THD/IMD measurement skipped — no dedicated IMD probe section "
                     "in this capture. Record the DIAG tape and re-run with --manifest "
                     "diag_manifest.json for a valid distortion measurement."),
        }

    # THD at f1: harmonics 2f, 3f
    h2 = _bin(2 * f1)
    h3 = _bin(3 * f1)
    thd_pct = 100.0 * np.sqrt(h2 ** 2 + h3 ** 2) / fund

    # IMD: 2nd-order products f2-f1, 2nd-order IM = 2f1-f2, 2f2-f1
    imd_prod = max(_bin(abs(f2 - f1)), _bin(abs(2 * f1 - f2)), _bin(abs(2 * f2 - f1)))
    imd_dbr = 20.0 * np.log10(imd_prod / fund + 1e-12)

    if thd_pct > 10.0 or imd_dbr > -10.0:
        status = "FAIL"
        action = ("high distortion (THD %.1f%%, IMD %.0f dBr) — "
                  "lower record level (SOP: ~7.0, not 8.5); "
                  "8.5 saturates tape → IMD blooms and kills dense carriers." % (thd_pct, imd_dbr))
    elif thd_pct > 5.0 or imd_dbr > -20.0:
        status = "WARN"
        action = "borderline distortion — consider lowering record level by 0.5–1.0 notch"
    else:
        status = "PASS"
        action = None

    return {
        "status": status,
        "thd_pct": round(thd_pct, 2),
        "imd_dbr": round(imd_dbr, 1),
        "action": action,
        "note": ("THD/IMD estimates from the dedicated IMD probe section; "
                 "use the diag tape for the most reliable numbers."),
    }


# ─── 7. Decodability (diag-tape mode, modems from make_master2.py) ────────

def _decode_diag_sections(audio_nom: np.ndarray, manifest: dict,
                           sr: int) -> dict | None:
    """Decode the data sections from a diag-tape capture.

    Returns a dict with per-config results, or None if not a diag tape.
    """
    if not manifest or "sections" not in manifest:
        return None
    try:
        import modems_index, modems_ofdm
        MODEM_MAP = {
            "mfsk32": modems_index,
            "c1_gray_m16": modems_index,
            "c4_bpsk": modems_ofdm,
            "c4_qpsk": modems_ofdm,
        }
    except ImportError:
        return None

    try:
        import analyze_master2 as am2
        sync = am2.global_sync_and_resample(audio_nom.astype(np.float32), manifest)
        audio_nom = sync["audio_nominal"]
        align = sync["chirp0_nominal"] - int(manifest.get("tx_chirp0", 0))
    except Exception:
        align = 0

    results: dict[str, dict] = {}
    for sec in manifest.get("sections", []):
        cfg = sec.get("config")
        mod = MODEM_MAP.get(cfg)
        if mod is None:
            continue
        scar_path = TAPE_V2 / sec["payload_sidecar"]
        if not scar_path.exists():
            continue
        expected = scar_path.read_bytes()
        start = sec["start_sample"] + align
        length = sec["length"]
        pad = int(0.5 * sr)
        w_lo = max(0, start - pad)
        w_hi = min(len(audio_nom), start + length + pad)
        window = audio_nom[w_lo:w_hi].astype(np.float32)
        try:
            rx = mod.demodulate(window, cfg)
            ok = (rx == expected)
        except Exception:
            ok = False
        d = results.setdefault(cfg, {"reps": 0, "passes": 0})
        d["reps"] += 1
        if ok:
            d["passes"] += 1

    for cfg, d in results.items():
        d["passrate"] = d["passes"] / d["reps"] if d["reps"] else 0.0
        d["status"] = ("PASS" if d["passrate"] >= 0.9 else
                       "WARN" if d["passrate"] >= 0.5 else "FAIL")
    return results


# ════════════════════════════════════════════════════════════════════════════
# Report card assembly
# ════════════════════════════════════════════════════════════════════════════

def build_report_card(audio: np.ndarray, sr: int,
                      capture_name: str = "",
                      manifest: dict | None = None,
                      carrier_freqs_hz: list | None = None) -> dict:
    """Run all checks and return a structured report card dict."""
    report: dict[str, Any] = {
        "version": VERSION,
        "capture": capture_name,
        "timestamp": datetime.datetime.now().isoformat(timespec="seconds"),
        "duration_s": round(len(audio) / sr, 2),
        "sr": sr,
        "channels": 2 if (np.asarray(audio).ndim > 1 and np.asarray(audio).shape[1] >= 2)
                    else 1,
    }

    report["levels"] = check_levels(audio, sr)
    report["lr"] = check_lr_relationship(audio, sr)
    report["hum"] = check_mains_hum(audio, sr)
    is_diag = bool(manifest and manifest.get("tone_comb"))
    report["frequency"] = check_frequency_response(
        audio, sr, carrier_freqs_hz, diag_tape_mode=is_diag)
    report["clock"] = check_clock_flutter(audio, sr, manifest)
    report["distortion"] = check_distortion(audio, sr, manifest=manifest)

    # Decodability (diag tape mode)
    if manifest and "sections" in manifest:
        L, R = _to_channels(np.asarray(audio, dtype=np.float32))
        mono = (L + R) * 0.5 if R is not None else L
        report["decodability"] = _decode_diag_sections(mono, manifest, sr)
    else:
        report["decodability"] = None

    # Overall status
    dim_statuses = [
        report["levels"]["level_status"],
        report["levels"]["dc_status"],
        report["lr"]["status"],
        report["hum"]["status"],
        report["frequency"]["status"],
        report["clock"].get("flutter_status", "SKIP"),
        report["clock"].get("speed_status", "SKIP"),
        report["distortion"]["status"],
    ]
    if "FAIL" in dim_statuses:
        overall = "FAIL"
    elif "WARN" in dim_statuses:
        overall = "WARN"
    else:
        overall = "PASS"
    report["overall"] = overall

    # Collect faults
    faults: list[str] = []
    if report["lr"]["action"]:
        faults.append("CRITICAL: " + report["lr"]["action"])
    if report["hum"]["action"]:
        faults.append("CRITICAL: " + report["hum"]["action"])
    if report["frequency"]["action"]:
        faults.append("WARN: " + report["frequency"]["action"])
    if report["distortion"]["action"]:
        faults.append("WARN: " + report["distortion"]["action"])
    if report["clock"].get("action"):
        faults.append("WARN: " + report["clock"]["action"])
    if report["levels"]["clip_any"]:
        faults.append("CRITICAL: clipping detected — lower record level")
    if report["levels"].get("dc_status") in ("WARN", "FAIL"):
        faults.append("WARN: DC offset detected — check DC-coupling on interface")

    # Recommended combo
    combo = report["lr"]["recommended_combo"]
    combo_label = {
        "L": "left channel only", "R": "right channel only",
        "LpR": "L+R (average)", "LmR": "L−R (difference)",
    }.get(combo, combo)

    lines = [
        f"OVERALL: {overall}",
        f"Recommended channel combo: {combo_label}",
    ]
    if faults:
        lines.append("")
        lines.append("Faults:")
        for f in faults:
            lines.append(f"  • {f}")
    if not faults:
        lines.append("No faults detected — setup looks clean.")

    report["summary_text"] = "\n".join(lines)
    report["faults"] = faults
    return report


# ════════════════════════════════════════════════════════════════════════════
# Pretty-print
# ════════════════════════════════════════════════════════════════════════════

def _status_icon(s: str) -> str:
    return {"PASS": "[PASS]", "WARN": "[WARN]", "FAIL": "[FAIL]",
            "SKIP": "[SKIP]", "N/A": "[N/A ]"}.get(s, f"[{s[:4]:4}]")


def print_report_card(report: dict) -> None:
    W = 64
    print("=" * W)
    print("  CASSETTE-AI SETUP REPORT CARD  " + report.get("version", ""))
    print(f"  Capture : {report.get('capture', '')}")
    print(f"  Duration: {report.get('duration_s', '?')} s  |  "
          f"{report.get('channels', '?')} ch  |  {report.get('sr', '?')} Hz")
    print(f"  Time    : {report.get('timestamp', '')}")
    print("=" * W)

    # --- Levels ---
    lv = report.get("levels", {})
    print("\nLEVELS / CLIPPING / DC")
    for ch in ("L", "R"):
        pk = lv.get(f"peak_{ch}")
        if pk is None:
            continue
        dbfs = lv.get(f"dbfs_{ch}", 0)
        clip = lv.get(f"clipping_{ch}", False)
        dc = lv.get(f"dc_{ch}", 0)
        tag = "CLIP!" if clip else "ok"
        print(f"  {ch}: peak {pk:.3f} ({dbfs:+.1f} dBFS)  dc {dc:+.4f}  [{tag}]")
    print(f"  Level status : {_status_icon(lv.get('level_status','?'))} "
          f"  DC status: {_status_icon(lv.get('dc_status','?'))}")

    # --- L/R Relationship ---
    lr = report.get("lr", {})
    print("\nL/R CHANNEL RELATIONSHIP")
    if lr.get("polarity") == "N/A (mono)":
        print("  Mono capture — L/R check not applicable.")
    else:
        corr = lr.get("corr")
        pol = lr.get("polarity", "?")
        print(f"  Correlation : {corr:+.3f}   Polarity: {pol}")
        snr = lr.get("snr_db", {})
        for k in ("L", "R", "LpR", "LmR"):
            v = snr.get(k)
            marker = " <-- RECOMMENDED" if k == lr.get("recommended_combo") else ""
            print(f"    SNR({k:<3}) : {v:+.1f} dB{marker}" if v is not None
                  else f"    SNR({k:<3}) : N/A")
        print(f"  {_status_icon(lr.get('status', '?'))}  "
              f"Recommended combo: {lr.get('recommended_combo', '?')}")
        if lr.get("action"):
            print(f"  ACTION: {lr['action']}")

    # --- Mains Hum ---
    hm = report.get("hum", {})
    print("\nMAINS HUM (50/60 Hz)")
    dets = hm.get("detected_freqs", [])
    per = hm.get("hum_db_per_freq", {})
    shown = {50, 100, 150, 60, 120}
    for f in sorted(shown):
        db = per.get(str(f))
        if db is not None:
            flag = " <-- DETECTED" if f in dets else ""
            print(f"  {f:3d} Hz: {db:+.1f} dB{flag}")
    print(f"  {_status_icon(hm.get('status', '?'))}  "
          f"Worst: {hm.get('worst_hum_db', '?'):+.1f} dB")
    if hm.get("action"):
        print(f"  ACTION: {hm['action']}")

    # --- Frequency Response ---
    fr = report.get("frequency", {})
    print("\nFREQUENCY RESPONSE (carrier SNR)")
    snr_map = fr.get("snr_per_freq", {})
    rel_map = fr.get("rel_snr_per_freq", {})
    notch_fail = set(str(int(f)) for f in fr.get("notch_freqs_hz", []))
    notch_warn = set(str(int(f)) for f in fr.get("notch_warn_freqs_hz", []))
    # Show a summary (every ~1 kHz or flagged)
    shown_freqs = sorted(int(k) for k in snr_map)
    # Show flagged + ~6 representative points
    representative = shown_freqs[::max(1, len(shown_freqs) // 8)]
    to_show = sorted(set(representative)
                     | set(int(f) for f in fr.get("notch_freqs_hz", []))
                     | set(int(f) for f in fr.get("notch_warn_freqs_hz", [])))
    for f in to_show:
        fs = str(f)
        snr = snr_map.get(fs, "?")
        rel = rel_map.get(fs, "?")
        flag = ""
        if fs in notch_fail:
            flag = " <-- DEAD CARRIER"
        elif fs in notch_warn:
            flag = " <-- weak"
        if snr != "?":
            print(f"  {f:5d} Hz: abs {snr:+.1f} dB  rel {rel:+.1f} dB{flag}")
    print(f"  HF rolloff (hi vs lo band): {fr.get('hf_rolloff_db', '?'):+.1f} dB  "
          f"Median SNR: {fr.get('median_snr_db', '?')} dB")
    print(f"  {_status_icon(fr.get('status', '?'))}")
    if fr.get("action"):
        print(f"  ACTION: {fr['action']}")

    # --- Clock / Flutter ---
    ck = report.get("clock", {})
    print("\nCLOCK / FLUTTER")
    spd = ck.get("speed")
    spd_str = f"{spd:.5f}x  ({ck.get('speed_offset_pct', '?'):+.3f}%)" if spd else "N/A"
    print(f"  Deck speed : {spd_str}  {_status_icon(ck.get('speed_status', 'SKIP'))}")
    flutter = ck.get("flutter_wrms_pct")
    flutter_str = f"{flutter:.3f}% WRMS" if flutter is not None else "N/A"
    print(f"  Flutter    : {flutter_str}  {_status_icon(ck.get('flutter_status', 'SKIP'))}")
    if ck.get("action"):
        print(f"  ACTION: {ck['action']}")

    # --- Distortion ---
    dt = report.get("distortion", {})
    print("\nDISTORTION / RECORD LEVEL")
    thd = dt.get("thd_pct")
    imd = dt.get("imd_dbr")
    thd_s = f"{thd:.1f}%" if thd is not None else "N/A"
    imd_s = f"{imd:.0f} dBr" if imd is not None else "N/A"
    print(f"  THD        : {thd_s}   IMD: {imd_s}   "
          f"{_status_icon(dt.get('status', '?'))}")
    if dt.get("action"):
        print(f"  ACTION: {dt['action']}")

    # --- Decodability ---
    dc = report.get("decodability")
    if dc:
        print("\nDECODABILITY (diag tape sections)")
        for cfg, d in dc.items():
            rate = d.get("passrate", 0)
            print(f"  {cfg:<16}: {d['passes']}/{d['reps']} "
                  f"({rate*100:.0f}%)  {_status_icon(d.get('status','?'))}")
    else:
        print("\nDECODABILITY: N/A (not a diag-tape capture)")
        print("  Run make_diag_master.py -> record -> analyze_diag.py for BER projection.")

    # --- Overall ---
    print()
    print("=" * W)
    print(f"  OVERALL VERDICT: {_status_icon(report['overall'])} {report['overall']}")
    print(f"  Recommended combo: {lr.get('recommended_combo', 'L')}")
    faults = report.get("faults", [])
    if faults:
        print()
        for f in faults:
            print(f"  • {f}")
    else:
        print("  No faults — setup looks clean.")
    print("=" * W)


# ════════════════════════════════════════════════════════════════════════════
# CLI entry point
# ════════════════════════════════════════════════════════════════════════════

def main() -> None:
    ap = argparse.ArgumentParser(
        description="Cassette-AI Setup Report Card — analyze any stereo capture.")
    ap.add_argument("capture", help="path to the WAV to analyze")
    ap.add_argument("--manifest", default=None,
                    help="diag_manifest.json for precise probe-window analysis")
    ap.add_argument("--window", type=float, default=60.0,
                    help="seconds of audio to use for universal checks (default 60)")
    ap.add_argument("--out-json", default=None,
                    help="write report card JSON to this file/directory")
    ap.add_argument("--carrier-freqs", default=None,
                    help="comma-separated carrier freqs in Hz (default: MFSK32+DQPSK grid)")
    args = ap.parse_args()

    capture_path = pathlib.Path(args.capture)
    audio, sr = sf.read(str(capture_path), dtype="float32", always_2d=True)
    print(f"[analyze_diag] {capture_path.name}  {sr} Hz  "
          f"{audio.shape[1]} ch  {len(audio)/sr:.1f} s")

    manifest = None
    if args.manifest:
        manifest = json.loads(pathlib.Path(args.manifest).read_text())

    carrier_freqs = None
    if args.carrier_freqs:
        carrier_freqs = [float(f) for f in args.carrier_freqs.split(",")]

    report = build_report_card(
        audio, sr,
        capture_name=capture_path.name,
        manifest=manifest,
        carrier_freqs_hz=carrier_freqs,
    )

    print_report_card(report)

    # Write JSON
    if args.out_json:
        out = pathlib.Path(args.out_json)
        if out.is_dir():
            out = out / f"diag_{capture_path.stem}_{report['timestamp'].replace(':', '')}.json"
        out.write_text(json.dumps(report, indent=2))
        print(f"\n[analyze_diag] JSON report → {out}")


if __name__ == "__main__":
    main()
