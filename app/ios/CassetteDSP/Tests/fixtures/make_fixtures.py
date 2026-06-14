#!/usr/bin/env python3
"""make_fixtures.py — Generate golden test fixtures for CassetteDSP XCTests.

Fixtures produced (all under the same directory as this script):
  chirp_fixture.wav      — global up-chirp embedded at a known offset in noise.
  sounder_fixture.wav    — Schroeder multitone + silence sections at known SNR.
  clip_fixture.wav       — clipped sine wave.
  expected.json          — ground-truth values for all fixture assertions.

Run from the repo root or from this directory:
  python3 app/ios/CassetteDSP/Tests/fixtures/make_fixtures.py

Requirements: numpy, scipy, soundfile (pip install numpy scipy soundfile).
"""
from __future__ import annotations

import json
import math
import pathlib
import sys

import numpy as np
import soundfile as sf
from scipy.signal import chirp as scipy_chirp

# ---------------------------------------------------------------------------
# Path bootstrap — give access to repo DSP modules.
# ---------------------------------------------------------------------------
_FIXTURES_DIR = pathlib.Path(__file__).resolve().parent
_REPO_ROOT    = _FIXTURES_DIR.parents[4]   # cassette-ai/
for _p in [str(_REPO_ROOT / "src"),
           str(_REPO_ROOT / "experiments" / "tape_v2")]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

SR = 48_000

# ---------------------------------------------------------------------------
# Chirp parameters — MUST match make_master2.py / analyze_master2.py.
# ---------------------------------------------------------------------------
CHIRP_F0   = 500.0
CHIRP_F1   = 5_000.0
CHIRP_T    = 0.20   # seconds
CHIRP_AMP  = 0.70

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_global_chirp(up: bool = True, sr: int = SR) -> np.ndarray:
    """Replicate make_master2.py::_make_global_chirp exactly."""
    n = int(CHIRP_T * sr)
    t = np.arange(n, dtype=np.float64) / sr
    f0, f1 = (CHIRP_F0, CHIRP_F1) if up else (CHIRP_F1, CHIRP_F0)
    sig = scipy_chirp(t, f0=f0, f1=f1, t1=CHIRP_T, method="linear")
    fade = int(0.01 * sr)
    sig[:fade]  *= np.linspace(0, 1, fade)
    sig[-fade:] *= np.linspace(1, 0, fade)
    return (CHIRP_AMP * sig).astype(np.float32)


def _schroeder_multitone(freqs: list[int], dur: float, amp: float,
                          sr: int = SR) -> np.ndarray:
    """Replicate make_master2.py::_schroeder_multitone exactly."""
    n = int(dur * sr)
    t = np.arange(n) / sr
    K = len(freqs)
    x = np.zeros(n)
    for k, f in enumerate(freqs):
        ph = np.pi * k * (k + 1) / K
        x += np.sin(2 * np.pi * f * t + ph)
    x /= np.max(np.abs(x)) + 1e-9
    fade = int(0.02 * sr)
    x[:fade]  *= np.linspace(0, 1, fade)
    x[-fade:] *= np.linspace(1, 0, fade)
    return (amp * x).astype(np.float32)


def _tone_freqs() -> list[int]:
    return np.round(np.geomspace(300, 11000, 64)).astype(int).tolist()


# ---------------------------------------------------------------------------
# (a) Chirp fixture
# ---------------------------------------------------------------------------

