from __future__ import annotations

import hashlib
import struct
import zlib
from dataclasses import dataclass

import numpy as np
from scipy.signal import chirp


SAMPLE_RATE = 48_000
BIT_RATE = 1_200
SAMPLES_PER_BIT = SAMPLE_RATE // BIT_RATE
FREQ_ZERO = 1_200.0
FREQ_ONE = 2_400.0
LEADER_SECONDS = 2.0
SYNC_SECONDS = 0.25
TRAILER_SECONDS = 1.0
FRAME_PAYLOAD_BYTES = 256
FORMAT_VERSION = 3
MAGIC = b"CAS3"
RESYNC_MARKER = b"\x1d\xea\xc0\xde"
TAIL_MARKER = b"TAIL"

HEADER = struct.Struct("<4sBBHIIHIH32s")
FRAME_PREFIX = struct.Struct("<4sIH")
TAIL = struct.Struct("<4sI32sI")


@dataclass(frozen=True)
class CassetteHeader:
    version: int
    flags: int
    payload_len: int
    frame_payload_bytes: int
    frame_count: int
    sample_rate: int
    bit_rate: int
    payload_hash: bytes


@dataclass(frozen=True)
class DecodeResult:
    payload: bytes
    header: CassetteHeader | None
    recovered_frames: int
    missing_frames: tuple[int, ...]
    bad_frames: int
    tail_hash_ok: bool
    complete: bool
    errors: tuple[str, ...]


def cassette_payload(name: str, size: int) -> bytes:
    """Deterministic bytes for roundtrip/profile tests."""
    out = bytearray()
    counter = 0
    seed = name.encode("utf-8")
    while len(out) < size:
        out.extend(hashlib.sha256(seed + counter.to_bytes(4, "little")).digest())
        counter += 1
    return bytes(out[:size])


def encode_container(payload: bytes, frame_payload_bytes: int = FRAME_PAYLOAD_BYTES) -> bytes:
    frame_count = (len(payload) + frame_payload_bytes - 1) // frame_payload_bytes
    payload_hash = hashlib.sha256(payload).digest()
    header = HEADER.pack(
        MAGIC,
        FORMAT_VERSION,
        0,
        HEADER.size,
        len(payload),
        frame_count,
        frame_payload_bytes,
        SAMPLE_RATE,
        BIT_RATE,
        payload_hash,
    )
    chunks = [header]
    for seq in range(frame_count):
        chunk = payload[seq * frame_payload_bytes : (seq + 1) * frame_payload_bytes]
        prefix = FRAME_PREFIX.pack(RESYNC_MARKER, seq, len(chunk))
        crc = zlib.crc32(prefix[4:] + chunk) & 0xFFFFFFFF
        chunks.append(prefix + chunk + struct.pack("<I", crc))
    tail_crc = zlib.crc32(payload_hash + struct.pack("<I", frame_count)) & 0xFFFFFFFF
    chunks.append(TAIL.pack(TAIL_MARKER, frame_count, payload_hash, tail_crc))
    return b"".join(chunks)


def decode_container(container: bytes) -> DecodeResult:
    errors: list[str] = []
    header = _parse_header(container, errors)
    if header is None:
        return DecodeResult(b"", None, 0, (), 0, False, False, tuple(errors))

    pos = HEADER.size
    frames: dict[int, bytes] = {}
    bad_frames = 0
    tail_hash_ok = False
    while pos < len(container):
        marker_at = container.find(RESYNC_MARKER, pos)
        tail_at = container.find(TAIL_MARKER, pos)
        if tail_at != -1 and (marker_at == -1 or tail_at < marker_at):
            tail_hash_ok = _parse_tail(container[tail_at:], header, errors)
            break
        if marker_at == -1:
            errors.append("no_more_resync_markers")
            break
        if marker_at + FRAME_PREFIX.size > len(container):
            errors.append("truncated_frame_prefix")
            break
        _, seq, length = FRAME_PREFIX.unpack_from(container, marker_at)
        frame_end = marker_at + FRAME_PREFIX.size + length + 4
        if frame_end > len(container):
            errors.append(f"truncated_frame:{seq}")
            bad_frames += 1
            break
        payload = container[marker_at + FRAME_PREFIX.size : marker_at + FRAME_PREFIX.size + length]
        expected_crc = struct.unpack_from("<I", container, frame_end - 4)[0]
        actual_crc = zlib.crc32(container[marker_at + 4 : marker_at + FRAME_PREFIX.size] + payload) & 0xFFFFFFFF
        if seq >= header.frame_count:
            errors.append(f"out_of_range_frame:{seq}")
            bad_frames += 1
        elif expected_crc == actual_crc:
            frames.setdefault(seq, payload)
        else:
            errors.append(f"crc_fail_frame:{seq}")
            bad_frames += 1
        pos = frame_end

    missing = tuple(seq for seq in range(header.frame_count) if seq not in frames)
    payload = b"".join(frames[seq] for seq in range(header.frame_count) if seq in frames)[: header.payload_len]
    payload_hash_ok = hashlib.sha256(payload).digest() == header.payload_hash
    complete = not missing and bad_frames == 0 and tail_hash_ok and payload_hash_ok
    if missing:
        errors.append(f"missing_frames:{len(missing)}")
    if not payload_hash_ok:
        errors.append("payload_hash_mismatch")
    return DecodeResult(payload, header, len(frames), missing, bad_frames, tail_hash_ok, complete, tuple(errors))


