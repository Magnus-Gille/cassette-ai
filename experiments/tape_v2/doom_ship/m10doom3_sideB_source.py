"""m10doom3_sideB_source.py -- SIDE B of the DOOM v3 cassette: the GPL source.

Side A carries dist/doom_cassette_v3.html (m10doom3_master.py, the ship tape).
GPL-2.0 section 3 requires the complete corresponding source to accompany the
binary -- so SIDE B opens with the source archive AS DATA, encoded at the
IDENTICAL tape10-proven r6 rung (D2X_P21_N256_sp2_drop1, RS(255,159), net
4910.3 bps, FB=10200 -- the exact modem config of the side-A ship tape),
followed by real (copyright-clean) music filling the rest of the side.

Payload: payloads/doom/dist/doom_v3_source.tar
  (build/src incl. doomgeneric_wasm_v3.c, src_v3/SDL_mixer.h, pre_wad_v3.js,
   build_v3.sh, trim_freedoom_v3.py, assemble_html_v3.py, rawpack.py,
   LICENSES/ [GPL-2.0 + Freedoom/miniwad BSD-3 + CREDITS], BUILD.md with the
   exact emsdk version and commands).

This module is a thin wrapper: ALL tape machinery is imported READ-ONLY from
m10doom3_master (build_tape, pack_doom/unpack_doom -- the proven H9PC lzma
bridge) and the self-check decodes the produced WAV through the v3 SHIPPING
receiver path (m10doom3_decode.decode_section_bytes = frozen m10 stage A +
bytes-returning x11 d2x rescue, ARMED) without touching any side-A artifact:
separate WAV / manifest / sidecar / results, nothing under version freeze is
rewritten.

Run:
    python3 experiments/tape_v2/doom_ship/m10doom3_sideB_source.py

Outputs (all NEW files):
    doom_ship/m10doom3_sideB_source.wav            the side-B data section
    doom_ship/m10doom3_sideB_source_manifest.json  decode manifest (m9/m10 schema)
    doom_ship/m10doom3_sideB_source.bin            packed payload sidecar (H9PC lzma)
    doom_ship/results/m10doom3_sideB_source_report.json
"""
from __future__ import annotations

import hashlib
import json
import pathlib
import sys

_HERE = pathlib.Path(__file__).resolve().parent          # .../tape_v2/doom_ship
TAPE_V2 = _HERE.parent
ROOT = pathlib.Path("/Users/magnus/repos/cassette-ai")
for _p in (
    ROOT / "src",
    ROOT / "tests" / "e2e",
    ROOT / "experiments" / "deepdive2",
    ROOT / "experiments" / "capacity",
    TAPE_V2,
    _HERE,
):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import m10doom3_master as v3  # noqa: E402  (read-only: build_tape + lzma bridge)
import m10doom3_decode as v3d  # noqa: E402  (read-only: shipping RX path)

TAR_PATH = ROOT / "payloads" / "doom" / "dist" / "doom_v3_source.tar"
SECTION_NAME = "m10doom3_sideB_source"
WAV_PATH = _HERE / "m10doom3_sideB_source.wav"
MANIFEST_PATH = _HERE / "m10doom3_sideB_source_manifest.json"
SIDECAR_PATH = _HERE / "m10doom3_sideB_source.bin"
REPORT_PATH = _HERE / "results" / "m10doom3_sideB_source_report.json"

C90_SIDE_PHYSICAL_MIN = 45.0   # one physical C90 side; remainder = music


