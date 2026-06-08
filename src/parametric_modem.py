"""parametric_modem.py — Non-coherent M-FSK modulator / demodulator with configurable
bit rate and tone set.

The decoder uses a matched-filter (Goertzel / windowed DFT) energy detector with
KNOWN symbol timing (simulation alignment). This measures RAW bit-error-rate without
the CAS3 framing overhead, so it cleanly exposes channel quality independent of
protocol details.

API
---
encode_bits(bits, *, bit_rate, tones, fs=48000) -> np.ndarray (float32)
decode_bits(audio, *, bit_rate, tones, fs=48000, n_bits) -> np.ndarray (int, symbol indices)
ber(tx_bits, rx_bits) -> float

For M=2 (binary FSK) tones should be (f0_hz, f1_hz).
For M=4 (4-FSK) tones should be (f0, f1, f2, f3) with spacing >= 1/T_sym to keep
symbols orthogonal (the experiment helper pick_tones() enforces this).

Design notes
------------
- Tones are continuous-phase within each symbol window (cos, zero initial phase
  per symbol). Non-coherent energy detector doesn't care about inter-symbol phase.
- Symbol window = fs / bit_rate_per_symbol samples (integer, rounded down).
  For 2-FSK, bits_per_symbol=1; for 4-FSK, bits_per_symbol=2.
- Matched filter: compute |DFT at each tone frequency|^2 over the symbol window
  using scipy.signal.fft (one per symbol, all tones vectorised in a matrix multiply).
- No guard intervals, no framing — pure raw-BER measurement.
"""

from __future__ import annotations

import math
from typing import Sequence

import numpy as np
from scipy.fft import rfft, rfftfreq


FS_DEFAULT = 48_000


# ---------------------------------------------------------------------------
# Tone selection helper
# ---------------------------------------------------------------------------

def pick_tones(
    n_tones: int,
    bit_rate_bps: int,
    *,
    fs: int = FS_DEFAULT,
    min_freq_hz: float = 400.0,
    max_freq_hz: float | None = None,
) -> tuple[float, ...]:
    """Return n_tones orthogonally-spaced FSK frequencies.

    Orthogonal spacing = 1 / T_symbol = bit_rate_bps / log2(n_tones).
    Tones start at min_freq_hz and are evenly spaced from there.

    Parameters
    ----------
    n_tones : int
        Number of FSK tones (must be a power of 2: 2, 4, 8, ...).
    bit_rate_bps : int
        Target bit rate in bits per second.
    fs : int
        Sample rate.
    min_freq_hz : float
        Lowest tone frequency.
    max_freq_hz : float or None
        If given, raises ValueError when the highest tone exceeds this.

    Returns
    -------
    tuple of floats, length n_tones.
    """
    if n_tones < 2 or (n_tones & (n_tones - 1)) != 0:
        raise ValueError(f"n_tones must be a power of 2; got {n_tones}")
    bits_per_symbol = int(math.log2(n_tones))
    symbol_rate = bit_rate_bps / bits_per_symbol
    # Orthogonal spacing: at least 1/T_sym but round up to nearest integer Hz
    spacing = math.ceil(symbol_rate)
    tones = tuple(min_freq_hz + i * spacing for i in range(n_tones))
    nyq = fs / 2.0
    if tones[-1] > nyq * 0.95:
        raise ValueError(
            f"Highest tone {tones[-1]:.0f} Hz exceeds 95% of Nyquist ({nyq:.0f} Hz) "
            f"for fs={fs}"
        )
    if max_freq_hz is not None and tones[-1] > max_freq_hz:
        raise ValueError(
            f"Highest tone {tones[-1]:.0f} Hz exceeds usable bandwidth {max_freq_hz:.0f} Hz"
        )
    return tones


# ---------------------------------------------------------------------------
# Encoder
# ---------------------------------------------------------------------------

