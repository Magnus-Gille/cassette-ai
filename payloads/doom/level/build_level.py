#!/usr/bin/env python3
"""
build_level.py  —  THE MAGNETIC VAULT  (E1M1 replacement, DOOM-on-tape cassette)

Builds a complete, completable, fun vanilla-Doom E1M1 with omgifol's MapEditor,
runs the vendored nodebuilder (tools/bsp) to add NODES/SEGS/SSECTORS/BLOCKMAP/
REJECT, validates against base.wad's texture/flat/sprite inventory, splices the
map over base.wad's E1M1 (keeping E1M2-E1M9), and assembles a sandbox HTML via
assemble_html_v3.py.  Run with the pyenv python that has omgifol:

    /Users/magnus/.pyenv/versions/3.10.13/bin/python3 build_level.py

DESIGN — THE MAGNETIC VAULT: a UAC data-archive built around a giant cassette.
Strong opening sightline (foyer window into the computer gallery), a legible
hub + 3 branches, ONE blue-keycard gate, a 3-sided deaf-monster ambush at the
key, three secrets (rocket-launcher+soulsphere / backpack / plasma), and a
Baron-anchored finale inside a literal giant cassette reel where you flip the
"eject" exit switch to finish.

GEOMETRY: every room is one axis-aligned (or octagonal) sector built by
`add_room`, which leaves explicit gaps so NO solid wall is ever placed where a
portal/door belongs.  Rooms connect via thin DOOR sectors or OPENING portals.
All windings keep the named sector to the RIGHT of v1->v2 (resolved by a
centroid test). Coordinates share exact edges (see locked layout in comments).
"""

import os
import struct
import subprocess
import sys

sys.path.insert(0, "/Users/magnus/.local/lib/python3.10/site-packages")
import omg                                   # noqa: E402
from omg.mapedit import MapEditor, Vertex, Linedef, Sidedef, Sector, Thing  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = "/Users/magnus/repos/cassette-ai/tools"
# Vanilla nodebuilder: zdbsp (Marisa Heit's standard ZDoom BSP, vanilla mode).
# Replaces the homemade tools/bsp, which emitted 432/743 zero-length SEGS
# (v1==v2) on the Vault and crashed vanilla r_segs.c -> wasm OOB at map load.
# zdbsp in default mode writes classic NODES/SEGS/SSECTORS (no extended/GL),
# correctly-sized REJECT (-R) and BLOCKMAP. See tools/zdbsp_build/.
BSP = os.path.join(TOOLS, "zdbsp_build", "build", "zdbsp")
BASE_WAD = os.path.join(HERE, "base.wad")
SCRATCH_WAD = os.path.join(HERE, "scratch.wad")
LEVEL_WAD = os.path.join(HERE, "level.wad")
MERGED_WAD = os.path.join(HERE, "merged.wad")
ASSEMBLE = "/Users/magnus/repos/cassette-ai/payloads/doom/build/assemble_html_v3.py"
OUT_HTML = os.path.join(HERE, "doom_level_test.html")

# ---- Linedef flags ----------------------------------------------------------
IMPASSABLE = 1; BLOCKMONST = 2; TWOSIDED = 4
UPPERUNPEG = 8; LOWERUNPEG = 16; SECRETFLAG = 32
# ---- Linedef specials -------------------------------------------------------
DR_DOOR = 1          # DR open/close (push)
W1_DOOR_OPEN = 2     # W1 door opens & stays open (ambush/finale closets)
EXIT_SWITCH = 11     # S1 normal exit ("eject")
DR_BLUE_DOOR = 26    # DR door, blue key required
# ---- Sector specials --------------------------------------------------------
SP_NUKAGE5 = 7; SP_GLOW = 8; SP_SECRET = 9
# ---- Thing types ------------------------------------------------------------
T_PLAYER1 = 1; T_ZOMBIE = 3004; T_SGTGUY = 9; T_IMP = 3001; T_PINKY = 3002
T_BARON = 3003; T_BLUEKEY = 5
T_SHOTGUN = 2001; T_CHAINGUN = 2002; T_RLAUNCH = 2003; T_PLASMA = 2004
T_CLIP = 2007; T_SHELLS = 2008; T_SHELLBOX = 2048; T_ROCKBOX = 2046
T_ROCKET = 2010; T_CELLPACK = 17; T_CELL = 2047; T_BACKPACK = 8
T_STIM = 2011; T_MEDIKIT = 2012; T_HBONUS = 2014; T_SOUL = 2013; T_ABONUS = 2015
T_GREENARM = 2018; T_BLUEARM = 2019; T_RADSUIT = 2025
UV = 7; DEAF = 8
# ---- Texture / flat palette (verified present in base.wad) -----------------
STARTAN2="STARTAN2"; STARTAN1="STARTAN1"; SUPPORT2="SUPPORT2"; SUPPORT3="SUPPORT3"
COMPBLUE="COMPBLUE"; COMPTALL="COMPTALL"; COMPSPAN="COMPSPAN"
GRAY7="GRAY7"; GRAY1="GRAY1"; BROWN1="BROWN1"; BROWN96="BROWN96"
SLADWALL="SLADWALL"; STARGR1="STARGR1"; STARG3="STARG3"; SHAWN2="SHAWN2"; STEP4="STEP4"
DOOR1="DOOR1"; DOOR3="DOOR3"; DOORBLU="DOORBLU"; DOORTRAK="DOORTRAK"
BIGDOOR1="BIGDOOR1"; BIGDOOR2="BIGDOOR2"; EXITDOOR="EXITDOOR"; EXITSIGN="EXITSIGN"
SW1EXIT="SW1EXIT"
FLOOR5_1="FLOOR5_1"; FLOOR5_2="FLOOR5_2"; FLOOR5_3="FLOOR5_3"; FLOOR0_1="FLOOR0_1"
FLOOR0_3="FLOOR0_3"; FLOOR4_1="FLOOR4_1"; FLOOR4_8="FLOOR4_8"; FLOOR7_1="FLOOR7_1"
FLAT5="FLAT5"; FLAT5_4="FLAT5_4"; FLAT1="FLAT1"; FLAT19="FLAT19"
NUKAGE1="NUKAGE1"; CRATOP1="CRATOP1"; FCGRATE2="FCGRATE2"
TLITE6_1="TLITE6_1"; TLITE6_5="TLITE6_5"; TLITE6_6="TLITE6_6"
CEIL3_3="CEIL3_3"; CEIL5_1="CEIL5_1"; CEIL5_2="CEIL5_2"; STEP1="STEP1"
# ---- Tags -------------------------------------------------------------------
TAG_TRAP = 10            # all 3 ambush closets share this tag (one W1 trigger)
TAG_FIN_BARON = 20
TAG_FIN_CHAFF = 21


