# Modern Library — Build Notes

## Artifacts

| File | Books | Purpose |
|------|-------|---------|
| `dist/modern_library.html` | All 8 (Watts + Doctorow) | Combined; too large for one C90 side |
| `dist/modern_library_watts.html` | Blindsight, Starfish, Maelstrom, Behemoth | Side A (Watts) |
| `dist/modern_library_doctorow.html` | Little Brother, Down and Out, For the Win, Makers | Side B (Doctorow) |

Self-contained, self-narrating HTML readers. Zero runtime network fetches.
Works over both `file://` and HTTP.

Build script: `/tmp/build_modern_library_v2.py` (not tracked; regenerate from sources).

---

## Books included

| # | Title | Author | Year | License | Source | Chapters |
|---|-------|--------|------|---------|--------|----------|
| 1 | Blindsight | Peter Watts | 2006 | CC BY-NC-SA 2.5 | https://www.rifters.com/real/Blindsight.htm | 6 |
| 2 | Starfish | Peter Watts | 1999 | CC BY-NC-SA 2.5 | https://www.rifters.com/real/STARFISH.htm | 42 |
| 3 | Maelstrom | Peter Watts | 2001 | CC BY-NC-SA 2.5 | https://www.rifters.com/real/MAELSTROM.htm | 50 |
| 4 | Behemoth | Peter Watts | 2004 | CC BY-NC-SA 2.5 | https://www.rifters.com/real/Behemoth.htm | 50 |
| 5 | Little Brother | Cory Doctorow | 2008 | CC BY-NC-SA 3.0 | https://craphound.com/littlebrother/Cory_Doctorow_-_Little_Brother.txt | 21 |
| 6 | Down and Out in the Magic Kingdom | Cory Doctorow | 2003 | CC BY-NC-SA 3.0 | https://craphound.com/down/Cory_Doctorow_-_Down_and_Out_in_the_Magic_Kingdom.txt | 10 |
| 7 | For the Win | Cory Doctorow | 2010 | CC BY-NC-SA 3.0 | https://craphound.com/ftw/Cory_Doctorow_-_For_the_Win.txt | 52 |
| 8 | Makers | Cory Doctorow | 2009 | CC BY-NC-SA 3.0 | http://craphound.com/makers/Cory_Doctorow_-_Makers.txt | 38 |

Echopraxia (Watts, 2014): dropped — not freely available on rifters.com, all URL variants return 404. Not included.

---

## Sizes

| File | Raw HTML | xz -9 | C90 side budget | Fits? | Margin |
|------|----------|--------|----------------|-------|--------|
| modern_library.html (all 8) | 6.63 MB | 2.10 MB (2,198,984 B) | 1.86 MB (1,949,696 B) | **NO** | −249,288 B |
| modern_library_watts.html | 3.94 MB | 1.33 MB (1,399,344 B) | 1.86 MB | **YES** | +550,352 B |
| modern_library_doctorow.html | 4.41 MB | 1.45 MB (1,520,148 B) | 1.86 MB | **YES** | +429,548 B |

**Conclusion:** 8 books in one file is 249 KB over the C90 side budget. The natural split is Watts side / Doctorow side — each fits with >400 KB headroom.

---

## Engine embedding

eSpeak-ng 1.52, built to WASM with Emscripten 6.0.0 (English-only package).
Three files embedded in each HTML:

| File | Raw bytes | Embedded as |
|------|-----------|-------------|
| espeakng.js | 77,373 | Inlined verbatim JavaScript |
| espeakng.wasm | 350,287 | Base64 (const WASM_B64, 467,052 chars) |
| espeakng.data | 936,055 | Base64 (const DATA_B64, 1,248,076 chars) |

Decoding: `b64toAB()` (inline helper, `atob()` → `Uint8Array` → `ArrayBuffer`). Module init:
```js
M = await espeakng({ wasmBinary: b64toAB(WASM_B64),
                     getPreloadedPackage: name => name === 'espeakng.data' ? b64toAB(DATA_B64) : null });
```
No network fetch for `.data` — intercepted by `getPreloadedPackage`.

---

## Verification results (Playwright, Chromium, HTTP — 2026-06-18)

**Watts variant (`modern_library_watts.html`):**
- Engine init: Loading overlay cleared, `window._testM` exposed, all eSpeak exports confirmed.
- Books: 4 cards (Blindsight, Starfish, Maelstrom, Behemoth), all selectable, no unavailable cards.
- Starfish synthesis: "The abyss should shut you up." → 29,851 samples @ 22,050 Hz, peak 26,395/32,767 — **non-silent, confirmed**.
- Network requests: Exactly 1 (`GET modern_library_watts.html 200`). Zero runtime dependency fetches.

**Doctorow variant (`modern_library_doctorow.html`):**
- Engine init: confirmed.
- Books: 4 cards (Little Brother, Down and Out, For the Win, Makers), all selectable.
- Makers synthesis: "PART I Suzanne Church almost never had to bother with the blue blazer these days." → 87,855 samples @ 22,050 Hz, peak 30,978/32,767 — **non-silent, confirmed**.
- Network requests: Zero runtime dependency fetches.

---

## License and obligations

### NC / SA obligations (CC BY-NC-SA works)

- **NonCommercial**: cassette-ai must remain non-commercial while shipping Watts and Doctorow texts. No commercial use of this artifact.
- **ShareAlike**: any adaptation or redistribution must carry CC BY-NC-SA 2.5 (Watts) or CC BY-NC-SA 3.0 (Doctorow) and credit original authors with source links.
- Attribution is shown in the in-reader "License / Attribution" panel.

### eSpeak-ng (GPLv3)

- Engine is GNU GPL v3. Source at `payloads/audiobook/engine/src/` (espeak-ng 1.52, git fbe4b37).
- GPLv3 requires shipping corresponding source. Include on cassette side B or a pointer to the repo.

---

## Notes / known limitations

- The speed slider (80–300) updates the UI label but does not alter synthesis rate — the WASM wrapper does not export `_espeak_set_rate`. Rate control would require recompiling `espeak_wrapper.c`. Acceptable for a first tape burn.
- Watts HTML sources (rifters.com) are parsed with stdlib html.parser; a handful of `?` replacement chars appear where sources had Windows-1252 em-dashes — source artefact, not a parsing bug.
- Watts chapter detection uses h2/h3 headings from the rifters.com HTML. Maelstrom and Behemoth hit the 50-chapter cap; content is complete, just chunked at that boundary.
