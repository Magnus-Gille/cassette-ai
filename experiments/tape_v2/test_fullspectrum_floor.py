"""Red/green test for the full-spectrum R-1 FLOOR rung (combo-MFSK).

The full-spectrum ladder's lowest rung used to be R0 (coherent DQPSK P10/RS127,
~1868 net bps). Coherent demod is the modulation flutter/wow hurts MOST, so on a
worn portable deck R0 can fail outright -- and then the tape yields only sounder
channel-stats, with a CLIFF to "zero bits recovered". This test pins the new
sub-floor rung that fills that gap: a NON-COHERENT combinatorial-MFSK section
(make_tracked_combo, the PHY that recovered the 153 KB cassette-LLM byte-exact off
a real worn tape). Energy detection + a per-symbol timing tracker shrug off the
flutter that kills coherent DQPSK, so the floor still lands a number when all the
coherent rungs fail.

Asserts:
  1. the manifest carries exactly one `kind == "combo_mfsk"` floor rung, net bps
     BELOW R0 (it is a floor, not a peer);
  2. it decodes BYTE-EXACT on a clean master (downmixed mono = acoustic sim);
  3. it STILL decodes byte-exact through a flutter + AWGN channel that is
     deliberately rough -- the robustness that justifies its existence.

Run:  python3 experiments/tape_v2/test_fullspectrum_floor.py
"""
from __future__ import annotations

import pathlib
import sys
import tempfile

import numpy as np
import soundfile as sf

_HERE = pathlib.Path(__file__).resolve().parent
ROOT = pathlib.Path("/Users/magnus/repos/cassette-ai")
for _p in (ROOT / "src", ROOT / "tests" / "e2e", ROOT / "experiments" / "deepdive2",
           ROOT / "experiments" / "capacity", _HERE):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import fullspectrum_master as fsm          # noqa: E402
import fullspectrum_decode as fsd          # noqa: E402
import analyze_master2 as am2              # noqa: E402
import capture_scenarios as cs             # noqa: E402 (proven cassette channel model)
from fractions import Fraction             # noqa: E402
from scipy.signal import resample_poly     # noqa: E402

SR = 48_000


def _build_once():
    """Build the master to a temp WAV (also regenerates manifest + sidecars)."""
    tmp = pathlib.Path(tempfile.mkdtemp()) / "fullspectrum_master_test.wav"
    fsm.build(tmp)
    manifest = __import__("json").loads(fsm.MANIFEST_PATH.read_text())
    audio, sr = sf.read(str(tmp), dtype="float32", always_2d=True)
    assert sr == SR, sr
    mono = audio.mean(axis=1).astype(np.float32)   # acoustic-sum simulation
    return manifest, mono


def _floor_section(manifest: dict) -> dict:
    floors = [s for s in manifest["ws_payloads"] if s.get("kind") == "combo_mfsk"]
    assert len(floors) == 1, f"expected exactly one combo_mfsk floor rung, got {len(floors)}"
    return floors[0]


def _decode_floor(mono: np.ndarray, manifest: dict, floor: dict) -> dict:
    sync = am2.global_sync_and_resample(mono, manifest)
    audio_nom = sync["audio_nominal"]
    align = int(sync["chirp0_nominal"]) - int(manifest["tx_chirp0"])
    return fsd._decode_combo_section(audio_nom, floor, align)


def _cassette_channel(x: np.ndarray, tape_preset: str, speed_offset: float,
                      seed: int) -> np.ndarray:
    """Run the master mono mix through the PROVEN cassette channel model
    (capture_scenarios.full_chain) -- the same tape/capture/flutter simulation the
    combo PHY's survival numbers came from, and the exact `worn + -0.12 speed`
    channel that recovered the 153 KB cassette-LLM byte-exact. Resample back to
    48 kHz if the capture path changed the rate (the real decoder does the same)."""
    rx, sr, _info = cs.full_chain(x, tape_preset, "usb_soundcard",
                                  speed_offset=speed_offset, seed=seed)
    if sr != SR:
        fr = Fraction(SR, sr).limit_denominator(20000)
        rx = resample_poly(rx.astype(np.float64), fr.numerator, fr.denominator)
    return np.asarray(rx, dtype=np.float32)


def main() -> int:
    print("[test] building full-spectrum master (temp)...")
    manifest, mono = _build_once()
    floor = _floor_section(manifest)

    # ---- structural: floor exists and sits BELOW R0 -----------------------
    others = [s for s in manifest["ws_payloads"] if s.get("kind") != "combo_mfsk"]
    r0_net = min(s["projected_net_bps"] for s in others)
    print(f"[test] floor rung = {floor['name']}  net {floor['projected_net_bps']:.0f} bps  "
          f"(lowest coherent rung = {r0_net:.0f} bps)")
    assert floor["projected_net_bps"] < r0_net, \
        "floor rung must be a FLOOR (net bps below the lowest coherent rung)"
    assert "body_end" in floor and floor["frame_starts"], "floor needs frame slicing info"

    # ---- clean: must be byte-exact ----------------------------------------
    res_clean = _decode_floor(mono, manifest, floor)
    print(f"[test] CLEAN : byte_exact={res_clean['byte_exact']}  "
          f"cwFail={res_clean['rs_codewords_failed']}/{res_clean['n_codewords']}  "
          f"byteErr={res_clean['byte_errors']}")
    assert res_clean["byte_exact"], "floor rung must decode byte-exact on a clean master"

    # ---- realistic cassette channels: STILL byte-exact (the whole point) ---
    # 'normal' (the clean "sim" channel) and the HARSH 'worn + -0.12 speed' "real"
    # channel -- the latter is the exact model that proved byte-exact recovery off
    # the physical cassette. The floor must clear both.
    for preset, spd in (("normal", 0.0), ("worn", -0.12)):
        rough = _cassette_channel(mono, preset, spd, seed=3)
        res = _decode_floor(rough, manifest, floor)
        print(f"[test] CHANNEL {preset:6s} spd{spd:+.2f} : "
              f"byte_exact={res['byte_exact']}  "
              f"cwFail={res['rs_codewords_failed']}/{res['n_codewords']}  "
              f"byteErr={res['byte_errors']}")
        assert res["byte_exact"], \
            f"floor rung must survive the {preset} cassette channel (its reason for existing)"

    print("[test] PASS -- combo-MFSK floor rung present, below R0, robust on the "
          "proven worn channel.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