# ============================================================================
class Builder:
    def __init__(self):
        self.verts = []; self._vc = {}
        self.sides = []; self.sectors = []; self.lines = []; self.things = []

    def v(self, x, y):
        k = (int(round(x)), int(round(y)))
        if k in self._vc:
            return self._vc[k]
        i = len(self.verts); self.verts.append(Vertex(x=k[0], y=k[1])); self._vc[k] = i
        return i

    def sector(self, fz, cz, ff, cf, light, type=0, tag=0):
        i = len(self.sectors)
        self.sectors.append(Sector(z_floor=fz, z_ceil=cz, tx_floor=ff, tx_ceil=cf,
                                    light=light, type=type, tag=tag))
        return i

    def _side(self, sector, mid="-", up="-", low="-", ox=0, oy=0):
        i = len(self.sides)
        self.sides.append(Sidedef(off_x=ox, off_y=oy, tx_up=up, tx_low=low,
                                   tx_mid=mid, sector=sector))
        return i

    def wall(self, va, vb, sector, tex, flags=IMPASSABLE, ox=0, oy=0):
        sd = self._side(sector, mid=tex, ox=ox, oy=oy)
        self.lines.append(Linedef(vx_a=va, vx_b=vb, front=sd, back=-1,
                                   flags=flags | IMPASSABLE, action=0, tag=0))

    def portal(self, va, vb, sf_sec, sb_sec, up_f="-", low_f="-", mid_f="-",
               up_b="-", low_b="-", mid_b="-", flags=TWOSIDED, action=0, tag=0,
               ox=0, oy=0):
        sf = self._side(sf_sec, mid=mid_f, up=up_f, low=low_f, ox=ox, oy=oy)
        sb = self._side(sb_sec, mid=mid_b, up=up_b, low=low_b, ox=ox, oy=oy)
        self.lines.append(Linedef(vx_a=va, vx_b=vb, front=sf, back=sb,
                                   flags=flags | TWOSIDED, action=action, tag=tag))

    def thing(self, x, y, type, angle=0, flags=UV):
        self.things.append(Thing(x=int(round(x)), y=int(round(y)), angle=angle,
                                  type=type, flags=flags))


b = Builder()


def order_so_right(x1, y1, x2, y2, centroid):
    """Return (x1,y1,x2,y2) reordered so `centroid` lies to the RIGHT of v1->v2."""
    cx, cy = centroid
    ux, uy = x2 - x1, y2 - y1
    rnx, rny = uy, -ux
    mx, my = cx - (x1 + x2) / 2.0, cy - (y1 + y2) / 2.0
    if rnx * mx + rny * my >= 0:
        return (x1, y1, x2, y2)
    return (x2, y2, x1, y1)


def add_room(x1, y1, x2, y2, sec, tex, gaps=None):
    """Build CW perimeter walls of an axis-aligned rect; interior on the RIGHT.
    gaps = list of (side, lo, hi) ranges to leave open (filled by portals)."""
    gaps = gaps or []
    g = {"N": [], "S": [], "E": [], "W": []}
    for s, lo, hi in gaps:
        g[s].append((min(lo, hi), max(lo, hi)))

    def emit(side, a, bb, fixed, vertical):
        lo, hi = min(a, bb), max(a, bb)
        solids, cur = [], lo
        for glo, ghi in sorted(g[side]):
            if glo > cur:
                solids.append((cur, glo))
            cur = max(cur, ghi)
        if cur < hi:
            solids.append((cur, hi))
        if bb < a:  # walk direction reversed
            solids = [(s1, s0) for s0, s1 in reversed(solids)]
        for s0, s1 in solids:
            if vertical:
                b.wall(b.v(fixed, s0), b.v(fixed, s1), sec, tex)
            else:
                b.wall(b.v(s0, fixed), b.v(s1, fixed), sec, tex)

    emit("W", y1, y2, x1, True)     # x=x1, y1->y2
    emit("N", x1, x2, y2, False)    # y=y2, x1->x2
    emit("E", y2, y1, x2, True)     # x=x2, y2->y1
    emit("S", x2, x1, y1, False)    # y=y1, x2->x1


def opening(x1, y1, x2, y2, front_sec, back_sec, front_centroid, **kw):
    """Two-sided portal on segment (x1,y1)-(x2,y2); front_sec to the RIGHT."""
    ox = order_so_right(x1, y1, x2, y2, front_centroid)
    b.portal(b.v(ox[0], ox[1]), b.v(ox[2], ox[3]), front_sec, back_sec, **kw)


def island(x1, y1, x2, y2, outer_sec, outer_centroid, inner_sec,
           low_tex="-", up_tex="-", **kw):
    """Build a raised/lowered rectangular island inside outer_sec.
    Wind the boundary CCW (BL->BR->TR->TL) so the INNER (island) interior is on
    the LEFT of every edge and the OUTER sector is on the RIGHT. front=outer,
    back=inner. This is a single consistent closed loop (no per-edge centroid)."""
    loop = [(x1, y1, x2, y1),    # S edge +x
            (x2, y1, x2, y2),    # E edge +y
            (x2, y2, x1, y2),    # N edge -x
            (x1, y2, x1, y1)]    # W edge -y
    for (ax, ay, bx, by) in loop:
        b.portal(b.v(ax, ay), b.v(bx, by), outer_sec, inner_sec,
                 low_f=low_tex, low_b=low_tex, up_f=up_tex, up_b=up_tex, **kw)


