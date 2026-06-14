"""modems_combo.py — Combinatorial K-of-M multitone FSK ladder for the tape_v2 physical test.

Exposes the FROZEN MODEM INTERFACE:

    SR = 48000
    CONFIGS = { "<config_name>": {<params>}, ... }   # ordered robust -> aggressive
    def modulate(payload: bytes, config: str) -> np.ndarray
    def demodulate(audio: np.ndarray, config: str) -> bytes | None

DSP reused from experiments/capacity/c2_combo_mfsk.py (ComboMFSKScheme).

Configs (robust -> aggressive):
    c2_m32_k2  M=32, K=2  ~8 bits/sym, robust
    c2_m32_k4  M=32, K=4  15 bits/sym, mid
    c2_m48_k6  M=48, K=6  23 bits/sym, aggressive (C2 capacity winner)

CANONICAL FRAME (shared across all tape_v2 modems):
    MAGIC(2) + len(2,BE) + payload(L) + CRC32(4,BE)
    CRC32 = zlib.crc32(payload)
"""

from __future__ import annotations

import math
import struct
import sys
import zlib
import pathlib

import numpy as np
from scipy.signal import resample_poly as _resample_poly
from fractions import Fraction

# ---------------------------------------------------------------------------
# Path bootstrap (canonical for this repo)
# ---------------------------------------------------------------------------
ROOT = pathlib.Path("/Users/magnus/repos/cassette-ai")
for _p in ["src", "tests/e2e"]:
    _fp = str(ROOT / _p)
    if _fp not in sys.path:
        sys.path.insert(0, _fp)

# The DSP lives in experiments/capacity/c2_combo_mfsk.py
_CAP = str(ROOT / "experiments" / "capacity")
if _CAP not in sys.path:
    sys.path.insert(0, _CAP)

import hyp_common as hc  # noqa: E402
from c2_combo_mfsk import ComboMFSKScheme  # noqa: E402

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
SR = 48_000
MAGIC = b"CA"
PREAMBLE_SECONDS = 0.25

# ---------------------------------------------------------------------------
# Config registry (ordered robust -> aggressive)
# ---------------------------------------------------------------------------
CONFIGS: dict[str, dict] = {
    "c2_m32_k2": {"M": 32, "K": 2},
    "c2_m32_k4": {"M": 32, "K": 4},
    "c2_m48_k6": {"M": 48, "K": 6},
}

# ---------------------------------------------------------------------------
# Per-config ComboMFSKScheme cache
# ---------------------------------------------------------------------------
_scheme_cache: dict[str, ComboMFSKScheme] = {}


def _get_scheme(config: str) -> ComboMFSKScheme:
    if config not in _scheme_cache:
        if config not in CONFIGS:
            raise ValueError(f"Unknown config '{config}'. Available: {list(CONFIGS)}")
        p = CONFIGS[config]
        _scheme_cache[config] = ComboMFSKScheme(
            M=p["M"], K=p["K"], preamble_seconds=PREAMBLE_SECONDS
        )
    return _scheme_cache[config]


# ---------------------------------------------------------------------------
# Canonical frame helpers
# ---------------------------------------------------------------------------

def _build_frame(payload: bytes) -> bytes:
    """Wrap payload in the canonical frame: MAGIC + len(2,BE) + payload + CRC32(4,BE)."""
    crc = zlib.crc32(payload) & 0xFFFFFFFF
    return MAGIC + struct.pack(">H", len(payload)) + payload + struct.pack(">I", crc)


def _parse_frame(frame_bytes: bytes) -> bytes | None:
    """Parse and verify a canonical frame. Returns payload bytes or None on error."""
    try:
        if len(frame_bytes) < 8:
            return None
        if frame_bytes[:2] != MAGIC:
            return None
        (L,) = struct.unpack(">H", frame_bytes[2:4])
        if len(frame_bytes) < 4 + L + 4:
            return None
        payload = frame_bytes[4: 4 + L]
        (stored_crc,) = struct.unpack(">I", frame_bytes[4 + L: 4 + L + 4])
        expected_crc = zlib.crc32(payload) & 0xFFFFFFFF
        if stored_crc != expected_crc:
            return None
        return payload
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Gross BPS helper
# ---------------------------------------------------------------------------

def gross_bps(config: str) -> float:
    """Return the gross bit-rate (bits/second) for a config, including preamble overhead."""
    scheme = _get_scheme(config)
    # Approximate: compute from a typical frame size (96-byte payload = 104-byte frame)
    sample_payload = bytes(96)
    frame = _build_frame(sample_payload)
    n_bits = len(frame) * 8
    bps = scheme.bits_per_sym
    n_syms = math.ceil(n_bits / bps)
    n_samples = int(PREAMBLE_SECONDS * SR) + n_syms * scheme.samples_per_sym
    duration = n_samples / SR
    return n_bits / duration if duration > 0 else 0.0


