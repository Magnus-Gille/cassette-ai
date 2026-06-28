"""Red/green tests for inband_crc -- self-contained RS-codeword decode.

Proves the manifest `crc32_codewords` "must-know-CRC-beforehand" dependency can
be removed: a real RS(255,k) round trip with channel errors decodes BYTE-EXACT
using only the in-band CRC, with NO external table -- and still rejects the
RS mis-corrections the external table used to guard against.

Run:  python3 experiments/tape_v2/test_inband_crc.py
"""
import struct
import zlib

import numpy as np
from reedsolo import RSCodec, ReedSolomonError

import inband_crc as ib

RS_N = 255


def _rs_roundtrip_self_contained(rs_k, payload, errors_per_cw, seed=0):
    """Full pipeline: in-band frame -> RS encode -> inject byte errors -> RS
    decode -> accept via IN-BAND crc only -> reassemble. Returns recovered bytes.
    Crucially, the decode side is handed NO external CRC table."""
    rng = np.random.default_rng(seed)
    rsc = RSCodec(RS_N - rs_k)
    t = (RS_N - rs_k) // 2
    msgs = ib.frame_payload(payload, rs_k)

    accepted: list[bytes | None] = []
    for m in msgs:
        cw = bytearray(rsc.encode(bytearray(m)))                 # 255-byte codeword
        npos = min(errors_per_cw, t)
        if npos:
            for p in rng.choice(RS_N, size=npos, replace=False):
                cw[p] ^= 0xFF                                     # whole-byte error
        try:
            dec = bytes(rsc.decode(bytes(cw))[0])
        except ReedSolomonError:
            accepted.append(None)                                # unrecoverable -> gap
            continue
        ok, data = ib.accept_message(dec)                        # <-- in-band only
        accepted.append(data if ok else None)

    body, hdr = ib.reassemble(accepted, rs_k)
    return body, hdr


def test_self_contained_byte_exact():
    """Headline: decode byte-exact with NO pre-known CRC table, at the real rung
    rs_k values, with channel errors up to the RS correction limit."""
    payload = np.random.default_rng(42).integers(0, 256, 4000, dtype=np.uint8).tobytes()
    for rs_k in (127, 159, 191):                                 # R0/R3, R3-top, R1
        t = (RS_N - rs_k) // 2
        body, hdr = _rs_roundtrip_self_contained(rs_k, payload, errors_per_cw=t)
        assert body == payload, f"rs_k={rs_k}: payload mismatch"
        assert hdr and hdr["payload_len"] == len(payload), f"rs_k={rs_k}: bad header"
    print("PASS test_self_contained_byte_exact  (rs_k=127/159/191, errors at RS limit)")


def test_empty_and_unaligned_payloads():
    for n in (0, 1, ib.k_data_bytes(159) - ib.HEADER.size,        # exactly fills cw0
              ib.k_data_bytes(159), 12345):
        payload = np.random.default_rng(n + 1).integers(0, 256, n, dtype=np.uint8).tobytes()
        body, hdr = _rs_roundtrip_self_contained(159, payload, errors_per_cw=0)
        assert body == payload, f"len={n}: mismatch"
    print("PASS test_empty_and_unaligned_payloads  (0, 1, boundary, multi-cw)")


def test_acceptance_channel_rejects_tampering():
    """The guard the external table provided, now in-band: accept_message must
    return True only for an intact framed message, False for any altered byte."""
    payload = b"the magnetic vault" * 8
    msg = ib.frame_payload(payload, 159)[0]
    ok, _ = ib.accept_message(msg)
    assert ok, "intact message rejected"
    # flip one DATA bit
    bad = bytearray(msg); bad[5] ^= 0x01
    assert not ib.accept_message(bytes(bad))[0], "tampered data accepted"
    # flip one CRC bit
    bad = bytearray(msg); bad[-1] ^= 0x01
    assert not ib.accept_message(bytes(bad))[0], "tampered crc accepted"
    print("PASS test_acceptance_channel_rejects_tampering")


def test_rejects_rs_miscorrection_without_table():
    """Why the external table existed -- and that in-band replaces it.

    RS(255,k) can DECODE CLEANLY (no exception) yet return a wrong codeword when
    the error weight exceeds t (a 'mis-correction'). With no table and a naive
    'RS decoded -> accept' rule, that garbage is taken silently. We construct a
    codeword that is NOT in-band-framed, RS-encode+lightly-corrupt it so RS
    returns it without error, and confirm accept_message REJECTS it (its trailing
    4 bytes do not match crc32 of its data). That is exactly the mis-correction
    guard, now carried in-band."""
    rs_k = 159
    rsc = RSCodec(RS_N - rs_k)
    rng = np.random.default_rng(7)
    rejected = 0
    trials = 200
    for _ in range(trials):
        # a random (NON-framed) message -> stands in for an RS mis-correction target
        rogue = rng.integers(0, 256, rs_k, dtype=np.uint8).tobytes()
        cw = bytearray(rsc.encode(bytearray(rogue)))
        cw[0] ^= 0xFF                                            # 1 error, within t
        dec = bytes(rsc.decode(bytes(cw))[0])                   # decodes cleanly to `rogue`
        assert dec == rogue
        ok, _ = ib.accept_message(dec)                          # in-band guard fires
        if not ok:
            rejected += 1
    # 2**-32 false-accept rate -> expect all 200 rejected
    assert rejected == trials, f"only {rejected}/{trials} rogue codewords rejected"
    print(f"PASS test_rejects_rs_miscorrection_without_table  ({rejected}/{trials} rejected, "
          f"naive 'RS-ok=accept' would have taken all {trials})")


def test_gap_fill_preserves_offsets():
    """A lost codeword (None) must zero-fill so later codewords stay byte-aligned
    -- and recovered codewords are still byte-exact at their true offsets."""
    rs_k = 159
    k_data = ib.k_data_bytes(rs_k)
    payload = np.random.default_rng(3).integers(0, 256, k_data * 5, dtype=np.uint8).tobytes()
    msgs = ib.frame_payload(payload, rs_k)
    accepted = [ib.accept_message(m)[1] for m in msgs]
    accepted[3] = None                                          # drop codeword 3
    body, hdr = ib.reassemble(accepted, rs_k)
    assert hdr["payload_len"] == len(payload)
    # everything except the dropped codeword's data window must match
    lo = 3 * k_data - ib.HEADER.size
    hi = lo + k_data
    assert body[:max(0, lo)] == payload[:max(0, lo)], "pre-gap corrupted"
    assert body[hi:] == payload[hi:], "post-gap shifted (offset not preserved)"
    print("PASS test_gap_fill_preserves_offsets")


if __name__ == "__main__":
    test_self_contained_byte_exact()
    test_empty_and_unaligned_payloads()
    test_acceptance_channel_rejects_tampering()
    test_rejects_rs_miscorrection_without_table()
    test_gap_fill_preserves_offsets()
    print("\nALL PASS -- self-contained in-band CRC decode, no manifest table needed.")
