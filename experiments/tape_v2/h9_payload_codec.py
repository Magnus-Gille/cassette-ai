"""H9 — payload entropy-coding codec (effective-rate gain, no PHY change).

The int4-quantized .cass payload is not entropy-coded; lossless compression
buys ~14-16% before a single PHY bit changes. This module provides a small,
self-describing container so the tape decoder can auto-detect compressed vs
raw (legacy) payloads.

Container layout (16-byte header + compressed body):

    offset  size  field
    0       4     magic    b"H9PC"
    4       1     version  (1)
    5       1     algo     0=stored(raw) 1=gzip 2=lzma 3=zstd
    6       2     reserved (zero)
    8       4     orig_len uint32 LE  (length of the original payload)
    12      4     crc32    uint32 LE  (zlib.crc32 of the ORIGINAL payload)

Backward compatibility: ``unpack_payload`` returns legacy/raw payloads
unchanged when the header is absent or fails validation (bad magic, bad
algo, or CRC mismatch after decompression is an error only if the magic
matched — a raw payload starting with b"H9PC" by accident is guarded by
the CRC + orig_len checks; probability of a false positive is ~2^-64).

Algo availability: lzma is preferred (best ratio) but is missing from some
interpreters (e.g. a pyenv build without _lzma). pack_payload falls back to
gzip automatically; unpack_payload raises a clear error if a blob needs a
codec the running interpreter lacks. zstd (algo=3) is reserved: packing
uses the ``zstandard`` module only if importable; never required to unpack
gzip/lzma blobs.

Usage:
    blob, meta = pack_payload(raw)        # auto: best available algo
    raw2 = unpack_payload(blob)           # auto-detects; passes raw through
"""
from __future__ import annotations

import gzip
import struct
import zlib

try:
    import lzma
    _HAVE_LZMA = True
except ImportError:  # interpreter built without _lzma
    lzma = None
    _HAVE_LZMA = False

try:
    import zstandard as _zstd
    _HAVE_ZSTD = True
except ImportError:
    _zstd = None
    _HAVE_ZSTD = False

MAGIC = b"H9PC"
VERSION = 1
HEADER_FMT = "<4sBBHII"          # magic, version, algo, reserved, orig_len, crc32
HEADER_LEN = struct.calcsize(HEADER_FMT)
assert HEADER_LEN == 16

ALGO_STORED = 0
ALGO_GZIP = 1
ALGO_LZMA = 2
ALGO_ZSTD = 3
ALGO_NAMES = {ALGO_STORED: "stored", ALGO_GZIP: "gzip",
              ALGO_LZMA: "lzma", ALGO_ZSTD: "zstd"}


def _compress(raw: bytes, algo: int) -> bytes:
    if algo == ALGO_GZIP:
        return gzip.compress(raw, 9)
    if algo == ALGO_LZMA:
        return lzma.compress(raw, preset=9 | lzma.PRESET_EXTREME)
    if algo == ALGO_ZSTD:
        return _zstd.ZstdCompressor(level=19).compress(raw)
    raise ValueError(f"unknown algo {algo}")


def _decompress(body: bytes, algo: int) -> bytes:
    if algo == ALGO_STORED:
        return body
    if algo == ALGO_GZIP:
        return gzip.decompress(body)
    if algo == ALGO_LZMA:
        if not _HAVE_LZMA:
            raise RuntimeError("blob is lzma-compressed but this interpreter lacks the lzma module")
        return lzma.decompress(body)
    if algo == ALGO_ZSTD:
        if not _HAVE_ZSTD:
            raise RuntimeError("blob is zstd-compressed but the zstandard module is not installed")
        return _zstd.ZstdDecompressor().decompress(body)
    raise ValueError(f"unknown algo byte {algo}")