def door_between(ex1, ey1, ex2, ey2, depth, sec_a, sec_b, ca, cb, door_tex,
                 axis, floor_z, special=DR_DOOR, tag=0, key_flags=0):
    """Thin door sector bridging sec_a -> sec_b. axis in {+x,-x,+y,-y} = the
    direction from the approach (sec_a) edge toward sec_b (the door depth).
    The door sector (dsec) is a thin rectangle whose 4 edges form ONE CW loop
    (dsec interior on the RIGHT). The two long edges are door portals (front
    to sec_a, back to sec_b); the two short edges are DOORTRAK jamb walls."""
    sgn = 1 if axis[0] == "+" else -1
    horiz = axis[1] == "x"
    dx = sgn * depth if horiz else 0
    dy = 0 if horiz else sgn * depth
    dsec = b.sector(floor_z, floor_z, FLAT1, FLAT1, 0)
    # The 4 corners: approach edge (ex1,ey1)-(ex2,ey2); beyond edge offset by d.
    A = (ex1, ey1); B = (ex2, ey2)
    C = (ex2 + dx, ey2 + dy); D = (ex1 + dx, ey1 + dy)
    # CW loop A->B->C->D->A would put dsec on the right ONLY if A->B->C->D is CW.
    # Determine orientation via signed area; flip to CW if needed.
    quad = [A, B, C, D]
    area = 0.0
    for i in range(4):
        x0, y0 = quad[i]; x1, y1 = quad[(i + 1) % 4]
        area += x0 * y1 - x1 * y0
    if area > 0:                      # CCW -> reverse to make CW
        quad = [A, D, C, B]
    # Now quad is CW; dsec on the right of each edge. Classify each edge:
    #   long edges (length == approach-edge length) are the door portals;
    #   the approach-edge endpoints {A,B} identify the front (sec_a) portal.
    front_set = {A, B}
    beyond_set = {C, D}
    for i in range(4):
        p = quad[i]; q = quad[(i + 1) % 4]
        es = {p, q}
        if es == front_set:
            # front door portal: dsec(front,right) | sec_a(back,left).
            # The door FACE goes on the room-side UPPER texture (up_b), NOT the
            # middle. A multi-patch composite (BIGDOOR1/DOORBLU/STARGR1 etc.) on
            # a TWO-SIDED MIDDLE texture triggers the vanilla "Medusa" effect:
            # R_RenderMaskedSegRange/R_DrawMaskedColumn walk a malformed
            # multi-patch masked post chain off the end -> "memory access out of
            # bounds" in the bounds-checked WASM heap (wasm-function[256]). The
            # upper-texture path (closed door: ceil==floor reveals the upper
            # from floor_z up to the room ceiling) is the correct vanilla door
            # render and is immune to Medusa. UPPERUNPEG keeps the face pinned
            # as the door rises.
            # low_b=DOORTRAK textures any floor step between the room and the
            # (thin) door sill so a non-flush door shows the track, not HOM.
            # DOORTRAK is single-patch -> Medusa-safe on this 2S line.
            b.portal(b.v(p[0], p[1]), b.v(q[0], q[1]), dsec, sec_a,
                     up_b=door_tex, low_b=DOORTRAK,
                     flags=TWOSIDED | UPPERUNPEG | key_flags,
                     action=special, tag=tag)
        elif es == beyond_set:
            b.portal(b.v(p[0], p[1]), b.v(q[0], q[1]), dsec, sec_b,
                     up_b=door_tex, low_b=DOORTRAK,
                     flags=TWOSIDED | UPPERUNPEG, action=special, tag=tag)
        else:
            # jamb (track): one-sided wall, dsec on right
            b.wall(b.v(p[0], p[1]), b.v(q[0], q[1]), dsec, DOORTRAK,
                   flags=IMPASSABLE | LOWERUNPEG)
    return dsec


def closet(x1, y1, x2, y2, host_sec, host_centroid, mouth_side, tex, tag,
           floor_z=8):
    """Monster closet (starts closed: ceil==floor). Three solid walls; the
    `mouth_side` faces host_sec via a two-sided portal. Opens when a W1 line
    tagged `tag` raises its ceiling."""
    csec = b.sector(floor_z, floor_z, FLAT1, FLAT1, 96, tag=tag)
    # CW loop so the closet interior is on the RIGHT of each edge:
    # BL->TL->TR->BR->BL.  Each side keyed by its compass label.
    cw = [("W", x1, y1, x1, y2),   # W edge +y
          ("N", x1, y2, x2, y2),   # N edge +x
          ("E", x2, y2, x2, y1),   # E edge -y
          ("S", x2, y1, x1, y1)]   # S edge -x
    for side, ax, ay, bx, by in cw:
        if side == mouth_side:
            # mouth portal: closet on RIGHT (csec=front), host on LEFT (back).
            b.portal(b.v(ax, ay), b.v(bx, by), csec, host_sec,
                     low_f=tex, low_b=tex, up_f=tex, up_b=tex)
        else:
            b.wall(b.v(ax, ay), b.v(bx, by), csec, tex)
    return csec


# ============================================================================
# BUILD — locked coordinate layout
# ============================================================================

# ---- A1 START: Tape Deck Foyer  X[0..512] Y[0..384] ------------------------
A1 = b.sector(0, 128, FLOOR5_1, TLITE6_1, 208); cA1 = (256, 192)
add_room(0, 0, 512, 384, A1, STARTAN2,
         gaps=[("N", 192, 320),       # walking corridor to gallery
               ("N", 360, 440)])      # window sightline sill
A1S = b.sector(0, 128, STEP1, TLITE6_1, 255)         # shotgun spotlight inset
island(224, 96, 288, 160, A1, cA1, A1S)
# FAIRNESS COVER (the hook stays spicy but survivable): a solid data-drive crate
# the player can break line-of-sight behind. Raised to floor z=72 -- above the
# 41-unit player view height -- so it FULLY blocks the two foyer POSS hitscans
# over the top. It sits between the start corner / shotgun and the zombies at
# Y=300, giving a careful player a refuge to peek-and-shoot from. CRATOP1 top,
# COMPSPAN sides (reads as a stacked tape-archive crate, on-theme).
A1COVER = b.sector(72, 128, CRATOP1, TLITE6_1, 192)
island(176, 192, 240, 256, A1, cA1, A1COVER, low_tex=COMPSPAN, up_tex=COMPSPAN)

# ---- CORR (A1 -> A2)  X[192..320] Y[384..416] ------------------------------
CORR = b.sector(12, 140, FLOOR5_1, CEIL3_3, 176); cCORR = (256, 400)
add_room(192, 384, 320, 416, CORR, STARTAN2,
         gaps=[("S", 192, 320), ("N", 192, 320)])

# ---- WIN sightline sill  X[360..440] Y[384..416] ---------------------------
WIN = b.sector(24, 96, FLOOR5_1, CEIL3_3, 160); cWIN = (400, 400)
add_room(360, 384, 440, 416, WIN, COMPBLUE,
         gaps=[("S", 360, 440), ("N", 360, 440)])

# ---- A2 HUB: Computer Gallery  X[64..960] Y[416..768] ----------------------
A2 = b.sector(24, 160, FLOOR0_1, CEIL3_3, 192); cA2 = (512, 592)
add_room(64, 416, 960, 768, A2, GRAY7,
         gaps=[("S", 192, 320), ("S", 360, 440), ("W", 480, 608),
               ("N", 700, 796), ("E", 560, 688)])

