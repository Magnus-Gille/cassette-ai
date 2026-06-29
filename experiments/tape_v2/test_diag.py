"""test_diag.py -- Test-first suite for make_diag_master.py + analyze_diag.py.

Run:  python3 -m pytest experiments/tape_v2/test_diag.py -v
"""
from __future__ import annotations

import json
import pathlib
import sys
import numpy as np
import pytest

ROOT = pathlib.Path("/Users/magnus/repos/cassette-ai")
TAPE_V2 = ROOT / "experiments" / "tape_v2"
for _p in (ROOT / "src", ROOT / "tests" / "e2e", TAPE_V2):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

SR = 48_000


# ---------------------------------------------------------------------------
# Import (may fail until implemented — that's the RED step)
# ---------------------------------------------------------------------------
def _import_analyze():
    import analyze_diag as ad
    return ad


# ===========================================================================
# 1. L/R correlation and combo selection
# ===========================================================================
def _stereo(sig_L: np.ndarray, sig_R: np.ndarray) -> np.ndarray:
    return np.column_stack([sig_L, sig_R]).astype(np.float32)


def _sine(freq: float, dur: float, amp: float = 0.5) -> np.ndarray:
    n = int(dur * SR)
    t = np.arange(n) / SR
    return (amp * np.sin(2 * np.pi * freq * t)).astype(np.float32)


def test_lr_in_phase_recommends_LplusR():
    """Correlated (in-phase) stereo → combo L+R recommended, corr ≈ +1."""
    ad = _import_analyze()
    sig = _sine(1000.0, 2.0)
    audio = _stereo(sig, sig)
    r = ad.check_lr_relationship(audio, SR)
    assert r["corr"] > 0.9, f"expected corr near +1, got {r['corr']:.3f}"
    assert r["recommended_combo"] in ("L", "R", "LpR"), \
        f"expected L/R/L+R for in-phase, got {r['recommended_combo']}"
    assert r["polarity"] == "in-phase"


def test_lr_anti_phase_recommends_LmR():
    """Anti-phase stereo (R = −L) → combo L−R recommended, corr ≈ −1."""
    ad = _import_analyze()
    sig = _sine(1000.0, 2.0)
    audio = _stereo(sig, -sig)
    r = ad.check_lr_relationship(audio, SR)
    assert r["corr"] < -0.8, f"expected corr near −1, got {r['corr']:.3f}"
    assert r["recommended_combo"] == "LmR", \
        f"expected L−R for anti-phase, got {r['recommended_combo']}"
    assert r["polarity"] == "anti-phase"


def test_lr_mono_sets_NA():
    """Mono (1-channel) audio → L/R check returns N/A."""
    ad = _import_analyze()
    sig = _sine(1000.0, 2.0, amp=0.5)
    audio = sig.reshape(-1, 1)        # shape (N,1)
    r = ad.check_lr_relationship(audio, SR)
    assert r["polarity"] == "N/A (mono)"
    assert r["recommended_combo"] == "L"   # single channel → just use L


def test_lr_snr_LmR_beats_LpR_for_antiphase():
    """For anti-phase input, SNR(L−R) > SNR(L+R) by a large margin."""
    ad = _import_analyze()
    noise = np.random.default_rng(42).standard_normal(SR * 2).astype(np.float32) * 0.02
    sig = _sine(3000.0, 2.0, amp=0.5)
    # Anti-phase: L=sig+noise_L, R=−sig+noise_R (independent noise)
    noise2 = np.random.default_rng(99).standard_normal(SR * 2).astype(np.float32) * 0.02
    audio = _stereo(sig + noise, -sig + noise2)
    r = ad.check_lr_relationship(audio, SR)
    assert r["snr_db"]["LmR"] > r["snr_db"]["LpR"] + 10, \
        f"SNR(L-R)={r['snr_db']['LmR']:.1f} not > SNR(L+R)={r['snr_db']['LpR']:.1f}+10"


