# WAD Provenance — `mini.wad` (v1) · `freedoom_trim.wad` (v2, see bottom)

**Artifact:** `/Users/magnus/repos/cassette-ai/payloads/doom/build/mini.wad`
**Produced:** 2026-06-11 (verbatim copy of upstream `miniwad.wad`; no modifications)

## Source

| Field | Value |
|---|---|
| Project | **miniwad** — a minimalist Doom IWAD |
| Author | Simon Howard (*fragglet*; Doom community / Chocolate Doom maintainer) |
| Repository | <https://github.com/fragglet/miniwad> |
| Prebuilt download | <https://soulsphere.org/random/miniwad.zip> (fetched 2026-06-11) |
| `miniwad.zip` SHA-256 | `b4c9804343be34e485fddab802c18ecf836168d733c2f03441d8a9dff80b2393` |
| `miniwad.wad` = `mini.wad` SHA-256 | `daed5e9dc341a9ff4b9c6901cb8467a630bd31b87f3ecb58a93a8b2bc186fbfb` |
| Size | 230,497 B raw (225.1 KB) · 34,272 B lzma preset-9 (33.5 KB) |

## License — BSD 3-clause (permissive, product-safe)

miniwad is derived from the **Freedoom** project's assets and carries Freedoom's
BSD 3-clause license. Verbatim license text shipped alongside the WAD in the zip:
`/Users/magnus/repos/cassette-ai/payloads/doom/build/miniwad/COPYING.adoc`
("Copyright © 2001-2018 Contributors to the Freedoom project. All rights
reserved." + standard BSD 3-clause terms). No proprietary or shareware id
Software content is present — every lump is Freedoom-derived or
purpose-made stub data.

**Obligations when shipping:** reproduce the copyright notice + license text in
the distributed artifact (include `COPYING.adoc` text in the HTML's credits/
attribution block). Do not use the Freedoom name to endorse the product.

## Structural validation (2026-06-11, `validate_wad.py`)

Validated with `python3.13 /Users/magnus/repos/cassette-ai/payloads/doom/build/validate_wad.py mini.wad` — **PASS**:

- Valid `IWAD` header, 2,438 lumps, directory in bounds.
- 32 map markers (MAP01–MAP32, Doom II format), all 32 with the complete
  THINGS…BLOCKMAP sublump set. (All maps are the same small box room by
  design — "vaguely playable", boots any port.)
- All boot-critical lumps present (per doomgeneric source audit): PLAYPAL,
  COLORMAP, TEXTURE1, PNAMES, TITLEPIC, CREDIT, HELP, INTERPIC, F_SKY1,
  DEMO1/2/3 (title demo loop), 40 `M_*` menu lumps, 67 `STCFN*` font lumps,
  173 `ST*` status-bar lumps, 626 sprite lumps inside S_START/S_END
  (incl. PLAY* player sprites), 153 flats, plus GENMIDI and stub `DS*` sounds.
- Missing only Doom1-retail-mode lumps (M_EPISOD, WIMAP0, …) — irrelevant in
  commercial (Doom II) mode.

## Integration notes for the doomgeneric build

- `miniwad.wad` is **not** in `d_iwad.c`'s `iwads[]` table. Either place it in
  MEMFS named **`freedoom2.wad`** (auto-identified as doom2/commercial) or pass
  `-iwad`. Commercial mode matches the WAD's MAP01 format and lump set.
- Stub `DS*` sounds + GENMIDI mean a sound-enabled build boots, but
  `FEATURE_SOUND` off is preferred to shrink the WASM.

## Why not the fallback (freedoom1.wad single-map trim)

Measured asset closure for a faithful E1M1 trim is ~1.6–2.0 MB raw
(~0.8–1.2 MB after lzma) — exceeds the 530 KB tape cap before the engine is
counted. miniwad at 33.5 KB compressed leaves ~496 KB for the WASM engine +
HTML shell. If richer gameplay is wanted later: graft 1–2 real Freedoom map
geometries into miniwad via omgifol with texture-name remapping
(est. +20–60 KB compressed).

*(2026-06-12 note: the budget was later re-derived from cassette physics —
600 KB lzma hard cap on a C90 side — which made exactly this trim viable.
That is v2, below.)*

---

# V2 — `freedoom_trim.wad` (2026-06-12)

**Artifact:** `/Users/magnus/repos/cassette-ai/payloads/doom/build/freedoom_trim.wad`
**Produced:** 2026-06-12 by `/Users/magnus/repos/cassette-ai/payloads/doom/build/trim_freedoom.py`
(deterministic trim; rebuild with `/usr/bin/python3 trim_freedoom.py` — defaults
reproduce this artifact). `build/doom1.wad` is a byte-identical copy (the name
the engine pack expects in MEMFS).

## Source

| Field | Value |
|---|---|
| Project | **Freedoom: Phase 1** v0.13.0 — <https://freedoom.github.io/> |
| Upstream zip | `payloads/doom/freedoom-0.13.0.zip`, SHA-256 `3f9b264f3e3ce503b4fb7f6bdcb1f419d93c7b546f4df3e874dd878db9688f59` |
| `freedoom1.wad` (input) | 28,795,076 B, SHA-256 `7323bcc168c5a45ff10749b339960e98314740a734c30d4b9f3337001f9e703d` |
| Stub donor | `miniwad/miniwad.wad` (v1 provenance above) — supplies sound/music/demo stubs |
| `freedoom_trim.wad` (output) | 1,616,811 B raw · 468,048 B lzma preset-9 (457.1 KB) · SHA-256 `7c072573ed31d88cd9843972761e436601be3576f5d07d5d8c0988014d63cacb` |

## What the trim keeps / strips (verified by lump audit, 2026-06-12)

- **1,015 lumps.** Real Freedoom maps **E1M1 + E1M2** (141.9 KB / 139.3 KB of
  map data) with full BSP; E1M3–E1M9 are 351-B "THE END" stub maps so no
  map-progression path hits a missing lump.
- **Monsters kept** (front-rotation-only sprites, Jaguar-DOOM style): POSS
  (zombieman), SPOS (shotgun guy), TROO (imp), SARG (demon). **Weapons kept:**
  fist, pistol, shotgun, chaingun (+ rocket MISF/MISL frames for projectiles).
  231 sprite frames across 61 sprite prefixes incl. full PLAY* set.
- **Textures/flats:** 71 TEXTURE1 entries, 56 patches, 35 flats — the closure
  of what E1M1/E1M2 + the shareware switch/anim tables actually reference.
  Real TITLEPIC; HELP2 + ENDOOM present.
- **Sounds/music stripped to stubs:** all 214 `DS*`/`DP*` lumps are tiny stubs
  (16.5 KB total, real PCM removed), 14 `D_*` music lumps are 868 B of stubs,
  GENMIDI kept (boot-required), DMXGUS dropped. The engine carries no sound
  backend, so nothing is lost.
- Served to the engine as **`/doom1.wad`** (`pre_wad1.js`,
  `DG_IWAD_PATH=/doom1.wad`): `d_iwad.c` → gamemission=doom; the E1-only lump
  set → shareware gamemode, matching the kept switch/anim/finale tables.

## License — unchanged: BSD 3-clause (Freedoom)

Identical obligations to v1: Freedoom copyright + BSD 3-clause text reproduced
verbatim in the shipped HTML head comment (`assemble_html2.py` embeds
`miniwad/COPYING.adoc`, which is the Freedoom license text). No id Software
content anywhere in the chain. Do not use the Freedoom name to endorse the
product.

*(Bookkeeping note: this section was added 2026-06-12 during the v2 ship
report; the trim step itself had not written it.)*