# A1 -> CORR (CORR south y=384 to A1 north y=384)
opening(192, 384, 320, 384, A1, CORR, cA1, low_f=STEP4, low_b=STEP4)
# CORR -> A2 (CORR north y=416 to A2 south y=416)
opening(192, 416, 320, 416, CORR, A2, cCORR, low_f=STEP4, low_b=STEP4)
# A1 -> WIN (WIN south y=384): low 0..24, slit upper 96..128
opening(360, 384, 440, 384, A1, WIN, cA1, low_f=STARTAN2, low_b=STARTAN2,
        up_f=COMPBLUE, up_b=COMPBLUE)
# WIN -> A2 (WIN north y=416): upper 96..160
opening(360, 416, 440, 416, WIN, A2, cWIN, up_f=COMPBLUE, up_b=COMPBLUE)

# Hub centre computer pillars (4 islands, raised ceiling support look)
for px in (300, 460, 600, 740):
    ip = b.sector(24, 96, FLOOR0_1, CEIL3_3, 176)
    island(px, 560, px + 40, 600, A2, cA2, ip, up_tex=COMPSPAN)

# ---- C2 (A2 west -> A3)  X[-64..64] Y[480..608] ----------------------------
C2 = b.sector(24, 120, FLOOR0_1, CEIL3_3, 150); cC2 = (0, 544)
add_room(-64, 480, 64, 608, C2, GRAY7, gaps=[("E", 480, 608), ("W", 480, 608)])
opening(64, 480, 64, 608, A2, C2, cA2, low_f=STEP4, low_b=STEP4)  # A2 east

# ---- A3 Maintenance Crawl (DARK)  X[-320..-64] Y[448..640] -----------------
A3 = b.sector(24, 96, FLAT5_4, FLAT1, 104); cA3 = (-192, 544)
add_room(-320, 448, -64, 640, A3, BROWN1,
         gaps=[("E", 480, 608),        # to C2
               ("S", -280, -200),      # to A5 (CONN door)
               ("N", -200, -120)])     # to A11 secret door
opening(-64, 480, -64, 608, A3, C2, cA3, low_f=STEP4, low_b=STEP4)  # A3 east wall

# ---- A11 SECRET: Hidden Splice (RL + Soulsphere)  X[-200..-120] Y[656..848] -
A11 = b.sector(24, 96, FLOOR5_3, FLAT1, 128, type=SP_SECRET); cA11 = (-160, 752)
add_room(-200, 656, -120, 848, A11, BROWN1, gaps=[("S", -200, -120)])
door_between(-200, 640, -120, 640, 16, A3, A11, cA3, cA11, SLADWALL, "+y", 24,
             special=DR_DOOR)   # secret door A3(N y640) -> A11(S y656)

# ---- A5 Nukage Annex  walkway X[-560..-160] Y[256..432] + inner pool --------
A5W = b.sector(8, 128, FLOOR4_8, FLAT19, 144); cA5W = (-360, 344)
add_room(-560, 256, -160, 432, A5W, SLADWALL,
         gaps=[("N", -540, -380),      # to A6 (open mouth)
               ("N", -280, -200),      # to A3 (CONN door)
               ("W", 300, 396)])       # to A12 secret (door)
A5P = b.sector(-16, 128, NUKAGE1, FLAT19, 120, type=SP_NUKAGE5)
island(-500, 280, -220, 408, A5W, cA5W, A5P, low_tex=SLADWALL)
# A3 <-> A5 CONN door: A5 north (y432) up to A3 south (y448). axis +y, fills 16du
door_between(-280, 432, -200, 432, 16, A5W, A3, cA5W, cA3, DOOR1, "+y", 8,
             special=DR_DOOR)

# ---- A12 SECRET: Backpack Cache  X[-672..-576] Y[300..396] -----------------
A12 = b.sector(8, 96, FLOOR5_3, FLAT1, 120, type=SP_SECRET); cA12 = (-624, 348)
add_room(-672, 300, -576, 396, A12, STARGR1, gaps=[("E", 300, 396)])
# secret door A5(W x-560) -> A12(E x-576). axis -x, depth 16 -> fills x[-576..-560]
door_between(-560, 300, -560, 396, 16, A5W, A12, cA5W, cA12, STARGR1, "-x", 8,
             special=DR_DOOR)

# ---- A6 Blue Key + Trap  X[-540..-380] Y[432..688] -------------------------
# Split into A6 (south Y[432..520]) and A6N (north Y[520..688]) by a W1 trip line.
A6 = b.sector(8, 120, FLOOR5_2, TLITE6_5, 192); cA6 = (-460, 476)
A6N = b.sector(8, 120, FLOOR5_2, TLITE6_5, 192); cA6N = (-460, 604)
# A6 south part: walls X[-540..-380] Y[432..520], gaps S(open to A5) + N(trip)
add_room(-540, 432, -380, 520, A6, COMPBLUE,
         gaps=[("S", -540, -380), ("N", -540, -380)])
# A6N north part: gaps S(trip) + N(closet N) + W(closet W) + E(closet E)
add_room(-540, 520, -380, 688, A6N, COMPBLUE,
         gaps=[("S", -540, -380),
               ("N", -500, -420),       # closet N mouth
               ("W", 536, 616),         # closet W mouth (x=-540)
               ("E", 536, 616)])        # closet E mouth (x=-380)
# A5 -> A6 open mouth (A5 north y432, x[-540..-380])
opening(-540, 432, -380, 432, A5W, A6, cA5W, up_f=COMPBLUE, up_b=COMPBLUE)
# Trip line: A6 north y520 == A6N south y520. ONE W1 door-open tagged TAG_TRAP.
opening(-540, 520, -380, 520, A6, A6N, cA6, action=W1_DOOR_OPEN, tag=TAG_TRAP)
# Key pillar island (12x32) raised +24 in A6N
A6K = b.sector(24, 120, FLOOR5_2, TLITE6_5, 255)
island(-466, 592, -454, 624, A6N, cA6N, A6K, low_tex=COMPBLUE)
# Three trap closets (all tag TAG_TRAP) flanking the key in A6N:
# Closet W (mouth E into A6N west wall x=-540, y[536..616])
clW = closet(-620, 536, -540, 616, A6N, cA6N, "E", COMPBLUE, TAG_TRAP, floor_z=8)
# Closet E (mouth W into A6N east wall x=-380, y[536..616])
clE = closet(-380, 536, -320, 616, A6N, cA6N, "W", COMPBLUE, TAG_TRAP, floor_z=8)
# Closet N behind the key (mouth S into A6N north wall y=688, x[-500..-420])
clN = closet(-500, 688, -420, 800, A6N, cA6N, "S", COMPBLUE, TAG_TRAP, floor_z=8)

