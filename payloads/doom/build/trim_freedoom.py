#!/usr/bin/env python3
"""trim_freedoom.py — build a budgeted, faithful-looking E1 IWAD from freedoom1.wad.

Produces freedoom_trim.wad: real Freedoom E1 map(s) + full dependency closure
(textures -> rebuilt TEXTURE1/PNAMES -> patches; flats; THINGS -> front-only
sprites; UI; stub sounds/music/demos; THE-END stub maps for every remaining
E1 slot so no map-progression path can hit a missing lump).

Engine facts this script relies on (verified against payloads/doom/build/src):
  * d_main.c: no E2M1/E3M1/E4M1 lumps  -> gamemode = shareware (episode 1 only).
  * p_switch.c: shareware -> all 19 episode-1 alphSwitchList pairs must exist as
    TEXTURE1 *entries* (R_TextureNumForName I_Errors); patches only needed if used.
  * p_spec.c P_InitPicAnims: anim skipped iff START name absent; if present the
    whole sequence must exist contiguously (texture numbering / flat lump order).
  * r_things.c: per sprite, frames must be contiguous A..max; each frame either
    one rot-0 lump or all 8 rotations.  Front-only (rot1 renamed rot0) is legal
    (miniwad ships exactly that).
  * r_main.c/r_bsp.c: numnodes==0 is legal (bspnum -1 -> R_Subsector(0)),
    so stub maps need no BSP.
  * s_sound.c S_ChangeMusic: W_GetNumForName on D_* unguarded -> music stubs
    mandatory (d_e1m1..9, inter, intro, introa, victor, bunny).
  * f_finale.c: ep1 finale needs flat FLOOR4_8 + HELP2; r_data R_FillBackScreen
    needs FLOOR7_2 + BRDR_*.
  * r_data.c R_InitTextures: every patch referenced by TEXTURE1 must exist.

Run under /usr/bin/python3 (pyenv 3.10 lacks _lzma).
"""
import argparse
import lzma
import struct
import sys
from collections import Counter, defaultdict

HERE = "/Users/magnus/repos/cassette-ai/payloads/doom/build"

# ---------------------------------------------------------------- WAD I/O

def read_wad(path):
    d = open(path, "rb").read()
    ident, num, off = struct.unpack("<4sII", d[:12])
    lumps = []
    for i in range(num):
        o, sz, nm = struct.unpack("<II8s", d[off + 16 * i: off + 16 * i + 16])
        lumps.append((nm.rstrip(b"\0").decode("latin1").upper(), d[o:o + sz]))
    return lumps


def write_wad(path, lumps):
    """Write IWAD with raw-level dedup: identical lump bytes share one data blob."""
    blob_off = {}
    data = bytearray(b"IWAD\0\0\0\0\0\0\0\0")
    direntries = []
    for name, payload in lumps:
        key = bytes(payload)
        if key not in blob_off:
            blob_off[key] = len(data)
            data += key
        direntries.append((blob_off[key], len(payload), name))
    diroff = len(data)
    for off, sz, name in direntries:
        data += struct.pack("<II8s", off if sz else 0, sz, name.encode("ascii").ljust(8, b"\0"))
    struct.pack_into("<II", data, 4, len(direntries), diroff)
    open(path, "wb").write(data)
    return len(data)

# ---------------------------------------------------------------- engine tables

EP1_SWITCH_PAIRS = [
    ("SW1BRCOM", "SW2BRCOM"), ("SW1BRN1", "SW2BRN1"), ("SW1BRN2", "SW2BRN2"),
    ("SW1BRNGN", "SW2BRNGN"), ("SW1BROWN", "SW2BROWN"), ("SW1COMM", "SW2COMM"),
    ("SW1COMP", "SW2COMP"), ("SW1DIRT", "SW2DIRT"), ("SW1EXIT", "SW2EXIT"),
    ("SW1GRAY", "SW2GRAY"), ("SW1GRAY1", "SW2GRAY1"), ("SW1METAL", "SW2METAL"),
    ("SW1PIPE", "SW2PIPE"), ("SW1SLAD", "SW2SLAD"), ("SW1STARG", "SW2STARG"),
    ("SW1STON1", "SW2STON1"), ("SW1STON2", "SW2STON2"), ("SW1STONE", "SW2STONE"),
    ("SW1STRTN", "SW2STRTN"),
]
ALL_SWITCH_NAMES = {n for p in EP1_SWITCH_PAIRS for n in p}

