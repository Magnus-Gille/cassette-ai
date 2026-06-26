"""Hard-acoustic R0 fixture: the real Voice-Memos Grundig-era acoustic capture
(New Recording 38) globally-synced to nominal, for testing the Rust R0 RESCUE
ENSEMBLE. The minimal single-front-end path leaves ~2/31 codewords here; only
the ensemble (EMA sweep + CRC union + late-window) reaches 0/31, matching
Python's full m10 receiver.

Writes:
  fixtures/vm38_nominal.wav   global-synced nominal audio (mono f32, gitignored)
  fixtures/vm38_r0.json       { align, payload[], crc32_codewords[], meta, section }

Run: python3 experiments/tape_v2/rust_fixtures/gen_vm38_r0_fixture.py
"""
from __future__ import annotations
import json, pathlib, sys
import numpy as np, soundfile as sf

_HERE = pathlib.Path(__file__).resolve().parent
ROOT = pathlib.Path("/Users/magnus/repos/cassette-ai")
for _p in (ROOT / "src", ROOT / "tests" / "e2e", ROOT / "experiments" / "deepdive2",
           ROOT / "experiments" / "capacity", ROOT / "experiments" / "tape_v2"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))
import analyze_master2 as am2     # noqa: E402
import m10_decode as m10          # noqa: E402

OUT = _HERE / "fixtures"
SRC = ROOT / "experiments/tape_v2/captures/vm_newrec38_20260626.wav"
R0_NAME = "fs_r0_robust_dqpsk_p10_rs127"


def main():
    if not SRC.exists():
        print(f"missing {SRC} — convert New Recording 38 first (see CLAUDE.md capture recipe)")
        return 1
    man = json.loads((ROOT / "experiments/tape_v2/fullspectrum_manifest.json").read_text())
    sec = [s for s in man["ws_payloads"] if s["name"] == R0_NAME][0]
    meta = sec["meta"]
    sidecar = (ROOT / "experiments/tape_v2" / sec["payload_sidecar"]).read_bytes()

    au, sr = sf.read(str(SRC))
    assert sr == 48000, sr
    sync = am2.global_sync_and_resample(np.asarray(au), man)
    align = int(sync["chirp0_nominal"]) - int(man["tx_chirp0"])
    audio_nom = np.asarray(sync["audio_nominal"], dtype=np.float32)
    sf.write(str(OUT / "vm38_nominal.wav"), audio_nom, 48000, subtype="FLOAT")

    # Confirm Python: minimal vs full-rescue, so the Rust target is unambiguous.
    for rescue in (False, True):
        led = {"rs_attempts": 0, "crc_checks": 0, "crc_rejects": 0, "crc_accepts": 0}
        r, _ = m10._decode_section(audio_nom, sec, align, led, rescue=rescue, verbose=False)
        print(f"[vm38] python rescue={rescue!s:5} cwFail={r['rs_codewords_failed']}/{r['n_codewords']} "
              f"byte_exact={r['byte_exact']} front_end={r.get('front_end_used')}")

    rec = {
        "label": "vm38_acoustic",
        "align": align,
        "speed": float(sync["speed"]),
        "tx_chirp0": int(man["tx_chirp0"]),
        "tx_chirp1": int(man["tx_chirp1"]),
        "section": {
            "frame_starts": [int(s) for s in sec["frame_starts"]],
            "body_end": int(sec["body_end"]),
            "p": int(sec["dqpsk_params"]["P"]), "n": int(sec["dqpsk_params"]["N"]),
            "spacing": int(sec["dqpsk_params"]["spacing"]),
            "skip": sec["dqpsk_params"].get("skip"),
            "pilot_hz": float(sec["dqpsk_params"]["pilot_hz"]),
        },
        "meta": {"rs_n": int(meta["rs_n"]), "rs_k": int(meta["rs_k"]),
                 "n_codewords": int(meta["n_codewords"]), "frame_bits": int(meta["frame_bits"]),
                 "n_frames": int(meta["n_frames"]), "stream_bits": int(meta["stream_bits"]),
                 "payload_len": int(meta["payload_len"])},
        "crc32_codewords": [int(c) for c in sec["crc32_codewords"]],
        "payload_len": int(meta["payload_len"]),
        "payload": list(sidecar),
    }
    (OUT / "vm38_r0.json").write_text(json.dumps(rec))
    print(f"[vm38] wrote vm38_nominal.wav ({len(audio_nom)} samp) + vm38_r0.json (align={align:+d})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