def make_chirp_fixture(rng: np.random.Generator,
                       output_path: pathlib.Path) -> dict:
    """Embed an up-chirp at a known sample offset in white noise."""
    lead_silence_s = 2.0   # 2 s of pre-roll noise before the chirp
    tail_silence_s = 1.0

    chirp = _make_global_chirp(up=True)
    chirp_n = len(chirp)
    lead_n = int(lead_silence_s * SR)
    tail_n = int(tail_silence_s * SR)
    total  = lead_n + chirp_n + tail_n

    # White noise at -30 dBFS (SNR ~20 dB relative to chirp 0.70 amp)
    noise_amp = 10 ** (-30.0 / 20.0)
    audio = rng.standard_normal(total).astype(np.float32) * noise_amp

    # Embed chirp.
    chirp_start = lead_n
    audio[chirp_start: chirp_start + chirp_n] += chirp

    # Write 16-bit WAV (small).
    sf.write(str(output_path), audio, SR, subtype="PCM_16")

    snr_db = 20 * np.log10(CHIRP_AMP / noise_amp)
    print(f"  chirp_fixture: offset={chirp_start}, chirp_n={chirp_n}, "
          f"total={total}, SNR~{snr_db:.1f} dB")

    return {
        "chirp_offset_samples": int(chirp_start),
        "chirp_n_samples":      int(chirp_n),
        "total_samples":        int(total),
        "sample_rate":          SR,
        "noise_amp":            float(noise_amp),
        "expected_snr_db":      float(snr_db),
        # Tolerance for Swift assertion: ±64 samples.
        "tolerance_samples":    64,
    }


# ---------------------------------------------------------------------------
# (b) Sounder fixture
# ---------------------------------------------------------------------------

def _compute_python_snr(segment: np.ndarray, freqs: list[int],
                         sr: int = SR) -> list[float]:
    """Replicate analyze_master2.py::analyze_sounder SNR computation exactly."""
    n = len(segment)
    win = np.hanning(n)
    sp = np.abs(np.fft.rfft(segment * win))
    fax = np.fft.rfftfreq(n, 1.0 / sr)
    snr_db = []
    for f in freqs:
        bl = np.searchsorted(fax, f - 30)
        bh = max(np.searchsorted(fax, f + 30), bl + 1)
        tone = float(np.max(sp[bl:bh]))
        nl = np.searchsorted(fax, f + 80)
        nh = max(np.searchsorted(fax, f + 140), nl + 1)
        nh = min(nh, len(sp))
        noise_amp = float(np.median(sp[nl:nh])) if nh > nl else 1e-9
        snr_db.append(20.0 * np.log10(
            max(tone, 1e-12) / max(noise_amp, 1e-12)))
    return snr_db


def make_sounder_fixture(rng: np.random.Generator,
                          output_path: pathlib.Path) -> dict:
    """Schroeder multitone section + silence section at known noise level."""
    freqs = _tone_freqs()
    tone_dur   = 3.0   # seconds — same as make_master2.py
    tone_amp   = 0.60
    silence_dur = 3.0

    # White noise at a fixed level — -40 dBFS.
    noise_dbfs = -40.0
    noise_amp  = 10 ** (noise_dbfs / 20.0)

    multitone = _schroeder_multitone(freqs, tone_dur, tone_amp)
    silence   = np.zeros(int(silence_dur * SR), dtype=np.float32)

    # Add noise to both.
    noise_mt  = rng.standard_normal(len(multitone)).astype(np.float32) * noise_amp
    noise_sil = rng.standard_normal(len(silence)).astype(np.float32) * noise_amp
    noisy_mt  = (multitone + noise_mt).astype(np.float32)
    noisy_sil = (silence   + noise_sil).astype(np.float32)

    # Concatenate with a 0.1 s gap.
    gap = np.zeros(int(0.1 * SR), dtype=np.float32)
    audio = np.concatenate([noisy_mt, gap, noisy_sil]).astype(np.float32)

    # Write 16-bit WAV.
    sf.write(str(output_path), audio, SR, subtype="PCM_16")

    # Trim 0.3 s from each end before SNR computation — matches Python.
    trim = int(0.3 * SR)
    trimmed = noisy_mt[trim: -trim] if len(noisy_mt) > 2 * trim else noisy_mt

    snr_list = _compute_python_snr(trimmed, freqs)
    snr_arr  = np.array(snr_list)
    snr_med  = float(np.median(snr_arr))
    snr_p10  = float(np.percentile(snr_arr, 10))
    frac8    = float(np.mean(snr_arr < 8.0))

    # Noise floor: RMS of the silence section (trimmed 0.3 s).
    trim2 = int(0.3 * SR)
    sil_trim = noisy_sil[trim2: -trim2] if len(noisy_sil) > 2 * trim2 else noisy_sil
    nf_rms = float(np.sqrt(np.mean(sil_trim ** 2)))
    nf_dbfs = float(20.0 * np.log10(nf_rms)) if nf_rms > 0 else -120.0

    # Layout info for Swift: where each section starts.
    mt_start  = 0
    mt_len    = len(noisy_mt)
    sil_start = mt_len + len(gap)
    sil_len   = len(noisy_sil)

    print(f"  sounder_fixture: SNR med={snr_med:.1f} dB, p10={snr_p10:.1f} dB, "
          f"frac<8dB={frac8:.2f}, noise_floor={nf_dbfs:.1f} dBFS")

    return {
        "sample_rate":          SR,
        "mt_start_sample":      int(mt_start),
        "mt_length_samples":    int(mt_len),
        "sil_start_sample":     int(sil_start),
        "sil_length_samples":   int(sil_len),
        "expected_snr_db_median": snr_med,
        "expected_snr_db_p10":   snr_p10,
        "expected_frac_below_8db": frac8,
        "expected_noise_floor_dbfs": nf_dbfs,
        # Tolerances for Swift assertions.
        "tolerance_snr_db":     2.0,
        "tolerance_nf_db":      2.0,
    }