# ---------------------------------------------------------------------------
# Public interface: tx_bits / rx_bits / modulate / demodulate
# ---------------------------------------------------------------------------

def _build_bit_stream(payload: bytes, config: str) -> np.ndarray:
    """Return the EXACT bit stream fed to the symbol mapper for payload+config.

    Canonical frame bytes converted to bits MSB-first — no tail padding for
    combo (the tail guard in modulate() is silence samples, not extra bits).
    Shared by tx_bits() and modulate() so they cannot drift apart.
    """
    if config not in CONFIGS:
        raise ValueError(f"Unknown config '{config}'. Available: {list(CONFIGS)}")
    frame = _build_frame(payload)
    return np.unpackbits(np.frombuffer(frame, dtype=np.uint8), bitorder="big")


def tx_bits(payload: bytes, config: str) -> np.ndarray:
    """Return the ground-truth transmitted bit stream for payload+config.

    This is the EXACT bit sequence modulate() feeds to the K-of-M symbol mapper
    (canonical frame bits, MSB-first). Returned as a uint8 array.
    """
    return _build_bit_stream(payload, config)


def _sym_to_bits(scheme, start: int, audio: np.ndarray) -> np.ndarray:
    """Demodulate K-of-M symbols starting at sample `start`, return raw bits."""
    N = scheme.samples_per_sym
    data = audio[start:]
    n_complete = len(data) // N
    if n_complete == 0:
        return np.zeros(0, dtype=np.uint8)
    mat = data[:n_complete * N].reshape(n_complete, N).astype(np.float64)
    fft_mat = np.fft.rfft(mat, n=N, axis=1)
    bins = np.clip(scheme._bin_indices, 0, fft_mat.shape[1] - 1)
    energies = np.abs(fft_mat[:, bins])
    K = scheme.K
    top_k = np.argpartition(energies, -K, axis=1)[:, -K:]
    bps = scheme.bits_per_sym
    out_bits = np.empty(n_complete * bps, dtype=np.uint8)
    for i in range(n_complete):
        subset = tuple(sorted(top_k[i].tolist()))
        sym_idx = scheme._rev_table.get(subset, 0)
        sym_idx = min(sym_idx, scheme._sym_cap - 1)
        v = sym_idx
        b_arr = []
        for _ in range(bps):
            b_arr.append(v & 1)
            v >>= 1
        out_bits[i * bps:(i + 1) * bps] = np.array(b_arr[::-1], dtype=np.uint8)
    return out_bits


def _demod_raw_bits(audio: np.ndarray, config: str) -> np.ndarray:
    """Return raw recovered bits without the CRC gate.

    Uses the same chirp sync + symbol demod path as demodulate() but returns
    the raw bit stream at the tx_bits layer. Never raises; returns empty array
    on failure. Uses nominal_start directly (same as delta=0 in demodulate).
    """
    try:
        if config not in CONFIGS:
            return np.zeros(0, dtype=np.uint8)
        scheme = _get_scheme(config)
        audio = np.asarray(audio, dtype=np.float32)
        N = scheme.samples_per_sym
        nominal_start = hc.find_preamble(audio, PREAMBLE_SECONDS)
        # Use the same scan as demodulate() — try backward deltas first, return
        # the first offset that yields enough bits for a frame; otherwise return
        # from the nominal start (best-effort raw bits for BER measurement).
        guard = N // 2
        candidates = list(range(0, -guard - 1, -1)) + list(range(1, guard + 1))
        frame_bits_min = len(_build_bit_stream(bytes(1), config))
        best_bits = None
        for delta in candidates:
            start = max(0, nominal_start + delta)
            bits_out = _sym_to_bits(scheme, start, audio)
            if len(bits_out) >= frame_bits_min:
                return bits_out
            if best_bits is None or len(bits_out) > len(best_bits):
                best_bits = bits_out
        return best_bits if best_bits is not None else np.zeros(0, dtype=np.uint8)
    except Exception:
        return np.zeros(0, dtype=np.uint8)


def rx_bits(audio: np.ndarray, config: str) -> np.ndarray:
    """Best-effort recovered bit stream from audio (same path as demodulate).

    Returns raw recovered bits at the frame layer (no CRC gate). Never returns
    None. The caller is responsible for aligning length to tx_bits().
    """
    return _demod_raw_bits(audio, config)


