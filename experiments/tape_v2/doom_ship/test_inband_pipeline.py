"""End-to-end red/green test: the inband-CRC d2x pipeline on a REAL payload.

Proves issue #17's deliverable at the unit level: a real payload, framed with
the self-describing in-band CRC (NO external crc32_codewords table on the
manifest), survives the PROVEN simulated cassette channel
(capture_scenarios.full_chain -- the same model used in the real-recovery tests)
and decodes BYTE-EXACT through the m10doom3 d2x receiver, verified inband-only.

Asserts:
  1. build_tape(inband_crc=True) emits a manifest section with crc_mode=="inband"
     and NO "crc32_codewords" key (the pre-known-CRC dependency is gone);
  2. the produced tape WAV, run through the simulated cassette channel, decodes
     BYTE-EXACT to the original real payload (verdict BYTE-EXACT + orig_byte_exact),
     using only inband acceptance -- this FAILS if inband verification is bypassed
     (with no table, the table path rejects/crashes every codeword);
  3. a forced RS mis-correction on the REAL payload framing -- an RS codeword that
     decodes cleanly but is NOT a valid in-band frame -- is REJECTED by
     accept_message (DoD #4), while the genuine inband frame is ACCEPTED.

Run:  python3 experiments/tape_v2/doom_ship/test_inband_pipeline.py
"""
from __future__ import annotations

import json
import pathlib
import sys
import tempfile

import numpy as np
import soundfile as sf
from reedsolo import RSCodec

_HERE = pathlib.Path(__file__).resolve().parent          # .../tape_v2/doom_ship
TAPE_V2 = _HERE.parent
ROOT = pathlib.Path("/Users/magnus/repos/cassette-ai")
for _p in (ROOT / "src", ROOT / "tests" / "e2e", ROOT / "experiments" / "deepdive2",
           ROOT / "experiments" / "capacity", TAPE_V2, _HERE):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import hashlib                                  # noqa: E402
from fractions import Fraction                  # noqa: E402

import capture_scenarios as cs                  # noqa: E402 (proven cassette channel)
import inband_crc as ib                         # noqa: E402
import m3_codec as codec                        # noqa: E402
import m10doom3_master as m3m                   # noqa: E402
import m10doom3_decode as m3d                   # noqa: E402
from scipy.signal import resample_poly          # noqa: E402

SR = 48_000
RS_N = 255
RS_K = 159                                       # the r6 / d2x rung


def _real_payload(n: int = 2500) -> bytes:
    """A few KB of a REAL payload: the head of the on-tape cassette-LLM."""
    return codec.CASS.read_bytes()[:n]


def _channel(audio: np.ndarray, preset: str, speed: float, seed: int) -> np.ndarray:
    rx, sr, _diag = cs.full_chain(audio, preset, "usb_soundcard",
                                  speed_offset=speed, seed=seed)
    if sr != SR:
        fr = Fraction(SR, sr).limit_denominator(20000)
        rx = resample_poly(rx.astype(np.float64), fr.numerator, fr.denominator)
    return np.asarray(rx, dtype=np.float32)


