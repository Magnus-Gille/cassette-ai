"""sim_v2.py — faithful cassette-channel simulator v2: REAL AAC round-trip.

The v1 faithful sim (real_channel_sim.py, FROZEN) models the Voice-Memos AAC
codec only INDIRECTLY, folded into a diffuse convolutional contamination floor
(diffuse_gain). External review identified AAC as the binding adversary: it
injects quantization noise adjacent to tonal peaks (the masking skirt) — 2-bin
(300 Hz) tone spacing died on real tape, 3-bin (562 Hz) survived. v2 therefore
runs the signal through the REAL Apple AAC-LC encoder (afconvert, the same
encoder family iOS Voice Memos uses: LC-AAC, 48 kHz, stereo, ~205 kbps CBR).

Public API
----------
PROFILES        measured per-capture channel stats ('tape7', 'tape4'); both use
                the master3 H(f) curves (same physical deck).
aac_roundtrip(x, fs=48000, bitrate=204800, workdir=None)
                mono float -> stereo 24-bit wav -> afconvert AAC-LC m4a (CBR)
                -> decode -> mono, SAMPLE-ALIGNED to the input (codec delay is
                measured empirically ONCE via a chirp and cached).
channel_v2(x, *, profile='tape7', aac=True, seed_offset=0, snr_db=None, ...)
                real_channel(...) physics FIRST (tape + room), THEN the AAC
                round-trip (the phone encodes what it heard).
test_aac_alignment()
                returns the measured codec delay + post-alignment corr peak.

Calibration
-----------
The v1 "_sim" block (diffuse_gain=0.5 etc., in real_channel_params.json) was
calibrated against captures that ALREADY went through Voice Memos AAC — adding
an explicit AAC stage on top would double-count codec contamination. SIM2 below
holds sim_v2-specific overrides (validated by sim_v2_validate.py against the
real master7 tape decode, results/m7_results_tape7_run1.json). The v1 "_sim"
values are NOT touched — other code depends on them.
"""
from __future__ import annotations

import copy
import pathlib
import shutil
import subprocess
import sys
import tempfile

import numpy as np
import soundfile as sf

_HERE = pathlib.Path(__file__).resolve().parent
ROOT = pathlib.Path("/Users/magnus/repos/cassette-ai")
for _p in (ROOT / "src", _HERE):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import real_channel_sim as rcs  # noqa: E402  (FROZEN — wrapped, never edited)

FS = 48_000

# Measured stats of the two real master-tape captures (same deck; H(f) from the
# master3 sounder curves in real_channel_params.json).
PROFILES = {
    "tape7": {"snr_db": 36.4, "flutter_wrms_pct": 0.365},  # noisier take (m7 ground truth)
    "tape4": {"snr_db": 40.4, "flutter_wrms_pct": 0.32},   # quieter take
}

# sim_v2 calibration overrides, applied ON TOP of the v1 "_sim" block at runtime
# (the JSON is never modified). Calibrated by sim_v2_validate.py against the
# real tape7 per-rung outcomes (results/m7_results_tape7_run1.json).
#
# Calibration result (see results/sim_v2_validation.json):
#   diffuse_gain=0.65 is the best-matching value: 7/9 rungs match, the gate-FAIL
#   rung m32_rs111_4k FAILs on BOTH seeds (the headline AAC-killed-turbo
#   constraint), and the gate-PASS rung m16_rs191_8k PASSes on 1/2 seeds (it sits
#   on its RS-191 cliff in sim, raw BER ~.034-.039 vs real .022, so seed variance
#   flips seed1 by ~1 codeword). The pre-registered both-seeds gate is therefore
#   NOT fully met (gate_met=false). The two gate constraints are mutually
#   exclusive under these knobs: m16_rs191 PASS wants diffuse_gain<=~0.6 / +SNR,
#   m32_rs111 FAIL wants diffuse_gain>=~0.65 / no +SNR. Lower dg (0.55-0.63) lets
#   m32_rs111 PASS; +1.5 dB SNR pulled m32_rs111 into PASS too. dg=0.65 is the
#   closest honest calibration. The contamination floor (diffuse_gain) carries the
#   cross-bin/codec noise; the explicit AAC stage does NOT measurably worsen
#   m32_rs111 at this point (aac on .1123 vs off .1115).
SIM2 = {
    "diffuse_gain": 0.65,          # best-match calibration (sim_v2_validate.py)
    "snr_delta_db": 0.0,           # added to the profile snr_db (no delta — +SNR broke the gate)
    # flutter_residual_frac inherited from "_sim" (0.15) — not retuned.
}