# (startname, endname) per p_spec.c animdefs (struct order is end,start!)
TEX_ANIMS = [
    ("BLODGR1", "BLODGR4"), ("SLADRIP1", "SLADRIP3"), ("BLODRIP1", "BLODRIP4"),
    ("FIREWALA", "FIREWALL"), ("GSTFONT1", "GSTFONT3"), ("FIRELAV3", "FIRELAVA"),
    ("FIREMAG1", "FIREMAG3"), ("FIREBLU1", "FIREBLU2"), ("ROCKRED1", "ROCKRED3"),
    ("BFALL1", "BFALL4"), ("SFALL1", "SFALL4"), ("WFALL1", "WFALL4"),
    ("DBRAIN1", "DBRAIN4"),
]
FLAT_ANIMS = [
    ("NUKAGE1", "NUKAGE3"), ("FWATER1", "FWATER4"), ("SWATER1", "SWATER4"),
    ("LAVA1", "LAVA4"), ("BLOOD1", "BLOOD3"), ("RROCK05", "RROCK08"),
    ("SLIME01", "SLIME04"), ("SLIME05", "SLIME08"), ("SLIME09", "SLIME12"),
]

MUSIC_STUBS = (["D_E1M%d" % i for i in range(1, 10)]
               + ["D_INTER", "D_INTRO", "D_INTROA", "D_VICTOR", "D_BUNNY"])

# doomednum -> sprite prefixes (vanilla info.c, shareware-relevant set)
GLOBAL_SPRITES = ["PLAY", "PUNG", "PISG", "PISF", "PUFF", "BLUD", "TFOG"]
THING_SPRITES = {
    1: ["PLAY"], 2: ["PLAY"], 3: ["PLAY"], 4: ["PLAY"], 11: [], 14: [],
    3004: ["POSS", "CLIP"], 9: ["SPOS", "SHOT", "SHTG", "SHTF"],
    3001: ["TROO", "BAL1"], 3002: ["SARG"], 58: ["SARG"],
    3005: ["HEAD", "BAL2"], 3006: ["SKUL"], 3003: ["BOSS", "BAL7"],
    5: ["BKEY"], 6: ["YKEY"], 13: ["RKEY"], 38: ["RSKU"], 39: ["YSKU"], 40: ["BSKU"],
    8: ["BPAK"], 17: ["CELP"],
    2001: ["SHOT", "SHTG", "SHTF"], 2002: ["MGUN", "CHGG", "CHGF"],
    2003: ["LAUN", "MISG", "MISF", "MISL"],
    2004: ["PLAS", "PLSG", "PLSF", "PLSS", "PLSE"], 2005: ["CSAW", "SAWG"],
    2006: ["BFUG", "BFGG", "BFGF", "BFS1", "BFE1", "BFE2"],
    2007: ["CLIP"], 2008: ["SHEL"], 2010: ["ROCK"], 2046: ["BROK"],
    2047: ["CELL"], 2048: ["AMMO"], 2049: ["SBOX"],
    2011: ["STIM"], 2012: ["MEDI"], 2013: ["SOUL"], 2014: ["BON1"], 2015: ["BON2"],
    2018: ["ARM1"], 2019: ["ARM2"], 2022: ["PINV"], 2023: ["PSTR"], 2024: ["PINS"],
    2025: ["SUIT"], 2026: ["PMAP"], 2028: ["COLU"], 2045: ["PVIS"],
    2035: ["BAR1", "BEXP"],
    10: ["PLAY"], 12: ["PLAY"], 15: ["PLAY"], 18: ["POSS"], 19: ["SPOS"],
    20: ["TROO"], 21: ["SARG"], 23: ["SKUL"],
    24: ["POL5"], 25: ["POL1"], 26: ["POL6"], 27: ["POL4"], 28: ["POL2"], 29: ["POL3"],
    30: ["COL1"], 31: ["COL2"], 32: ["COL3"], 33: ["COL4"], 36: ["COL5"], 37: ["COL6"],
    34: ["CAND"], 35: ["CBRA"], 41: ["CEYE"], 42: ["FSKU"], 43: ["TRE1"],
    44: ["TBLU"], 45: ["TGRN"], 46: ["TRED"], 47: ["SMIT"], 48: ["ELEC"],
    49: ["GOR1"], 50: ["GOR2"], 51: ["GOR3"], 52: ["GOR4"], 53: ["GOR5"],
    54: ["TRE2"], 55: ["SMBT"], 56: ["SMGT"], 57: ["SMRT"],
    59: ["GOR2"], 60: ["GOR4"], 61: ["GOR3"], 62: ["GOR5"], 63: ["GOR1"],
}
DECORATION_NUMS = {10, 12, 15, 18, 19, 20, 21, 23, 24, 25, 26, 27, 28, 29, 30, 31,
                   32, 33, 34, 35, 36, 37, 41, 42, 43, 44, 45, 46, 47, 48, 49, 50,
                   51, 52, 53, 54, 55, 56, 57, 59, 60, 61, 62, 63}

# ---------------------------------------------------------------- helpers

def s8(name):
    return name.encode("ascii").ljust(8, b"\0")