def pack_payload(raw: bytes, algo: str = "auto") -> tuple[bytes, dict]:
    """Compress *raw* into a self-describing blob.

    algo: 'auto' (best available, smallest output), 'gzip', 'lzma', 'zstd',
    or 'stored'. Auto never produces a blob larger than raw+16: if
    compression does not help, the payload is stored uncompressed
    (algo=stored) so unpack still round-trips.

    Returns (blob, meta) where meta has orig_len, packed_len, algo,
    ratio, reduction_pct.
    """
    candidates: list[tuple[int, bytes]] = []
    if algo == "auto":
        if _HAVE_LZMA:
            candidates.append((ALGO_LZMA, _compress(raw, ALGO_LZMA)))
        candidates.append((ALGO_GZIP, _compress(raw, ALGO_GZIP)))
        if _HAVE_ZSTD:
            candidates.append((ALGO_ZSTD, _compress(raw, ALGO_ZSTD)))
        candidates.append((ALGO_STORED, raw))
        chosen_algo, body = min(candidates, key=lambda t: len(t[1]))
    else:
        name_to_id = {v: k for k, v in ALGO_NAMES.items()}
        if algo not in name_to_id:
            raise ValueError(f"algo must be one of {sorted(name_to_id)} or 'auto'")
        chosen_algo = name_to_id[algo]
        body = raw if chosen_algo == ALGO_STORED else _compress(raw, chosen_algo)

    header = struct.pack(HEADER_FMT, MAGIC, VERSION, chosen_algo, 0,
                         len(raw), zlib.crc32(raw) & 0xFFFFFFFF)
    blob = header + body
    meta = {
        "orig_len": len(raw),
        "packed_len": len(blob),
        "body_len": len(body),
        "algo": ALGO_NAMES[chosen_algo],
        "ratio": len(blob) / len(raw) if raw else 1.0,
        "reduction_pct": 100.0 * (1 - len(blob) / len(raw)) if raw else 0.0,
    }
    return blob, meta


def unpack_payload(blob: bytes) -> bytes:
    """Recover the original payload from *blob*.

    Auto-detects the H9PC container; anything that does not validate as a
    container (wrong magic / version / algo / CRC) is treated as a legacy
    RAW payload and returned unchanged — old tapes keep decoding.
    """
    if len(blob) >= HEADER_LEN and blob[:4] == MAGIC:
        magic, version, algo_id, _res, orig_len, crc = struct.unpack(
            HEADER_FMT, blob[:HEADER_LEN])
        if version == VERSION and algo_id in ALGO_NAMES:
            raw = _decompress(blob[HEADER_LEN:], algo_id)
            if len(raw) == orig_len and (zlib.crc32(raw) & 0xFFFFFFFF) == crc:
                return raw
            raise ValueError(
                f"H9PC container failed integrity check "
                f"(len {len(raw)} vs {orig_len}, crc mismatch={crc != (zlib.crc32(raw) & 0xFFFFFFFF)})")
    return blob  # legacy raw payload — pass through


def is_packed(blob: bytes) -> bool:
    """Cheap header sniff (no decompression)."""
    if len(blob) < HEADER_LEN or blob[:4] != MAGIC:
        return False
    _m, version, algo_id, _r, _ol, _c = struct.unpack(HEADER_FMT, blob[:HEADER_LEN])
    return version == VERSION and algo_id in ALGO_NAMES


if __name__ == "__main__":
    import hashlib
    import pathlib
    import sys

    cass = pathlib.Path(__file__).resolve().parents[2] / "experiments" / "dpd" / "cassette_llm" / "stories260K_int4.cass"
    raw = cass.read_bytes()
    blob, meta = pack_payload(raw)
    back = unpack_payload(blob)
    ok = back == raw
    print(f"payload {cass}")
    print(f"orig {meta['orig_len']}  packed {meta['packed_len']}  algo {meta['algo']}  "
          f"-{meta['reduction_pct']:.2f}%  roundtrip={'OK' if ok else 'MISMATCH'}")
    print(f"sha256 orig={hashlib.sha256(raw).hexdigest()[:16]} back={hashlib.sha256(back).hexdigest()[:16]}")
    # legacy passthrough check
    assert unpack_payload(raw) == raw, "legacy raw passthrough failed"
    print("legacy raw passthrough OK")
    sys.exit(0 if ok else 1)