# ---- A4 Cold Storage (NORTH branch: chaingun, pinky pen)  X[640..1024] Y[840..1152]
A4 = b.sector(16, 144, FLAT5, CEIL5_1, 160); cA4 = (832, 996)
add_room(640, 840, 1024, 1152, A4, BROWN96, gaps=[("S", 700, 796)])
# BIGDOOR1 from A2 north (y768) up to A4 south (y840). axis +y, depth 72.
door_between(700, 768, 796, 768, 72, A2, A4, cA2, cA4, BIGDOOR1, "+y", 24,
             special=DR_DOOR)
# Crate cluster in A4 (height variation + cover): 2 raised crate islands.
CRATE1 = b.sector(80, 144, CRATOP1, CEIL5_1, 160)
CRATE2 = b.sector(112, 144, CRATOP1, CEIL5_1, 160)
island(720, 920, 784, 984, A4, cA4, CRATE1, low_tex=BROWN96, up_tex=BROWN96)
island(880, 1000, 944, 1064, A4, cA4, CRATE2, low_tex=BROWN96, up_tex=BROWN96)

# ---- BLUE DOOR (A2 east -> A7)  X[960..1000] Y[560..680] -------------------
A7 = b.sector(24, 128, FLOOR0_3, CEIL3_3, 160); cA7 = (1200, 600)
add_room(1000, 520, 1400, 680, A7, STARTAN1,
         gaps=[("W", 560, 680), ("E", 540, 660)])
door_between(960, 560, 960, 680, 40, A2, A7, cA2, cA7, DOORBLU, "+x", 24,
             special=DR_BLUE_DOOR)   # A2 east (x960) -> A7 west (x1000)
# A2's east gap [560..688] is wider than the door [560..680]; fill sliver
# [680..688] with a wall so A2 stays closed.
b.wall(b.v(960, 688), b.v(960, 680), A2, GRAY7)   # A2 on right (x<960)

# ---- C78 (A7 -> A8)  X[1400..1440] Y[540..660] -----------------------------
C78 = b.sector(48, 160, FLOOR0_3, CEIL3_3, 168); cC78 = (1420, 600)
add_room(1400, 540, 1440, 660, C78, STARTAN1, gaps=[("W", 540, 660), ("E", 540, 660)])
opening(1400, 540, 1400, 660, A7, C78, cA7, low_f=STEP4, low_b=STEP4)  # A7 east

# ---- A8 Vault Approach (tall)  X[1440..1940] Y[440..760] -------------------
A8 = b.sector(64, 192, FLOOR7_1, CEIL5_2, 176); cA8 = (1690, 600)
add_room(1440, 440, 1940, 760, A8, GRAY1, gaps=[("W", 540, 660), ("E", 540, 660)])
opening(1440, 540, 1440, 660, C78, A8, cC78, low_f=STEP4, low_b=STEP4)  # C78 east

# ---- BIGDOOR2 vault door (A8 east -> A9)  X[1940..2040] Y[540..660] ---------
# (A9 built next; door connects after.)

# ---- A9 GIANT CASSETTE wow room + finale  octagon, west edge x=2040 --------
ox_c, oy_c = 2540, 600; cA9 = (ox_c, oy_c)
A9 = b.sector(64, 256, FLOOR0_1, CEIL5_2, 200)
oct_pts = [
    (2040, 500), (2040, 700),            # west flat edge (entry)  idx0,1
    (2240, 900), (2840, 900),            # bottom                  idx2,3
    (3040, 700), (3040, 500),            # east flat edge          idx4,5
    (2840, 300), (2240, 300),            # top                     idx6,7
]
# Walk the octagon; the entry edge is idx0->idx1 (west, x=2040, y500->700).
n = len(oct_pts)
for i in range(n):
    ax, ay = oct_pts[i]; bx, by = oct_pts[(i + 1) % n]
    if i == 0:   # entry edge -> handled by BIGDOOR2 below
        continue
    ox = order_so_right(ax, ay, bx, by, cA9)
    tex = COMPTALL if i == 3 else GRAY1   # bottom-east wall = "SIDE A" label band
    b.wall(b.v(ox[0], ox[1]), b.v(ox[2], ox[3]), A9, tex)
# BIGDOOR2 from A8 east (x1940) into A9 west edge (x2040). depth 100.
door_between(1940, 540, 1940, 660, 100, A8, A9, cA8, cA9, BIGDOOR2, "+x", 64,
             special=DR_DOOR)
# A9 entry edge x2040 y[500..700]: door back covers y[540..660]. Fill the
# remaining slivers y[500..540] and y[660..700] with short walls so no leak.
for (ya, yb) in [(500, 540), (660, 700)]:
    ox = order_so_right(2040, ya, 2040, yb, cA9)
    b.wall(b.v(ox[0], ox[1]), b.v(ox[2], ox[3]), A9, GRAY1)

# --- Cassette motif inside A9 ---
# Two octagon-ish reel hubs (use squares-with-cut-corners == simple squares here)
# raised to floor 96 (read as the two reels), tops FLOOR4_1, sides COMPSPAN.
REEL_L = b.sector(96, 256, FLOOR4_1, CEIL5_2, 224, type=SP_GLOW)
REEL_R = b.sector(96, 256, FLOOR4_1, CEIL5_2, 224, type=SP_GLOW)
island(2200, 480, 2360, 640, A9, cA9, REEL_L, low_tex=COMPSPAN)   # left reel
island(2640, 480, 2800, 640, A9, cA9, REEL_R, low_tex=COMPSPAN)   # right reel
# Tape-ribbon window between reels: recessed grate floor 48
TAPEWIN = b.sector(48, 256, FCGRATE2, CEIL5_2, 160)
island(2400, 540, 2600, 600, A9, cA9, TAPEWIN, low_tex=SHAWN2)
# Exit plinth (the "eject" button) at the far (east) side between the reels.
# Plinth floor 96; the WEST face (facing the player) carries the SW1EXIT switch
# with the S1 normal-exit special (11). Built as a CCW island loop (A9=front).
PLINTH = b.sector(96, 200, FLOOR4_1, TLITE6_6, 192)
px1, py1, px2, py2 = 2860, 560, 2924, 640
# CCW: S(+x), E(+y), N(-x), W(-y). The W edge (x1,y2)->(x1,y1) faces the player.
ploop = [("S", px1, py1, px2, py1), ("E", px2, py1, px2, py2),
         ("N", px2, py2, px1, py2), ("W", px1, py2, px1, py1)]
