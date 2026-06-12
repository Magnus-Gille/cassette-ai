"""m10doom2_decode.py -- recover the v2 (Freedoom-assets) DOOM HTML from a WAV.

THIN WRAPPER around the blessed, committed m10doom_decode.py. The v1 receiver
chain (m9 global sync + PLL front-end + RS sweep + CRC32 manifest guard + H9PC
lzma-bridge unpack) is reused UNCHANGED; only the module-level paths are
rebound to the v2 tape:

    manifest : m10doom2_manifest.json   (written by m10doom2_master.py)
    output   : doom_ship/doom2_decoded.html

Usage:
    python3 experiments/tape_v2/doom_ship/m10doom2_decode.py <capture.wav>
        [--out-tag TAG]
(default recording: the clean v2 master, i.e. a no-channel self-check)
"""
from __future__ import annotations

import argparse
import pathlib
import sys

_HERE = pathlib.Path(__file__).resolve().parent          # .../tape_v2/doom_ship
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

import m10doom2_master as v2m  # noqa: E402  (rebinds m10doom_master's knobs)
import m10doom_decode as v1d  # noqa: E402  (blessed v1 receiver, unmodified)

DECODED_PATH = _HERE / "doom2_decoded.html"
WAV_PATH = v2m.WAV_PATH

# ---- rebind the v1 decoder's module globals to the v2 tape -----------------
v1d.MANIFEST_PATH = v2m.MANIFEST_PATH
v1d.DECODED_PATH = DECODED_PATH
v1d.WAV_PATH = WAV_PATH


def decode(recording_path: str, out_tag: str | None = None,
           verbose: bool = True) -> dict:
    return v1d.decode(recording_path, out_tag=out_tag, verbose=verbose)


if __name__ == "__main__":
    import warnings
    warnings.filterwarnings("ignore")
    ap = argparse.ArgumentParser()
    ap.add_argument("recording", nargs="?", default=str(WAV_PATH),
                    help="captured tape-playback WAV (default: the clean v2 master)")
    ap.add_argument("--out-tag", default=None)
    args = ap.parse_args()
    res = decode(args.recording, args.out_tag)
    sys.exit(0 if res["verdict"] == "BYTE-EXACT" else 1)
