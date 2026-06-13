#!/usr/bin/env python3
"""trim_freedoom_v3b.py — v3b: a SLIGHTLY trimmed v3 to gain ~2 min tape margin.

Copy-and-extend of trim_freedoom_v3.py (frozen).  v3b's job: shave ~62-70 KB
of *packed* (h9-lzma) payload off the v3 cassette so DOOM side A drops from
44.77 min to ~42.7 min on a physical 45.0-min C90 side (>=1.7 min margin
REQUIRED, ~2.2 min TARGET).  Nothing about gameplay changes.

Pre-registered drop order (stop at TARGET; all closure-safe):
  STEP 1  --v3b-demo-stub : DEMO1/2/3/4 -> the 18 B miniwad SP stub (loses only
          the idle attract demo; the engine boots the stub cleanly).
  STEP 3  --v3b-bigpic-alias : CREDIT/HELP/HELP1/HELP2 (one 68168 B blob in v3)
          aliased to the TITLEPIC blob -> one full 68 KB blob removed.  Lumps
          still resolve (write_wad dedup), so closure holds; the attract credit
          page + F1 help now show the title art.  PLAYPAL/COLORMAP/HUD/status
          bar/WILV intermission pics/WIMAP0 untouched.  Biggest single safe lever.
  STEP 2  --v3b-drop-decorations : drop the 23 PLACED pure-decoration sprite
          prefixes (TRE1/TRE2/SMIT/ELEC/POL5/POL6/CBRA/CAND/TGRN/GOR1/GOR2/GOR4/
          GOR5/FSKU/COL1/COL2/COL3/COL5/TBLU/TRED/SMBT/SMGT/SMRT) and FORCE-
          REMOVE the 197 THINGS that reference them so no kept map points at a
          missing sprite.  Corpse/gib decorations (dn 10/12/15/18/19/20/21/23)
          share LIVING monster/player sprites (PLAY/POSS/SPOS/TROO/SARG/SKUL/
          BLUD) and are KEPT IN PLACE.  TEXTURE1/PNAMES/flats untouched.
  STEP 4  --v3b-sfx-8k : downsample (NOT drop) the 6 largest monster-vocal barks
          to 8 kHz via the existing audioop ratecv path.  Only reached for TARGET.

Closure is preserved at build time AND re-checked by the v3 internal validator
(the same self-validation block trim_freedoom_v3 runs before writing): every
referenced texture/flat/sprite-frame and every kept-thing sfx must resolve.

--- original trim_freedoom_v3 docstring follows ---

trim_freedoom_v3.py — full Freedoom Phase 1 EPISODE 1 IWAD for the v3 cassette.

Copy-and-extend of trim_freedoom.py (v2 trimmer, frozen).  v3 differences:
  * ALL nine maps E1M1..E1M9 real (no stub map slots needed).
  * Full E1 bestiary + all SP-placed weapons real (plasma + chainsaw kept;
    the single MP-only BFG placement converted to rocket launcher — recon
    pre-registered free drop; --keep-bfg restores it).
  * Real DS* sound effects for the engine-reachable set (ground truth derived
    from src/info.c mobjinfo sfx fields of kept MTs + per-function sfx_ grep
    over src/*.c with absent-monster action functions excluded; 58 of 69
    lumps).  Unreachable DS* (cyber/spider/caco/ouch/skldth/jump) stay stubs.
    Budget ladder (pre-registered): (a) downsample >cap to --sfx-rate-cap
    (default 11025), (b) byte-alias per SFX_ALIAS_LADDER (--sfx-alias-level).
  * Music dropped: every D_* music name is a stub (S_ChangeMusic does an
    unguarded W_GetNumForName, and IDMUS01..32 can request any doom1 slot,
    so the full registered-doom1 music namespace is stubbed).  GENMIDI stub.
    No DMXGUS.
  * DEMO1 real from the IWAD (E1M6 SP attract demo, header-validated);
    DEMO2/3/4 are E2/E3/E4 in Freedoom -> byte-aliased to DEMO1 (free).
  * Intermission/finale real: WIMAP0, WILV00-08, CREDIT, HELP2 (HELP/HELP1
    alias HELP2; INTERPIC aliases TITLEPIC — never drawn in doom1 mode).
  * Stray doomednum 22 (dead-cacodemon decoration, E1M9) dropped — keeping
    it would pull the full HEAD A..L sprite set for a corpse.
  * --sprite-mode full validation fixed (v2 checked XXXXF0 names only).

Engine facts relied on: see trim_freedoom.py header (unchanged).
Run under /usr/bin/python3 (needs _lzma + audioop; pyenv 3.10 lacks _lzma).

SHIP CONFIG (2026-06-12, defaults below reproduce it):
  --tex-budget 70 --flat-budget 60 --sprite-mode front --sfx-rate-cap 11025
  --sfx-alias-level 8  ->  freedoom_e1_v3.wad  RAW 4482.2 KB, LZMA9 1393.8 KB
  (WAD-slice band 1.30-1.45 MB lzma; total-artifact TARGET 1.50 MB holds for
  engine <=130 KB lzma).  Measured ladder: tex100/alias0 1577.6 KB (over cap),
  tex100/a8 1470.8, tex80/a8 1403.3, tex70/a8 1393.8, tex60/a8 1374.6.
  No decoration drops, no demo stubbing — drop-order steps beyond the sfx
  ladder were not needed.
"""
import argparse
import audioop
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