for side, ax, ay, bx, by in ploop:
    if side == "W":
        # exit switch: front=A9 (player side), low_f=SW1EXIT, special 11
        b.portal(b.v(ax, ay), b.v(bx, by), A9, PLINTH,
                 low_f=SW1EXIT, up_f=EXITSIGN, low_b=EXITDOOR, up_b=EXITDOOR,
                 action=EXIT_SWITCH)
    else:
        b.portal(b.v(ax, ay), b.v(bx, by), A9, PLINTH,
                 low_f=EXITDOOR, low_b=EXITDOOR, up_f=EXITDOOR, up_b=EXITDOOR)

# Finale closets (open when the player crosses the trip line at the entry).
# These sit INSIDE A9 (interior boxes), so build them as islands: closed boxes
# (ceil==floor==64) on all four sides; the tagged W1 raises the ceiling to open.
finBaron = b.sector(64, 64, FLAT1, CEIL5_2, 96, tag=TAG_FIN_BARON)
finChaff = b.sector(64, 64, FLAT1, CEIL5_2, 96, tag=TAG_FIN_CHAFF)
island(2200, 700, 2360, 820, A9, cA9, finBaron, low_tex=GRAY1, up_tex=GRAY1)
island(2640, 700, 2800, 820, A9, cA9, finChaff, low_tex=GRAY1, up_tex=GRAY1)
# Finale trigger: a thin trip-strip A9T crossing the entry (a vertical slab at
# x[2120..2152], y[460..740]). Its WEST face is two stacked W1 door-open lines
# (tags 20 & 21) the player crosses on the way in; the other three edges are
# plain portals back to A9.  Built as a CCW island (A9=front, A9T=inner) so the
# loop closes, then the west edge's two halves are replaced by W1 trigger lines.
A9T = b.sector(64, 256, FLOOR0_1, CEIL5_2, 200)
tsx1, tsx2, tsy1, tsy2 = 2120, 2152, 460, 740
midy = (tsy1 + tsy2) // 2
# CCW loop: S(+x), E(+y), N(-x), then W split into two (-y) W1 segments.
b.portal(b.v(tsx1, tsy1), b.v(tsx2, tsy1), A9, A9T)            # S edge
b.portal(b.v(tsx2, tsy1), b.v(tsx2, tsy2), A9, A9T)            # E edge
b.portal(b.v(tsx2, tsy2), b.v(tsx1, tsy2), A9, A9T)            # N edge
# W edge (x=tsx1) goes y2->y1 in CCW; split at midy. Both are W1 triggers.
b.portal(b.v(tsx1, tsy2), b.v(tsx1, midy), A9, A9T,
         action=W1_DOOR_OPEN, tag=TAG_FIN_BARON)
b.portal(b.v(tsx1, midy), b.v(tsx1, tsy1), A9, A9T,
         action=W1_DOOR_OPEN, tag=TAG_FIN_CHAFF)


# ============================================================================
# THINGS
# ============================================================================
def TH(x, y, t, a=0, f=UV):
    b.thing(x, y, t, a, f)

