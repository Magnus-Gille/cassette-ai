"""make_calibration.py — Generate the calibration WAV for Stage-A setup testing.

Layout (~25 s total):
  1 s  silence
  0.2 s  global up-chirp  (500→5000 Hz)
  0.5 s  gap
  3 s    Schroeder multitone rep 1 (300-11000 Hz, 64 tones)
  0.5 s  gap
  3 s    Schroeder multitone rep 2
  0.5 s  gap
  0.2 s  global down-chirp  (5000→500 Hz)
  1 s  silence

Sample rate: 48 kHz, 16-bit PCM WAV (lossless; ~5 MB).
Also writes calibration_meta.json with exact layout offsets.

Run:
    python3 app/backend/calibration/make_calibration.py
"""
from __future__ import annotations

import json
import pathlib
import sys

import numpy as np
import soundfile as sf
from scipy.signal import chirp as _scipy_chirp

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
HERE = pathlib.Path(__file__).resolve().parent
REPO_ROOT = HERE.parent.parent.parent     # cassette-ai/
TAPE_V2 = REPO_ROOT / "experiments" / "tape_v2"

# Reuse make_master2.py sounder functions via import
sys.path.insert(0, str(TAPE_V2))
sys.path.insert(0, str(REPO_ROOT / "src"))

WAV_OUT = HERE / "calibration.wav"
META_OUT = HERE / "calibration_meta.json"

# ---------------------------------------------------------------------------
# Signal parameters — mirror make_master2.py exactly
# ---------------------------------------------------------------------------
SR = 48_000
GLOBAL_CHIRP_T = 0.20
GLOBAL_CHIRP_F0 = 500.0
GLOBAL_CHIRP_F1 = 5000.0
GLOBAL_CHIRP_AMP = 0.70
SOUNDER_AMP = 0.60
# 64 log-spaced freqs 300-11000 Hz (same as master2/master8)
SOUNDER_FREQS = np.round(np.geomspace(300, 11_000, 64)).astype(int).tolist()


def _silence(dur: float) -> np.ndarray:
    return np.zeros(int(dur * SR), dtype=np.float32)


def _make_global_chirp(up: bool = True) -> np.ndarray:
    n = int(GLOBAL_CHIRP_T * SR)
    t = np.arange(n, dtype=np.float64) / SR
    f0, f1 = (GLOBAL_CHIRP_F0, GLOBAL_CHIRP_F1) if up else (GLOBAL_CHIRP_F1, GLOBAL_CHIRP_F0)
    sig = _scipy_chirp(t, f0=f0, f1=f1, t1=GLOBAL_CHIRP_T, method="linear")
    fade = int(0.01 * SR)
    sig[:fade] *= np.linspace(0, 1, fade)
    sig[-fade:] *= np.linspace(1, 0, fade)
    return (GLOBAL_CHIRP_AMP * sig).astype(np.float32)


def _schroeder_multitone(freqs: list[int], dur: float, amp: float) -> np.ndarray:
    """Low-PAPR Schroeder multitone (same algorithm as make_master2._schroeder_multitone)."""
    n = int(dur * SR)
    t = np.arange(n) / SR
    K = len(freqs)
    x = np.zeros(n)
    for k, f in enumerate(freqs):
        ph = np.pi * k * (k + 1) / K
        x += np.sin(2 * np.pi * f * t + ph)
    x /= np.max(np.abs(x)) + 1e-9
    fade = int(0.02 * SR)
    x[:fade] *= np.linspace(0, 1, fade)
    x[-fade:] *= np.linspace(1, 0, fade)
    return (amp * x).astype(np.float32)


def build_calibration() -> dict:
    """Build calibration WAV + meta. Returns the meta dict."""
    parts: list[np.ndarray] = []
    meta_sections: list[dict] = []
    pos = 0  # current sample position

    def add(name: str, sig: np.ndarray, info: dict = None):
        nonlocal pos
        meta_sections.append({
            "name": name,
            "start_sample": int(pos),
            "length_samples": int(len(sig)),
            "start_sec": pos / SR,
            "length_sec": len(sig) / SR,
            "info": info or {},
        })
        parts.append(sig)
        pos += len(sig)

    def gap(dur: float):
        nonlocal pos
        g = _silence(dur)
        parts.append(g)
        pos += len(g)

    # --- layout ---
    gap(1.0)
    add("global_chirp_up", _make_global_chirp(up=True), {
        "type": "chirp", "f0": GLOBAL_CHIRP_F0, "f1": GLOBAL_CHIRP_F1,
        "T": GLOBAL_CHIRP_T,
    })
    gap(0.5)
    add("sounder_rep0", _schroeder_multitone(SOUNDER_FREQS, 3.0, SOUNDER_AMP), {
        "type": "multitone", "rep": 0, "freqs": SOUNDER_FREQS,
        "duration_s": 3.0,
    })
    gap(0.5)
    add("sounder_rep1", _schroeder_multitone(SOUNDER_FREQS, 3.0, SOUNDER_AMP), {
        "type": "multitone", "rep": 1, "freqs": SOUNDER_FREQS,
        "duration_s": 3.0,
    })
    gap(0.5)
    add("global_chirp_down", _make_global_chirp(up=False), {
        "type": "chirp", "f0": GLOBAL_CHIRP_F1, "f1": GLOBAL_CHIRP_F0,
        "T": GLOBAL_CHIRP_T,
    })
    gap(1.0)

    audio = np.concatenate(parts)
    # Peak-normalise to 0.95
    peak = float(np.max(np.abs(audio)))
    if peak > 1e-9:
        audio = audio * (0.95 / peak)
    audio_i16 = (audio * 32767).clip(-32768, 32767).astype(np.int16)

    sf.write(str(WAV_OUT), audio_i16, SR, format="WAV", subtype="PCM_16")
    total_dur = len(audio) / SR

    meta = {
        "sample_rate": SR,
        "duration_sec": total_dur,
        "n_samples": len(audio),
        "sounder_freqs": SOUNDER_FREQS,
        "sections": meta_sections,
        "chirp": {
            "T": GLOBAL_CHIRP_T,
            "f0": GLOBAL_CHIRP_F0,
            "f1": GLOBAL_CHIRP_F1,
            "amp": GLOBAL_CHIRP_AMP,
        },
    }
    META_OUT.write_text(json.dumps(meta, indent=2))
    print(f"[make_calibration] wrote {WAV_OUT} ({total_dur:.1f} s, "
          f"{WAV_OUT.stat().st_size / 1024:.0f} KB)")
    print(f"[make_calibration] wrote {META_OUT}")
    return meta


if __name__ == "__main__":
    build_calibration()