def parse_texture_lump(buf):
    """-> list of dicts {name,width,height,patches:[(ox,oy,pidx)]} in order."""
    n = struct.unpack("<i", buf[:4])[0]
    offs = struct.unpack("<%di" % n, buf[4:4 + 4 * n])
    out = []
    for o in offs:
        name = buf[o:o + 8].rstrip(b"\0").decode("latin1").upper()
        w, h = struct.unpack("<hh", buf[o + 12:o + 16])
        pc = struct.unpack("<h", buf[o + 20:o + 22])[0]
        patches = []
        for i in range(pc):
            po = o + 22 + 10 * i
            ox, oy, pidx = struct.unpack("<hhh", buf[po:po + 6])
            patches.append((ox, oy, pidx))
        out.append({"name": name, "width": w, "height": h, "patches": patches})
    return out


def build_texture_lump(texdefs):
    n = len(texdefs)
    header = struct.pack("<i", n)
    body = b""
    offs = []
    base = 4 + 4 * n
    for t in texdefs:
        offs.append(base + len(body))
        rec = s8(t["name"]) + struct.pack("<ihhi", 0, t["width"], t["height"], 0)
        rec += struct.pack("<h", len(t["patches"]))
        for ox, oy, pidx in t["patches"]:
            rec += struct.pack("<hhhhh", ox, oy, pidx, 1, 0)
        body += rec
    return header + struct.pack("<%di" % n, *offs) + body


def build_pnames(names):
    return struct.pack("<i", len(names)) + b"".join(s8(n) for n in names)


def solid_patch(w, h, color):
    """Doom picture format, single shared column (all columns identical)."""
    col = bytes([0, h, 0]) + bytes([color]) * h + bytes([0, 255])
    hdr = struct.pack("<hhhh", w, h, 0, 0)
    coloff = 8 + 4 * w
    offs = struct.pack("<%di" % w, *([coloff] * w))
    return hdr + offs + col


def common_prefix_len(a, b):
    n = 0
    for x, y in zip(a, b):
        if x != y:
            break
        n += 1
    return n


def lzkb(b):
    return len(lzma.compress(bytes(b), preset=9)) / 1024.0

# ---------------------------------------------------------------- stub map

def make_stub_map(wall_tex, switch_tex, flat):
    """One convex square room (512x512), 0 BSP nodes, exit switch (type 11) on
    the east wall.  Returns dict lumpname->bytes."""
    V = [(0, 0), (0, 512), (512, 512), (512, 0)]
    vertexes = b"".join(struct.pack("<hh", x, y) for x, y in V)
    # clockwise so the right side of each line faces the interior
    lines = [(0, 1, 0), (1, 2, 0), (2, 3, 11), (3, 0, 0)]  # east wall (v2->v3) = exit
    linedefs = b"".join(struct.pack("<7h", v1, v2, 1, special, 0, i, -1)
                        for i, (v1, v2, special) in enumerate(lines))
    sidedefs = b"".join(struct.pack("<hh8s8s8s h".replace(" ", ""), 0, 0, s8("-"), s8("-"),
                                    s8(switch_tex if sp == 11 else wall_tex), 0)
                        for (v1, v2, sp) in lines)
    angles = [0x4000, 0x0000, 0xC000, 0x8000]
    segs = b"".join(struct.pack("<hhHhhh", lines[i][0], lines[i][1], angles[i], i, 0, 0)
                    for i in range(4))
    ssectors = struct.pack("<hh", 4, 0)
    nodes = b""
    sectors = struct.pack("<hh8s8shhh", 0, 128, s8(flat), s8(flat), 160, 0, 0)
    things = struct.pack("<5h", 256, 256, 0, 1, 7)
    reject = b"\0"
    # blockmap: grid covering the room, all blocks share one list of all 4 lines
    x0, y0, bw = -8, -8, 128
    cols = (512 + 8 - x0) // bw + 1
    rows = cols
    header = struct.pack("<4h", x0, y0, cols, rows)
    listoff = 4 + cols * rows               # in words
    offsets = struct.pack("<%dH" % (cols * rows), *([listoff] * (cols * rows)))
    blist = struct.pack("<6H", 0, 0, 1, 2, 3, 0xFFFF)
    blockmap = header + offsets + blist
    return {"THINGS": things, "LINEDEFS": linedefs, "SIDEDEFS": sidedefs,
            "VERTEXES": vertexes, "SEGS": segs, "SSECTORS": ssectors,
            "NODES": nodes, "SECTORS": sectors, "REJECT": reject,
            "BLOCKMAP": blockmap}