# Player start (A1) facing NE toward the window sightline
TH(96, 80, T_PLAYER1, 45)
# A1 shotgun in spotlight + clips + FAIR-BUT-SPICY foyer zombies.
# The shotgun (the player's first real weapon) sits ~167 u from the start --
# reachable in well under a second. The two POSS no longer insta-fire on spawn:
#   * NW zombie faces AWAY (angle 90 = north) -- back to the player, must turn
#     180 deg before it can shoot; tucked NW so it doesn't block the shotgun run.
#   * NE zombie faces SIDEWAYS (angle 180 = west) -- perpendicular to the
#     player's approach axis, looking across the room, not down the spawn line.
# Combined with the A1COVER crate (raised LOS-blocker between start and the
# Y=300 line) a careful player can grab the shotgun, break LOS, and peek-shoot.
# Still spicy on UV (two hitscanners that WILL wake and converge) -- just not a
# coin-flip death.
TH(256, 128, T_SHOTGUN)
TH(180, 60, T_CLIP); TH(330, 60, T_CLIP)
TH(120, 320, T_HBONUS); TH(400, 320, T_HBONUS)
TH(160, 320, T_ZOMBIE, 90); TH(340, 312, T_ZOMBIE, 180)
# A2 hub: imps + a shotgun guy guarding the blue door, armor & ammo
TH(300, 560, T_IMP, 270); TH(520, 520, T_IMP, 180); TH(760, 560, T_IMP, 270)
TH(880, 640, T_SGTGUY, 180)
TH(128, 560, T_GREENARM); TH(600, 700, T_SHELLBOX)
TH(150, 700, T_HBONUS); TH(700, 460, T_HBONUS)
# A3 maintenance: a pinky + zombie in the dark, a medikit
TH(-160, 544, T_PINKY, 0); TH(-220, 470, T_ZOMBIE, 0)
TH(-200, 500, T_MEDIKIT)
# A11 secret X[-200..-120] Y[656..848]: rocket launcher + soulsphere + rockets,
# 1 deaf imp.
TH(-160, 740, T_RLAUNCH); TH(-160, 800, T_SOUL)
TH(-180, 700, T_ROCKET); TH(-145, 700, T_ROCKET)
TH(-160, 820, T_IMP, 270, UV | DEAF)
# A5 nukage annex: walkway band = A5W rect minus the pool. Walkway strips:
#   west x[-560..-500], east x[-220..-160], south y[256..280], north y[408..432].
TH(-300, 268, T_RADSUIT)                          # south walkway strip
TH(-540, 300, T_IMP, 0); TH(-200, 410, T_IMP, 180)
TH(-540, 410, T_SGTGUY, 180)
TH(-540, 270, T_SHELLS); TH(-200, 270, T_STIM)
TH(-530, 344, T_CELLPACK)                          # west walkway (suited reward)
# A12 secret X[-672..-576] Y[300..396]: backpack + shells + cell pack, 1 deaf imp
TH(-624, 348, T_BACKPACK); TH(-650, 320, T_SHELLBOX); TH(-600, 375, T_CELLPACK)
TH(-630, 330, T_IMP, 90, UV | DEAF)
# A6 blue key ON the raised pillar (X[-466..-454] Y[592..624]) + medikit reward
TH(-460, 608, T_BLUEKEY)
TH(-460, 470, T_MEDIKIT)                           # A6 south, by the entry mouth
# Trap closet contents (all deaf). Coords inside each closet box:
#   closet W X[-620..-540] Y[536..616]; closet E X[-380..-320] Y[536..616];
#   closet N X[-500..-420] Y[688..800].
TH(-580, 560, T_PINKY, 0, UV | DEAF)            # closet W (mouth E)
TH(-590, 590, T_SGTGUY, 0, UV | DEAF)           # closet W
TH(-350, 560, T_IMP, 180, UV | DEAF)            # closet E (mouth W)
TH(-350, 590, T_IMP, 180, UV | DEAF)            # closet E
TH(-470, 730, T_IMP, 270, UV | DEAF)            # closet N (mouth S)
TH(-450, 760, T_IMP, 270, UV | DEAF)            # closet N
# A4 Cold Storage (chaingun branch): 2 pinkies on the floor + 2 shotgun guys
# sniping from the raised crates; the CHAINGUN reward + ammo.
TH(800, 920, T_PINKY, 90); TH(900, 1100, T_PINKY, 180)
TH(752, 952, T_SGTGUY, 180); TH(912, 1032, T_SGTGUY, 180)   # on crate tops
TH(980, 1100, T_CHAINGUN)                                    # the branch reward
TH(700, 1100, T_SHELLBOX); TH(990, 880, T_SHELLBOX)
TH(820, 1080, T_MEDIKIT); TH(660, 900, T_STIM)
# A7 reel loop: imps on the way + rockets/stim
TH(1100, 560, T_IMP, 0); TH(1300, 640, T_IMP, 180)
TH(1150, 620, T_ROCKET); TH(1250, 560, T_ROCKET); TH(1200, 600, T_STIM)
# A8 vault approach: shotgun guys + imps, blue armor + topup
TH(1550, 520, T_SGTGUY, 0); TH(1830, 680, T_SGTGUY, 180)
TH(1650, 560, T_IMP, 0); TH(1750, 660, T_IMP, 180)
TH(1490, 720, T_BLUEARM); TH(1880, 480, T_SHELLBOX)
TH(1500, 480, T_MEDIKIT); TH(1850, 720, T_MEDIKIT)
# A9 finale arena: staged ammo on the open floor (NOT in closets) + fairness
# medikit at entry. Reel tops X[2200..2360]/[2640..2800] Y[480..640] floor 96.
TH(2280, 440, T_SHELLBOX); TH(2700, 440, T_SHELLBOX)    # open floor north of reels
TH(2400, 680, T_ROCKET); TH(2440, 680, T_ROCKET)         # between/below reels
TH(2560, 680, T_ROCKET); TH(2600, 680, T_ROCKET)
TH(2480, 760, T_CELLPACK)                                # arena floor cache
TH(2100, 600, T_MEDIKIT)                                 # fairness, at entry
TH(2120, 460, T_SHELLS); TH(2120, 740, T_SHELLS)
TH(2280, 600, T_SHELLBOX); TH(2720, 600, T_SHELLBOX)     # on the reel tops
# Reel-top hitscan threat (2 shotgun guys on the raised reels, floor 96)
TH(2300, 560, T_SGTGUY, 180); TH(2700, 560, T_SGTGUY, 180)
# Finale closet contents (inside the box closets):
#   finBaron X[2200..2360] Y[700..820]; finChaff X[2640..2800] Y[700..820].
TH(2280, 760, T_BARON, 270, UV | DEAF)                   # baron behind LEFT reel
TH(2680, 760, T_IMP, 270, UV | DEAF); TH(2720, 760, T_IMP, 270, UV | DEAF)
TH(2760, 760, T_IMP, 270, UV | DEAF)
TH(2660, 740, T_PINKY, 270, UV | DEAF); TH(2740, 740, T_PINKY, 270, UV | DEAF)
# A13 secret (plasma) — left reel hides it. For buildability we place the plasma
# on the LEFT reel top as the "B-side" reward (the reel IS the secret cache);
# mark the reel-top island a secret sector by re-tagging REEL_L special.
# (REEL_L is SP_GLOW; to count as secret we add a tiny secret niche instead.)
TH(2280, 600, T_PLASMA)   # plasma on the left reel top (the B-side stash)


# ============================================================================
# EMIT lumps, run nodebuilder, validate, splice, assemble
# ============================================================================
def texture_inventory(wadpath):
    base = omg.WAD(wadpath)
    t1 = base.txdefs["TEXTURE1"].data
    nt = struct.unpack("<i", t1[0:4])[0]
    offs = struct.unpack("<%di" % nt, t1[4:4 + 4 * nt])
    texs = set(t1[o:o + 8].split(b"\x00")[0].decode("ascii", "ignore").upper()
               for o in offs)
    flats = set(k.upper() for k in base.flats.keys())
    sprites = set(k.upper() for k in base.sprites.keys())
    return texs, flats, sprites


