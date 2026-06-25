"""Generate golden parity fixtures for the Rust port of the R-1 combo-MFSK floor rung.

Mirrors test_fullspectrum_floor.py's build + channel + sync path, but instead of
asserting in-process it DUMPS artifacts the Rust test suite consumes:

  fixtures/<chan>_raw.wav        post-channel audio AS CAPTURED (pre global sync) — mono f32
  fixtures/<chan>_nominal.wav    audio_nominal AFTER am2.global_sync_and_resample — mono f32
  fixtures/<chan>.json           sync params (speed, resample, align, chirp0), the floor
                                 section meta, frame_starts/body_end, and ground-truth payload

Channels: clean (downmixed mono, no channel), normal (preset normal, spd 0),
worn (preset worn, spd -0.12 — the exact model that recovered the 153 KB cassette-LLM
byte-exact off a physical worn tape). The Rust decoder must reproduce the payload
byte-exact from <chan>_nominal.wav (PHY+FEC port) and ultimately from <chan>_raw.wav
(adding the global-sync port).

Run: python3 experiments/tape_v2/rust_fixtures/gen_floor_fixtures.py
"""
from __future__ import annotations

import json
import pathlib
import sys
import tempfile

import numpy as np
import soundfile as sf

_HERE = pathlib.Path(__file__).resolve().parent
ROOT = pathlib.Path("/Users/magnus/repos/cassette-ai")
for _p in (ROOT / "src", ROOT / "tests" / "e2e", ROOT / "experiments" / "deepdive2",
           ROOT / "experiments" / "capacity", ROOT / "experiments" / "tape_v2"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import fullspectrum_master as fsm          # noqa: E402
import fullspectrum_decode as fsd          # noqa: E402
import analyze_master2 as am2              # noqa: E402
import capture_scenarios as cs             # noqa: E402
import m3_codec as codec                   # noqa: E402
from fractions import Fraction             # noqa: E402
from scipy.signal import resample_poly     # noqa: E402

SR = 48_000
OUT = _HERE / "fixtures"
OUT.mkdir(parents=True, exist_ok=True)


def _build_once():
    tmp = pathlib.Path(tempfile.mkdtemp()) / "fullspectrum_master_fix.wav"
    fsm.build(tmp)
    manifest = json.loads(fsm.MANIFEST_PATH.read_text())
    audio, sr = sf.read(str(tmp), dtype="float32", always_2d=True)
    assert sr == SR, sr
    mono = audio.mean(axis=1).astype(np.float32)
    return manifest, mono


def _floor_section(manifest: dict) -> dict:
    floors = [s for s in manifest["ws_payloads"] if s.get("kind") == "combo_mfsk"]
    assert len(floors) == 1, f"expected one combo_mfsk floor, got {len(floors)}"
    return floors[0]


def _cassette_channel(x, preset, spd, seed):
    rx, sr, _info = cs.full_chain(x, preset, "usb_soundcard", speed_offset=spd, seed=seed)
    if sr != SR:
        fr = Fraction(SR, sr).limit_denominator(20000)
        rx = resample_poly(rx.astype(np.float64), fr.numerator, fr.denominator)
    return np.asarray(rx, dtype=np.float32)


def _dump_channel(label, raw, manifest, floor):
    sync = am2.global_sync_and_resample(raw, manifest)
    audio_nom = np.asarray(sync["audio_nominal"], dtype=np.float32)
    align = int(sync["chirp0_nominal"]) - int(manifest["tx_chirp0"])

    # decode in Python to capture the reference result + confirm byte-exact here
    res = fsd._decode_combo_section(audio_nom, floor, align)
    sidecar = (pathlib.Path(fsd._HERE) / floor["payload_sidecar"]).read_bytes()

    sf.write(str(OUT / f"{label}_raw.wav"), raw, SR, subtype="FLOAT")
    sf.write(str(OUT / f"{label}_nominal.wav"), audio_nom, SR, subtype="FLOAT")

    meta = floor["meta"]
    rec = {
        "label": label,
        "byte_exact_python": bool(res["byte_exact"]),
        "rs_codewords_failed": int(res["rs_codewords_failed"]),
        "n_codewords": int(meta["n_codewords"]),
        "sync": {
            "speed": float(sync["speed"]),
            "resample_num": int(sync["resample_num"]),
            "resample_den": int(sync["resample_den"]),
            "chirp0_nominal": int(sync["chirp0_nominal"]),
            "tx_chirp0": int(manifest["tx_chirp0"]),
            "align": align,
        },
        "section": {
            "name": floor["name"],
            "frame_starts": [int(s) for s in floor["frame_starts"]],
            "body_end": int(floor["body_end"]),
            "guard_samples": int(0.05 * SR),
        },
        "meta": {k: (int(v) if isinstance(v, (int, np.integer)) else v)
                 for k, v in meta.items()},
        "payload_len": int(meta["payload_len"]),
        "payload_sha_first16": list(sidecar[:16]),
        "payload": list(sidecar),
    }
    (OUT / f"{label}.json").write_text(json.dumps(rec))
    print(f"[fixture] {label:6s} align={align:+d} speed={sync['speed']:.5f} "
          f"nom_len={len(audio_nom)} payload={len(sidecar)}B "
          f"py_byte_exact={res['byte_exact']} cwFail={res['rs_codewords_failed']}/{meta['n_codewords']}")
    return res["byte_exact"]


def main():
    print("[gen] building full-spectrum master (temp)...")
    manifest, mono = _build_once()
    floor = _floor_section(manifest)
    print(f"[gen] floor rung = {floor['name']}  "
          f"M={floor['meta']['M']} K={floor['meta']['K']} "
          f"RS(255,{floor['meta']['rs_k']}) net {floor['projected_net_bps']:.0f} bps")

    ok = True
    ok &= _dump_channel("clean", mono, manifest, floor)
    ok &= _dump_channel("normal", _cassette_channel(mono, "normal", 0.0, 3), manifest, floor)
    ok &= _dump_channel("worn", _cassette_channel(mono, "worn", -0.12, 3), manifest, floor)

    # also persist the floor section meta standalone (handy for the Rust framing test)
    (OUT / "floor_meta.json").write_text(json.dumps({
        "meta": {k: (int(v) if isinstance(v, (int, np.integer)) else v)
                 for k, v in floor["meta"].items()},
        "frame_starts": [int(s) for s in floor["frame_starts"]],
        "body_end": int(floor["body_end"]),
    }))
    print(f"[gen] {'ALL PYTHON-SIDE BYTE-EXACT' if ok else 'WARNING: a channel was NOT byte-exact'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