def modulate(payload: bytes, config: str) -> np.ndarray:
    """payload bytes -> float32 PCM @48k with 0.25s chirp preamble.

    Frames the payload with the canonical frame, maps frame bytes to bits
    (MSB-first), modulates with the K-of-M scheme, peak-normalizes to 0.70.

    Appends one symbol-length of silence after the payload symbols to guard
    against the chirp correlator overshooting by a few tens of samples and
    making the last symbol incomplete.
    """
    scheme = _get_scheme(config)
    bits = _build_bit_stream(payload, config)
    audio = scheme.modulate(bits)
    # Add one symbol of silence as a tail guard
    tail = np.zeros(scheme.samples_per_sym, dtype=np.float32)
    audio = np.concatenate([audio, tail])
    # Peak-normalize to 0.70 (ComboMFSKScheme already does this on the body,
    # but the tail might affect the overall peak — re-normalize)
    peak = float(np.max(np.abs(audio)))
    if peak > 0:
        audio = (audio / peak * 0.70).astype(np.float32)
    return audio.astype(np.float32)


def _decode_from_offset(audio: np.ndarray, start: int, scheme) -> bytes | None:
    """Decode K-of-M symbols starting at sample `start` and parse canonical frame."""
    N = scheme.samples_per_sym
    data = audio[start:]
    n_complete = len(data) // N
    if n_complete == 0:
        return None

    mat = data[: n_complete * N].reshape(n_complete, N).astype(np.float64)
    fft_mat = np.fft.rfft(mat, n=N, axis=1)
    bins = np.clip(scheme._bin_indices, 0, fft_mat.shape[1] - 1)
    energies = np.abs(fft_mat[:, bins])

    K = scheme.K
    top_k = np.argpartition(energies, -K, axis=1)[:, -K:]

    bps = scheme.bits_per_sym
    out_bits = np.empty(n_complete * bps, dtype=np.uint8)
    for i in range(n_complete):
        subset = tuple(sorted(top_k[i].tolist()))
        sym_idx = scheme._rev_table.get(subset, 0)
        sym_idx = min(sym_idx, scheme._sym_cap - 1)
        v = sym_idx
        b = []
        for _ in range(bps):
            b.append(v & 1)
            v >>= 1
        out_bits[i * bps: (i + 1) * bps] = np.array(b[::-1], dtype=np.uint8)

    n_bytes = len(out_bits) // 8
    if n_bytes < 8:
        return None
    frame_bytes = np.packbits(out_bits[: n_bytes * 8], bitorder="big").tobytes()
    return _parse_frame(frame_bytes)


def demodulate(audio: np.ndarray, config: str) -> bytes | None:
    """audio @48k (float32) -> payload bytes, or None if CRC fails.

    Syncs via chirp cross-correlation (hc.find_preamble), then fine-scans
    ±half-symbol around the correlation peak to compensate for the small
    overshoot inherent in the chirp correlator. Returns the first start
    offset that yields a valid CRC, or None.
    Never raises.
    """
    try:
        scheme = _get_scheme(config)
        audio = np.asarray(audio, dtype=np.float32)

        N = scheme.samples_per_sym
        nominal_start = hc.find_preamble(audio, PREAMBLE_SECONDS)

        # The chirp correlator tends to report a data_start that is slightly
        # LATE (by 10-50 samples) — preamble energy bleeds into the first
        # symbol window.  Scan backward first (negative deltas), then forward,
        # with step = 1 sample so we never miss the exact frame boundary.
        # Guard ±(N//2) covers the worst-case overshoot observed in sim.
        guard = N // 2
        # Prioritise negative deltas (back off from late estimate) then positive
        candidates = list(range(0, -guard - 1, -1)) + list(range(1, guard + 1))
        for delta in candidates:
            start = max(0, nominal_start + delta)
            result = _decode_from_offset(audio, start, scheme)
            if result is not None:
                return result
        return None
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Self-test
# ---------------------------------------------------------------------------

def self_test_clean_roundtrip(payload: bytes | None = None) -> dict[str, bool]:
    """Verify byte-exact clean (no channel) round-trip for all configs.

    Returns {config_name: True/False}.
    """
    if payload is None:
        payload = bytes(range(96))  # 96 bytes
    results = {}
    for cfg in CONFIGS:
        audio = modulate(payload, cfg)
        recovered = demodulate(audio, cfg)
        results[cfg] = recovered == payload
    return results