# ---------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--iwad", default=HERE + "/freedoom1.wad")
    ap.add_argument("--miniwad", default=HERE + "/miniwad/miniwad.wad")
    ap.add_argument("--out", default=HERE + "/freedoom_trim.wad")
    ap.add_argument("--maps", default="E1M1,E1M2",
                    help="comma list; SRC:DST relabels (e.g. E1M5:E1M2)")
    ap.add_argument("--tex-budget", type=int, default=40)
    ap.add_argument("--flat-budget", type=int, default=30)
    ap.add_argument("--wimap", choices=["stub", "real"], default="stub")
    ap.add_argument("--titlepic", choices=["real", "stub"], default="real")
    ap.add_argument("--sprite-mode", choices=["front", "full"], default="front")
    ap.add_argument("--drop-chaingun", action="store_true")
    ap.add_argument("--remap-spos", action="store_true")
    ap.add_argument("--remap-sarg", action="store_true")
    ap.add_argument("--drop-decorations", action="store_true")
    ap.add_argument("--drop-endoom", action="store_true")
    args = ap.parse_args()

    src = read_wad(args.iwad)
    mini = read_wad(args.miniwad)
    srcidx = {}
    for i, (n, b) in enumerate(src):
        srcidx.setdefault(n, i)
    minib = {}
    for n, b in mini:
        minib.setdefault(n, b)

    report = {"kept": [], "dropped": [], "warn": []}

    # ---- thing-type conversions ------------------------------------------
    conv = {2004: 2002, 2005: 2023, 2006: 2003}     # plasma->chaingun, saw->berserk, BFG->launcher
    if args.drop_chaingun:
        conv[2002] = 2049
        conv[2004] = 2049
        report["dropped"].append("chaingun (2002/2004 -> shell box)")
    if args.remap_spos:
        conv[9] = 3004
        conv[19] = 18
        report["dropped"].append("shotgun-guy SPOS (-> POSS)")
    if args.remap_sarg:
        conv[3002] = 3001
        conv[58] = 3001
        conv[21] = 20
        report["dropped"].append("demon SARG (-> TROO)")

    # ---- extract + edit real maps ----------------------------------------
    map_specs = []
    for item in args.maps.split(","):
        if ":" in item:
            s, dst = item.split(":")
        else:
            s = dst = item
        map_specs.append((s.strip().upper(), dst.strip().upper()))

    MAPL = ["THINGS", "LINEDEFS", "SIDEDEFS", "VERTEXES", "SEGS",
            "SSECTORS", "NODES", "SECTORS", "REJECT", "BLOCKMAP"]
    real_maps = {}          # dst -> {lumpname: bytes}
    used_things = Counter()
    for srcname, dst in map_specs:
        i = srcidx[srcname]
        lumps = {}
        for j in range(i + 1, i + 11):
            n, b = src[j]
            assert n == MAPL[j - i - 1], f"{srcname}: unexpected lump order {n}"
            lumps[n] = bytearray(b)
        # THINGS edits
        t = lumps["THINGS"]
        out_things = bytearray()
        for k in range(0, len(t), 10):
            x, y, ang, typ, fl = struct.unpack("<5h", t[k:k + 10])
            typ = conv.get(typ, typ)
            if args.drop_decorations and typ in DECORATION_NUMS:
                continue
            if typ not in THING_SPRITES:
                report["warn"].append(f"{srcname}: unknown doomednum {typ} removed")
                continue
            used_things[typ] += 1
            out_things += struct.pack("<5h", x, y, ang, typ, fl)
        lumps["THINGS"] = out_things
        lumps["REJECT"] = bytearray(len(lumps["REJECT"]))   # zero-fill
        real_maps[dst] = lumps

    # ---- texture usage ----------------------------------------------------
    texdefs = parse_texture_lump(src[srcidx["TEXTURE1"]][1])
    if "TEXTURE2" in srcidx:
        texdefs += parse_texture_lump(src[srcidx["TEXTURE2"]][1])
    pnames_buf = src[srcidx["PNAMES"]][1]
    npn = struct.unpack("<i", pnames_buf[:4])[0]
    old_pnames = [pnames_buf[4 + 8 * i:12 + 8 * i].rstrip(b"\0").decode("latin1").upper()
                  for i in range(npn)]
    tex_by_name = {}
    tex_order = []
    for t in texdefs:
        if t["name"] not in tex_by_name:
            tex_by_name[t["name"]] = t
            tex_order.append(t["name"])

    tex_refs = Counter()
    mid2s = set()           # textures used as middle on two-sided lines
    for dst, lumps in real_maps.items():
        sd = lumps["SIDEDEFS"]
        ld = lumps["LINEDEFS"]
        two_sided_sd = set()
        for k in range(0, len(ld), 14):
            v1, v2, fl, sp, tag, s0, s1 = struct.unpack("<7h", ld[k:k + 14])
            if s1 != -1:
                two_sided_sd.add(s0)
                two_sided_sd.add(s1)
        for n in range(len(sd) // 30):
            rec = sd[30 * n:30 * n + 30]
            up, lo, mid = (rec[4:12], rec[12:20], rec[20:28])
            for fi, f in enumerate((up, lo, mid)):
                nm = f.rstrip(b"\0").decode("latin1").upper()
                if nm and nm != "-":
                    tex_refs[nm] += 1
                    if fi == 2 and n in two_sided_sd:
                        mid2s.add(nm)
    unknown = [n for n in tex_refs if n not in tex_by_name]
    if unknown:
        sys.exit(f"FATAL: sidedef textures missing from TEXTURE1/2: {unknown}")

    # ---- choose kept textures ---------------------------------------------
    keep_tex = set()
    for nm in tex_refs:
        if nm.startswith(("SW1", "SW2", "EXIT", "DOOR", "BIGDOOR", "SKY")):
            keep_tex.add(nm)
    keep_tex.add("SKY1")
    for a, b in EP1_SWITCH_PAIRS:           # partner of any used switch: real
        if a in keep_tex or b in keep_tex:
            keep_tex.update(x for x in (a, b) if x in tex_by_name)
    for nm, _ in tex_refs.most_common():
        if len(keep_tex) >= args.tex_budget:
            break
        keep_tex.add(nm)
    # animated texture sequences: whole original slice if any member kept/used
    for start, end in TEX_ANIMS:
        if start in tex_order and end in tex_order:
            i0, i1 = tex_order.index(start), tex_order.index(end)
            seq = tex_order[i0:i1 + 1]
            if any(s in keep_tex for s in seq):
                keep_tex.update(seq)
    keep_tex = {t for t in keep_tex if t in tex_by_name}

    # ---- remap dropped textures -------------------------------------------
    anim_members = set()
    for start, end in TEX_ANIMS:
        if start in tex_order and end in tex_order:
            anim_members.update(tex_order[tex_order.index(start):tex_order.index(end) + 1])
    remap_pool = [t for t in keep_tex
                  if t not in ALL_SWITCH_NAMES and t not in anim_members
                  and not t.startswith("SKY")]
    tex_remap = {}
    for nm in tex_refs:
        if nm in keep_tex:
            continue
        t = tex_by_name[nm]
        need_single = nm in mid2s

        def rank(c):
            ct = tex_by_name[c]
            return (ct["width"] == t["width"] and ct["height"] == t["height"],
                    ct["height"] == t["height"],
                    not need_single or len(ct["patches"]) == 1,
                    common_prefix_len(c, nm),
                    tex_refs[c])
        cands = [c for c in remap_pool
                 if not need_single or len(tex_by_name[c]["patches"]) == 1]
        if need_single and not cands:
            tex_remap[nm] = "-"
            report["warn"].append(f"2-sided mid {nm}: no single-patch target, blanked")
            continue
        best = max(cands, key=rank)
        bt = tex_by_name[best]
        if (bt["width"], bt["height"]) != (t["width"], t["height"]) and bt["height"] != t["height"]:
            report["warn"].append(
                f"remap {nm} {t['width']}x{t['height']} -> {best} {bt['width']}x{bt['height']} (dim mismatch)")
        tex_remap[nm] = best

    # ---- flats -------------------------------------------------------------
    flat_region = []        # names in original order between F_START/F_END
    in_f = False
    flat_bytes = {}
    for n, b in src:
        if n in ("F_START", "FF_START"):
            in_f = True
            continue
        if n in ("F_END", "FF_END"):
            in_f = False
            continue
        if in_f and len(b) == 4096 and n not in flat_bytes:
            flat_region.append(n)
            flat_bytes[n] = b

    flat_refs = Counter()
    for dst, lumps in real_maps.items():
        se = lumps["SECTORS"]
        for k in range(0, len(se), 26):
            fl = se[k + 4:k + 12].rstrip(b"\0").decode("latin1").upper()
            ce = se[k + 12:k + 20].rstrip(b"\0").decode("latin1").upper()
            flat_refs[fl] += 1
            flat_refs[ce] += 1
    unknown = [n for n in flat_refs if n not in flat_bytes and n != "F_SKY1"]
    if "F_SKY1" not in flat_bytes:
        sys.exit("FATAL: F_SKY1 missing")
    if unknown:
        sys.exit(f"FATAL: sector flats not found: {unknown}")

    keep_flat = {"F_SKY1", "FLOOR4_8", "FLOOR7_2"}
    for nm, _ in flat_refs.most_common():
        if len(keep_flat) >= args.flat_budget:
            break
        keep_flat.add(nm)
    for start, end in FLAT_ANIMS:
        if start in flat_region and end in flat_region:
            i0, i1 = flat_region.index(start), flat_region.index(end)
            seq = flat_region[i0:i1 + 1]
            if any(s in keep_flat for s in seq):
                keep_flat.update(seq)
    keep_flat = {f for f in keep_flat if f in flat_bytes}

    flat_anim_members = set()
    for start, end in FLAT_ANIMS:
        if start in flat_region and end in flat_region:
            flat_anim_members.update(flat_region[flat_region.index(start):flat_region.index(end) + 1])
    flat_pool = [f for f in keep_flat if f != "F_SKY1" and f not in flat_anim_members]
    flat_remap = {}
    for nm in flat_refs:
        if nm in keep_flat:
            continue
        best = max(flat_pool, key=lambda c: (common_prefix_len(c, nm), flat_refs[c]))
        flat_remap[nm] = best

    # ---- apply remaps to sidedefs/sectors -----------------------------------
    for dst, lumps in real_maps.items():
        sd = lumps["SIDEDEFS"]
        for n in range(len(sd) // 30):
            base = 30 * n
            for fo in (4, 12, 20):
                nm = sd[base + fo:base + fo + 8].rstrip(b"\0").decode("latin1").upper()
                if nm in tex_remap:
                    sd[base + fo:base + fo + 8] = s8(tex_remap[nm])
        se = lumps["SECTORS"]
        for k in range(0, len(se), 26):
            for fo in (4, 12):
                nm = se[k + fo:k + fo + 8].rstrip(b"\0").decode("latin1").upper()
                if nm in flat_remap:
                    se[k + fo:k + fo + 8] = s8(flat_remap[nm])

    # ---- rebuild TEXTURE1 + PNAMES ------------------------------------------
    DUMMY_PATCH = "ZZDUMMY1"
    new_pnames = []
    pidx_of = {}

    def pname_index(nm):
        if nm not in pidx_of:
            pidx_of[nm] = len(new_pnames)
            new_pnames.append(nm)
        return pidx_of[nm]

    pname_index(DUMMY_PATCH)
    new_texdefs = [{"name": "AASTINKY", "width": 8, "height": 8,
                    "patches": [(0, 0, 0)]}]            # index 0 = never-drawn sentinel
    real_entries = [t for t in tex_order if t in keep_tex]
    for nm in real_entries:
        t = tex_by_name[nm]
        patches = [(ox, oy, pname_index(old_pnames[pidx])) for ox, oy, pidx in t["patches"]]
        new_texdefs.append({"name": nm, "width": t["width"], "height": t["height"],
                            "patches": patches})
    stub_switches = []
    for a, b in EP1_SWITCH_PAIRS:
        for nm in (a, b):
            if nm not in keep_tex and not any(d["name"] == nm for d in new_texdefs):
                new_texdefs.append({"name": nm, "width": 8, "height": 8,
                                    "patches": [(0, 0, 0)]})
                stub_switches.append(nm)

    patch_lumps = {}
    for nm in new_pnames:
        if nm == DUMMY_PATCH:
            patch_lumps[nm] = solid_patch(8, 8, 96)
        else:
            if nm not in srcidx:
                sys.exit(f"FATAL: patch {nm} not found in IWAD")
            patch_lumps[nm] = src[srcidx[nm]][1]

    # ---- sprites -------------------------------------------------------------
    sprite_prefixes = set(GLOBAL_SPRITES)
    for typ in used_things:
        sprite_prefixes.update(THING_SPRITES[typ])
    if args.drop_chaingun:
        sprite_prefixes -= {"MGUN", "CHGG", "CHGF"}
    if args.remap_spos:
        sprite_prefixes -= {"SPOS"}
    if args.remap_sarg:
        sprite_prefixes -= {"SARG"}

    s0 = next(i for i, (n, _) in enumerate(src) if n == "S_START")
    s1 = next(i for i, (n, _) in enumerate(src) if n == "S_END")
    sprite_src = defaultdict(list)          # prefix -> [(name, bytes)]
    for n, b in src[s0 + 1:s1]:
        if len(n) >= 6:
            sprite_src[n[:4]].append((n, b))

    sprite_lumps = []                       # (name, bytes)
    for pref in sorted(sprite_prefixes):
        lumps = sprite_src.get(pref)
        if not lumps:
            sys.exit(f"FATAL: no sprite lumps for prefix {pref}")
        if args.sprite_mode == "full":
            sprite_lumps.extend(lumps)
            continue
        # front-only: per frame keep rot0 as-is, else the rot-1 image renamed F0
        by_frame = {}
        for n, b in lumps:
            pairs = [(n[4], n[5])] + ([(n[6], n[7])] if len(n) == 8 else [])
            for frame, rot in pairs:
                by_frame.setdefault(frame, {})[rot] = (n, b)
        for frame in sorted(by_frame):
            rots = by_frame[frame]
            if "0" in rots:
                sprite_lumps.append((pref + frame + "0", rots["0"][1]))
            elif "1" in rots:
                sprite_lumps.append((pref + frame + "0", rots["1"][1]))
            else:
                sys.exit(f"FATAL: sprite {pref} frame {frame} has no rot 0/1 lump")
        # frame contiguity check (engine requirement)
        frames = sorted(by_frame)
        expect = [chr(ord("A") + i) for i in range(len(frames))]
        if frames != expect:
            sys.exit(f"FATAL: sprite {pref} frames not contiguous: {frames}")

    # ---- UI / fixed lumps ------------------------------------------------------
    def src_lump(nm):
        return src[srcidx[nm]][1]

    fixed = []
    fixed.append(("PLAYPAL", src_lump("PLAYPAL")))
    fixed.append(("COLORMAP", src_lump("COLORMAP")))
    if not args.drop_endoom:
        fixed.append(("ENDOOM", src_lump("ENDOOM")))
    else:
        report["dropped"].append("ENDOOM")
    demo = minib["DEMO1"]
    for d in ("DEMO1", "DEMO2", "DEMO3", "DEMO4"):
        fixed.append((d, demo))
    title = src_lump("TITLEPIC") if args.titlepic == "real" else solid_patch(320, 200, 0)
    fixed.append(("TITLEPIC", title))
    for alias in ("HELP", "HELP1", "HELP2", "CREDIT", "INTERPIC"):
        fixed.append((alias, title))       # byte-aliases, free after dedup

    ui_names = []
    for n, b in src:
        if n.startswith(("M_", "BRDR_", "AMMNUM")) or \
           (n.startswith("ST") and not n.startswith("STEP")):
            if n not in ("ENDOOM",):
                ui_names.append(n)
    wi_keep = {"WIURH0", "WIURH1", "WISPLAT", "WIMINUS", "WIPCNT", "WIF", "WIENTER",
               "WIOSTK", "WIOSTS", "WISCRT2", "WIOSTI", "WIFRGS", "WICOLON",
               "WITIME", "WISUCKS", "WIPAR", "WIKILRS", "WIVCTMS", "WIMSTT"}
    wi_keep.update("WINUM%d" % i for i in range(10))
    wi_keep.update("WIP%d" % i for i in range(1, 5))
    wi_keep.update("WIBP%d" % i for i in range(1, 5))
    wi_keep.update("WILV0%d" % i for i in range(9))
    for n, b in src:
        if n in wi_keep or n.startswith("WIA0"):
            ui_names.append(n)
    seen = set()
    for n in ui_names:
        if n not in seen and n in srcidx:
            seen.add(n)
            fixed.append((n, src_lump(n)))
    wimap = src_lump("WIMAP0") if args.wimap == "real" else solid_patch(320, 200, 0)
    fixed.append(("WIMAP0", wimap))

    # no compiled code path reads GENMIDI (no OPL module in this build) — stub it
    fixed.append(("GENMIDI", b"#OPL_II#"))
    ds_stub, dp_stub, d_stub = minib["DSBFG"], minib["DPBFG"], minib["D_RUNNIN"]
    for n, b in mini:
        if n.startswith("DS"):
            fixed.append((n, ds_stub))
        elif n.startswith("DP"):
            fixed.append((n, dp_stub))
    for n in MUSIC_STUBS:
        fixed.append((n, d_stub))

    # ---- stub maps ---------------------------------------------------------
    sw_real = next((a for a, b in EP1_SWITCH_PAIRS if a in keep_tex), None)
    wall = max((t for t in remap_pool), key=lambda c: tex_refs[c])
    stub = make_stub_map(wall, sw_real or wall, "FLOOR4_8")

    # ---- assemble ----------------------------------------------------------
    out = list(fixed)
    have_maps = set(real_maps)
    for dst in sorted(real_maps):
        out.append((dst, b""))
        for ln in MAPL:
            out.append((ln, bytes(real_maps[dst][ln])))
    for slot in range(1, 10):
        nm = "E1M%d" % slot
        if nm in have_maps:
            continue
        out.append((nm, b""))
        for ln in MAPL:
            out.append((ln, stub[ln]))
    out.append(("TEXTURE1", build_texture_lump(new_texdefs)))
    out.append(("PNAMES", build_pnames(new_pnames)))
    out.append(("P_START", b""))
    for nm in new_pnames:
        out.append((nm, patch_lumps[nm]))
    out.append(("P_END", b""))
    out.append(("S_START", b""))
    out.extend(sprite_lumps)
    out.append(("S_END", b""))
    out.append(("F_START", b""))
    for nm in flat_region:                  # original order keeps anims contiguous
        if nm in keep_flat:
            out.append((nm, flat_bytes[nm]))
    out.append(("F_END", b""))

    raw = write_wad(args.out, out)

    # ---- internal closure validation ----------------------------------------
    errs = []
    final = read_wad(args.out)
    fnames = [n for n, _ in final]
    fset = set(fnames)
    texnames = {t["name"] for t in new_texdefs}
    for dst, lumps in real_maps.items():
        sd = lumps["SIDEDEFS"]
        for n in range(len(sd) // 30):
            for fo in (4, 12, 20):
                nm = sd[30 * n + fo:30 * n + fo + 8].rstrip(b"\0").decode("latin1").upper()
                if nm and nm != "-" and nm not in texnames:
                    errs.append(f"{dst} sidedef {n}: texture {nm} not in TEXTURE1")
                if nm == "AASTINKY":
                    errs.append(f"{dst}: sidedef references sentinel texture 0")
        se = lumps["SECTORS"]
        fkept = set(keep_flat)
        for k in range(0, len(se), 26):
            for fo in (4, 12):
                nm = se[k + fo:k + fo + 8].rstrip(b"\0").decode("latin1").upper()
                if nm not in fkept:
                    errs.append(f"{dst} sector flat {nm} not kept")
    for t in new_texdefs:
        for ox, oy, pidx in t["patches"]:
            if pidx >= len(new_pnames) or new_pnames[pidx] not in fset:
                errs.append(f"texture {t['name']}: bad patch index {pidx}")
    for a, b in EP1_SWITCH_PAIRS:
        for nm in (a, b):
            if nm not in texnames:
                errs.append(f"switch entry {nm} missing from TEXTURE1")
    for start, end in TEX_ANIMS:
        order = [t["name"] for t in new_texdefs]
        if start in order:
            if end not in order:
                errs.append(f"tex anim {start}: end {end} missing")
            else:
                i0, i1 = order.index(start), order.index(end)
                if i1 - i0 < 1:
                    errs.append(f"tex anim {start}..{end}: bad cycle")
    out_flat_order = [nm for nm in flat_region if nm in keep_flat]
    for start, end in FLAT_ANIMS:
        if start in out_flat_order:
            if end not in out_flat_order:
                errs.append(f"flat anim {start}: end {end} missing")
            else:
                i0, i1 = out_flat_order.index(start), out_flat_order.index(end)
                orig = flat_region[flat_region.index(start):flat_region.index(end) + 1]
                if out_flat_order[i0:i1 + 1] != orig:
                    errs.append(f"flat anim {start}..{end} not contiguous")
    for nm in ("E1M%d" % i for i in range(1, 10)):
        if nm not in fset:
            errs.append(f"map {nm} missing")
    for nm in ("E2M1", "E3M1", "E4M1"):
        if nm in fset:
            errs.append(f"{nm} present — would break shareware detection")
    for nm in MUSIC_STUBS + ["GENMIDI", "F_SKY1", "FLOOR4_8", "FLOOR7_2",
                             "WIMAP0", "PLAYPAL", "COLORMAP", "STBAR", "STFST00"]:
        if nm not in fset:
            errs.append(f"required lump {nm} missing")
    # sprite sanity in final wad
    si0, si1 = fnames.index("S_START"), fnames.index("S_END")
    by_pref = defaultdict(set)
    for n, _ in final[si0 + 1:si1]:
        if len(n) != 6 or n[5] != "0":
            errs.append(f"sprite lump {n}: expected XXXXF0 form")
        else:
            by_pref[n[:4]].add(n[4])
    for pref, frames in by_pref.items():
        fr = sorted(frames)
        if fr != [chr(ord("A") + i) for i in range(len(fr))]:
            errs.append(f"sprite {pref}: frames {fr} not contiguous")
    for pref in sprite_prefixes:
        if pref not in by_pref:
            errs.append(f"sprite prefix {pref} absent")

    if errs:
        for e in errs:
            print("VALIDATION ERROR:", e)
        sys.exit(1)

    # ---- report --------------------------------------------------------------
    wad_bytes = open(args.out, "rb").read()
    print(f"== {args.out}")
    print(f"maps: {[f'{s}->{d}' if s != d else s for s, d in map_specs]} + stubs for the rest of E1")
    print(f"textures kept {len(real_entries)} real (+{len(stub_switches)} stub switch entries), "
          f"remapped {len(tex_remap)}; coverage {sum(tex_refs[t] for t in keep_tex)}/{sum(tex_refs.values())} refs "
          f"({100.0 * sum(tex_refs[t] for t in keep_tex) / sum(tex_refs.values()):.1f}%)")
    print(f"flats kept {len(keep_flat)}, remapped {len(flat_remap)}; coverage "
          f"{100.0 * sum(flat_refs[f] for f in keep_flat if f in flat_refs) / sum(flat_refs.values()):.1f}%")
    print(f"sprites: {len(sprite_prefixes)} prefixes, {len(sprite_lumps)} lumps ({args.sprite_mode})")
    print(f"patches: {len(new_pnames)} | things kept: {sum(used_things.values())}")
    for w in report["warn"]:
        print("  warn:", w)
    if report["dropped"]:
        print("dropped:", "; ".join(report["dropped"]))
    print(f"RAW {raw / 1024:.1f} KB   LZMA9 {lzkb(wad_bytes):.1f} KB")


if __name__ == "__main__":
    main()
