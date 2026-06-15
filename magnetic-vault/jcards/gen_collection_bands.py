#!/usr/bin/env python3
"""
gen_collection_bands.py — render the spot-recolored signal-trace bands for the
COLLECTION MOCKUP (collection_mockup.html).

The locked Magnetic-Specimen J-card uses ONE duotone spectrogram band per cover,
coloured in that release's single ferric SPOT colour (see spectrogram.py: the
duotone ramp is ink -> spot -> bone). For the collection mockup we keep the
template identical and only vary the SPOT — so every cover needs its band
re-rendered in its palette's spot colour.

The 4 cassettes (DOOM, The Willows, Grandmaster, The Great Library) each sample a
DIFFERENT window of the real DOOM master so the four traces read as distinct
signal textures (DOOM keeps the canonical body window). The point of the mockup
is the COLOUR SYSTEM, so all four are real spectrograms of the data, recoloured
per version's spot.

Emits collection_assets/<version>_<cassette>.png for 3 versions x 4 cassettes.
Also prints, for each palette, the per-colour PERCEIVED LIGHTNESS over the bone
paper so we can confirm the four spots are value-matched (no one jumps out).
"""
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import spectrogram as spec  # reuse the exact duotone renderer

MASTER = HERE.parent.parent / "experiments/tape_v2/doom_ship/m10doom3_sideB_source.wav"
OUT = HERE / "collection_assets"
OUT.mkdir(exist_ok=True)

# ---- THE THREE PALETTES (tuned hexes) --------------------------------------
# Order maps to the 4 cassettes: DOOM, willows, grandmaster, great-library.
PALETTES = {
    "v1": {  # OXIDE — warm analogous "aged ferric metal", value-matched
        "doom":          "c75e34",  # burnt orange (DOOM's canonical oxide)
        "willows":       "bf7e35",  # ochre / amber (pulled down from cf9442)
        "grandmaster":   "b1402c",  # rust red (lifted from a83b29)
        "great-library": "97603a",  # clay / umber (lifted from 8a5630)
    },
    "v2": {  # RISO — muted, equally-chalky risograph inks (varied hue), value-matched
        "doom":          "c56b50",  # faded coral
        "willows":       "4a847a",  # dusty teal (lifted)
        "grandmaster":   "b88c3d",  # mustard (pulled down from c39a44)
        "great-library": "5e7596",  # slate blue (lifted from 566b8c)
    },
    "v3": {  # TONAL — graduated single-family set (sand -> oxblood), even ramp
        "doom":          "d0a85f",  # sand
        "willows":       "c5893f",  # amber
        "grandmaster":   "ad5e3a",  # terracotta
        "great-library": "8a4a3a",  # oxblood (lifted slightly for an even step)
    },
}

# distinct master windows (seconds) so the 4 traces look different but are all
# real data. DOOM uses the canonical ~12% body window.
WINDOWS = {
    "doom":          585.3 * 0.12,
    "willows":       585.3 * 0.34,
    "grandmaster":   585.3 * 0.58,
    "great-library": 585.3 * 0.79,
}


def rel_lum(hexstr):
    """sRGB relative luminance (0..1) of a hex colour."""
    r, g, b = (int(hexstr[i:i + 2], 16) / 255.0 for i in (0, 2, 4))
    def lin(c):
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    R, G, B = lin(r), lin(g), lin(b)
    return 0.2126 * R + 0.7152 * G + 0.0722 * B


def contrast_ratio(a, b):
    la, lb = rel_lum(a), rel_lum(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


BONE = "efe7d6"


def main():
    if not MASTER.exists():
        print(f"!! master not found: {MASTER}", file=sys.stderr)
        sys.exit(1)

    for vname, pal in PALETTES.items():
        print(f"\n=== {vname.upper()} ===")
        for cass, spot in pal.items():
            start = WINDOWS[cass]
            out = OUT / f"{vname}_{cass}.png"
            spec.render(
                str(MASTER), str(out), spot=spot,
                start=start, dur=9.0, width=1100, height=440,
            )
            L = rel_lum(spot)
            cr = contrast_ratio(spot, BONE)
            print(f"  {cass:14s} #{spot}  lum={L:.3f}  contrast-vs-bone={cr:.2f}")
        # report value spread within the set (lower = more uniform)
        lums = [rel_lum(s) for s in pal.values()]
        spread = max(lums) - min(lums)
        print(f"  -> luminance spread = {spread:.3f} "
              f"(min {min(lums):.3f}, max {max(lums):.3f})")


if __name__ == "__main__":
    main()
