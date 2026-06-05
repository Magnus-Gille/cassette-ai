"""Digital loopback self-test for the cassette-data-modem robust front-end.

Proves the codec + robust front-end work before any physical tape by simulating
the record/playback chain entirely in software.  Each case runs:

    encode_payload_to_audio -> simulate impairments -> robust_decode -> compare_payload

All six cases must achieve byte-exact recovery (byte_exact=True) to PASS.

Run:
    cd /Users/magnus/repos/cassette-ai
    python3 tests/e2e/loopback_selftest.py
"""

from __future__ import annotations

import sys
import pathlib

# ---- path bootstrap (must happen before importing cassette_e2e / channel) ----
HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parents[1]
SRC = REPO / "src"
sys.path.insert(0, str(SRC))
sys.path.insert(0, str(HERE))

import numpy as np
from scipy.signal import resample_poly
from fractions import Fraction

import cassette_e2e as e2e  # sibling module
import channel as ch        # from src/ (already on sys.path)

# ---------------------------------------------------------------------------
# Fixed test payload (small — keeps residual flutter within one speed pass)
# ---------------------------------------------------------------------------
PAYLOAD = b"loopback self-test :: " + bytes(range(48))   # 70 bytes total
SR48 = e2e.SAMPLE_RATE  # 48000


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _resample_factor(audio: np.ndarray, factor: float) -> np.ndarray:
    """Resample audio by `factor` (>1 = more samples = slower playback)."""
    if abs(factor - 1.0) < 1e-9:
        return audio.astype(np.float64)
    frac = Fraction(factor).limit_denominator(2000)
    up, down = frac.numerator, frac.denominator
    return resample_poly(audio.astype(np.float64), up, down)


def _add_offsets(audio: np.ndarray, lead_s: float, tail_s: float,
                 gain: float, dc: float) -> np.ndarray:
    """Pad with silence and apply gain + DC offset."""
    lead = np.zeros(int(round(lead_s * SR48)), dtype=np.float64)
    tail = np.zeros(int(round(tail_s * SR48)), dtype=np.float64)
    padded = np.concatenate([lead, audio.astype(np.float64), tail])
    return (padded * gain + dc).astype(np.float32)


def _run_channel(audio: np.ndarray, seed: int) -> np.ndarray:
    """Standard channel impairment for cases that include it."""
    return ch.cassette_channel(
        audio,
        snr_db=38,
        wow_flutter_wrms=0.0009,
        bandwidth_hz=11000,
        seed_offset=seed,
    )


# ---------------------------------------------------------------------------
# Test case definitions
# Each is a callable () -> (audio, sr_claimed)
# ---------------------------------------------------------------------------

def case_clean() -> tuple[np.ndarray, int]:
    """No impairment — sanity check."""
    audio = e2e.encode_payload_to_audio(PAYLOAD)
    return audio, SR48


def case_silence_offset() -> tuple[np.ndarray, int]:
    """Leading/trailing silence, gain change, DC offset — no channel noise."""
    audio = e2e.encode_payload_to_audio(PAYLOAD)
    out = _add_offsets(audio, lead_s=0.41, tail_s=0.50, gain=0.5, dc=0.015)
    return out, SR48


def case_bandlimit_noise() -> tuple[np.ndarray, int]:
    """Full channel impairment + silence/gain/DC."""
    audio = e2e.encode_payload_to_audio(PAYLOAD)
    out = _add_offsets(audio, lead_s=0.41, tail_s=0.50, gain=0.5, dc=0.015)
    out = _run_channel(out, seed=5)
    return out, SR48


def case_speed_fast() -> tuple[np.ndarray, int]:
    """Tape plays ~1.5% FAST.

    A 1.5% speed-fast deck produces a signal where each original second of audio
    arrives in only 1/1.015 of a real second — i.e. the signal is time-compressed
    (fewer samples at nominal rate).  We simulate this by resampling to
    factor = 1/1.015 < 1 (dropping samples), then adding impairments.
    The speed_search in robust_decode should pick ratio ~1.015 to compensate.
    """
    audio = e2e.encode_payload_to_audio(PAYLOAD)
    # time-compress: 1.5% faster playback -> fewer samples at 48k
    compressed = _resample_factor(audio, 1.0 / 1.015)
    out = _add_offsets(compressed, lead_s=0.41, tail_s=0.50, gain=0.5, dc=0.015)
    out = _run_channel(out, seed=7)
    return out, SR48


def case_speed_slow() -> tuple[np.ndarray, int]:
    """Tape plays ~1.5% SLOW.

    Slow deck time-stretches: each nominal second of audio spreads over more real
    time -> more samples.  Resample by factor > 1.  The speed_search should pick
    ratio ~0.985.
    """
    audio = e2e.encode_payload_to_audio(PAYLOAD)
    stretched = _resample_factor(audio, 1.0 / 0.985)
    out = _add_offsets(stretched, lead_s=0.41, tail_s=0.50, gain=0.5, dc=0.015)
    out = _run_channel(out, seed=9)
    return out, SR48


def case_rate_44100() -> tuple[np.ndarray, int]:
    """Recording device samples at 44100 Hz.

    Pass sr=44100 so robust_decode resamples back to 48k.  Adds channel + offsets.
    """
    audio = e2e.encode_payload_to_audio(PAYLOAD)
    out = _add_offsets(audio, lead_s=0.41, tail_s=0.50, gain=0.5, dc=0.015)
    out = _run_channel(out, seed=11)
    # Resample the whole thing to 44100 to simulate a different recording rate.
    frac = Fraction(44100, SR48).limit_denominator(4000)
    out_44100 = resample_poly(out.astype(np.float64), frac.numerator, frac.denominator)
    return out_44100.astype(np.float32), 44100


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

CASES = [
    ("clean",          case_clean),
    ("silence_offset", case_silence_offset),
    ("bandlimit_noise", case_bandlimit_noise),
    ("speed_fast",     case_speed_fast),
    ("speed_slow",     case_speed_slow),
    ("rate_44100",     case_rate_44100),
]

COL_W = {
    "name":               16,
    "speed_ratio":        12,
    "corr_peak":          10,
    "rec_frac":           10,
    "ber":                10,
    "result":             6,
}

def _hdr() -> str:
    return (
        f"{'case':<16} {'speed_ratio':>12} {'corr_peak':>10} "
        f"{'rec_frac':>10} {'byte_err_rt':>11} {'result':>6}"
    )


def _sep() -> str:
    return "-" * 69


def run_all() -> int:
    print()
    print("Cassette-AI Digital Loopback Self-test")
    print(_sep())
    print(_hdr())
    print(_sep())

    n_fail = 0
    for name, fn in CASES:
        audio, sr = fn()
        rr = e2e.robust_decode(audio, sr, speed_search=(0.94, 1.06, 0.005))
        cmp = e2e.compare_payload(PAYLOAD, rr.result)

        passed = cmp["byte_exact"]
        if not passed:
            n_fail += 1

        status = "PASS" if passed else "FAIL"
        print(
            f"{name:<16} {rr.speed_ratio:>12.4f} {rr.corr_peak:>10.4f} "
            f"{cmp['recovered_fraction']:>10.4f} {cmp['byte_error_rate']:>11.6f} "
            f"{status:>6}"
        )

    print(_sep())
    if n_fail == 0:
        print("ALL PASS")
    else:
        print(f"{n_fail} FAILED")
    print()
    return 0 if n_fail == 0 else 1


if __name__ == "__main__":
    raise SystemExit(run_all())