# ===========================================================================
# 2. Mains hum detection
# ===========================================================================
def _make_hum(freq_hz: float, hum_amp: float, sig_amp: float, dur: float) -> np.ndarray:
    n = int(dur * SR)
    t = np.arange(n) / SR
    signal = sig_amp * np.sin(2 * np.pi * 2000.0 * t)   # 2 kHz carrier (not a hum freq)
    hum = hum_amp * np.sin(2 * np.pi * freq_hz * t)
    return (signal + hum).astype(np.float32)


def test_hum_50hz_detected():
    """50 Hz hum at +20 dB above the 2 kHz reference → FAIL status."""
    ad = _import_analyze()
    # hum_amp = 10x signal → +20 dBc relative to carrier band noise
    audio = _make_hum(50.0, hum_amp=0.3, sig_amp=0.03, dur=3.0)
    r = ad.check_mains_hum(audio.reshape(-1, 1), SR)
    assert r["worst_hum_db"] > 10.0, \
        f"expected >10 dB hum at 50 Hz, got {r['worst_hum_db']:.1f}"
    assert r["status"] in ("WARN", "FAIL"), f"expected WARN/FAIL, got {r['status']}"
    assert 50 in r["detected_freqs"] or any(abs(f - 50) < 5 for f in r["detected_freqs"])


def test_hum_60hz_detected():
    """60 Hz hum at +15 dB → WARN status."""
    ad = _import_analyze()
    audio = _make_hum(60.0, hum_amp=0.18, sig_amp=0.03, dur=3.0)
    r = ad.check_mains_hum(audio.reshape(-1, 1), SR)
    assert r["worst_hum_db"] > 8.0, \
        f"expected >8 dB hum at 60 Hz, got {r['worst_hum_db']:.1f}"
    assert r["status"] in ("WARN", "FAIL")


def test_no_hum_passes():
    """Clean signal with no mains hum → PASS status."""
    ad = _import_analyze()
    rng = np.random.default_rng(7)
    noise = rng.standard_normal(SR * 3).astype(np.float32) * 0.01
    # Add a wideband carrier above 400 Hz (no DC, no 50/60 Hz)
    t = np.arange(SR * 3) / SR
    carrier = 0.4 * np.sin(2 * np.pi * 2000 * t).astype(np.float32)
    audio = (carrier + noise).reshape(-1, 1)
    r = ad.check_mains_hum(audio, SR)
    assert r["status"] == "PASS", f"expected PASS for clean signal, got {r['status']}"


# ===========================================================================
# 3. Notch / HF rolloff detection
# ===========================================================================
def _tone_comb_with_notch(freqs: list, notch_freqs: list, dur: float) -> np.ndarray:
    """Schroeder multitone at `freqs`, zeroing out `notch_freqs`."""
    n = int(dur * SR)
    t = np.arange(n) / SR
    active = [f for f in freqs if not any(abs(f - nf) < 100 for nf in notch_freqs)]
    K = len(active)
    x = np.zeros(n)
    for k, f in enumerate(active):
        ph = np.pi * k * (k + 1) / K
        x += np.sin(2 * np.pi * f * t + ph)
    x /= (np.max(np.abs(x)) + 1e-9)
    return (0.5 * x).astype(np.float32)


def test_notch_detected_at_4300hz():
    """Tone comb with zero amplitude at 4.1–4.5 kHz → notch flagged at ~4.3 kHz."""
    ad = _import_analyze()
    # Use MFSK32-like carrier set
    freqs = list(np.linspace(1100, 9000, 32))
    audio_with_notch = _tone_comb_with_notch(freqs, notch_freqs=[4100, 4300, 4500], dur=3.0)
    audio = audio_with_notch.reshape(-1, 1)
    r = ad.check_frequency_response(audio, SR, carrier_freqs_hz=freqs)
    notch_freqs_found = r.get("notch_freqs_hz", [])
    # At least one carrier near 4.3 kHz should be flagged
    assert any(3800 < f < 5000 for f in notch_freqs_found), \
        f"expected notch near 4.3 kHz, got {notch_freqs_found}"
    assert r["status"] in ("WARN", "FAIL")


