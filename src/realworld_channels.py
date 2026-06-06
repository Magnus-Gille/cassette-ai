"""realworld_channels.py — Realistic transmission front-end library for the
cassette-AI study (RealChannels phase).

Models the FULL real-world link from tape playback to captured audio:

    tape playback -> [acoustic / cable / bluetooth front-end] -> captured audio

The tape core is ALWAYS applied first (ch.cassette_channel with the study's
STANDARD "normal" preset), then a path-specific front-end transforms the audio
into what a real capture device would actually receive.

Acoustic primitives (composable):
  speaker_response(x, kind)      — small-speaker frequency response (bass rolloff + HF rolloff)
  mic_response(x, kind)          — phone MEMS mic band (recorder wideband vs telephony narrow)
  room_reverb(x, rt60, distance) — synthetic exponential-decay RIR convolution
  ambient_noise(x, snr_db, kind) — pink or babble-like additive noise at the mic
  soft_clip(x, k)                — tanh soft clipping (speaker drive / line overdrive)
  distance_atten(x, distance_m)  — 1/r amplitude attenuation

PATH PRESETS — signature path(audio48k, seed) -> (audio48k, sr=48000):
  P1 cable_usb_soundcard   transparent reference (tape core only)
  P2 cable_trrs_phone_mic  line->mic hard overdrive + phone recorder band + AGC
  P3 acoustic_close_quiet  laptop spkr + mild clip + reverb(0.25,0.15) + mic + noise(30) + AGC
  P4 acoustic_far_noisy    spkr + reverb(0.5,1.0) + mic + babble noise(~15) + AGC
  P5 bluetooth_hfp_narrow  lowpass(3400) + real libopus voip 12k roundtrip + AGC

REFERENCE_MODEMS:
  "bfsk_b0"  — the shipping CAS3/BFSK codec wrapped as a Scheme (== hc._B0Scheme)
  "mfsk32"   — H2 winner: 32-FSK band-spanning grid, no FEC (== hyp_h2_mfsk.MFSKScheme)

evaluate_realworld(scheme, path_key, ...) routes audio through PATHS[path_key]
instead of the usb_soundcard capture stage, returning the same metric family as
hc.evaluate_scheme plus clean_decode_prob and corr_peak (sync acquisition) stats.

Reuses cscn._agc / cscn._lowpass / cscn._ffmpeg_roundtrip and ch.cassette_channel.
Seeds are set+logged per call; no HF models.
"""

from __future__ import annotations

import json
import math
import pathlib
import sys
from typing import Callable

import numpy as np
from scipy import signal

# ---------------------------------------------------------------------------
# Path bootstrap (canonical for this repo)
# ---------------------------------------------------------------------------
ROOT = pathlib.Path("/Users/magnus/repos/cassette-ai")
for _p in ["src", "tests/e2e"]:
    _full = str(ROOT / _p)
    if _full not in sys.path:
        sys.path.insert(0, _full)

import cassette_format as cf          # noqa: E402
import channel as ch                  # noqa: E402
import capture_scenarios as cscn      # noqa: E402
import cassette_e2e as e2e            # noqa: E402
import hyp_common as hc               # noqa: E402
import hyp_h2_mfsk as h2              # noqa: E402

FS = 48_000
DATA_DIR = ROOT / "RESULTS" / "data"

# Study-standard tape core ("normal"). The brief pins these exact values
# (note: ch.cassette_channel bandwidth here is 12000, matching the brief's
# STANDARD tape core, not TAPE_PRESETS["normal"]'s 11000).
NORMAL_TAPE = dict(
    snr_db=42.0,
    bandwidth_hz=12_000.0,
    wow_flutter_wrms=0.0010,
    burst_rate_per_s=0.3,
    burst_length_ms=6.0,
)


def tape_core(audio48k: np.ndarray, seed: int = 0) -> np.ndarray:
    """Apply the study-standard 'normal' tape record/playback channel."""
    x = np.asarray(audio48k, dtype=np.float32)
    return ch.cassette_channel(
        x, fs=FS, seed_offset=seed, **NORMAL_TAPE
    ).astype(np.float32)


