"""modems_index.py — Single-tone index-modulation modem ladder for physical tape tests.

Exposes the FROZEN MODEM INTERFACE:
    SR       = 48000
    CONFIGS  = { "<name>": {<params>} ... }   # ordered robust -> aggressive
    modulate(payload: bytes, config: str) -> np.ndarray
    demodulate(audio: np.ndarray, config: str) -> bytes | None

Two configs (robust -> aggressive):
  "mfsk32"      : Plain MFSK-32 (reference anchor), reusing MFSKScheme(M=32,walsh_k=0).
  "c1_gray_m16" : Gray-coded MFSK M=16 over 400-7000 Hz, reusing GrayMFSKScheme.

Every call frames the payload with the CANONICAL FRAME (MAGIC + len + payload + CRC32)
before converting to bits, and verifies the frame on receive.
"""

from __future__ import annotations

import struct
import sys
import zlib
import pathlib

import numpy as np
from scipy.signal import resample_poly
from fractions import Fraction

# ---------------------------------------------------------------------------
# Path bootstrap
# ---------------------------------------------------------------------------
ROOT = pathlib.Path("/Users/magnus/repos/cassette-ai")
for _p in ["src", "tests/e2e"]:
    _full = str(ROOT / _p)
    if _full not in sys.path:
        sys.path.insert(0, _full)

# Experiments capacity path for c1_gray_mfsk
_CAP = str(ROOT / "experiments" / "capacity")
if _CAP not in sys.path:
    sys.path.insert(0, _CAP)

import hyp_common as hc               # noqa: E402
from hyp_h2_mfsk import MFSKScheme    # noqa: E402
from c1_gray_mfsk import GrayMFSKScheme  # noqa: E402

SR = 48_000

# ---------------------------------------------------------------------------
# CONFIGS: ordered robust -> aggressive
# ---------------------------------------------------------------------------
CONFIGS: dict[str, dict] = {
    "mfsk32": {
        "M": 32,
        "walsh_k": 0,
        "description": "Plain MFSK-32 — reference anchor, most robust",
    },
    "c1_gray_m16": {
        "M": 16,
        "bw_low": 400.0,
        "bw_high": 7000.0,
        "tsym_mult": 1.0,
        "description": "Gray-coded MFSK M=16, 400-7000 Hz — higher throughput",
    },
}

# ---------------------------------------------------------------------------
# Canonical frame helpers
# ---------------------------------------------------------------------------
MAGIC = b"CA"


def _frame(payload: bytes) -> bytes:
    """Wrap payload in canonical frame: MAGIC + 2-byte len + payload + 4-byte CRC32."""
    length = struct.pack(">H", len(payload))
    crc = struct.pack(">I", zlib.crc32(payload) & 0xFFFFFFFF)
    return MAGIC + length + payload + crc


def _unframe(data: bytes) -> bytes | None:
    """Parse canonical frame; return payload bytes on success, None on any error."""
    try:
        if len(data) < 8:
            return None
        if data[:2] != MAGIC:
            return None
        L = struct.unpack(">H", data[2:4])[0]
        if len(data) < 4 + L + 4:
            return None
        payload = data[4:4 + L]
        stored_crc = struct.unpack(">I", data[4 + L:4 + L + 4])[0]
        computed_crc = zlib.crc32(payload) & 0xFFFFFFFF
        if stored_crc != computed_crc:
            return None
        return payload
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Bit packing helpers
# ---------------------------------------------------------------------------

def _bytes_to_bits(data: bytes) -> np.ndarray:
    """Convert bytes to MSB-first bit array (uint8)."""
    return np.unpackbits(np.frombuffer(data, dtype=np.uint8), bitorder="big")


