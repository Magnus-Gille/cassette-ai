"""m10doom2_master.py -- assemble the DOOM v2 (Freedoom-assets) ship tape.

THIN WRAPPER around the blessed, committed m10doom_master.py -- the v1 module
is imported UNCHANGED and only its module-level configuration is rebound:

    input HTML : payloads/doom/dist/doom_cassette_v2.html
    outputs    : m10doom2_master.wav / m10doom2_manifest.json /
                 m10doom2_dense375.bin

The modem is bit-identical to v1 (and to the rung that survived the real
master9 tape): m9_m8_dense375, DQPSK P22 N512 sp4, RS(255,159),
min_spacing_hz=375, gross 4125.0 -> net 2572.1 bps.

The ONLY behavioural difference: the v1 module hard-gates the tape length at
29 min (one C60 side). The v2 artifact carries ~12x more WAD and runs past a
C60 side, so the hard gate here is the PHYSICAL C90 side (45.0 min); the
planning gates -- 43 min (C90 with margin) and 29 min (C60 side) -- are
measured and reported, not asserted. NOTE the spec tension: the 600 KB
artifact-lzma cap and the 43-min margin gate are inconsistent at the top of
the range (measured all-in cost is ~0.004366 s/byte incl. fixed sync, so
43.0 min <=> packed <= ~590.8 KB = 1858 frames x 318 B).

Run:
    python3 experiments/tape_v2/doom_ship/m10doom2_master.py
        [--html PATH] [--out PATH]
"""
from __future__ import annotations

import argparse
import pathlib
import sys

_HERE = pathlib.Path(__file__).resolve().parent          # .../tape_v2/doom_ship
ROOT = pathlib.Path("/Users/magnus/repos/cassette-ai")
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

import m10doom_master as v1  # noqa: E402  (blessed v1 module, unmodified)

# ---- v2 configuration: rebind the v1 module's knobs, nothing else ----------
HTML_PATH = ROOT / "payloads" / "doom" / "dist" / "doom_cassette_v2.html"
SECTION_NAME = "m10doom2_dense375"
WAV_PATH = _HERE / "m10doom2_master.wav"
MANIFEST_PATH = _HERE / "m10doom2_manifest.json"
SIDECAR_PATH = _HERE / f"{SECTION_NAME}.bin"
C60_SIDE_BUDGET_MIN = 29.0            # reported (bonus target)
C90_MARGIN_BUDGET_MIN = 43.0          # reported (C90 side with margin)
C90_SIDE_PHYSICAL_MIN = 45.0          # HARD gate: must fit a physical C90 side

v1.HTML_PATH = HTML_PATH
v1.SECTION_NAME = SECTION_NAME
v1.WAV_PATH = WAV_PATH
v1.MANIFEST_PATH = MANIFEST_PATH
v1.SIDECAR_PATH = SIDECAR_PATH
v1.C60_SIDE_BUDGET_MIN = C90_SIDE_PHYSICAL_MIN  # v1's assert now gates at 45

# re-export the bridge helpers so m10doom2_decode can import from here
unpack_doom = v1.unpack_doom
pack_doom = v1.pack_doom


def build(html_path: pathlib.Path = HTML_PATH,
          out_wav: pathlib.Path = WAV_PATH) -> dict:
    res = v1.build(html_path, out_wav)
    m = res["wav_minutes"]
    res["fits_c60_side"] = m <= C60_SIDE_BUDGET_MIN
    res["fits_c90_margin"] = m <= C90_MARGIN_BUDGET_MIN
    res["fits_c90_side"] = m <= C90_SIDE_PHYSICAL_MIN
    print(f"[m10doom2] sides    C90 physical ({C90_SIDE_PHYSICAL_MIN:.0f} min): "
          f"{'OK' if res['fits_c90_side'] else 'OVER'}   "
          f"C90 w/ margin ({C90_MARGIN_BUDGET_MIN:.0f} min): "
          f"{'OK' if res['fits_c90_margin'] else 'OVER'}   "
          f"C60 side ({C60_SIDE_BUDGET_MIN:.0f} min): "
          f"{'OK (bonus)' if res['fits_c60_side'] else 'no'}")
    return res


if __name__ == "__main__":
    import warnings
    warnings.filterwarnings("ignore")
    ap = argparse.ArgumentParser()
    ap.add_argument("--html", default=str(HTML_PATH))
    ap.add_argument("--out", default=str(WAV_PATH))
    args = ap.parse_args()
    build(pathlib.Path(args.html), pathlib.Path(args.out))