def test_inband_pipeline_byte_exact_through_channel():
    raw = _real_payload()
    sha_orig = hashlib.sha256(raw).hexdigest()
    packed, pmeta = m3m.pack_doom(raw)
    assert m3m.unpack_doom(packed) == raw

    tmp = pathlib.Path(tempfile.mkdtemp())
    wav = tmp / "inband_pipe.wav"
    manifest_path = tmp / "inband_pipe_manifest.json"
    sidecar = TAPE_V2 / "_inband_pipe_test.bin"          # must live under tape_v2
    payload_rel = sidecar.name

    try:
        res = m3m.build_tape(
            packed,
            out_wav=wav, manifest_path=manifest_path, sidecar_path=sidecar,
            payload_sidecar_rel=payload_rel, section_name="inband_pipe_test",
            frame_bytes=10_200, tape_id="inband_pipe",
            inband_crc=True,
            manifest_extra={"html_path": str(tmp / "no_such_dist.bin"),
                            "html_sha256": sha_orig},
            entry_extra={"pack": {
                "algo": pmeta["algo"], "orig_len": pmeta["orig_len"],
                "packed_len": pmeta["packed_len"],
                "reduction_pct": pmeta["reduction_pct"],
                "sha256_orig": sha_orig,
                "sha256_packed": hashlib.sha256(packed).hexdigest(),
            }},
            verbose=False,
        )

        # ---- assertion 1: manifest carries NO external CRC table -----------
        man = json.loads(manifest_path.read_text())
        sec = man["ws_payloads"][0]
        assert sec.get("crc_mode") == "inband", "section not flagged inband"
        assert "crc32_codewords" not in sec, \
            "manifest still carries the pre-known crc32_codewords table"
        print(f"[test] built {res['n_codewords']} cw / {res['n_frames']} frame(s), "
              f"{res['wav_seconds']:.1f}s tape; manifest has NO crc32_codewords")

        # ---- assertion 2: byte-exact through the PROVEN cassette channel ----
        rough = _channel(sf.read(str(wav), dtype="float32")[0], "good", 0.0, seed=11)
        rwav = tmp / "inband_pipe_chan.wav"
        sf.write(str(rwav), rough, SR, subtype="FLOAT")
        out = m3d.decode(str(rwav), out_tag="inband_pipe_test",
                         manifest_path=manifest_path, verbose=False,
                         use_cache=False)
        print(f"[test] channel(good): verdict={out['verdict']} "
              f"cwFail={out['payload']['rs_codewords_failed']}/"
              f"{out['payload']['n_codewords']} "
              f"orig_exact={out['payload']['orig_byte_exact']}")
        assert out["verdict"] == "BYTE-EXACT", "inband decode not byte-exact"
        assert out["payload"]["orig_byte_exact"], "original payload not recovered"
        assert out["payload"]["byte_exact"], "packed bytes not byte-exact"
    finally:
        sidecar.unlink(missing_ok=True)
    print("PASS test_inband_pipeline_byte_exact_through_channel "
          f"(real payload {len(raw)} B, inband-only, no table)")


def test_real_payload_rs_miscorrection_rejected():
    """DoD #4: an RS codeword that decodes CLEANLY but is NOT a valid in-band
    frame of the real payload (the shape of an RS mis-correction) is REJECTED by
    accept_message -- exactly the guard the external table used to provide."""
    raw = _real_payload()
    packed, _ = m3m.pack_doom(raw)
    rsc = RSCodec(RS_N - RS_K)

    # control: a GENUINE in-band frame of the real payload is ACCEPTED
    good_msg = ib.frame_payload(packed, RS_K)[0]
    cw = bytearray(rsc.encode(bytearray(good_msg)))
    cw[0] ^= 0xFF                                          # 1 error, within t
    dec = bytes(rsc.decode(bytes(cw))[0])
    assert dec == good_msg
    assert ib.accept_message(dec)[0], "genuine inband frame rejected"

    # forced mis-correction: real payload BYTES that are NOT inband-framed (a raw
    # rs_k slice) -> RS decodes them cleanly, but the in-band CRC guard rejects.
    rogue = (packed + bytes((-len(packed)) % RS_K))[:RS_K]   # raw, unframed
    cw = bytearray(rsc.encode(bytearray(rogue)))
    cw[3] ^= 0xFF
    dec = bytes(rsc.decode(bytes(cw))[0])
    assert dec == rogue
    assert not ib.accept_message(dec)[0], \
        "non-framed real-payload bytes (RS mis-correction) wrongly accepted"
    print("PASS test_real_payload_rs_miscorrection_rejected "
          "(genuine frame accepted, non-framed real bytes rejected)")


if __name__ == "__main__":
    import warnings
    warnings.filterwarnings("ignore")
    test_real_payload_rs_miscorrection_rejected()
    test_inband_pipeline_byte_exact_through_channel()
    print("\nALL PASS -- inband-CRC d2x pipeline byte-exact through the simulated "
          "cassette channel, no external CRC table.")