# ===========================================================================
# Acoustic / electrical primitives
# ===========================================================================

def _bandpass(x: np.ndarray, f_low: float, f_high: float,
              fs: int = FS, order: int = 4) -> np.ndarray:
    """Zero-phase Butterworth band-pass. f_low<=0 collapses to a low-pass."""
    x = np.asarray(x, dtype=np.float64)
    nyq = fs / 2.0
    f_high = min(f_high, nyq * 0.999)
    if f_low <= 1.0:
        sos = signal.butter(order, f_high / nyq, btype="lowpass", output="sos")
    else:
        f_low = max(f_low, 1.0)
        sos = signal.butter(order, [f_low / nyq, f_high / nyq],
                            btype="bandpass", output="sos")
    return signal.sosfiltfilt(sos, x).astype(np.float32)


def soft_clip(x: np.ndarray, k: float) -> np.ndarray:
    """tanh soft clip y = tanh(k*x)/tanh(k). Larger k = harder clipping.

    FSK is frequency-coded so amplitude clipping (which preserves zero
    crossings) is often survivable — a key thing this study probes.
    """
    x = np.asarray(x, dtype=np.float64)
    k = float(k)
    norm = math.tanh(k)
    if norm <= 0:
        return x.astype(np.float32)
    return (np.tanh(k * x) / norm).astype(np.float32)


def distance_atten(x: np.ndarray, distance_m: float, ref_m: float = 0.1) -> np.ndarray:
    """1/r amplitude attenuation relative to a reference distance (default 0.1 m).

    At ref_m the gain is 1.0; doubling distance halves amplitude. Far links
    therefore arrive much quieter (AGC later restores level but not SNR).
    """
    d = max(float(distance_m), ref_m)
    g = ref_m / d
    return (np.asarray(x, dtype=np.float64) * g).astype(np.float32)


def speaker_response(x: np.ndarray, kind: str = "laptop") -> np.ndarray:
    """Small-speaker frequency response: bass rolloff + treble rolloff.

    kind="laptop": tiny laptop/deck speaker ~150 Hz – 12 kHz (strong bass
                   rolloff, gentle HF rolloff).
    kind="phone":  phone loudspeaker, even less bass ~350 Hz – 10 kHz.
    """
    if kind == "phone":
        f_low, f_high = 350.0, 10_000.0
    else:  # laptop / deck small speaker
        f_low, f_high = 150.0, 12_000.0
    # High-pass for bass rolloff (1st order, gentle) + low-pass for HF rolloff.
    nyq = FS / 2.0
    xd = np.asarray(x, dtype=np.float64)
    sos_hp = signal.butter(1, f_low / nyq, btype="highpass", output="sos")
    sos_lp = signal.butter(3, min(f_high, nyq * 0.999) / nyq,
                           btype="lowpass", output="sos")
    y = signal.sosfiltfilt(sos_hp, xd)
    y = signal.sosfiltfilt(sos_lp, y)
    return y.astype(np.float32)


def mic_response(x: np.ndarray, kind: str = "phone_recorder") -> np.ndarray:
    """Phone MEMS microphone band-limiting.

    kind="phone_recorder":  raw recorder app ~250 Hz – 7500 Hz (wideband MEMS).
    kind="phone_telephony": HFP/telephony path ~300 Hz – 3400 Hz (narrowband).
    """
    if kind == "phone_telephony":
        f_low, f_high = 300.0, 3400.0
    else:  # phone_recorder
        f_low, f_high = 250.0, 7500.0
    return _bandpass(x, f_low, f_high, order=4)


