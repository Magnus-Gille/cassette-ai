#!/usr/bin/env python3
"""
integrate_level.py — Splice THE MAGNETIC VAULT (E1M1) into the final trimmed WAD.

Usage:
    python3 integrate_level.py <target_wad> [output_wad]

    <target_wad>  — path to the final trimmed Freedoom-E1 WAD (e.g. freedoom_e1_v3b.wad)
    [output_wad]  — output path (default: same dir as target, named freedoom_e1_with_vault.wad)

The script:
  1. Reads the E1M1 lump-set (THINGS, LINEDEFS, SIDEDEFS, VERTEXES, SEGS, SSECTORS,
     NODES, SECTORS, REJECT, BLOCKMAP) from level.wad (next to this script).
  2. Replaces the target WAD's E1M1 with ours (E1M2-E1M9 untouched).
  3. Writes the merged WAD to output_wad.

This script is SAFE to run any number of times (it never modifies the input WAD in-place
unless you pass the same path as both arguments — don't do that).

Run with the pyenv python that has omgifol installed:
    /Users/magnus/.pyenv/versions/3.10.13/bin/python3 integrate_level.py <target> [output]
or any system python3 that has omgifol 0.5.0:
    python3 integrate_level.py <target> [output]
"""

import os
import sys

# Support both pyenv omgifol location and system installs.
sys.path.insert(0, "/Users/magnus/.local/lib/python3.10/site-packages")
try:
    import omg
except ImportError:
    sys.exit("omgifol not found — install with: pip install omgifol==0.5.0")

HERE = os.path.dirname(os.path.abspath(__file__))
LEVEL_WAD = os.path.join(HERE, "level.wad")

MAP_NAME = "E1M1"

# Lumps that make up a complete Doom-format map (in canonical order).
MAP_LUMPS = [
    "_HEADER_", "THINGS", "LINEDEFS", "SIDEDEFS", "VERTEXES",
    "SEGS", "SSECTORS", "NODES", "SECTORS", "REJECT", "BLOCKMAP",
]


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    target_path = os.path.abspath(sys.argv[1])
    if not os.path.isfile(target_path):
        sys.exit(f"target WAD not found: {target_path}")

    if not os.path.isfile(LEVEL_WAD):
        sys.exit(f"level.wad not found at {LEVEL_WAD} — run build_level.py first")

    # Default output path: next to the target WAD.
    if len(sys.argv) >= 3:
        output_path = os.path.abspath(sys.argv[2])
    else:
        base_name = os.path.splitext(os.path.basename(target_path))[0]
        output_path = os.path.join(
            os.path.dirname(target_path),
            f"{base_name}_with_vault.wad",
        )

    if output_path == target_path:
        sys.exit("output_wad must differ from target_wad — refusing in-place overwrite")

    # ------------------------------------------------------------------ load
    print(f"Loading level WAD:  {LEVEL_WAD}")
    level_wad = omg.WAD(LEVEL_WAD)
    if MAP_NAME not in level_wad.maps:
        sys.exit(f"level.wad does not contain {MAP_NAME}")

    our_map = level_wad.maps[MAP_NAME]

    # Verify all node lumps are non-empty.
    required_non_empty = ("NODES", "SEGS", "SSECTORS", "BLOCKMAP", "REJECT")
    for lump in required_non_empty:
        if lump not in our_map or len(our_map[lump].data) == 0:
            sys.exit(f"level.wad {MAP_NAME}/{lump} is empty — rebuild with build_level.py")

    print(f"Loading target WAD: {target_path}")
    target_wad = omg.WAD(target_path)
    original_maps = list(target_wad.maps.keys())
    print(f"  Maps found: {original_maps}")

    if MAP_NAME not in target_wad.maps:
        print(f"  WARNING: target WAD has no {MAP_NAME} — adding it")

    # ------------------------------------------------------------------ splice
    target_wad.maps[MAP_NAME] = our_map

    merged_maps = list(target_wad.maps.keys())
    print(f"  Maps after splice: {merged_maps}")

    # ------------------------------------------------------------------ sizes
    orig_e1m1_size = (
        sum(len(target_wad.maps[MAP_NAME][k].data)
            for k in target_wad.maps[MAP_NAME].keys()
            if k != "_HEADER_")
    )
    our_size = sum(
        len(our_map[k].data) for k in our_map.keys() if k != "_HEADER_"
    )
    print(f"  E1M1 lump bytes (ours): {our_size:,}")

    # ------------------------------------------------------------------ write
    target_wad.to_file(output_path)
    out_size = os.path.getsize(output_path)
    print(f"  Written: {output_path}  ({out_size/1024:.1f} KB)")
    print()
    print("Integration complete.")
    print(f"Next step — assemble the final HTML tape:")
    print(f"  python3 payloads/doom/build/assemble_html_v3.py payloads/doom/dist/doom_cassette_v3.html")
    print(f"  (set DOOM_V3_WAD={output_path} in the environment, or edit assemble_html_v3.py)")


if __name__ == "__main__":
    main()
