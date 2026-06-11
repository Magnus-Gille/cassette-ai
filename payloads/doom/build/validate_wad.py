#!/usr/bin/env python3
"""Structural validation of a Doom IWAD for the cassette-ai DOOM payload.

Checks: header magic/sanity, directory bounds, required boot-critical lumps
(per doomgeneric source audit), at least one complete map (MAPxx or ExMy),
sprite frame presence, and reports lzma-compressed size.
"""
import lzma
import struct
import sys

REQUIRED = [
    "PLAYPAL", "COLORMAP", "TEXTURE1", "PNAMES",
    "TITLEPIC", "CREDIT", "HELP", "INTERPIC",
    "F_SKY1", "DEMO1", "DEMO2", "DEMO3",
]
MAP_SUBLUMPS = ["THINGS", "LINEDEFS", "SIDEDEFS", "VERTEXES",
                "SEGS", "SSECTORS", "NODES", "SECTORS", "REJECT", "BLOCKMAP"]


def main(path):
    data = open(path, "rb").read()
    errs = []

    # Header
    magic, numlumps, diroff = struct.unpack("<4sii", data[:12])
    if magic != b"IWAD":
        errs.append(f"bad magic {magic!r}, expected IWAD")
    if not (0 < diroff <= len(data) - 16 * numlumps):
        errs.append(f"directory out of bounds: off={diroff} numlumps={numlumps} size={len(data)}")

    # Directory
    names = []
    for i in range(numlumps):
        off, size, name = struct.unpack("<ii8s", data[diroff + 16 * i: diroff + 16 * i + 16])
        name = name.rstrip(b"\x00").decode("ascii", "replace")
        if size > 0 and not (0 <= off and off + size <= len(data)):
            errs.append(f"lump {name} data out of bounds (off={off} size={size})")
        names.append(name)
    nameset = set(names)

    # Required singleton lumps
    missing = [n for n in REQUIRED if n not in nameset]
    if missing:
        errs.append(f"missing required lumps: {missing}")

    # Maps: MAPxx (Doom II) or ExMy
    maps = sorted(n for n in nameset
                  if (len(n) == 5 and n.startswith("MAP") and n[3:].isdigit())
                  or (len(n) == 4 and n[0] == "E" and n[2] == "M"
                      and n[1].isdigit() and n[3].isdigit()))
    if not maps:
        errs.append("no map marker lumps (MAPxx/ExMy) found")
    complete = 0
    for m in maps:
        i = names.index(m)
        following = names[i + 1: i + 1 + len(MAP_SUBLUMPS)]
        if all(s in following for s in MAP_SUBLUMPS):
            complete += 1
    if maps and complete == 0:
        errs.append("no map has the full THINGS..BLOCKMAP sublump set")

    # Classes of lumps that doomgeneric needs at least some of
    counts = {
        "menu M_*": sum(1 for n in nameset if n.startswith("M_")),
        "font STCFN*": sum(1 for n in nameset if n.startswith("STCFN")),
        "statusbar ST*": sum(1 for n in nameset if n.startswith("ST")),
        "sprites (between S_START/S_END)": 0,
        "flats (between F markers)": 0,
    }
    if "S_START" in nameset and "S_END" in nameset:
        counts["sprites (between S_START/S_END)"] = (
            names.index("S_END") - names.index("S_START") - 1)
    else:
        errs.append("missing S_START/S_END sprite markers")
    fs = "F_START" if "F_START" in nameset else ("FF_START" if "FF_START" in nameset else None)
    fe = "F_END" if "F_END" in nameset else ("FF_END" if "FF_END" in nameset else None)
    if fs and fe:
        counts["flats (between F markers)"] = names.index(fe) - names.index(fs) - 1
    else:
        errs.append("missing flat section markers")
    for k in ("menu M_*", "font STCFN*", "statusbar ST*"):
        if counts[k] == 0:
            errs.append(f"no {k} lumps")
    # Player sprite frames (r_things.c hard-errors without consistent frames)
    if not any(n.startswith("PLAY") for n in nameset):
        errs.append("no PLAY* player sprite lumps")

    comp = len(lzma.compress(data, preset=9))

    print(f"file        : {path}")
    print(f"magic       : {magic.decode()}  lumps: {numlumps}  size: {len(data)} B"
          f" ({len(data)/1024:.1f} KB)")
    print(f"lzma -9     : {comp} B ({comp/1024:.1f} KB)")
    print(f"maps        : {len(maps)} markers, {complete} structurally complete"
          f"  (first: {maps[0] if maps else '-'})")
    for k, v in counts.items():
        print(f"{k:32s}: {v}")
    print(f"required ok : {[n for n in REQUIRED if n in nameset]}")
    if errs:
        print("FAIL:")
        for e in errs:
            print("  -", e)
        sys.exit(1)
    print("VALIDATION: PASS")


if __name__ == "__main__":
    main(sys.argv[1])