def room_reverb(x: np.ndarray, rt60: float = 0.3, distance_m: float = 0.5,
                seed: int = 0) -> np.ndarray:
    """Convolve x with a synthetic RIR (exponentially-decaying gaussian noise).

    The RIR = direct impulse + a decaying gaussian-noise tail with the given
    RT60. The direct/reverb energy ratio worsens with distance (more
    reverberant energy at >~0.5 m), modelling a moving mic. Output is
    length-matched to the input (tail truncated) and energy-normalised so the
    primitive does not change overall level (level is handled by
    distance_atten / AGC separately).
    """
    x = np.asarray(x, dtype=np.float64)
    g = np.random.default_rng(7000 + seed)
    rt60 = max(float(rt60), 0.01)
    rir_len = int(min(rt60 * 1.5, 1.0) * FS)
    t = np.arange(rir_len) / FS
    # Exponential decay to -60 dB over rt60 seconds.
    decay = np.exp(-6.908 * t / rt60)  # ln(1000)=6.908
    tail = g.normal(0.0, 1.0, size=rir_len) * decay

    # Direct path strength relative to reverberant tail. Closer = more direct.
    # direct_ratio ~ 1 at very close range, falling toward the diffuse field.
    direct_ratio = 1.0 / (1.0 + max(0.0, float(distance_m)) / 0.3)
    rir = tail.copy()
    rir[0] += direct_ratio * np.sqrt(np.sum(tail ** 2) + 1e-12)
    # Normalise RIR energy so convolution preserves signal level.
    rir /= np.sqrt(np.sum(rir ** 2) + 1e-12)

    y = signal.fftconvolve(x, rir, mode="full")[: len(x)]
    return y.astype(np.float32)


def _pink_noise(n: int, g: np.random.Generator) -> np.ndarray:
    """Pink (1/f) noise via FFT shaping of white gaussian noise."""
    white = g.normal(0.0, 1.0, size=n)
    X = np.fft.rfft(white)
    f = np.arange(len(X))
    f[0] = 1.0
    X = X / np.sqrt(f)  # 1/sqrt(f) amplitude -> 1/f power
    y = np.fft.irfft(X, n=n)
    return y


def _babble_noise(n: int, g: np.random.Generator) -> np.ndarray:
    """Babble-like noise: pink noise band-limited to the speech band with slow
    amplitude modulation (mimics overlapping background talkers)."""
    base = _pink_noise(n, g)
    # Restrict to speech band 200–4000 Hz where babble energy concentrates.
    nyq = FS / 2.0
    sos = signal.butter(2, [200.0 / nyq, 4000.0 / nyq], btype="bandpass", output="sos")
    base = signal.sosfiltfilt(sos, base)
    # Slow random amplitude modulation (1–5 Hz syllabic envelope).
    t = np.arange(n) / FS
    env = np.zeros(n)
    for _ in range(4):
        fmod = g.uniform(1.0, 5.0)
        ph = g.uniform(0, 2 * np.pi)
        env += 0.5 * (1.0 + np.sin(2 * np.pi * fmod * t + ph))
    env /= 4.0
    return base * (0.4 + 0.6 * env)


def ambient_noise(x: np.ndarray, snr_db: float = 25.0, kind: str = "pink",
                  seed: int = 0) -> np.ndarray:
    """Add ambient acoustic noise at the mic at a target SNR (dB).

    kind="pink":   stationary 1/f room/HVAC noise.
    kind="babble": non-stationary overlapping-talkers noise (harder for a
                   narrow-band detector that overlaps the speech band).
    SNR is measured against the signal power of x.
    """
    x = np.asarray(x, dtype=np.float64)
    n = len(x)
    g = np.random.default_rng(8000 + seed)
    if kind == "babble":
        noise = _babble_noise(n, g)
    else:
        noise = _pink_noise(n, g)
    sig_pow = float(np.mean(x ** 2)) if n else 1e-9
    noise_pow = float(np.mean(noise ** 2)) + 1e-12
    target_noise_pow = max(sig_pow, 1e-12) / (10 ** (snr_db / 10.0))
    noise *= math.sqrt(target_noise_pow / noise_pow)
    return (x + noise).astype(np.float32)


# ===========================================================================
# PATH PRESETS — full link: tape core -> front-end -> captured audio
# ===========================================================================

def cable_usb_soundcard(audio48k: np.ndarray, seed: int = 0):
    """P1: transparent reference — tape core then a tiny ADC floor.

    Equivalent to the prior 'usb_soundcard' capture: the ceiling path.
    """
    y = tape_core(audio48k, seed)
    y = cscn.capture_usb_soundcard(y, seed)
    return y.astype(np.float32), FS