def _bits_to_bytes(bits: np.ndarray) -> bytes:
    """Convert MSB-first bit array to bytes (pads to multiple of 8)."""
    bits = np.asarray(bits, dtype=np.uint8)
    # Trim to multiple of 8
    trim = (len(bits) // 8) * 8
    if trim == 0:
        return b""
    return np.packbits(bits[:trim], bitorder="big").tobytes()


# ---------------------------------------------------------------------------
# Scheme builders (cached)
# ---------------------------------------------------------------------------
_schemes: dict[str, object] = {}


def _get_scheme(config: str):
    """Return (and cache) the underlying scheme object for the given config."""
    if config in _schemes:
        return _schemes[config]
    if config == "mfsk32":
        s = MFSKScheme(M=32, walsh_k=0)
    elif config == "c1_gray_m16":
        s = GrayMFSKScheme(M=16, bw_low=400.0, bw_high=7000.0, tsym_mult=1.0)
    else:
        raise ValueError(f"Unknown config: {config!r}. Available: {list(CONFIGS)}")
    _schemes[config] = s
    return s


# ---------------------------------------------------------------------------
# Frozen interface
# ---------------------------------------------------------------------------

def _build_bit_stream(payload: bytes, config: str) -> np.ndarray:
    """Return the EXACT bit stream fed to the symbol mapper for payload+config.

    Canonical frame bits + 4-symbol tail of zeros (the same tail guard used
    by modulate). This is the shared internal that both modulate() and
    tx_bits() call so they cannot drift apart.
    """
    if config not in CONFIGS:
        raise ValueError(f"Unknown config: {config!r}. Available: {list(CONFIGS)}")
    frame = _frame(payload)
    bits = _bytes_to_bits(frame)
    scheme = _get_scheme(config)
    bps = scheme.bits_per_sym
    tail = np.zeros(4 * bps, dtype=np.uint8)
    return np.concatenate([bits, tail])


def tx_bits(payload: bytes, config: str) -> np.ndarray:
    """Return the ground-truth transmitted bit stream for payload+config.

    This is the EXACT bit sequence that modulate() feeds to the symbol mapper
    (canonical frame + tail guard), returned as a uint8 array. tx_bits and
    modulate() share _build_bit_stream() so they cannot drift apart.
    """
    return _build_bit_stream(payload, config)


def _demod_raw_bits(audio: np.ndarray, config: str) -> np.ndarray:
    """Return raw recovered bits from audio (no CRC gate, no None).

    Uses the SAME sync + demod path as demodulate() but returns the raw bit
    array without the CRC/frame validation step. Never raises; returns an empty
    array on catastrophic failure.
    """
    try:
        if config not in CONFIGS:
            return np.zeros(0, dtype=np.uint8)
        audio = np.asarray(audio, dtype=np.float32)
        scheme = _get_scheme(config)
        return np.asarray(scheme.demodulate(audio, SR), dtype=np.uint8)
    except Exception:
        return np.zeros(0, dtype=np.uint8)


def rx_bits(audio: np.ndarray, config: str) -> np.ndarray:
    """Best-effort recovered bit stream from audio (same path as demodulate).

    Returns the raw recovered bits (same framing layer as tx_bits), zero-padded
    or truncated to len(tx_bits(payload, config)) for a canonical 96-byte
    payload. For BER measurement the caller is expected to align lengths using
    the companion tx_bits() call.

    Never returns None; zero-pads/truncates to match the tx_bits length.
    """
    return _demod_raw_bits(audio, config)


def modulate(payload: bytes, config: str) -> np.ndarray:
    """Encode payload into audio.

    Frames payload with canonical frame, converts frame bytes -> bits MSB-first,
    appends a tail of 2 extra symbol-loads of zero bits (so preamble-sync jitter
    cannot cut off the last frame symbol), modulates, and peak-normalises to 0.70.

    Returns float32 @48k.
    """
    bits_with_tail = _build_bit_stream(payload, config)

    scheme = _get_scheme(config)
    audio = scheme.modulate(bits_with_tail)
    audio = np.asarray(audio, dtype=np.float32)

    peak = float(np.max(np.abs(audio)))
    if peak > 0:
        audio = (audio / peak * 0.70).astype(np.float32)
    return audio


def demodulate(audio: np.ndarray, config: str) -> bytes | None:
    """Decode audio to payload bytes.

    Syncs to the 0.25 s chirp preamble (via hc.find_preamble), recovers bits,
    converts to bytes, parses the canonical frame, verifies CRC.
    Returns payload bytes on success, None on any failure. Never raises.
    """
    try:
        if config not in CONFIGS:
            return None

        audio = np.asarray(audio, dtype=np.float32)
        scheme = _get_scheme(config)

        # The scheme's own demodulate does find_preamble sync internally.
        bits = scheme.demodulate(audio, SR)
        frame_bytes = _bits_to_bytes(bits)
        return _unframe(frame_bytes)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Gross bps accessor (convenience, mirrors scheme value)
# ---------------------------------------------------------------------------

def gross_bps(config: str) -> float:
    """Return the gross_bps for the given config (preamble overhead included)."""
    return float(_get_scheme(config).gross_bps)


# ---------------------------------------------------------------------------
# Self-test / simulation measurement
# ---------------------------------------------------------------------------

def _resample_to_nominal(audio: np.ndarray, speed_offset: float) -> np.ndarray:
    """Undo a known speed offset (mimic analyzer's global resample-to-nominal step).

    If the tape ran at (1 + speed_offset) * nominal, the captured audio is
    stretched/compressed by that factor relative to nominal. To restore nominal
    timing we resample by 1/(1+speed_offset).
    """
    if abs(speed_offset) < 1e-9:
        return audio
    # The tape ran faster/slower; to undo, resample by inverse ratio.
    ratio = 1.0 / (1.0 + speed_offset)
    frac = Fraction(ratio).limit_denominator(4000)
    return resample_poly(
        audio.astype(np.float64), frac.numerator, frac.denominator
    ).astype(np.float32)


def run_self_test(
    n_seeds: int = 8,
    payload: bytes | None = None,
) -> dict:
    """Run the full self-test for all configs and return a structured result dict.

    For each config:
      1. Clean round-trip (no channel): modulate -> demodulate.  Must be byte-exact.
      2. normal_passrate: n_seeds seeds through cs.full_chain("normal", speed_offset=0.0).
      3. worn_passrate  : n_seeds seeds through cs.full_chain("worn", speed_offset=-0.12),
                          with a global resample-to-nominal step before decode.

    Pass = frame CRC checks AND payload bytes exactly equal tx payload.
    """
    import capture_scenarios as cs  # imported late to keep module loadable without it

    if payload is None:
        # ~96-byte test payload (printable ASCII for easy inspection)
        payload = (
            b"CASSETTE-AI tape_v2 self-test payload 0123456789 "
            b"ABCDEFGHIJKLMNOPQRSTUVWXYZ abcdefghijklmnopqrstu"
        )
        # Trim/pad to exactly 96 bytes
        payload = (payload * 2)[:96]

    results_per_config: list[dict] = []
    all_clean_ok = True

    for config in CONFIGS:
        # ------------------------------------------------------------------
        # 1. Clean round-trip
        # ------------------------------------------------------------------
        audio_clean = modulate(payload, config)
        rx_clean = demodulate(audio_clean, config)
        clean_ok = rx_clean == payload
        if not clean_ok:
            all_clean_ok = False
            print(
                f"[SELF-TEST] {config}: CLEAN ROUND-TRIP FAILED "
                f"rx={rx_clean!r} tx={payload!r}"
            )

        # ------------------------------------------------------------------
        # 2. Normal channel passrate
        # ------------------------------------------------------------------
        normal_pass = 0
        for seed in range(n_seeds):
            rx_audio, _sr, _diag = cs.full_chain(
                audio_clean, "normal", "usb_soundcard",
                speed_offset=0.0, seed=seed,
            )
            rx = demodulate(rx_audio, config)
            if rx == payload:
                normal_pass += 1
        normal_passrate = normal_pass / n_seeds

        # ------------------------------------------------------------------
        # 3. Worn channel passrate (speed_offset=-0.12, then resample-to-nominal)
        # ------------------------------------------------------------------
        worn_pass = 0
        for seed in range(n_seeds):
            rx_audio, _sr, _diag = cs.full_chain(
                audio_clean, "worn", "usb_soundcard",
                speed_offset=-0.12, seed=seed,
            )
            # Mimic analyzer: global resample to nominal speed before decode
            rx_audio_nominal = _resample_to_nominal(rx_audio, speed_offset=-0.12)
            rx = demodulate(rx_audio_nominal, config)
            if rx == payload:
                worn_pass += 1
        worn_passrate = worn_pass / n_seeds

        g_bps = gross_bps(config)
        row = {
            "config": config,
            "gross_bps": g_bps,
            "clean_ok": clean_ok,
            "normal_passrate": normal_passrate,
            "worn_passrate": worn_passrate,
            "normal_pass": normal_pass,
            "worn_pass": worn_pass,
            "n_seeds": n_seeds,
        }
        results_per_config.append(row)

        print(
            f"[SELF-TEST] {config:20s}  gross={g_bps:6.0f} bps  "
            f"clean={'OK' if clean_ok else 'FAIL'}  "
            f"normal={normal_passrate:.2f}  worn={worn_passrate:.2f}"
        )

    return {
        "clean_roundtrip_ok": all_clean_ok,
        "per_config": results_per_config,
        "payload_len": len(payload),
        "n_seeds": n_seeds,
    }


if __name__ == "__main__":
    print("=" * 60)
    print("modems_index.py self-test")
    print("=" * 60)

    # --- tx_bits / rx_bits alignment check (clean round-trip, hamming must be 0) ---
    _test_payload = (b"CASSETTE-AI tape_v2 self-test payload 0123456789 "
                     b"ABCDEFGHIJKLMNOPQRSTUVWXYZ abcdefghijklmnopqrstu")
    _test_payload = (_test_payload * 2)[:96]
    print("\n[tx/rx bit alignment check]")
    _all_bits_ok = True
    for _cfg in CONFIGS:
        _tb = tx_bits(_test_payload, _cfg)
        _audio = modulate(_test_payload, _cfg)
        _rb = rx_bits(_audio, _cfg)
        # Align lengths: truncate/pad rx to tx length
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
        print("  ERROR: tx_bits/rx_bits alignment failed — fix before continuing")
        sys.exit(1)

    result = run_self_test(n_seeds=8)
    print()
    print(f"clean_roundtrip_ok : {result['clean_roundtrip_ok']}")
    for row in result["per_config"]:
        print(
            f"  {row['config']:20s}  gross={row['gross_bps']:6.0f}  "
            f"normal={row['normal_passrate']:.2f}  worn={row['worn_passrate']:.2f}"
        )
