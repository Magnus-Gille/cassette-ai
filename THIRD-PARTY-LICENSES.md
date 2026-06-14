# Third-party licenses

The original work in this repository (the cassette data-over-audio modem, DSP,
analysis, scripts, and the "DECODED" album) is licensed **MIT** — see
[`LICENSE`](LICENSE). It is authored by Magnus Gille.

This repository additionally **bundles and redistributes** the third-party
components listed below. They retain their own licenses; the MIT license does
**not** cover them. In this project DOOM is stored as *payload data on tape*,
not linked into the modem — the components are a mere aggregation, so MIT for
the original code and the licenses below for the bundled code coexist.

---

## 1. doomgeneric / DOOM engine — GPL-2.0

**What:** the DOOM game engine used to build the playable on-tape artifact.
This includes:

- `payloads/doom/doomgeneric/` — the doomgeneric engine source
- `payloads/doom/build/src/doomgeneric_wasm.c` — the SDL-free Emscripten
  backend written for this project (explicitly GPL-2.0, same as the engine it
  links against)
- the compiled WebAssembly engine embedded in the `dist/doom_cassette*.html`
  artifacts
- `payloads/doom/dist/doom_v3_source.tar` — the corresponding source archive
  shipped on **side B of the cassette** to satisfy GPL-2.0 §3 (source offer)

**License:** GNU General Public License, version 2. doomgeneric is a port of
id Software's DOOM source, which id Software released under the GPL. Any
distribution of the engine (including the WASM build and the on-tape artifact)
must carry the GPL-2.0 terms and provide corresponding source — which side B of
the tape, and `doom_v3_source.tar`, do.

Full text: <https://www.gnu.org/licenses/old-licenses/gpl-2.0.txt>
Upstream: <https://github.com/ozkl/doomgeneric>

## 2. Freedoom game assets — BSD-3-Clause

**What:** the game data (WAD assets — graphics, levels, sounds) used in place
of id Software's proprietary/shareware content. The custom "Magnetic Vault"
E1M1 is built on Freedoom assets.

- `payloads/doom/build/miniwad/COPYING.adoc` — the verbatim Freedoom license
- the trimmed Freedoom WADs produced by `payloads/doom/build/trim_freedoom*.py`
- see `payloads/doom/build/WAD_PROVENANCE.md` for the per-lump provenance

**License:** BSD 3-Clause. "Copyright © 2001–2018 Contributors to the Freedoom
project. All rights reserved." Redistribution must reproduce the copyright
notice and license text, and must not use the Freedoom name to endorse a
derived product. **No proprietary or shareware id Software content is present**
— every lump is Freedoom-derived.

Upstream: <https://freedoom.github.io/>

---

## Obligations when redistributing this repo or the cassette

- Keep this file, [`LICENSE`](LICENSE), `COPYING.adoc`, and the GPL source
  archive together with the artifacts.
- Distributing the DOOM artifact (file or tape) = distributing GPL-2.0 binary →
  the corresponding source must accompany it. Side B of the cassette and
  `doom_v3_source.tar` are that source.
- Reproduce the Freedoom BSD notice; do not use the Freedoom name to endorse.