def cable_trrs_phone_mic(audio48k: np.ndarray, seed: int = 0, *,
                         level_pad: bool = False):
    """P2: line-out -> TRRS -> phone mic input.

    Line level is ~10x the phone mic full-scale, so without a pad the input
    HARD-overdrives the mic preamp -> heavy soft/hard clipping. FSK is
    frequency-coded, so we test whether amplitude clipping is survivable.

    level_pad=True inserts an inline resistor pad (~ -16 dB) so the signal sits
    in the linear region — the recommended fix; compare to the un-padded case.
    """
    y = tape_core(audio48k, seed)
    # Normalise tape output to a known level first.
    peak = float(np.max(np.abs(y))) or 1.0
    y = y / peak
    if level_pad:
        # Inline pad: ~ -16 dB, signal stays in the linear region.
        y = y * 0.16
        drive = 1.5
    else:
        # Line drives mic input ~10x full-scale -> hard overdrive.
        y = y * 8.0
        drive = 8.0
    y = soft_clip(y, k=drive)
    # Phone recorder mic band (~250–7500 Hz).
    y = mic_response(y, kind="phone_recorder")
    # Mic-stage AGC.
    y = cscn._agc(y, target_rms=0.2, attack=0.005, release=0.20)
    return y.astype(np.float32), FS


def acoustic_close_quiet(audio48k: np.ndarray, seed: int = 0):
    """P3: laptop speaker -> short quiet-room air gap -> phone recorder mic.

    laptop speaker_response + mild soft_clip + reverb(0.25, 0.15 m) +
    phone recorder mic + ambient pink noise (~30 dB SNR) + AGC.
    """
    y = tape_core(audio48k, seed)
    y = speaker_response(y, kind="laptop")
    y = soft_clip(y, k=1.2)  # mild speaker drive
    y = room_reverb(y, rt60=0.25, distance_m=0.15, seed=seed)
    y = distance_atten(y, distance_m=0.15)
    y = mic_response(y, kind="phone_recorder")
    y = ambient_noise(y, snr_db=30.0, kind="pink", seed=seed)
    y = cscn._agc(y, target_rms=0.2, attack=0.005, release=0.20)
    return y.astype(np.float32), FS


def acoustic_far_noisy(audio48k: np.ndarray, seed: int = 0, *,
                       snr_db: float = 15.0, noise_kind: str = "babble"):
    """P4: speaker across a noisy room (~1 m) -> phone recorder mic.

    speaker_response + reverb(0.5, 1.0 m) + distance attenuation + mic +
    ambient babble noise (default ~15 dB SNR, configurable) + AGC.
    """
    y = tape_core(audio48k, seed)
    y = speaker_response(y, kind="laptop")
    y = soft_clip(y, k=1.2)
    y = room_reverb(y, rt60=0.5, distance_m=1.0, seed=seed)
    y = distance_atten(y, distance_m=1.0)
    y = mic_response(y, kind="phone_recorder")
    y = ambient_noise(y, snr_db=snr_db, kind=noise_kind, seed=seed)
    y = cscn._agc(y, target_rms=0.2, attack=0.005, release=0.20)
    return y.astype(np.float32), FS


def bluetooth_hfp_narrow(audio48k: np.ndarray, seed: int = 0):
    """P5: Bluetooth HFP / hands-free narrowband voice link.

    lowpass(3400) + real ffmpeg libopus voip 12k roundtrip + AGC. Very
    destructive: narrow band + lossy speech codec optimised for voice, not
    tones.
    """
    y = tape_core(audio48k, seed)
    y = cscn._lowpass(y, fc=3400.0)
    y = cscn._agc(y, target_rms=0.2, attack=0.003, release=0.15)
    # Real lossy speech-codec roundtrip (documented fallback chain).
    try:
        y = cscn._ffmpeg_roundtrip(
            y,
            encode_args=["-c:a", "libopus", "-application", "voip", "-b:a", "12k"],
            decode_ext="opus",
        )
    except RuntimeError:
        # Documented fallback: AAC low-rate if libopus is unavailable.
        y = cscn._ffmpeg_roundtrip(
            y, encode_args=["-c:a", "aac", "-b:a", "16k"], decode_ext="m4a"
        )
    y = cscn._agc(y, target_rms=0.2, attack=0.003, release=0.15)
    return y.astype(np.float32), FS


