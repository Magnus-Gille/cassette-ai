"""Self-describing in-band CRC framing for the high-rate RS-codeword tape path.

Removes the dependency on a PRE-KNOWN per-codeword CRC table -- the manifest
`crc32_codewords` "acceptance channel" (see m10_master.py:24) that forces a
decoder to know each segment's CRC *beforehand*, so it can only decode tapes it
itself generated.

Each RS codeword's MESSAGE now carries its own CRC32 in its last 4 bytes,
protected by the same RS(255,k) parity. The decoder recomputes the CRC from the
decoded message and checks it against the embedded value -- integrity verified
from the bitstream alone, no manifest needed. This is the same in-band per-frame
CRC already shipping in src/cassette_format.py (lines 85/121), brought down to
the RS-codeword granularity the m8/m9/m10/d2x/fullspectrum stack uses.

What the receiver may still legitimately know (these are MODEM parameters, not
payload-derived oracles): rs_n, rs_k, n_codewords, carrier plan. What it must
NOT need: anything computed from the payload CONTENT -- i.e. the CRC. That, and
only that, moves in-band here.

Cost: CRC_BYTES per codeword. For RS(255,159) that is 4/159 = 2.5% of net rate
(R3 4910/ch -> ~4786/ch); RS(255,127) is 3.1%; RS(255,191) is 2.1%. That is the
honest cost of a self-describing format -- the external table was hiding it.
"""
from __future__ import annotations

import struct
import zlib

MAGIC = b"CIB1"                       # cassette in-band, v1
CRC_BYTES = 4                         # trailing CRC32 per codeword message
HEADER = struct.Struct("<4sIH")       # magic, payload_len (u32), rs_k (u16) -> 10 bytes
_CRC = struct.Struct("<I")


def k_data_bytes(rs_k: int, crc_bytes: int = CRC_BYTES) -> int:
    """Payload bytes carried per codeword (the rest is the in-band CRC)."""
    return rs_k - crc_bytes


def frame_payload(payload: bytes, rs_k: int, crc_bytes: int = CRC_BYTES) -> list[bytes]:
    """Split `payload` into RS MESSAGES (pre-RS-encode), each rs_k bytes:
    [k_data data bytes][crc_bytes = CRC32(data) little-endian].

    The very first message's leading bytes are a HEADER(magic, payload_len, rs_k)
    so the stream is self-describing: a decoder recovers payload_len from the data
    itself, not from a sidecar. Returns the list of rs_k-byte messages ready to
    hand to RSCodec.encode().
    """
    k_data = k_data_bytes(rs_k, crc_bytes)
    if k_data <= HEADER.size:
        raise ValueError(f"rs_k={rs_k} too small: need > {HEADER.size + crc_bytes}")
    blob = HEADER.pack(MAGIC, len(payload), rs_k) + payload
    msgs: list[bytes] = []
    # ceil-div so an empty payload still yields the single header-only codeword
    n = max(1, (len(blob) + k_data - 1) // k_data)
    for i in range(n):
        chunk = blob[i * k_data:(i + 1) * k_data]
        chunk = chunk + bytes(k_data - len(chunk))      # zero-pad the final chunk
        crc = _CRC.pack(zlib.crc32(chunk) & 0xFFFFFFFF)
        msgs.append(chunk + crc)
    return msgs


def accept_message(msg: bytes, crc_bytes: int = CRC_BYTES) -> tuple[bool, bytes]:
    """Verify a decoded rs_k-byte message against its IN-BAND CRC -- no external
    table. Returns (ok, data) where `data` is the k_data payload bytes. `ok` is
    False whenever the data has been altered relative to its embedded CRC, which
    is exactly what fires on an RS mis-correction (RS returning a wrong-but-valid
    codeword); the residual false-accept probability is 2**-32 per codeword.
    """
    if len(msg) <= crc_bytes:
        return False, b""
    data, stored = msg[:-crc_bytes], msg[-crc_bytes:]
    ok = _CRC.pack(zlib.crc32(data) & 0xFFFFFFFF) == stored
    return ok, data


def reassemble(accepted_data: list[bytes | None], rs_k: int,
               crc_bytes: int = CRC_BYTES) -> tuple[bytes | None, dict | None]:
    """Concatenate the per-codeword payload chunks back into the original bytes.

    `accepted_data[i]` is the k_data chunk from accept_message, or None for a
    codeword that no demod branch recovered -- filled with zeros to preserve
    byte offsets (mirrors m10_decode._assemble). Parses the in-band header and
    trims to payload_len.

    Graceful degradation: if the header codeword is lost, returns the full
    concatenated body with `header=None` (callers whose payload is itself
    length-framed -- lzma/h9 -- can still use it; only trailing zero padding of
    the last codeword may remain).
    """
    k_data = k_data_bytes(rs_k, crc_bytes)
    blob = bytearray()
    for d in accepted_data:
        blob += d if d is not None else bytes(k_data)
    if len(blob) < HEADER.size:
        return None, None
    magic, payload_len, rs_k_hdr = HEADER.unpack(bytes(blob[:HEADER.size]))
    if magic != MAGIC:
        # header codeword missing/corrupt -> hand back the raw body, no trim
        return bytes(blob), None
    body = bytes(blob[HEADER.size:HEADER.size + payload_len])
    return body, {"payload_len": payload_len, "rs_k": rs_k_hdr}