def encode_bits(
    bits: np.ndarray,
    *,
    bit_rate: int,
    tones: Sequence[float],
    fs: int = FS_DEFAULT,
) -> np.ndarray:
    """Modulate `bits` as M-FSK audio.

    Parameters
    ----------
    bits : np.ndarray, dtype int, shape (N,)
        Binary bit stream (values 0 or 1).
    bit_rate : int
        Gross bit rate in bits per second.
    tones : sequence of float
        FSK tone frequencies in Hz (length M=2^k).
        len(tones)==2 -> 2-FSK (1 bit/symbol)
        len(tones)==4 -> 4-FSK (2 bits/symbol)
        etc.
    fs : int
        Sample rate.

    Returns
    -------
    audio : np.ndarray, float32, shape (~N * samples_per_symbol,)
    """
    bits = np.asarray(bits, dtype=np.int32)
    tones = list(tones)
    M = len(tones)
    bits_per_sym = int(round(math.log2(M)))
    if 2 ** bits_per_sym != M:
        raise ValueError(f"len(tones)={M} must be a power of 2")

    # Pad bits so we have whole symbols
    remainder = len(bits) % bits_per_sym
    if remainder:
        bits = np.concatenate([bits, np.zeros(bits_per_sym - remainder, dtype=np.int32)])

    # Symbol rate and samples per symbol (keep it integer for clean alignment)
    symbol_rate = bit_rate / bits_per_sym
    sps = int(fs / symbol_rate)  # samples per symbol (floor)
    t_sym = np.arange(sps) / fs   # time axis for one symbol

    # Group bits into symbols
    n_syms = len(bits) // bits_per_sym
    sym_bits = bits[: n_syms * bits_per_sym].reshape(n_syms, bits_per_sym)
    # Convert bit groups to symbol indices (MSB first)
    powers = 2 ** np.arange(bits_per_sym - 1, -1, -1)
    sym_idx = (sym_bits * powers).sum(axis=1)  # shape (n_syms,)

    # Build audio symbol by symbol
    segments = []
    for idx in sym_idx:
        f = tones[int(idx)]
        segment = np.cos(2.0 * np.pi * f * t_sym).astype(np.float32)
        segments.append(segment)

    audio = np.concatenate(segments).astype(np.float32)
    return audio


# ---------------------------------------------------------------------------
# Decoder
# ---------------------------------------------------------------------------

def decode_bits(
    audio: np.ndarray,
    *,
    bit_rate: int,
    tones: Sequence[float],
    fs: int = FS_DEFAULT,
    n_bits: int,
) -> np.ndarray:
    """Demodulate M-FSK audio using matched-filter (energy detector) with known timing.

    Parameters
    ----------
    audio : np.ndarray, float32/64
        Received audio from encode_bits() -> channel().
    bit_rate : int
        Gross bit rate in bits per second (must match encoder).
    tones : sequence of float
        FSK tone frequencies in Hz.
    fs : int
        Sample rate.
    n_bits : int
        Expected number of bits (to trim padding).

    Returns
    -------
    bits : np.ndarray, dtype int, shape (n_bits,)
        Decoded bit stream.
    """
    audio = np.asarray(audio, dtype=np.float64)
    tones = list(tones)
    M = len(tones)
    bits_per_sym = int(round(math.log2(M)))

    symbol_rate = bit_rate / bits_per_sym
    sps = int(fs / symbol_rate)  # samples per symbol (same formula as encoder)

    n_syms_needed = math.ceil(n_bits / bits_per_sym)

    # Pre-compute matched filter kernels: exp(-j2pi*f*t) for each tone
    t_sym = np.arange(sps) / fs
    # kernels shape: (M, sps), complex
    kernels = np.exp(-1j * 2.0 * np.pi * np.array(tones)[:, None] * t_sym[None, :])

    decoded_syms = []
    for sym_i in range(n_syms_needed):
        start = sym_i * sps
        end = start + sps
        if end > len(audio):
            # Pad with zeros if audio is short (shouldn't happen in clean experiments)
            chunk = np.zeros(sps)
            chunk[: len(audio) - start] = audio[start : len(audio)]
        else:
            chunk = audio[start:end]

        # Matched filter: energy per tone = |sum(chunk * conj(kernel))|^2
        # = |dot(chunk, kernel^H)|^2 since kernel rows are our basis vectors
        energies = np.abs((kernels * chunk[None, :]).sum(axis=1)) ** 2
        best_tone = int(np.argmax(energies))
        decoded_syms.append(best_tone)

    # Convert symbol indices back to bits (MSB first)
    decoded_syms = np.array(decoded_syms, dtype=np.int32)
    powers = 2 ** np.arange(bits_per_sym - 1, -1, -1)
    bits_out = ((decoded_syms[:, None] & powers[None, :]) > 0).astype(np.int32)
    bits_flat = bits_out.flatten()[:n_bits]
    return bits_flat


# ---------------------------------------------------------------------------
# Timing-recovery decoder (DLL-like)
# ---------------------------------------------------------------------------