PATHS: dict[str, Callable] = {
    "P1": cable_usb_soundcard,
    "P2": cable_trrs_phone_mic,
    "P3": acoustic_close_quiet,
    "P4": acoustic_far_noisy,
    "P5": bluetooth_hfp_narrow,
    # Friendly aliases
    "cable_usb_soundcard": cable_usb_soundcard,
    "cable_trrs_phone_mic": cable_trrs_phone_mic,
    "acoustic_close_quiet": acoustic_close_quiet,
    "acoustic_far_noisy": acoustic_far_noisy,
    "bluetooth_hfp_narrow": bluetooth_hfp_narrow,
}


# ===========================================================================
# Reference modems (the two schemes we evaluate over every path)
# ===========================================================================

def build_reference_modems(payload_bits: int = 2000) -> dict:
    """Build the two reference Schemes used across all paths.

    "bfsk_b0" — the shipping CAS3/BFSK codec (hc._B0Scheme), self-syncing via
                the robust chirp decoder.
    "mfsk32"  — the H2 winner: 32-tone band-spanning MFSK, no FEC
                (hyp_h2_mfsk.MFSKScheme(M=32, walsh_k=0)).
    """
    b0 = hc._B0Scheme(payload_bits)
    mfsk = h2.MFSKScheme(M=32, walsh_k=0)
    return {"bfsk_b0": b0, "mfsk32": mfsk}


# Module-level default instances (payload_bits=2000 matches eval default).
REFERENCE_MODEMS = build_reference_modems(2000)


# ===========================================================================
# Real-world Monte-Carlo evaluation
# ===========================================================================

def _corr_peak(audio: np.ndarray, seconds: float = hc.PREAMBLE_SECONDS) -> float:
    """Normalised cross-correlation peak of the preamble chirp in `audio`.

    A proxy for sync-acquisition quality (1.0 = perfect match, ~0 = lost).
    Mirrors hc.find_preamble's correlation but returns the normalised peak.
    """
    a = np.asarray(audio, dtype=np.float64)
    pre = np.asarray(hc.make_preamble(seconds), dtype=np.float64)
    if len(a) < len(pre):
        return 0.0
    corr = signal.correlate(a, pre, mode="valid")
    denom = (np.linalg.norm(pre) * np.sqrt(len(pre))) * (np.std(a) + 1e-12)
    return float(np.max(np.abs(corr)) / (denom + 1e-12))


