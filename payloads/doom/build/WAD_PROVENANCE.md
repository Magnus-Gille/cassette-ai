# WAD Provenance — `mini.wad`

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