def decode_bits_with_timing(
    audio: np.ndarray,
    *,
    bit_rate: int,
    tones: Sequence[float],
    fs: int = FS_DEFAULT,
    n_bits: int,
    max_drift_samples: int | None = None,
) -> np.ndarray:
    """Demodulate M-FSK audio with a simple decision-directed timing tracker.

    Models a hardware PLL/DLL that tracks wow/flutter at frequencies <= ~5 Hz
    (the dominant cassette WF components). The tracker is a first-order loop
    that adjusts the symbol boundary estimate after each symbol by:
      - Computing energy for a 3-way search: nominal position, +shift, -shift
        where shift = sps // 4 (coarse fractional sample offset).
      - Moving the cursor toward the position of maximum energy.

    This is a simplified DLL (delay-locked loop) suitable for simulation purposes.
    It cannot track phase offsets faster than ~symbol_rate / 10, which is
    sufficient for cassette WF (0.55 Hz and 4.8 Hz components).

    Parameters
    ----------
    audio : np.ndarray
        Received audio.
    bit_rate : int
        Gross bit rate in bps.
    tones : sequence of float
        FSK tone frequencies.
    fs : int
        Sample rate.
    n_bits : int
        Expected number of bits.
    max_drift_samples : int or None
        Maximum number of samples the cursor is allowed to drift from nominal
        position per symbol (clamp). Default = sps // 2.

    Returns
    -------
    bits : np.ndarray, dtype int, shape (n_bits,)
    """
    audio = np.asarray(audio, dtype=np.float64)
    tones = list(tones)
    M = len(tones)
    bits_per_sym = int(round(math.log2(M)))

    symbol_rate = bit_rate / bits_per_sym
    sps = int(fs / symbol_rate)

    if max_drift_samples is None:
        max_drift_samples = sps // 2

    n_syms_needed = math.ceil(n_bits / bits_per_sym)

    # Pre-compute matched filter kernels
    t_sym = np.arange(sps) / fs
    kernels = np.exp(-1j * 2.0 * np.pi * np.array(tones)[:, None] * t_sym[None, :])

    # DLL parameters: coarse search offset = sps // 8, loop gain ~ 0.25
    search_shift = max(1, sps // 8)
    loop_gain = 0.25

    decoded_syms = []
    cursor = 0.0  # floating-point sample position of current symbol start
    cumulative_offset = 0  # integer cursor adjustment relative to nominal

    for sym_i in range(n_syms_needed):
        nominal_start = sym_i * sps + cumulative_offset

        # Try 3 candidate windows: nominal, early, late
        best_energy = -1.0
        best_offset = 0
        best_sym = 0

        for candidate_offset in (-search_shift, 0, search_shift):
            start = nominal_start + candidate_offset
            if start < 0:
                start = 0
            end = start + sps
            if end > len(audio):
                chunk = np.zeros(sps)
                available = len(audio) - start
                if available > 0:
                    chunk[:available] = audio[start : start + available]
            else:
                chunk = audio[start:end]

            energies = np.abs((kernels * chunk[None, :]).sum(axis=1)) ** 2
            total_e = float(np.max(energies))
            if total_e > best_energy:
                best_energy = total_e
                best_offset = candidate_offset
                best_sym = int(np.argmax(energies))

        decoded_syms.append(best_sym)

        # DLL update: move cursor toward the best-energy window
        update = int(round(loop_gain * best_offset))
        cumulative_offset += update
        # Clamp total drift
        cumulative_offset = int(np.clip(cumulative_offset, -max_drift_samples, max_drift_samples))

    # Convert symbol indices back to bits (MSB first)
    decoded_syms = np.array(decoded_syms, dtype=np.int32)
    powers = 2 ** np.arange(bits_per_sym - 1, -1, -1)
    bits_out = ((decoded_syms[:, None] & powers[None, :]) > 0).astype(np.int32)
    bits_flat = bits_out.flatten()[:n_bits]
    return bits_flat


# ---------------------------------------------------------------------------
# BER helper
# ---------------------------------------------------------------------------

def ber(tx_bits: np.ndarray, rx_bits: np.ndarray) -> float:
    """Bit error rate: fraction of positions that differ."""
    tx = np.asarray(tx_bits, dtype=np.int32).flatten()
    rx = np.asarray(rx_bits, dtype=np.int32).flatten()
    n = min(len(tx), len(rx))
    if n == 0:
        return 1.0
    return float(np.sum(tx[:n] != rx[:n])) / n