def evaluate_realworld(
    scheme,
    path_key: str,
    n_seeds: int = 12,
    payload_bits: int = 2000,
    **path_kwargs,
) -> dict:
    """Monte-Carlo a Scheme through a real-world PATH front-end.

    Like hc.evaluate_scheme, but routes the modulated audio through
    PATHS[path_key](audio, seed, **path_kwargs) instead of the usb_soundcard
    capture stage. Returns gross_bps, raw_bit_error_rate, erasure_rate,
    clean_decode_prob, per-seed arrays, and corr_peak (sync) statistics.

    clean_decode_prob = fraction of seeds with BER == 0 (a perfectly recovered
    payload before any FEC) — the practical "did it just work" metric.
    """
    if path_key not in PATHS:
        raise ValueError(f"Unknown path '{path_key}'. Choose from: {sorted(PATHS)}")
    path_fn = PATHS[path_key]

    bers: list[float] = []
    eras: list[float] = []
    peaks: list[float] = []
    cleans: list[bool] = []

    for seed in range(n_seeds):
        tx_bits = hc._random_bits(payload_bits, seed)
        audio = np.asarray(scheme.modulate(tx_bits), dtype=np.float32)
        rx_audio, sr = path_fn(audio, seed, **path_kwargs)
        rx_bits = np.asarray(scheme.demodulate(rx_audio, sr), dtype=np.uint8)

        ber = hc._ber(tx_bits, rx_bits)
        bers.append(ber)
        cleans.append(ber == 0.0)
        peaks.append(_corr_peak(rx_audio))

        ef = getattr(scheme, "erasure_fn", None)
        if ef is not None:
            eras.append(float(ef(rx_audio, sr, tx_bits)))
        elif hasattr(scheme, "erasure_rate_for"):
            # B0-style scheme: frame-CRC erasure rate from last decode.
            eras.append(float(scheme.erasure_rate_for(0)))
        else:
            eras.append(0.0)

    return {
        "name": getattr(scheme, "name", "scheme"),
        "path_key": path_key,
        "path_kwargs": {k: (v if isinstance(v, (int, float, str, bool)) else str(v))
                        for k, v in path_kwargs.items()},
        "gross_bps": float(scheme.gross_bps),
        "raw_bit_error_rate": float(np.mean(bers)),
        "erasure_rate": float(np.mean(eras)),
        "clean_decode_prob": float(np.mean(cleans)),
        "corr_peak_mean": float(np.mean(peaks)),
        "corr_peak_min": float(np.min(peaks)),
        "corr_peak_std": float(np.std(peaks)),
        "per_seed_ber": [float(x) for x in bers],
        "per_seed_erasure": [float(x) for x in eras],
        "per_seed_corr_peak": [float(x) for x in peaks],
        "per_seed_clean": [bool(x) for x in cleans],
        "n_seeds": int(n_seeds),
        "payload_bits": int(payload_bits),
        "tape_preset": "normal",
    }


# ===========================================================================
# Self-verify / smoke test
# ===========================================================================

def _smoketest():
    import time
    print("=" * 70)
    print("realworld_channels.py — smoke test")
    print("=" * 70)

    n_seeds = 6
    payload_bits = 2000
    modems = build_reference_modems(payload_bits)

    results = {}
    for mname, scheme in modems.items():
        for pkey in ["P1", "P3"]:
            t0 = time.time()
            res = evaluate_realworld(scheme, pkey, n_seeds=n_seeds,
                                     payload_bits=payload_bits)
            dt = time.time() - t0
            key = f"{mname}@{pkey}"
            results[key] = res
            print(f"\n[{key}]  gross_bps={res['gross_bps']:.0f}")
            print(f"  raw_ber          = {res['raw_bit_error_rate']:.3e}")
            print(f"  clean_decode_prob= {res['clean_decode_prob']:.2f}")
            print(f"  erasure_rate     = {res['erasure_rate']:.3f}")
            print(f"  corr_peak_mean   = {res['corr_peak_mean']:.3f}")
            print(f"  ({dt:.1f}s)")

    # Confirm P5 ffmpeg roundtrip executes (single seed, BFSK).
    print("\n[P5 ffmpeg roundtrip check — bfsk_b0, 1 seed]")
    t0 = time.time()
    p5 = evaluate_realworld(modems["bfsk_b0"], "P5", n_seeds=1,
                            payload_bits=payload_bits)
    results["bfsk_b0@P5"] = p5
    print(f"  raw_ber={p5['raw_bit_error_rate']:.3e}  "
          f"clean={p5['clean_decode_prob']:.2f}  "
          f"corr_peak={p5['corr_peak_mean']:.3f}  ({time.time()-t0:.1f}s)")
    print("  P5 ffmpeg roundtrip: OK")

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    out_path = DATA_DIR / "rw_smoketest.json"
    payload = {
        "n_seeds": n_seeds,
        "payload_bits": payload_bits,
        "normal_tape": NORMAL_TAPE,
        "results": results,
    }
    with open(out_path, "w") as f:
        json.dump(payload, f, indent=2,
                  default=lambda o: list(o) if hasattr(o, "__iter__") else str(o))
    print(f"\nSaved {out_path}")
    return results


if __name__ == "__main__":
    _smoketest()