_AAC_BITRATE = 204_800  # ~205 kbps total, stereo — matches the probed .qta
_ENCODER = None          # 'afconvert' | 'ffmpeg', resolved lazily
_DELAY_CACHE: dict[tuple, dict] = {}


# ---------------------------------------------------------------------------
# AAC round-trip
# ---------------------------------------------------------------------------
def _run(cmd: list[str]) -> None:
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"{cmd[0]} failed ({r.returncode}): {r.stderr.strip()[:500]}")


def _resolve_encoder() -> str:
    """Prefer Apple's afconvert (same encoder family as iOS Voice Memos);
    fall back to ffmpeg's native aac if afconvert is unusable (e.g. sandbox)."""
    global _ENCODER
    if _ENCODER is not None:
        return _ENCODER
    if shutil.which("afconvert"):
        try:
            with tempfile.TemporaryDirectory() as td:
                p = pathlib.Path(td)
                sf.write(p / "probe.wav",
                         np.zeros((4800, 2), np.float32), FS, subtype="PCM_24")
                _run(["afconvert", "-f", "m4af", "-d", "aac",
                      "-b", str(_AAC_BITRATE), "-s", "0",
                      str(p / "probe.wav"), str(p / "probe.m4a")])
            _ENCODER = "afconvert"
            return _ENCODER
        except Exception:
            pass
    if shutil.which("ffmpeg"):
        _ENCODER = "ffmpeg"
        return _ENCODER
    raise RuntimeError("neither afconvert nor ffmpeg available for AAC round-trip")


def _roundtrip_raw(x: np.ndarray, fs: int, bitrate: int, workdir: pathlib.Path) -> np.ndarray:
    """mono float -> stereo wav -> AAC-LC m4a -> wav -> mono. NO delay trim."""
    enc = _resolve_encoder()
    wav_in = workdir / "rt_in.wav"
    m4a = workdir / "rt.m4a"
    wav_out = workdir / "rt_out.wav"
    stereo = np.stack([x, x], axis=1).astype(np.float64)
    sf.write(wav_in, stereo, fs, subtype="PCM_24")  # Voice Memos records 2ch
    if enc == "afconvert":
        _run(["afconvert", "-f", "m4af", "-d", "aac",
              "-b", str(bitrate), "-s", "0",      # CBR ~205 kbps (matches .qta)
              str(wav_in), str(m4a)])
        _run(["afconvert", "-f", "WAVE", "-d", f"LEF32@{fs}", str(m4a), str(wav_out)])
    else:  # ffmpeg fallback (acceptable, Apple encoder preferred)
        _run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
              "-i", str(wav_in), "-c:a", "aac", "-b:a", str(bitrate), str(m4a)])
        _run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
              "-i", str(m4a), "-f", "wav", "-acodec", "pcm_f32le",
              "-ar", str(fs), str(wav_out)])
    y, sr = sf.read(wav_out, dtype="float64", always_2d=True)
    assert sr == fs, sr
    for f in (wav_in, m4a, wav_out):
        f.unlink(missing_ok=True)
    return y.mean(axis=1)