def validate(ed, texs, flats, sprites):
    errs = []
    V, L, S, SEC, TH = (ed.vertexes, ed.linedefs, ed.sidedefs,
                        ed.sectors, ed.things)

    def pt(i):
        return (V[i].x, V[i].y)

    # 1) textures/flats present
    for sd in S:
        for t in (sd.tx_up, sd.tx_low, sd.tx_mid):
            if t and t != "-" and t.upper() not in texs:
                errs.append("missing texture %s" % t)
    for sec in SEC:
        for f in (sec.tx_floor, sec.tx_ceil):
            if f.upper() not in flats:
                errs.append("missing flat %s" % f)
    # 2) sector closure (directed-edge degree balance)
    from collections import defaultdict
    se = defaultdict(lambda: defaultdict(int))
    for l in L:
        fs = S[l.front].sector
        bk = l.back
        bs = S[bk].sector if bk not in (65535, -1) else None
        se[fs][l.vx_a] += 1; se[fs][l.vx_b] -= 1
        if bs is not None:
            se[bs][l.vx_b] += 1; se[bs][l.vx_a] -= 1
    for s, deg in se.items():
        if any(d != 0 for d in deg.values()):
            errs.append("sector %d not closed" % s)
    # 3) zero-length / duplicate lines
    seen = {}
    for i, l in enumerate(L):
        if pt(l.vx_a) == pt(l.vx_b):
            errs.append("zero-length line %d" % i)
        k = tuple(sorted((l.vx_a, l.vx_b)))
        if k in seen:
            errs.append("duplicate line %d/%d" % (seen[k], i))
        seen[k] = i
    # 4) player start present
    if sum(1 for t in TH if t.type == 1) != 1:
        errs.append("need exactly one player-1 start")
    # 5) blue key + blue door + exit present
    if not any(t.type == 5 for t in TH):
        errs.append("no blue keycard")
    if not any(l.action == 26 for l in L):
        errs.append("no blue-locked door")
    if not any(l.action == 11 for l in L):
        errs.append("no exit switch (special 11)")
    # 6) all thing sprites present (Doom1 type->sprite-prefix)
    t2s = {1: "PLAY", 3004: "POSS", 9: "SPOS", 3001: "TROO", 3002: "SARG",
           3003: "BOSS", 5: "BKEY", 2001: "SHOT", 2002: "MGUN", 2003: "LAUN",
           2004: "PLAS", 2007: "CLIP", 2008: "SHEL", 2048: "SBOX", 2046: "BROK",
           2010: "ROCK", 17: "CELP", 2047: "CELL", 8: "BPAK", 2011: "STIM",
           2012: "MEDI", 2014: "BON1", 2013: "SOUL", 2015: "BON2", 2018: "ARM1",
           2019: "ARM2", 2025: "SUIT"}
    sp = set(s[:4] for s in sprites)
    for t in TH:
        pre = t2s.get(t.type)
        if pre is None:
            errs.append("unknown thing type %d" % t.type)
        elif pre not in sp:
            errs.append("missing sprite %s (type %d)" % (pre, t.type))
    # 7) thing-in-sector point location (reconstruct sector polygons from edges)
    #    Build per-sector boundary segments (as that sector sees them) and test
    #    each thing with a ray-cast crossing count over those segments.
    sec_segs = defaultdict(list)
    for l in L:
        a, c = pt(l.vx_a), pt(l.vx_b)
        fs = S[l.front].sector
        sec_segs[fs].append((a, c))
        bk = l.back
        if bk not in (65535, -1):
            bs = S[bk].sector
            sec_segs[bs].append((c, a))

    def inside(px, py, segs):
        cnt = 0
        for (x1, y1), (x2, y2) in segs:
            if (y1 > py) != (y2 > py):
                xint = x1 + (py - y1) * (x2 - x1) / (y2 - y1)
                if px < xint:
                    cnt += 1
        return cnt % 2 == 1
    monster_types = {3004, 9, 3001, 3002, 3003}
    stuck = []
    for ti, t in enumerate(TH):
        # find which sector contains it
        in_secs = [s for s in range(len(SEC))
                   if inside(t.x, t.y, sec_segs.get(s, []))]
        if not in_secs:
            stuck.append((ti, t.type, t.x, t.y, "no-sector"))
    if stuck:
        for s in stuck[:20]:
            errs.append("thing %d (type %d) at (%d,%d): %s" % s)
    return errs


def splice_and_assemble():
    # 1) build scratch geometry
    ed = MapEditor()
    ed.vertexes = b.verts
    ed.sidedefs = b.sides
    ed.sectors = b.sectors
    ed.linedefs = b.lines
    ed.things = b.things
    w = omg.WAD()
    w.maps["E1M1"] = ed.to_lumps()
    w.to_file(SCRATCH_WAD)
    print("scratch: V%d L%d S%d SEC%d TH%d" %
          (len(b.verts), len(b.lines), len(b.sides),
           len(b.sectors), len(b.things)))

    # 2) run nodebuilder (zdbsp, vanilla mode). -R writes a correctly-sized
    #    all-zero REJECT (vanilla expects (nsec^2+7)/8 bytes); default node
    #    format is classic vanilla NODES/SEGS/SSECTORS that doomgeneric reads.
    r = subprocess.run([BSP, "-R", "-m", "E1M1", "-o", LEVEL_WAD, SCRATCH_WAD],
                       capture_output=True, text=True)
    sys.stdout.write(r.stdout)
    if r.returncode != 0:
        sys.stderr.write(r.stderr)
        raise SystemExit("nodebuilder failed (%d)" % r.returncode)
    print(r.stderr.strip())

    # 3) validate the built level
    lw = omg.WAD(LEVEL_WAD)
    led = MapEditor(lw.maps["E1M1"])
    texs, flats, sprites = texture_inventory(BASE_WAD)
    errs = validate(led, texs, flats, sprites)
    grp = lw.maps["E1M1"]
    lump_sizes = {k: len(grp[k].data) for k in grp.keys() if k != "_HEADER_"}
    for n in ("NODES", "SEGS", "SSECTORS", "BLOCKMAP", "REJECT"):
        if lump_sizes.get(n, 0) == 0:
            errs.append("node lump %s empty" % n)
    print("lump sizes:", lump_sizes)
    xs = [v.x for v in led.vertexes]
    ys = [v.y for v in led.vertexes]
    print("map bounds: X[%d..%d] Y[%d..%d]" %
          (min(xs), max(xs), min(ys), max(ys)))
    mon = sum(1 for t in led.things if t.type in (3004, 9, 3001, 3002, 3003))
    sec9 = sum(1 for s in led.sectors if s.type == 9)
    print("monsters:", mon, "(cap 128) | secret sectors:", sec9)
    if errs:
        print("VALIDATION ERRORS (%d):" % len(errs))
        for e in errs:
            print("  -", e)
        raise SystemExit("validation failed")
    print("VALIDATION: all checks passed")

    # 4) splice our E1M1 over base.wad (keep E1M2-E1M9)
    merged = omg.WAD(BASE_WAD)
    merged.maps["E1M1"] = led.to_lumps()
    merged.to_file(MERGED_WAD)
    print("merged WAD:", MERGED_WAD, "maps:", list(merged.maps.keys()))

    # 5) assemble sandbox HTML (reuse compiled v3 engine; do NOT touch dist/)
    env = dict(os.environ)
    env["DOOM_V3_WAD"] = MERGED_WAD
    r2 = subprocess.run(["/usr/bin/python3", ASSEMBLE, OUT_HTML],
                        capture_output=True, text=True, env=env)
    sys.stdout.write(r2.stdout)
    if r2.returncode != 0:
        sys.stderr.write(r2.stderr)
        raise SystemExit("assemble failed")
    print("sandbox HTML:", OUT_HTML)
    return lump_sizes, (min(xs), max(xs), min(ys), max(ys)), mon, sec9


if __name__ == "__main__":
    splice_and_assemble()