def test_hf_rolloff_detected():
    """Audio with steep HF rolloff above 6 kHz → flagged."""
    ad = _import_analyze()
    freqs = list(np.linspace(1100, 9000, 32))
    # Build comb with HF carriers at −15 dB
    n = int(3.0 * SR)
    t = np.arange(n) / SR
    K = len(freqs)
    x = np.zeros(n)
    for k, f in enumerate(freqs):
        ph = np.pi * k * (k + 1) / K
        amp = 0.05 if f > 6000 else 0.5    # HF 20 dB below MF
        x += amp * np.sin(2 * np.pi * f * t + ph)
    x /= (np.max(np.abs(x)) + 1e-9)
    audio = (0.5 * x).astype(np.float32).reshape(-1, 1)
    r = ad.check_frequency_response(audio, SR, carrier_freqs_hz=freqs)
    assert r.get("hf_rolloff_db", 0) < -10, \
        f"expected >10 dB HF rolloff, got {r.get('hf_rolloff_db', 0):.1f}"


def test_flat_response_passes():
    """Flat response across 1.1–9 kHz → PASS."""
    ad = _import_analyze()
    freqs = list(np.linspace(1100, 9000, 32))
    n = int(3.0 * SR)
    t = np.arange(n) / SR
    K = len(freqs)
    x = np.zeros(n)
    for k, f in enumerate(freqs):
        ph = np.pi * k * (k + 1) / K
        x += np.sin(2 * np.pi * f * t + ph)
    x /= (np.max(np.abs(x)) + 1e-9)
    audio = (0.4 * x).astype(np.float32).reshape(-1, 1)
    r = ad.check_frequency_response(audio, SR, carrier_freqs_hz=freqs)
    assert r["status"] == "PASS", f"expected PASS for flat response, got {r['status']}"


# ===========================================================================
# 4. DC offset
# ===========================================================================
def test_dc_offset_detected():
    ad = _import_analyze()
    n = int(1.0 * SR)
    noise = np.random.default_rng(0).standard_normal(n).astype(np.float32) * 0.05
    dc_audio = (noise + 0.05).reshape(-1, 1)   # +5% DC
    r = ad.check_levels(dc_audio, SR)
    assert abs(r["dc_L"]) > 0.03, f"expected DC > 0.03, got {r['dc_L']:.4f}"
    assert r["dc_status"] in ("WARN", "FAIL")


def test_no_dc_passes():
    ad = _import_analyze()
    n = int(1.0 * SR)
    t = np.arange(n) / SR
    audio = (0.4 * np.sin(2 * np.pi * 1000 * t)).astype(np.float32).reshape(-1, 1)
    r = ad.check_levels(audio, SR)
    assert r["dc_status"] == "PASS"


# ===========================================================================
# 5. Report card integration (smoke test)
# ===========================================================================
def test_report_card_anti_phase_surfaces_LmR():
    """End-to-end: anti-phase stereo → report card mentions L-R."""
    ad = _import_analyze()
    sig = _sine(3000.0, 5.0, amp=0.4)
    noise = (np.random.default_rng(1).standard_normal(len(sig)) * 0.02).astype(np.float32)
    audio = _stereo(sig + noise, -(sig + noise))
    report = ad.build_report_card(audio, SR, capture_name="test_anti_phase")
    text = report["summary_text"]
    assert "L-R" in text or "L−R" in text or "LmR" in text, \
        f"expected L-R mention in report, got:\n{text}"
    assert report["lr"]["polarity"] == "anti-phase"


# ===========================================================================
# 6. Manifest generation smoke test
# ===========================================================================
def test_manifest_keys():
    """make_diag_master.build_manifest() returns required keys."""
    import make_diag_master as mdm
    m = mdm.build_manifest_template()
    for k in ("version", "SR", "tx_chirp0", "tx_chirp1",
              "probe_L", "probe_R", "hum_probe", "flutter_probe",
              "tone_comb", "imd_probe", "sections"):
        assert k in m, f"manifest missing key: {k}"