# ---------------------------------------------------------------------------
# (c) Clip fixture
# ---------------------------------------------------------------------------

def make_clip_fixture(output_path: pathlib.Path) -> dict:
    """Sine wave clipped, written as float32 WAV so threshold survives round-trip."""
    dur = 1.0    # 1 second
    n   = int(dur * SR)
    t   = np.arange(n) / SR
    freq = 1000.0
    amp  = 1.5   # over-drive

    raw  = (amp * np.sin(2 * np.pi * freq * t)).astype(np.float32)
    threshold = 0.99
    clipped = np.clip(raw, -threshold, threshold).astype(np.float32)

    # Expected clip fraction: fraction of samples where |clipped| >= threshold.
    # After hard-clip, samples AT exactly ±threshold count as clipped.
    # Use float32 WAV so threshold is preserved exactly.
    clip_frac = float(np.mean(np.abs(clipped) >= np.float32(threshold)))

    sf.write(str(output_path), clipped, SR, subtype="FLOAT")
    print(f"  clip_fixture: clip_frac={clip_frac:.4f}, threshold={threshold}")

    return {
        "sample_rate":           SR,
        "expected_clip_fraction": clip_frac,
        "clipping_threshold":    threshold,
        # Swift tolerance: ±10% relative.
        "tolerance_relative":    0.10,
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    rng = np.random.default_rng(seed=42)

    chirp_path   = _FIXTURES_DIR / "chirp_fixture.wav"
    sounder_path = _FIXTURES_DIR / "sounder_fixture.wav"
    clip_path    = _FIXTURES_DIR / "clip_fixture.wav"
    json_path    = _FIXTURES_DIR / "expected.json"

    print("Generating fixtures...")

    chirp_info   = make_chirp_fixture(rng, chirp_path)
    sounder_info = make_sounder_fixture(rng, sounder_path)
    clip_info    = make_clip_fixture(clip_path)

    expected = {
        "chirp":   chirp_info,
        "sounder": sounder_info,
        "clip":    clip_info,
    }
    json_path.write_text(json.dumps(expected, indent=2))

    # Report file sizes.
    for p in [chirp_path, sounder_path, clip_path]:
        kb = p.stat().st_size / 1024
        print(f"  {p.name}: {kb:.1f} KB")

    total_kb = sum(p.stat().st_size for p in [chirp_path, sounder_path, clip_path]) / 1024
    print(f"  Total WAV: {total_kb:.0f} KB (limit 5000 KB)")
    assert total_kb < 5000, f"Fixtures too large: {total_kb:.0f} KB"

    print(f"\nWrote {json_path}")
    print("Done.")


if __name__ == "__main__":
    main()
