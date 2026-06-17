# Audiobook — Build Notes

## Artifact

`payloads/audiobook/dist/willows_audiobook.html`

| Metric | Value |
|---|---|
| Raw size | 1,925,627 bytes (~1.84 MB) |
| xz -9 compressed | 726,340 bytes (~709 KB) |
| Fits one C90 side? | **YES** — 709 KB of 1,860 KB budget (38%) |
| Fits whole C90? | Yes (19% of 3,700 KB budget) |

## Book

**The Willows** — Algernon Blackwood, 1907. Public domain.
5 sections, 326 paragraphs, ~108,000 characters of prose.
Source: extracted from `experiments/tape_v2/ebook_reader/the_willows.html`
(the `story-data` JSON payload embedded in that file).

## Engine embedding

Three eSpeak-ng WASM files are base64-encoded inline in the HTML:

| File | Raw | xz -9 |
|---|---|---|
| espeakng.js | 77,373 B | 19,152 B |
| espeakng.wasm | 350,287 B | 122,124 B |
| espeakng.data | 936,055 B | 393,400 B |

**No runtime fetches.** Two Emscripten Module hooks intercept the loader:
- `Module.wasmBinary` — decoded ArrayBuffer from WASM_B64 bypasses the wasm fetch
- `Module.getPreloadedPackage` — returns decoded ArrayBuffer from DATA_B64 when
  `remotePackageName === 'espeakng.data'`, bypassing the data fetch

The espeakng.js glue is inlined verbatim (not a `<script src>`).

## Player features

- Play/Pause, Prev/Next sentence navigation
- Sentence-level highlighting with auto-scroll
- Auto-advance sentence → sentence → paragraph → paragraph
- Pre-synthesis of next sentence during current playback
- Precise WebAudio scheduling (AudioBufferSourceNode.start at scheduled end time)
- Dark theme, Georgia serif, 38rem line length
- Loading overlay during WASM init (~1–2s)
- Speed slider rendered (80–300 wpm) — cosmetic only (see TODO below)

## Verification (Playwright, Chromium, real browser)

| Check | Result |
|---|---|
| Network requests for engine files | 0 (only favicon 404) |
| Engine init | OK — status shows "eSpeak-ng ready (sample rate: 22050 Hz)" |
| Synth output (first paragraph) | 276,190 samples @ 22050 Hz, peak 0.812 / 1.0 — non-silent |
| AudioContext state after Play click | 'running' — button transitions to Pause |
| Playback | AudioBufferSourceNode created with real synth buffer |

Verification method: AudioBufferSourceNode.prototype.start monkey-patched to intercept
the first buffer played — confirmed sampleRate 22050, length 276190, peak 0.812.

## Known TODO

**Rate control is cosmetic.** The compiled wrapper (`espeak_wrapper.c`) only exports
5 functions; `espeak_SetParameter` is not among them and was dead-code-eliminated from
the WASM. The speed slider updates a `rateValue` variable but it has no effect on synth
output. Fix: rebuild the WASM with an `espeak_set_rate(int wpm)` export in the wrapper,
calling `espeak_SetParameter(espeakRATE, wpm, 0)`. No recompile needed for any other
feature.

## License

eSpeak-ng is **GNU GPL v3**. Source lives at `payloads/audiobook/engine/src/`
(espeak-ng 1.52, git `fbe4b37`). The HTML notes this in small print.
Bundle the source alongside the tape, as done for the DOOM side-B GPL source.
The book text (Algernon Blackwood, 1907) is public domain.