# Full registered-doom1 music namespace (S_music doom1 slice + specials):
# IDMUSxy can reach mus_e1m1+0..31 = e1m1..e3m9,inter,intro,bunny,victor,introa.
MUSIC_STUBS = (["D_E%dM%d" % (e, m) for e in (1, 2, 3) for m in range(1, 10)]
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
# Pre-registered drops (recon 2026-06-12): dead-caco corpse would force HEAD A..L.
KNOWN_DROP_THINGS = {22: "dead cacodemon corpse (would pull full HEAD sprite set)"}

# ---- v3 sound tables ---------------------------------------------------------
# Engine-reachable DS* set, frozen ground truth (derivation in module docstring).
# NOT in this set (stay stubs): DSCACSIT DSCACDTH (no HEAD placed once dn-22
# dropped), DSCYBSIT DSCYBDTH DSHOOF DSMETAL (cyberdemon), DSSPISIT DSSPIDTH
# (mastermind), DSOUCH DSSKLDTH (defined but unreferenced in vanilla code),
# DSJUMP (Freedoom extra, no engine reference).
USED_SFX = [
    "DSBAREXP", "DSBDCLS", "DSBDOPN", "DSBFG", "DSBGACT", "DSBGDTH1",
    "DSBGDTH2", "DSBGSIT1", "DSBGSIT2", "DSBRSDTH", "DSBRSSIT", "DSCLAW",
    "DSDMACT", "DSDMPAIN", "DSDORCLS", "DSDOROPN", "DSFIRSHT", "DSFIRXPL",
    "DSGETPOW", "DSITEMUP", "DSITMBK", "DSNOWAY", "DSOOF", "DSPDIEHI",
    "DSPISTOL", "DSPLASMA", "DSPLDETH", "DSPLPAIN", "DSPODTH1", "DSPODTH2",
    "DSPODTH3", "DSPOPAIN", "DSPOSACT", "DSPOSIT1", "DSPOSIT2", "DSPOSIT3",
    "DSPSTART", "DSPSTOP", "DSPUNCH", "DSRLAUNC", "DSRXPLOD", "DSSAWFUL",
    "DSSAWHIT", "DSSAWIDL", "DSSAWUP", "DSSGCOCK", "DSSGTATK", "DSSGTDTH",
    "DSSGTSIT", "DSSHOTGN", "DSSKLATK", "DSSLOP", "DSSTNMOV", "DSSWTCHN",
    "DSSWTCHX", "DSTELEPT", "DSTINK", "DSWPNUP",
]
# Pre-registered alias ladder (recon, frozen order): aliased lumps share the
# target's bytes — free after write_wad dedup.  Steps 1-5 are near-inaudible
# (MP-only respawn blip, blaze->normal doors, 3rd sight/death bark variants);
# 6 retires the 107 KB baron sight bark to the imp bark; 7-8 are cheat-only
# (BFG is never placed in SP — fire/explode only reachable via IDFA/IDKFA).
SFX_ALIAS_LADDER = [
    ("DSITMBK", "DSITEMUP"),    # 1  deathmatch item-respawn blip
    ("DSBDOPN", "DSDOROPN"),    # 2  blaze door open -> door open
    ("DSBDCLS", "DSDORCLS"),    # 3  blaze door close -> door close
    ("DSPOSIT3", "DSPOSIT2"),   # 4  zombie sight bark #3 -> #2
    ("DSPODTH3", "DSPODTH2"),   # 5  zombie death bark #3 -> #2
    ("DSBRSSIT", "DSBGSIT2"),   # 6  baron sight (107 KB @44k1) -> imp sight
    ("DSBFG", "DSPLASMA"),      # 7  BFG fire (cheat-only)
    ("DSRXPLOD", "DSBAREXP"),   # 8  BFG ball explode (cheat-only)
]

# ---- v3b tables --------------------------------------------------------------
# STEP 2: the 23 PLACED pure-decoration doomednums.  Removed from every map's
# THINGS lump (so no kept map references a dropped sprite prefix) AND their
# sprite prefixes never enter the kept set (because no surviving thing places
# them).  These are subset of DECORATION_NUMS; the CORPSE/GIB decorations
# (10,12,15,18,19,20,21,23 -> PLAY/POSS/SPOS/TROO/SARG/SKUL/BLUD) are NOT here
# because their sprites must survive for the living monsters/player anyway, so
# dropping the corpse THINGS would save no sprite bytes — they stay in place.
# (dn 49/50/52 are the alt doomednums of GOR1/GOR2/GOR4; Freedoom E1 places the
# 59/60/63 variants, but listing both is harmless — removal is by doomednum.)
V3B_DECORATION_DROP_DNS = {
    54, 43, 47, 48,            # TRE2, TRE1, SMIT, ELEC
    24, 26,                    # POL5 (blood pool), POL6 (impaled human)
    35, 34, 45,                # CBRA, CAND, TGRN
    49, 63, 50, 59, 52, 60, 53, 62,   # GOR1/GOR2/GOR4/GOR5 hanging bodies
    42,                        # FSKU floating skull rock
    30, 31, 32, 36,            # COL1/COL2/COL3/COL5 pillars
    44, 46, 55, 56, 57,        # TBLU/TRED/SMBT/SMGT/SMRT torches
}

# STEP 4: the 6 largest MONSTER-VOCAL barks (death/sight/active vocalizations),
# downsampled (NOT dropped) to 8 kHz.  These are not weapons, doors, pickups,
# player sounds, UI, or any sound-core effect — they still PLAY, just at a
# lower rate.  Applied via the same audioop ratecv path used for the rate-cap.
V3B_SFX_8K = ["DSBRSDTH", "DSPODTH1", "DSSGTDTH", "DSPOSIT1", "DSDMACT", "DSPOSACT"]
V3B_SFX_8K_RATE = 8000

# STEP 3: big presentation pics aliased to TITLEPIC (closure-safe; lumps still
# resolve via write_wad dedup).  Applied at assemble time after the v3 fixed[]
# list is built, by rewriting these lumps' bytes to the TITLEPIC bytes.
V3B_BIGPIC_ALIAS_TO_TITLE = ("CREDIT", "HELP", "HELP1", "HELP2")

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


def downsample_dmx(buf, cap):
    """DMX sound lump: u16 fmt(3), u16 rate, u32 nsamples, u8 PCM.  Resample
    anything above `cap` Hz down to cap (audioop linear ratecv on de-biased
    signed bytes).  Lumps at/below cap pass through untouched."""
    if cap <= 0 or len(buf) < 8:
        return bytes(buf)
    fmt, rate = struct.unpack("<HH", buf[:4])
    n = struct.unpack("<I", buf[4:8])[0]
    if fmt != 3 or rate <= cap or n == 0 or len(buf) < 8 + n:
        return bytes(buf)
    pcm = bytes(buf[8:8 + n])
    signed = audioop.bias(pcm, 1, -128)          # unsigned 8-bit -> signed
    out, _ = audioop.ratecv(signed, 1, 1, rate, cap, None)
    out = audioop.bias(out, 1, 128)
    return struct.pack("<HHI", 3, cap, len(out)) + out


def demo_e1_compatible(buf, kept_maps):
    """True if a vanilla demo lump is playable on this E1-only IWAD:
    v1.9 header, episode 1, target map kept, single-player (no netgame)."""
    if len(buf) < 14:
        return False, "too short"
    ver, skill, ep, mp, dm = buf[0], buf[1], buf[2], buf[3], buf[4]
    players = list(buf[9:13])
    if ver != 109:
        return False, f"version {ver} != 109"
    if ep != 1 or ("E1M%d" % mp) not in kept_maps:
        return False, f"plays E{ep}M{mp} (not kept)"
    if dm != 0 or players[1:] != [0, 0, 0] or players[0] != 1:
        return False, "not a single-player demo"
    return True, f"E{ep}M{mp} skill {skill + 1} SP"

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
    ap.add_argument("--out", default=HERE + "/freedoom_e1_v3b.wad")
    ap.add_argument("--maps", default=",".join("E1M%d" % i for i in range(1, 10)),
                    help="comma list; SRC:DST relabels (e.g. E1M5:E1M2)")
    ap.add_argument("--tex-budget", type=int, default=70)
    ap.add_argument("--flat-budget", type=int, default=60)
    ap.add_argument("--wimap", choices=["stub", "real"], default="real")
    ap.add_argument("--titlepic", choices=["real", "stub"], default="real")
    ap.add_argument("--sprite-mode", choices=["front", "full"], default="front")
    ap.add_argument("--keep-bfg", action="store_true",
                    help="keep the MP-only BFG placement + sprites (default: ->launcher)")
    ap.add_argument("--sfx-mode", choices=["real", "stub"], default="real")
    ap.add_argument("--sfx-rate-cap", type=int, default=11025,
                    help="downsample DS* lumps above this rate (0 = keep original)")
    ap.add_argument("--sfx-alias-level", type=int, default=8,
                    help="apply first N entries of SFX_ALIAS_LADDER (0..%d)"
                         % len(SFX_ALIAS_LADDER))
    ap.add_argument("--demos", choices=["real", "stub"], default="real",
                    help="real: IWAD DEMO1 attract loop (header-validated), aliased x4")
    ap.add_argument("--drop-decorations", action="store_true")
    ap.add_argument("--drop-endoom", action="store_true")
    # ---- v3b margin levers (pre-registered drop order) ----
    ap.add_argument("--v3b-demo-stub", action="store_true",
                    help="STEP 1: DEMO1/2/3/4 -> 18 B miniwad SP stub")
    ap.add_argument("--v3b-bigpic-alias", action="store_true",
                    help="STEP 3: CREDIT/HELP/HELP1/HELP2 -> TITLEPIC blob")
    ap.add_argument("--v3b-drop-decorations", action="store_true",
                    help="STEP 2: drop 23 placed pure-decoration sprites + their THINGS")
    ap.add_argument("--v3b-sfx-8k", action="store_true",
                    help="STEP 4: downsample 6 monster-vocal barks to 8 kHz")
    # ---- v3b STEP 5/6 (next pre-registered tiers, only if 1-4 miss REQUIRED) ----
    ap.add_argument("--v3b-wimap-alias", action="store_true",
                    help="STEP 5 (tier 3 ext): alias WIMAP0 intermission bg to TITLEPIC")
    ap.add_argument("--v3b-sfx-cap-8k", action="store_true",
                    help="STEP 6 (tier 4 ext): cap ALL real sfx at 8 kHz (still play)")
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
    conv = {} if args.keep_bfg else {2006: 2003}    # BFG (MP-only in E1) -> launcher
    if not args.keep_bfg:
        report["dropped"].append("BFG9000 (MP-only placement -> rocket launcher)")

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
    known_drops = Counter()
    v3b_decor_drops = Counter()
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
            if typ in KNOWN_DROP_THINGS:
                known_drops[typ] += 1
                continue
            if args.drop_decorations and typ in DECORATION_NUMS:
                continue
            if args.v3b_drop_decorations and typ in V3B_DECORATION_DROP_DNS:
                v3b_decor_drops[typ] += 1
                continue
            if typ not in THING_SPRITES:
                report["warn"].append(f"{srcname}: unknown doomednum {typ} removed")
                continue
            used_things[typ] += 1
            out_things += struct.pack("<5h", x, y, ang, typ, fl)
        lumps["THINGS"] = out_things
        lumps["REJECT"] = bytearray(len(lumps["REJECT"]))   # zero-fill
        real_maps[dst] = lumps
    for typ, cnt in known_drops.items():
        report["dropped"].append(f"doomednum {typ} x{cnt}: {KNOWN_DROP_THINGS[typ]}")
    if args.v3b_drop_decorations:
        report["dropped"].append(
            "v3b decorations: %d THINGS across maps (dns %s)"
            % (sum(v3b_decor_drops.values()),
               ",".join(str(t) for t in sorted(v3b_decor_drops))))

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
            frames = sorted({n[4] for n, _ in lumps} |
                            {n[6] for n, _ in lumps if len(n) == 8})
            expect = [chr(ord("A") + i) for i in range(len(frames))]
            if frames != expect:
                sys.exit(f"FATAL: sprite {pref} frames not contiguous: {frames}")
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

    # demos: real IWAD DEMO1 (E1M6 attract) if compatible; E2/E3/E4 demos
    # (DEMO2/3/4) cannot play on an E1-only wad -> byte-alias to DEMO1 (free).
    demo_note = "stub"
    if args.v3b_demo_stub:
        d1 = minib["DEMO1"]
        ok, why = demo_e1_compatible(d1, set(real_maps))
        if not ok:
            sys.exit(f"FATAL: v3b miniwad DEMO1 stub not E1-compatible ({why})")
        demo_note = f"v3b stub ({why}, 18 B), DEMO2/3/4 aliased"
        report["dropped"].append("DEMO1/2/3/4 -> 18 B miniwad SP stub (no attract demo)")
        for d in ("DEMO1", "DEMO2", "DEMO3", "DEMO4"):
            fixed.append((d, d1))
    else:
        if args.demos == "real":
            d1 = src_lump("DEMO1")
            ok, why = demo_e1_compatible(d1, set(real_maps))
            if ok:
                demo_note = f"real DEMO1 ({why}), DEMO2/3/4 aliased"
            else:
                report["warn"].append(f"DEMO1 incompatible ({why}) -> stub")
                d1 = minib["DEMO1"]
                demo_note = "stub (real incompatible)"
        else:
            d1 = minib["DEMO1"]
        for d in ("DEMO1", "DEMO2", "DEMO3", "DEMO4"):
            fixed.append((d, d1))

    title = src_lump("TITLEPIC") if args.titlepic == "real" else solid_patch(320, 200, 0)
    fixed.append(("TITLEPIC", title))
    # demo-loop pages real in v3: CREDIT + HELP2 (shareware D_PageDrawer cycle,
    # f_finale ep1 end screen).  HELP/HELP1 alias HELP2; INTERPIC (doom2-only
    # code path, but validate_wad requires it) aliases TITLEPIC.
    # v3b STEP 3: alias CREDIT/HELP/HELP1/HELP2 to the TITLEPIC blob (closure-
    # safe — lumps still resolve via write_wad dedup; only the art shown on the
    # attract credit page / F1 help changes).  Frees one 68 KB blob.
    if args.v3b_bigpic_alias:
        credit = help2 = title
        report["dropped"].append(
            "v3b bigpic: CREDIT/HELP/HELP1/HELP2 aliased to TITLEPIC blob")
        demo_note += " | credit/help -> title art"
    else:
        credit = src_lump("CREDIT")
        help2 = src_lump("HELP2")
    fixed.append(("CREDIT", credit))
    fixed.append(("HELP2", help2))
    fixed.append(("HELP1", help2))
    fixed.append(("HELP", help2))
    fixed.append(("INTERPIC", title))

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
    # v3b STEP 5 (tier 3 ext): alias the intermission background WIMAP0 to the
    # TITLEPIC blob (closure-safe — lump resolves; the "you are here" splats and
    # level-name pics still draw ON TOP, only the background art changes).
    if args.v3b_wimap_alias:
        wimap = title
        report["dropped"].append("v3b wimap: WIMAP0 intermission bg aliased to TITLEPIC")
    else:
        wimap = src_lump("WIMAP0") if args.wimap == "real" else solid_patch(320, 200, 0)
    fixed.append(("WIMAP0", wimap))

    # ---- sounds ----------------------------------------------------------------
    # Music dropped entirely: every D_* is the miniwad stub (S_ChangeMusic is
    # unguarded).  GENMIDI stub (no OPL module compiled).  No DMXGUS.
    fixed.append(("GENMIDI", b"#OPL_II#"))
    ds_stub, dp_stub, d_stub = minib["DSBFG"], minib["DPBFG"], minib["D_RUNNIN"]

    sfx_alias = dict(SFX_ALIAS_LADDER[:max(0, args.sfx_alias_level)])
    real_sfx = {}
    sfx_raw_in = sfx_raw_out = 0
    if args.sfx_mode == "real":
        for nm in USED_SFX:
            if nm not in srcidx:
                sys.exit(f"FATAL: used sfx {nm} missing from IWAD")
        v3b_8k = set(V3B_SFX_8K) if args.v3b_sfx_8k else set()
        if v3b_8k:
            missing = v3b_8k - set(USED_SFX)
            if missing:
                sys.exit(f"FATAL: v3b 8k sfx not in USED_SFX: {sorted(missing)}")
        for nm in USED_SFX:
            tgt = sfx_alias.get(nm, nm)
            if tgt not in USED_SFX:
                sys.exit(f"FATAL: alias target {tgt} not in USED_SFX")
            buf = src_lump(tgt)
            sfx_raw_in += len(src_lump(nm))
            # v3b STEP 4: the 6 monster-vocal barks get an 8 kHz cap (still play,
            # just lower-rate); STEP 6 caps EVERY real sfx at 8 kHz; else the
            # normal rate-cap.
            if args.v3b_sfx_cap_8k:
                cap = V3B_SFX_8K_RATE
            elif nm in v3b_8k:
                cap = V3B_SFX_8K_RATE
            else:
                cap = args.sfx_rate_cap
            real_sfx[nm] = downsample_dmx(buf, cap)
        sfx_raw_out = sum(len(b) for b in set(map(bytes, real_sfx.values())))
        if v3b_8k:
            report["dropped"].append(
                "v3b sfx 8k (monster barks): " + ", ".join(sorted(v3b_8k)))
        if sfx_alias:
            report["dropped"].append(
                "sfx aliased (ladder %d): %s" % (args.sfx_alias_level,
                                                 ", ".join(f"{a}->{b}" for a, b in
                                                           SFX_ALIAS_LADDER[:args.sfx_alias_level])))

    ds_names = sorted({n for n, _ in mini if n.startswith("DS")} | set(USED_SFX))
    for n in ds_names:
        fixed.append((n, real_sfx.get(n, ds_stub)))
    for n, b in mini:
        if n.startswith("DP"):
            fixed.append((n, dp_stub))
    for n in MUSIC_STUBS:
        fixed.append((n, d_stub))

    # ---- stub maps (only if fewer than 9 real maps were requested) -----------
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
    n_stub_maps = 0
    for slot in range(1, 10):
        nm = "E1M%d" % slot
        if nm in have_maps:
            continue
        n_stub_maps += 1
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
                             "WIMAP0", "PLAYPAL", "COLORMAP", "STBAR", "STFST00",
                             "CREDIT", "HELP2", "TITLEPIC"]:
        if nm not in fset:
            errs.append(f"required lump {nm} missing")
    # every engine-reachable sfx must exist as a parseable DMX lump
    fbytes = dict(final)
    for nm in USED_SFX:
        b = fbytes.get(nm)
        if b is None or len(b) < 8 or struct.unpack("<H", b[:2])[0] != 3:
            errs.append(f"sfx {nm} missing or not DMX format")
        else:
            ln = struct.unpack("<I", b[4:8])[0]
            if 8 + ln > len(b):
                errs.append(f"sfx {nm}: length field overruns lump")
    # sprite sanity in final wad (front: XXXXF0 only; full: rotation sets)
    si0, si1 = fnames.index("S_START"), fnames.index("S_END")
    by_pref_frames = defaultdict(set)
    by_pref_rots = defaultdict(lambda: defaultdict(set))
    for n, _ in final[si0 + 1:si1]:
        if len(n) not in (6, 8):
            errs.append(f"sprite lump {n}: bad name length")
            continue
        if args.sprite_mode == "front" and (len(n) != 6 or n[5] != "0"):
            errs.append(f"sprite lump {n}: expected XXXXF0 form")
            continue
        halves = [(n[4], n[5])] + ([(n[6], n[7])] if len(n) == 8 else [])
        for frame, rot in halves:
            by_pref_frames[n[:4]].add(frame)
            by_pref_rots[n[:4]][frame].add(rot)
    for pref, frames in by_pref_frames.items():
        fr = sorted(frames)
        if fr != [chr(ord("A") + i) for i in range(len(fr))]:
            errs.append(f"sprite {pref}: frames {fr} not contiguous")
        for frame in fr:
            rots = by_pref_rots[pref][frame]
            if "0" in rots:
                if len(rots) != 1:
                    errs.append(f"sprite {pref}{frame}: rot0 mixed with rotations")
            elif rots != {"1", "2", "3", "4", "5", "6", "7", "8"}:
                errs.append(f"sprite {pref}{frame}: incomplete rotations {sorted(rots)}")
    for pref in sprite_prefixes:
        if pref not in by_pref_frames:
            errs.append(f"sprite prefix {pref} absent")

    if errs:
        for e in errs:
            print("VALIDATION ERROR:", e)
        sys.exit(1)

    # ---- report --------------------------------------------------------------
    wad_bytes = open(args.out, "rb").read()
    lz = lzkb(wad_bytes)
    print(f"== {args.out}")
    print(f"maps: {[f'{s}->{d}' if s != d else s for s, d in map_specs]}"
          + (f" + {n_stub_maps} stub slots" if n_stub_maps else " (all real)"))
    print(f"textures kept {len(real_entries)} real (+{len(stub_switches)} stub switch entries), "
          f"remapped {len(tex_remap)}; coverage {sum(tex_refs[t] for t in keep_tex)}/{sum(tex_refs.values())} refs "
          f"({100.0 * sum(tex_refs[t] for t in keep_tex) / sum(tex_refs.values()):.1f}%)")
    print(f"flats kept {len(keep_flat)}, remapped {len(flat_remap)}; coverage "
          f"{100.0 * sum(flat_refs[f] for f in keep_flat if f in flat_refs) / sum(flat_refs.values()):.1f}%")
    print(f"sprites: {len(sprite_prefixes)} prefixes, {len(sprite_lumps)} lumps ({args.sprite_mode})")
    print(f"patches: {len(new_pnames)} | things kept: {sum(used_things.values())}")
    if args.sfx_mode == "real":
        print(f"sfx: {len(USED_SFX)} real (rate-cap {args.sfx_rate_cap or 'off'}, "
              f"alias level {args.sfx_alias_level}"
              f"{', v3b-8k x6' if args.v3b_sfx_8k else ''}) {sfx_raw_in/1024:.1f} -> "
              f"{sfx_raw_out/1024:.1f} KB raw unique; "
              f"{len(ds_names) - len(USED_SFX)} unreachable DS* stubbed")
    else:
        print("sfx: all stubbed")
    print(f"demos: {demo_note} | music: dropped ({len(MUSIC_STUBS)} D_* stubs)")
    for w in report["warn"]:
        print("  warn:", w)
    if report["dropped"]:
        print("dropped:", "; ".join(report["dropped"]))
    print(f"RAW {raw / 1024:.1f} KB   LZMA9 {lz:.1f} KB   "
          f"(budget: target <=1400 KB, hard cap 1485 KB)")


if __name__ == "__main__":
    main()
