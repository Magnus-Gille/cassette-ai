"""
Empirical Grundig C 4100 cassette channel model.

Extracted from real tape recordings vm_grundig_39.wav and vm_grundig_40.wav
where all fullspectrum decode rungs fail. Reproduces that failure pattern
when applied to the clean transmitted master.

Usage:
    from grundig_channel import grundig_channel
    channel_out = grundig_channel(master_mono, sr=48000, seed=42)
"""

import json, pathlib
import numpy as np
from scipy.signal import fftconvolve

_HERE = pathlib.Path(__file__).parent
with open(_HERE / "grundig_channel.json") as _f:
    _PARAMS = json.load(_f)

_FIR = np.array(_PARAMS["fir_coeffs"])
_NOISE_RMS = _PARAMS["noise_rms"]
_FLUTTER_WRMS = _PARAMS["flutter_wrms_pct"] / 100.0


def grundig_channel(x: np.ndarray, sr: int = 48000, seed: int = 0) -> np.ndarray:
    """Apply empirical Grundig C 4100 cassette channel to clean 48 kHz mono signal.

    Pipeline:
      1. FIR frequency response H(f) — empirical HF tilt from real captures
      2. Flutter / wow modulation (wRMS 0.86%)
      3. Additive white Gaussian noise (empirical floor ~-44 dBFS)

    Args:
        x:    Input signal, 48 kHz mono float64 (or float32 — cast internally)
        sr:   Sample rate. Must be 48000.
        seed: RNG seed for flutter + noise (default 0 for reproducibility)

    Returns:
        Degraded signal as float64, same length as x.
    """
    if sr != 48000:
        raise ValueError(f"grundig_channel only supports sr=48000, got {sr}")

    x = np.asarray(x, dtype=np.float64)

    # 1. FIR frequency response (HF tilt / cassette bandwidth limiting)
    y = fftconvolve(x, _FIR, mode="same")

    # 2. Flutter / wow (speed modulation)
    t = np.arange(len(y)) / sr
    rng = np.random.default_rng(seed)
    wow_amp = _FLUTTER_WRMS * 0.7
    flutter_amp = _FLUTTER_WRMS * 0.3
    phase_wow = rng.uniform(0, 2 * np.pi)
    phase_fl = rng.uniform(0, 2 * np.pi)
    inst_dev = (
        wow_amp * np.sin(2 * np.pi * 0.5 * t + phase_wow)
        + flutter_amp * np.sin(2 * np.pi * 4.0 * t + phase_fl)
    )
    # Normalize to achieve wRMS = flutter_wrms
    inst_dev = inst_dev / (np.sqrt(np.mean(inst_dev ** 2)) + 1e-12) * _FLUTTER_WRMS
    warped_t = t + np.cumsum(inst_dev) / sr
    warped_t = np.clip(warped_t, 0.0, t[-1])
    y = np.interp(t, warped_t, y)

    # 3. Additive white Gaussian noise
    rng2 = np.random.default_rng(seed + 1)
    y = y + rng2.standard_normal(len(y)) * _NOISE_RMS

    return y.astype(np.float64)