def self_test_channel(
    n_seeds: int = 8,
    payload: bytes | None = None,
) -> dict[str, dict]:
    """Run channel sim (normal + worn) for all configs.

    Returns per-config dict with normal_passrate and worn_passrate.
    Applies a global resample-to-nominal for the worn+speed_offset=-0.12 case,
    mimicking the tape_v2 analyzer.
    """
    import capture_scenarios as cs  # noqa: E402

    if payload is None:
        # Use a 96-byte payload with recognizable content
        import hashlib
        payload = hashlib.sha256(b"tape_v2_combo_test").digest()[:96]

    results: dict[str, dict] = {}

    for cfg in CONFIGS:
        normal_pass = 0
        worn_pass = 0

        audio_tx = modulate(payload, cfg)

        for seed in range(n_seeds):
            # --- Normal channel, no speed offset ---
            rx_normal, sr, _diag = cs.full_chain(
                audio_tx, "normal", "usb_soundcard", speed_offset=0.0, seed=seed
            )
            rec_normal = demodulate(rx_normal.astype(np.float32), cfg)
            if rec_normal == payload:
                normal_pass += 1

            # --- Worn channel, speed_offset=-0.12 (deck running at ~0.88x) ---
            # tape_core resamples by (1 + speed_offset) = 0.88, making the signal
            # SHORTER (fewer samples).  The tape_v2 analyzer would resample the
            # received audio back to nominal by the inverse factor (1/0.88 = 25/22)
            # before handing to demodulate.  Replicate that here.
            rx_worn_raw, sr_w, _diag_w = cs.full_chain(
                audio_tx, "worn", "usb_soundcard", speed_offset=-0.12, seed=seed
            )
            # Inverse resample: multiply length by 1/(1+speed_offset) = 1/0.88 = 25/22
            speed = 1.0 + (-0.12)          # 0.88
            frac = Fraction(speed).limit_denominator(4000)
            # frac = 22/25; inverse is 25/22 — stretch back to nominal length
            rx_worn = _resample_poly(
                rx_worn_raw.astype(np.float64), frac.denominator, frac.numerator
            ).astype(np.float32)
            rec_worn = demodulate(rx_worn, cfg)
            if rec_worn == payload:
                worn_pass += 1

        results[cfg] = {
            "gross_bps": gross_bps(cfg),
            "normal_passrate": normal_pass / n_seeds,
            "worn_passrate": worn_pass / n_seeds,
            "n_seeds": n_seeds,
        }

    return results


# ---------------------------------------------------------------------------
# Module main — run self-tests and print summary
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import json

    print("=" * 65)
    print("modems_combo.py — self-test")
    print("=" * 65)

    # 0. tx_bits / rx_bits alignment check (clean round-trip, hamming must be 0)
    print("\n[0] tx_bits / rx_bits alignment check (no channel)")
    _test_payload = bytes(range(96))
    _all_bits_ok = True
    for _cfg in CONFIGS:
        _tb = tx_bits(_test_payload, _cfg)
        _audio = modulate(_test_payload, _cfg)
        _rb = rx_bits(_audio, _cfg)
        _n = len(_tb)
        if len(_rb) < _n:
            _rb = np.concatenate([_rb, np.zeros(_n - len(_rb), dtype=np.uint8)])
        else:
            _rb = _rb[:_n]
        _hamming = int(np.count_nonzero(_tb != _rb))
        _ok = _hamming == 0
        _all_bits_ok = _all_bits_ok and _ok
        print(f"  {_cfg}: hamming={_hamming}  {'OK' if _ok else 'FAIL — alignment wrong!'}")
    if not _all_bits_ok:
        print("  ERROR: tx_bits/rx_bits alignment failed")
        sys.exit(1)

    # 1. Clean round-trip
    print("\n[1] Clean round-trip (no channel)")
    payload_clean = bytes(range(96))
    rt = self_test_clean_roundtrip(payload_clean)
    all_clean_ok = True
    for cfg, ok in rt.items():
        status = "PASS" if ok else "FAIL"
        print(f"  {cfg}: {status}")
        if not ok:
            all_clean_ok = False
    print(f"  All clean: {all_clean_ok}")

    if not all_clean_ok:
        print("\nERROR: clean round-trip failed — bug in DSP. Aborting sim tests.")
        sys.exit(1)

    # 2. Channel sim
    print("\n[2] Channel sim (8 seeds each)")
    ch_results = self_test_channel(n_seeds=8)
    print(f"\n  {'Config':<14}  {'gross_bps':>9}  {'normal_pass':>11}  {'worn_pass':>10}")
    print(f"  {'-'*14}  {'-'*9}  {'-'*11}  {'-'*10}")
    for cfg, r in ch_results.items():
        print(
            f"  {cfg:<14}  {r['gross_bps']:>9.0f}  "
            f"{r['normal_passrate']:>11.2f}  {r['worn_passrate']:>10.2f}"
        )

    print("\n" + "=" * 65)
    print("Done.")