def encode_audio(payload: bytes) -> np.ndarray:
    bits = _bytes_to_bits(encode_container(payload))
    leader = _tone(FREQ_ZERO, LEADER_SECONDS, phase=0.0)
    sync = _sync_chirp()
    data = _bits_to_fsk(bits)
    trailer = _tone(FREQ_ZERO, TRAILER_SECONDS, phase=0.0)
    return np.concatenate([leader, sync, data, trailer]).astype(np.float32)


def decode_audio(audio: np.ndarray) -> DecodeResult:
    start = int((LEADER_SECONDS + SYNC_SECONDS) * SAMPLE_RATE)
    end = len(audio) - int(TRAILER_SECONDS * SAMPLE_RATE)
    if start >= end:
        return DecodeResult(b"", None, 0, (), 0, False, False, ("audio_too_short",))
    bits = _fsk_to_bits(np.asarray(audio[start:end], dtype=np.float32))
    container = _bits_to_bytes(bits)
    return decode_container(container)


def tape_seconds_for_payload(payload_len: int) -> float:
    frame_count = (payload_len + FRAME_PAYLOAD_BYTES - 1) // FRAME_PAYLOAD_BYTES
    container_len = HEADER.size + frame_count * (FRAME_PREFIX.size + FRAME_PAYLOAD_BYTES + 4) + TAIL.size
    data_seconds = container_len * 8 / BIT_RATE
    return LEADER_SECONDS + SYNC_SECONDS + data_seconds + TRAILER_SECONDS


def _parse_header(container: bytes, errors: list[str]) -> CassetteHeader | None:
    if len(container) < HEADER.size:
        errors.append("truncated_header")
        return None
    magic, version, flags, header_len, payload_len, frame_count, frame_bytes, sample_rate, bit_rate, payload_hash = HEADER.unpack_from(container)
    if magic != MAGIC:
        errors.append("bad_magic")
        return None
    if version != FORMAT_VERSION:
        errors.append(f"unsupported_version:{version}")
        return None
    if header_len != HEADER.size:
        errors.append(f"unsupported_header_len:{header_len}")
        return None
    if sample_rate != SAMPLE_RATE:
        errors.append(f"unsupported_sample_rate:{sample_rate}")
        return None
    if bit_rate != BIT_RATE:
        errors.append(f"unsupported_bit_rate:{bit_rate}")
        return None
    expected_frames = (payload_len + frame_bytes - 1) // frame_bytes
    if frame_count != expected_frames:
        errors.append("frame_count_mismatch")
        return None
    return CassetteHeader(version, flags, payload_len, frame_bytes, frame_count, sample_rate, bit_rate, payload_hash)


def _parse_tail(tail_bytes: bytes, header: CassetteHeader, errors: list[str]) -> bool:
    if len(tail_bytes) < TAIL.size:
        errors.append("truncated_tail")
        return False
    marker, frame_count, payload_hash, expected_crc = TAIL.unpack_from(tail_bytes)
    actual_crc = zlib.crc32(payload_hash + struct.pack("<I", frame_count)) & 0xFFFFFFFF
    ok = marker == TAIL_MARKER and frame_count == header.frame_count and payload_hash == header.payload_hash and expected_crc == actual_crc
    if not ok:
        errors.append("tail_mismatch")
    return ok


def _bytes_to_bits(data: bytes) -> np.ndarray:
    return np.unpackbits(np.frombuffer(data, dtype=np.uint8), bitorder="big")


def _bits_to_bytes(bits: np.ndarray) -> bytes:
    usable = len(bits) - (len(bits) % 8)
    if usable <= 0:
        return b""
    return np.packbits(bits[:usable].astype(np.uint8), bitorder="big").tobytes()


def _tone(freq: float, seconds: float, phase: float) -> np.ndarray:
    n = int(seconds * SAMPLE_RATE)
    t = np.arange(n, dtype=np.float64) / SAMPLE_RATE
    return 0.65 * np.sin((2.0 * np.pi * freq * t) + phase)


def _sync_chirp() -> np.ndarray:
    n = int(SYNC_SECONDS * SAMPLE_RATE)
    t = np.arange(n, dtype=np.float64) / SAMPLE_RATE
    return 0.65 * chirp(t, f0=800.0, f1=3_200.0, t1=SYNC_SECONDS, method="linear")


def _bits_to_fsk(bits: np.ndarray) -> np.ndarray:
    t = np.arange(SAMPLES_PER_BIT, dtype=np.float64) / SAMPLE_RATE
    zero = np.sin(2.0 * np.pi * FREQ_ZERO * t)
    one = np.sin(2.0 * np.pi * FREQ_ONE * t)
    symbols = np.where(bits[:, None] > 0, one, zero)
    return (0.65 * symbols.reshape(-1)).astype(np.float32)


def _fsk_to_bits(audio: np.ndarray) -> np.ndarray:
    usable = len(audio) - (len(audio) % SAMPLES_PER_BIT)
    symbols = audio[:usable].reshape(-1, SAMPLES_PER_BIT).astype(np.float64, copy=False)
    t = np.arange(SAMPLES_PER_BIT, dtype=np.float64) / SAMPLE_RATE
    zero = np.sin(2.0 * np.pi * FREQ_ZERO * t)
    one = np.sin(2.0 * np.pi * FREQ_ONE * t)
    score_zero = np.abs(np.sum(symbols * zero, axis=1))
    score_one = np.abs(np.sum(symbols * one, axis=1))
    return (score_one > score_zero).astype(np.uint8)