def _calibrate_delay(fs: int, bitrate: int) -> dict:
    """Measure the AAC encoder/decoder delay ONCE with a wideband chirp; cache.

    AAC-LC has an encoder priming delay (typically 2112 samples) plus possible
    trailing pad. afconvert's m4af container carries the priming info and its
    decoder trims it (measured delay 0), but we do NOT assume that — we measure.
    """
    key = (_resolve_encoder(), fs, bitrate)
    if key in _DELAY_CACHE:
        return _DELAY_CACHE[key]
    t = np.arange(int(fs * 1.0)) / fs
    chirp = 0.5 * np.sin(2 * np.pi * (300.0 + 0.5 * (8000.0 - 300.0) * t / 1.0) * t)
    x = np.pad(chirp, (4800, 4800))
    with tempfile.TemporaryDirectory(prefix="aac_cal_") as td:
        y = _roundtrip_raw(x, fs, bitrate, pathlib.Path(td))
    c = np.correlate(y, x, mode="full")
    pk = int(np.argmax(np.abs(c)))
    delay = pk - (len(x) - 1)
    # parabolic interpolation around the peak -> residual fractional misalignment
    if 0 < pk < len(c) - 1:
        a, b, cc = np.abs(c[pk - 1]), np.abs(c[pk]), np.abs(c[pk + 1])
        denom = (a - 2 * b + cc)
        frac = 0.5 * (a - cc) / denom if abs(denom) > 1e-12 else 0.0
    else:
        frac = 0.0
    # post-alignment normalized correlation peak
    seg = y[max(0, delay):max(0, delay) + len(x)]
    n = min(len(seg), len(x))
    corr = float(np.dot(seg[:n], x[:n]) /
                 (np.linalg.norm(seg[:n]) * np.linalg.norm(x[:n]) + 1e-12))
    info = {"encoder": key[0], "delay_samples": int(delay),
            "residual_frac_samples": float(frac), "corr_peak": corr}
    assert abs(frac) <= 1.0, f"AAC residual misalignment {frac:.2f} > 1 sample"
    assert corr > 0.98, f"AAC round-trip correlation too low: {corr:.3f}"
    _DELAY_CACHE[key] = info
    return info


def aac_roundtrip(x: np.ndarray, fs: int = FS, bitrate: int = _AAC_BITRATE,
                  workdir: str | pathlib.Path | None = None) -> np.ndarray:
    """Real AAC-LC round-trip (Voice-Memos-like: stereo, ~205 kbps CBR),
    sample-aligned to the input. Output length == input length (asserted)."""
    x = np.asarray(x, dtype=np.float64)
    cal = _calibrate_delay(fs, bitrate)
    d = cal["delay_samples"]
    if workdir is None:
        with tempfile.TemporaryDirectory(prefix="aac_rt_") as td:
            y = _roundtrip_raw(x, fs, bitrate, pathlib.Path(td))
    else:
        wd = pathlib.Path(workdir)
        wd.mkdir(parents=True, exist_ok=True)
        y = _roundtrip_raw(x, fs, bitrate, wd)
    if d > 0:
        y = y[d:]
    elif d < 0:
        y = np.concatenate([np.zeros(-d), y])
    if len(y) < len(x):
        y = np.concatenate([y, np.zeros(len(x) - len(y))])
    y = y[: len(x)]
    assert len(y) == len(x), (len(y), len(x))
    return y


def test_aac_alignment(fs: int = FS, bitrate: int = _AAC_BITRATE) -> dict:
    """Self-test: measured codec delay + post-alignment correlation peak."""
    return dict(_calibrate_delay(fs, bitrate))


# ---------------------------------------------------------------------------
# channel v2
# ---------------------------------------------------------------------------
def channel_v2(
    x: np.ndarray,
    *,
    profile: str = "tape7",
    aac: bool = True,
    seed_offset: int = 0,
    snr_db: float | None = None,
    sim_overrides: dict | None = None,
    **kw,
) -> np.ndarray:
    """Faithful channel v2: real_channel tape+room physics FIRST, then the REAL
    AAC round-trip (the phone encodes what it heard). aac=False skips the codec.

    profile selects measured snr/flutter ('tape7' | 'tape4'); both use the
    master3 H(f) curves. snr_db overrides the profile SNR. sim_overrides updates
    the SIM2/_sim calibration dict for this call (used by sim_v2_validate.py).
    """
    prof = PROFILES[profile]
    x = np.asarray(x, dtype=np.float64)

    params = copy.deepcopy(rcs.load_params())
    sim = dict(params.get("_sim", {}))
    sim.update(SIM2)
    if sim_overrides:
        sim.update(sim_overrides)
    params["_sim"] = sim
    # same deck as master3; override the measured flutter with the profile's
    params["flutter_wrms_pct"]["master3"] = prof["flutter_wrms_pct"]
    snr = (snr_db if snr_db is not None
           else prof["snr_db"] + float(sim.get("snr_delta_db", 0.0)))

    y = rcs.real_channel(x, params=params, capture="master3",
                         snr_db=float(snr), seed_offset=seed_offset, **kw)

    if aac:
        pk = float(np.max(np.abs(y))) + 1e-12
        g = 0.95 / pk  # codec sees a healthy level; scale restored after
        y = aac_roundtrip(y * g) / g
    return y.astype(np.float64)


if __name__ == "__main__":
    info = test_aac_alignment()
    print("AAC alignment self-test:", info)