def build() -> dict:
    raw = TAR_PATH.read_bytes()
    sha_orig = hashlib.sha256(raw).hexdigest()

    packed, pmeta = v3.pack_doom(raw)
    assert v3.unpack_doom(packed) == raw, "H9 pack/unpack roundtrip failed"
    print(f"[sideB] payload  {TAR_PATH.name}: {len(raw)} B raw -> "
          f"{pmeta['packed_len']} B packed ({pmeta['algo']}, "
          f"-{pmeta['reduction_pct']:.1f}%) = {pmeta['packed_len'] / 1024:.1f} KB")

    res = v3.build_tape(
        packed,
        out_wav=WAV_PATH,
        manifest_path=MANIFEST_PATH,
        sidecar_path=SIDECAR_PATH,
        payload_sidecar_rel=str(SIDECAR_PATH.relative_to(TAPE_V2)),
        section_name=SECTION_NAME,
        frame_bytes=v3.FRAME_BYTES,            # 10200, identical to side A
        tape_id="m10doom3_sideB",
        role="DOOM-v3-sideB-GPL-source",
        manifest_extra={
            # m10doom3_decode keys off html_path/html_sha256 for the orig
            # integrity check; the payload here is the source TAR.
            "html_path": str(TAR_PATH),
            "html_sha256": sha_orig,
            "payload_kind": "gpl-source-tar",
        },
        entry_extra={
            "pack": {
                "algo": pmeta["algo"],
                "orig_len": pmeta["orig_len"],
                "packed_len": pmeta["packed_len"],
                "reduction_pct": pmeta["reduction_pct"],
                "sha256_orig": sha_orig,
                "sha256_packed": hashlib.sha256(packed).hexdigest(),
            },
        },
    )

    # effective bps on the tar (incl. compression + framing), manifest patch
    eff = len(raw) * 8 / res["payload_seconds"]
    manifest = json.loads(MANIFEST_PATH.read_text())
    manifest["ws_payloads"][0]["effective_bps"] = eff
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2, default=float))

    res.update({"packed_len": pmeta["packed_len"], "algo": pmeta["algo"],
                "effective_bps": eff, "sha256_orig": sha_orig})
    print(f"[sideB] eff      {eff:.1f} bps on the tar "
          f"({len(raw)} B in {res['payload_seconds']:.1f} s of payload audio)")
    m = res["wav_minutes"]
    assert m <= C90_SIDE_PHYSICAL_MIN, m
    print(f"[sideB] tape     {m:.2f} min data; music budget on the side: "
          f"{C90_SIDE_PHYSICAL_MIN - m:.2f} min")
    return res


def selfcheck(build_res: dict) -> dict:
    """No-channel self-check: decode the clean side-B WAV through the v3
    SHIPPING receiver (frozen m10 stage A + bytes-returning x11 d2x rescue,
    armed). Must be 0 failed codewords and BYTE-EXACT to the tar on disk."""
    manifest = json.loads(MANIFEST_PATH.read_text())
    sec = manifest["ws_payloads"][0]
    ledger = v3d._new_ledger()
    audio_nom, sync, _ = v3d._load_capture(str(WAV_PATH), manifest,
                                           "sideB_source", use_cache=False)
    align = int(sync["align"])
    print(f"[sideB selfcheck] clock {sync.get('speed', 0):.5f}x  "
          f"align {align:+d}", flush=True)

    r, assembled = v3d.decode_section_bytes(audio_nom, sec, align, ledger,
                                            rescue=True, x11_rescue=True,
                                            verbose=True)
    recovered = v3.unpack_doom(assembled)
    raw = TAR_PATH.read_bytes()
    byte_exact = (recovered == raw)
    chk = {
        "cw_failed": int(r["rs_codewords_failed"]),
        "n_codewords": int(r["n_codewords"]),
        "decoder_stage": r["decoder_stage"],
        "front_end_used": r.get("front_end_used"),
        "packed_byte_exact": bool(r["byte_exact"]),
        "orig_byte_exact": bool(byte_exact),
        "orig_sha256": hashlib.sha256(recovered).hexdigest(),
        "fa_bound": ledger["crc_checks"] * 2.0 ** -32,
    }
    print(f"[sideB selfcheck] cw failed {chk['cw_failed']}/"
          f"{chk['n_codewords']}  stage={chk['decoder_stage']}  "
          f"packed_exact={chk['packed_byte_exact']}  "
          f"TAR BYTE-EXACT={chk['orig_byte_exact']}")
    return chk


if __name__ == "__main__":
    import warnings
    warnings.filterwarnings("ignore")
    res = build()
    chk = selfcheck(res)
    report = {
        "tar": str(TAR_PATH),
        "tar_bytes": TAR_PATH.stat().st_size,
        "lzma_sidecar_bytes": res["packed_len"],
        "wav": str(WAV_PATH),
        "wav_minutes": res["wav_minutes"],
        "payload_seconds": res["payload_seconds"],
        "packed_bps": res["packed_bps"],
        "effective_bps": res["effective_bps"],
        "net_bps": res["net_bps"],
        "n_frames": res["n_frames"],
        "n_codewords": res["n_codewords"],
        "music_minutes_remaining_45min_side": C90_SIDE_PHYSICAL_MIN
        - res["wav_minutes"],
        "selfcheck": chk,
    }
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, indent=2, default=float))
    print(f"[sideB] report -> {REPORT_PATH}")
    ok = chk["cw_failed"] == 0 and chk["orig_byte_exact"]
    print(f"[sideB] VERDICT: {'BYTE-EXACT' if ok else 'FAIL'}")
    sys.exit(0 if ok else 1)
