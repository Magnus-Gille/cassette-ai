"""capture_scenarios.py — Channel-scenario library for cassette capture experiments.

Models the full computer->tape->computer chain:
  tape_core():  tape record/playback physics (bandwidth, SNR, wow/flutter, dropouts, speed offset, soft-clip)
  capture_*():  ADC capture stage (USB soundcard, phone raw PCM, phone voice recorder AAC, phone VoIP Opus)
  full_chain():  convenience wrapper: tape_core -> capture function

Import from any experiment script via:
    from capture_scenarios import TAPE_PRESETS, tape_core, full_chain, CAPTURE_SCENARIOS
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
import pathlib
from collections import OrderedDict
from typing import Callable

import numpy as np
from scipy import signal
import soundfile as sf

ROOT = pathlib.Path("/Users/magnus/repos/cassette-ai")
sys.path.insert(0, str(ROOT / "src"))

import channel as ch

FS = 48_000  # canonical sample rate throughout


# ---------------------------------------------------------------------------
# Tape presets
# ---------------------------------------------------------------------------

TAPE_PRESETS: dict[str, dict] = {
    "pristine": {
        # Type-II / high-bias deck, fresh tape, same deck record+play
        "snr_db": 52.0,
        "bandwidth_hz": 15_000.0,
        "wow_flutter_wrms": 0.0005,
        "burst_rate_per_s": 0.05,
        "burst_length_ms": 3.0,
    },
    "good": {
        # Well-maintained consumer deck, good tape
        "snr_db": 48.0,
        "bandwidth_hz": 12_000.0,
        "wow_flutter_wrms": 0.0006,
        "burst_rate_per_s": 0.10,
        "burst_length_ms": 4.0,
    },
    "normal": {
        # Typical consumer deck, normal Type-I tape
        "snr_db": 42.0,
        "bandwidth_hz": 11_000.0,
        "wow_flutter_wrms": 0.0010,
        "burst_rate_per_s": 0.30,
        "burst_length_ms": 6.0,
    },
    "worn": {
        # Worn/cheap deck, old tape — marginal but still playable
        "snr_db": 36.0,
        "bandwidth_hz": 9_000.0,
        "wow_flutter_wrms": 0.0025,
        "burst_rate_per_s": 1.0,
        "burst_length_ms": 10.0,
    },
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _lowpass(y: np.ndarray, fc: float, fs: int = FS, order: int = 5) -> np.ndarray:
    """Zero-phase Butterworth low-pass filter."""
    nyq = fs / 2.0
    fc_norm = min(fc / nyq, 0.9999)
    sos = signal.butter(order, fc_norm, btype="lowpass", output="sos")
    return signal.sosfiltfilt(sos, y.astype(np.float64)).astype(np.float32)


def _agc(
    y: np.ndarray,
    target_rms: float = 0.2,
    attack: float = 0.005,
    release: float = 0.05,
    fs: int = FS,
) -> np.ndarray:
    """Scalar time-varying gain AGC.

    Uses a leaky-peak follower:
      envelope rises with attack time constant, falls with release.
    Gain = target_rms / envelope; clipped to [1/32, 32] to avoid blowup.
    """
    y = y.astype(np.float64)
    n = len(y)
    env = np.empty(n, dtype=np.float64)
    alpha_a = float(np.exp(-1.0 / (attack * fs)))
    alpha_r = float(np.exp(-1.0 / (release * fs)))
    e = target_rms  # initial envelope
    for i in range(n):
        x = abs(y[i])
        if x > e:
            e = alpha_a * e + (1.0 - alpha_a) * x
        else:
            e = alpha_r * e + (1.0 - alpha_r) * x
        env[i] = e
    env = np.maximum(env, 1e-6)
    gain = np.clip(target_rms / env, 1.0 / 32.0, 32.0)
    return (y * gain).astype(np.float32)


def _spectral_gate(y: np.ndarray, threshold_db: float = -35.0, fs: int = FS) -> np.ndarray:
    """Crude noise-suppression spectral gate (block-level magnitude threshold).

    Divides the signal into 50%-overlap STFT frames; bins below threshold
    relative to the block maximum are zeroed. Approximates a speech-tuned NS.
    """
    y = y.astype(np.float64)
    nperseg = 512
    noverlap = nperseg // 2
    freqs, times, Zxx = signal.stft(y, fs=fs, nperseg=nperseg, noverlap=noverlap)
    mag = np.abs(Zxx)
    phase = np.angle(Zxx)
    # Threshold relative to per-frame max (broadcast over freq axis)
    frame_max = np.max(mag, axis=0, keepdims=True) + 1e-12
    threshold_linear = frame_max * (10.0 ** (threshold_db / 20.0))
    mag_gated = np.where(mag >= threshold_linear, mag, 0.0)
    Zxx_gated = mag_gated * np.exp(1j * phase)
    _, y_out = signal.istft(Zxx_gated, fs=fs, nperseg=nperseg, noverlap=noverlap)
    # Trim/pad to original length
    if len(y_out) > len(y):
        y_out = y_out[: len(y)]
    elif len(y_out) < len(y):
        y_out = np.pad(y_out, (0, len(y) - len(y_out)))
    return y_out.astype(np.float32)


def _ffmpeg_roundtrip(
    y: np.ndarray,
    encode_args: list[str],
    decode_ext: str = "wav",
    fs: int = FS,
) -> np.ndarray:
    """Write y (float32 @48k mono) to a temp wav, transcode with ffmpeg using
    encode_args (everything between -i in.wav and the output path), decode back
    to wav, return float32 @48k mono. Cleans up temp files.

    encode_args example for AAC 64k:
        ["-c:a", "aac", "-b:a", "64k"]

    Raises RuntimeError if ffmpeg exits non-zero.
    """
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = pathlib.Path(tmp)
        in_wav = tmp_path / "in.wav"
        encoded_file = tmp_path / f"encoded.{decode_ext}"
        out_wav = tmp_path / "out.wav"

        # Normalize to ~0.7 peak before encoding to avoid clipping
        y32 = y.astype(np.float32)
        peak = float(np.max(np.abs(y32)))
        if peak > 0.0:
            y32 = y32 * (0.7 / peak)

        sf.write(str(in_wav), y32, fs, subtype="PCM_16")

        # Encode
        enc_cmd = (
            ["ffmpeg", "-y", "-loglevel", "error", "-i", str(in_wav)]
            + encode_args
            + [str(encoded_file)]
        )
        result = subprocess.run(enc_cmd, capture_output=True)
        if result.returncode != 0:
            raise RuntimeError(
                f"ffmpeg encode failed (exit {result.returncode}):\n"
                f"{result.stderr.decode(errors='replace')}"
            )

        # Decode back to wav
        dec_cmd = [
            "ffmpeg", "-y", "-loglevel", "error",
            "-i", str(encoded_file),
            str(out_wav),
        ]
        result = subprocess.run(dec_cmd, capture_output=True)
        if result.returncode != 0:
            raise RuntimeError(
                f"ffmpeg decode failed (exit {result.returncode}):\n"
                f"{result.stderr.decode(errors='replace')}"
            )

        audio, sr = sf.read(str(out_wav), dtype="float32", always_2d=False)
        if audio.ndim > 1:
            audio = audio.mean(axis=1).astype(np.float32)

        # Resample back to 48k if the codec changed the sample rate
        if int(sr) != FS:
            from fractions import Fraction
            frac = Fraction(FS / sr).limit_denominator(4000)
            from scipy.signal import resample_poly as _rp
            audio = _rp(audio.astype(np.float64), frac.numerator, frac.denominator).astype(np.float32)

        return audio


# ---------------------------------------------------------------------------
# Tape core
# ---------------------------------------------------------------------------

def tape_core(
    x: np.ndarray,
    preset: str = "normal",
    *,
    speed_offset: float = 0.0,
    soft_clip: float | None = None,
    seed: int = 0,
) -> tuple[np.ndarray, dict]:
    """Apply tape record/playback physics to audio x (float32/64 @48k).

    Parameters
    ----------
    x : np.ndarray
        Input audio, float, @48 kHz mono.
    preset : str
        One of TAPE_PRESETS keys: "pristine", "good", "normal", "worn".
    speed_offset : float
        Fractional steady deck speed mismatch, e.g. +0.015 = 1.5% fast.
        Applied by resampling the whole signal; output length changes but
        output sample rate is still reported as 48k (caller decodes at that rate).
    soft_clip : float or None
        If given, apply tanh soft-clip with drive k=soft_clip before tape
        physics. Useful as a sensitivity knob for record-level overdrive.
    seed : int
        RNG seed offset passed to ch.cassette_channel_diagnostics.

    Returns
    -------
    y : np.ndarray  float32 @48k
    diag : dict  {"measured_snr_db": float, "measured_wow_flutter_wrms_pct": float}
    """
    if preset not in TAPE_PRESETS:
        raise ValueError(f"Unknown tape preset '{preset}'. Choose from: {list(TAPE_PRESETS)}")

    p = TAPE_PRESETS[preset]
    x = np.asarray(x, dtype=np.float64)

    # Optional record-side soft-clip (tanh overdrive)
    if soft_clip is not None:
        k = float(soft_clip)
        norm = float(np.tanh(k))
        if norm > 0:
            x = np.tanh(k * x) / norm

    # Steady speed offset: resample so that a recording made at a slightly
    # different speed arrives stretched/compressed relative to 48k nominal.
    # ratio > 1 -> signal is "sped up" (shorter), ratio < 1 -> slowed down.
    if abs(speed_offset) > 1e-6:
        from fractions import Fraction
        from scipy.signal import resample_poly as _rp
        ratio = 1.0 + float(speed_offset)
        frac = Fraction(ratio).limit_denominator(4000)
        x = _rp(x, frac.numerator, frac.denominator)

    y, diag = ch.cassette_channel_diagnostics(
        x,
        fs=FS,
        snr_db=p["snr_db"],
        wow_flutter_wrms=p["wow_flutter_wrms"],
        bandwidth_hz=p["bandwidth_hz"],
        burst_rate_per_s=p["burst_rate_per_s"],
        burst_length_ms=p["burst_length_ms"],
        seed_offset=seed,
    )

    return y.astype(np.float32), diag


# ---------------------------------------------------------------------------
# Capture stage functions
# ---------------------------------------------------------------------------

def capture_usb_soundcard(y: np.ndarray, seed: int = 0) -> np.ndarray:
    """USB soundcard: transparent ADC, ~85 dB dynamic range.

    Adds a tiny ~85 dB SNR AWGN floor (essentially inaudible); otherwise
    passes the signal unchanged. This is the ceiling capture path.
    """
    y = np.asarray(y, dtype=np.float64)
    g = np.random.default_rng(2000 + seed)
    power = float(np.mean(y ** 2)) if y.size else 1e-6
    noise_power = max(power, 1e-12) / (10 ** (85.0 / 10.0))
    noise = g.normal(0.0, float(np.sqrt(noise_power)), size=len(y))
    return (y + noise).astype(np.float32)


def capture_phone_custom_pcm(y: np.ndarray, seed: int = 0) -> np.ndarray:
    """Phone with a purpose-built raw-PCM app: AGC/NS disabled, wideband.

    Models:
      - Gentle lowpass to ~18 kHz (slightly below soundcard ceiling)
      - ~65 dB ADC noise floor (worse than USB but still excellent)
      - Tiny clock offset ~150 ppm -> effectively negligible; omitted since
        robust_decode speed search handles it with trivial grid
    """
    y = np.asarray(y, dtype=np.float64)
    # Gentle lowpass @18 kHz
    y = _lowpass(y.astype(np.float32), fc=18_000.0).astype(np.float64)
    # ~65 dB ADC noise
    g = np.random.default_rng(3000 + seed)
    power = float(np.mean(y ** 2)) if y.size else 1e-6
    noise_power = max(power, 1e-12) / (10 ** (65.0 / 10.0))
    noise = g.normal(0.0, float(np.sqrt(noise_power)), size=len(y))
    return (y + noise).astype(np.float32)


def capture_voice_recorder_aac(y: np.ndarray, seed: int = 0) -> np.ndarray:
    """Generic voice-recorder app: speech-band lowpass + AGC + real AAC 64k roundtrip.

    Models:
      - Lowpass ~7500 Hz (speech-tuned mic/codec pipeline)
      - AGC (attack ~5 ms, release ~200 ms, target RMS 0.2)
      - Real ffmpeg AAC encode at 64 kbit/s -> decode back to PCM @48k
    """
    y = np.asarray(y, dtype=np.float32)
    # Band-limit to speech range
    y = _lowpass(y, fc=7_500.0)
    # AGC
    y = _agc(y, target_rms=0.2, attack=0.005, release=0.20)
    # Real AAC roundtrip via ffmpeg
    y = _ffmpeg_roundtrip(y, encode_args=["-c:a", "aac", "-b:a", "64k"], decode_ext="m4a")
    return y.astype(np.float32)


def capture_voip_opus_narrow(y: np.ndarray, seed: int = 0) -> np.ndarray:
    """VoIP / voice-call path: narrow-band lowpass + AGC + spectral NS + Opus 24k roundtrip.

    Models:
      - Lowpass ~3800 Hz (narrowband voice pipeline)
      - AGC (attack ~3 ms, release ~150 ms)
      - Crude spectral-gate noise suppression
      - Real ffmpeg libopus encode at 24 kbit/s, application=voip -> decode back @48k
    """
    y = np.asarray(y, dtype=np.float32)
    # Narrowband band-limit
    y = _lowpass(y, fc=3_800.0)
    # AGC
    y = _agc(y, target_rms=0.2, attack=0.003, release=0.15)
    # Crude spectral-gate NS
    y = _spectral_gate(y, threshold_db=-35.0)
    # Real Opus VoIP roundtrip via ffmpeg
    y = _ffmpeg_roundtrip(
        y,
        encode_args=["-c:a", "libopus", "-application", "voip", "-b:a", "24k"],
        decode_ext="opus",
    )
    return y.astype(np.float32)


# ---------------------------------------------------------------------------
# Capture scenario registry
# ---------------------------------------------------------------------------

CAPTURE_SCENARIOS: "OrderedDict[str, Callable[[np.ndarray, int], np.ndarray]]" = OrderedDict([
    ("usb_soundcard",             capture_usb_soundcard),
    ("phone_custom_pcm",          capture_phone_custom_pcm),
    ("phone_voice_recorder_aac",  capture_voice_recorder_aac),
    ("phone_voip_opus_narrow",    capture_voip_opus_narrow),
])


# ---------------------------------------------------------------------------
# Full chain convenience wrapper
# ---------------------------------------------------------------------------

def full_chain(
    payload_audio48k: np.ndarray,
    tape_preset: str,
    capture_key: str,
    *,
    speed_offset: float = 0.0,
    seed: int = 0,
) -> tuple[np.ndarray, int, dict]:
    """End-to-end: tape_core -> capture stage.

    Parameters
    ----------
    payload_audio48k : np.ndarray
        Raw BFSK audio from e2e.encode_payload_to_audio(), float @48k.
    tape_preset : str
        One of TAPE_PRESETS keys.
    capture_key : str
        One of CAPTURE_SCENARIOS keys.
    speed_offset : float
        Steady deck speed mismatch (see tape_core).
    seed : int
        RNG seed for both tape and capture stages.

    Returns
    -------
    audio : np.ndarray  float32
    sr    : int         (always 48000)
    diag  : dict        {"measured_snr_db", "measured_wow_flutter_wrms_pct"}
    """
    if capture_key not in CAPTURE_SCENARIOS:
        raise ValueError(f"Unknown capture key '{capture_key}'. Choose from: {list(CAPTURE_SCENARIOS)}")

    tape_audio, diag = tape_core(
        payload_audio48k,
        preset=tape_preset,
        speed_offset=speed_offset,
        seed=seed,
    )

    capture_fn = CAPTURE_SCENARIOS[capture_key]
    captured = capture_fn(tape_audio, seed)

    return captured.astype(np.float32), FS, diag


# ---------------------------------------------------------------------------
# Self-verify
# ---------------------------------------------------------------------------

def _self_verify() -> None:
    """Build a short BFSK signal, run all four capture scenarios over tape_preset='normal',
    decode with robust_decode (trivial speed grid since no speed_offset), and report results."""
    sys.path.insert(0, str(ROOT / "tests" / "e2e"))
    import cassette_format as cf
    import cassette_e2e as e2e

    payload = cf.cassette_payload("scen", 256)
    audio = e2e.encode_payload_to_audio(payload)

    print("=" * 65)
    print("capture_scenarios.py — self-verify")
    print(f"payload: 256 bytes, audio length: {len(audio)/FS:.2f}s @48kHz")
    print("=" * 65)

    for key in CAPTURE_SCENARIOS:
        print(f"\n[{key}]")
        out_audio, sr, diag = full_chain(audio, "normal", key, seed=0)
        # Trivial speed grid: no steady speed offset injected
        rr = e2e.robust_decode(out_audio, sr, speed_search=(1.0, 1.0001, 1.0))
        cmp = e2e.compare_payload(payload, rr.result)
        tape_snr = diag["measured_snr_db"]
        complete = rr.result.complete
        rec_frac = cmp["recovered_fraction"]
        print(f"  tape SNR:           {tape_snr:.1f} dB")
        print(f"  corr_peak:          {rr.corr_peak:.4f}")
        print(f"  complete decode:    {complete}")
        print(f"  recovered_fraction: {rec_frac:.3f}")
        print(f"  recovered_frames:   {rr.result.recovered_frames}")
        print(f"  bad_frames:         {rr.result.bad_frames}")
        print(f"  missing_frames:     {len(rr.result.missing_frames)}")
        if rr.result.errors:
            print(f"  errors:             {rr.result.errors[:4]}")

    print("\n" + "=" * 65)
    print("Self-verify done. Confirm usb_soundcard & phone_custom_pcm complete.")
    print("=" * 65)


if __name__ == "__main__":
    _self_verify()
