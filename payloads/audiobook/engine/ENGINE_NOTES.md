# Audiobook TTS engine — eSpeak-ng → WebAssembly (English-only)

In-browser, self-contained text-to-speech for the cassette audiobook tape.
Decodes off tape → runs from `file://` or HTTP → synthesizes English text to raw
PCM, playable via WebAudio. **Fetches nothing at runtime.**

## Approach that worked: A (build from source with Emscripten)

- Engine: **eSpeak-ng 1.52** (git `fbe4b37`), cloned to `src/`.
- Toolchain: Emscripten **6.0.0** (`tools/emsdk`), node v22.
- This espeak-ng is **CMake-only** (the old autotools / `autogen.sh` that the
  repo's `src/emscripten/Makefile` expects is gone), so the official asm.js
  Makefile path does **not** apply. Instead:
  1. **Native build** (`build-native/`) to produce the espeak-ng tool and run its
     `data` target → generates the binary phoneme/dictionary files
     (`phondata`, `phonindex`, `phontab`, `intonations`, `en_dict`, voice configs).
  2. **Emscripten build** of the static lib `libespeak-ng.a` (+ `libucd.a`,
     `libspeechPlayer.a`) with `emcmake cmake` and size-minimizing options
     (`-DUSE_MBROLA=OFF -DUSE_LIBSONIC=OFF -DUSE_LIBPCAUDIO=OFF -DUSE_ASYNC=OFF`,
     `MinSizeRel`, KLATT on).
  3. A tiny **C wrapper** (`build/espeak_wrapper.c`) instead of the WebIDL binder —
     calls `espeak_Initialize` / `espeak_SetVoiceByName("en")` / `espeak_Synth`
     with a synth callback that appends 16-bit PCM to a growable buffer, exported
     via `EMSCRIPTEN_KEEPALIVE`.
  4. Linked to **WASM** (`-s WASM=1 -O3 MODULARIZE EXPORT_NAME=espeakng
     ENVIRONMENT=web,worker,node ALLOW_MEMORY_GROWTH FORCE_FILESYSTEM`).
  5. English-only **data package** built with `file_packager.py`, preloading only
     the English data (all other `*_dict` excluded).

Two fixes during the build: header is `espeak-ng/speak_lib.h`; `espeak_Initialize`
must be given `"/espeak-ng-data"` explicitly (NULL points at a non-existent host path
in the WASM virtual FS).

## Runtime file set (all in `build/`)

| File | raw | xz -9 | gzip -9 | required? |
|---|---|---|---|---|
| `espeakng.js`   |  77,373 B | 19,152 B  | 21,046 B  | yes (Emscripten glue) |
| `espeakng.wasm` | 350,287 B | 122,124 B | 148,912 B | yes (engine) |
| `espeakng.data` | 936,055 B | 393,400 B | 481,260 B | yes (English phoneme + dict data, preloaded) |
| **Total**       | **1,363,715 B** | **534,512 B (~522 KB, tar+xz -9)** | — | |

`espeakng.data` is the dominant term; inside it `phondata` (~586 KB, shared
formant waveform data) and `en_dict` (~168 KB) are mandatory and incompressible
much further. Trimming the `voices/!v/` variant configs saves only ~7 KB xz, so
the full English package is kept for robustness.

**Budget:** tape is ~3.7 MB compressed (engine + book text + reader). Engine is
**~522 KB xz = ~14%** of budget. Comfortable; leaves ~3.2 MB for the book + UI.

## Synth API (one-liner)

The module is `MODULARIZE`d under global `espeakng`. Exports are plain C functions
on the Module (note the `_` prefix). PCM is **Int16, mono, 22 050 Hz**.

```js
const M = await espeakng();                       // load wasm + data
const sampleRate = M._espeak_init();              // -> 22050
M._espeak_set_voice_en();                         // select English
const b = new TextEncoder().encode(text + "\0");
const p = M._malloc(b.length); M.HEAPU8.set(b, p);
const n = M._espeak_synth_text(p); M._free(p);    // -> sample count
const pcm = new Int16Array(M.HEAP16.buffer, M._espeak_get_pcm_buf(), n);
// feed pcm to a WebAudio AudioBuffer at 22050 Hz
```

Helper sources: `build/espeak_wrapper.c` (the C exports), `build/test_synth.mjs`
(node test), `build/browser_test.html` (browser test).

## Verification (synthesized "Hello, this is a cassette.")

| Path | sample rate | sample count | peak amplitude | non-silent |
|---|---|---|---|---|
| node (`test_synth.mjs`) | 22 050 Hz | 30 695 (~1.39 s) | 25 703 / 32 767 | YES |
| **real browser** (Playwright, Chromium) | 22 050 Hz | 30 695 | 25 703 | YES |

Both paths agree exactly. Browser run had only a harmless favicon 404 in console —
the wasm + data loaded and synthesized correctly from HTTP, and the module also
supports `file://`.

## License — GPLv3 (ship source, like the DOOM tape side B)

- eSpeak-ng is **GNU GPL v3**. License text: `src/COPYING` (35,147 B).
  Additional component licenses in `src/COPYING.APACHE`, `COPYING.BSD2`, `COPYING.UCD`.
- We must ship the corresponding source. The full source tree is at
  `payloads/audiobook/engine/src/` (espeak-ng 1.52, git `fbe4b37`). Bundle it (or a
  pointer + the COPYING file) on the tape's source side, as done for DOOM.

## Verdict

**Engine ready.** Real-browser-verified English TTS to Int16 PCM @ 22.05 kHz,
self-contained (no runtime fetches), ~522 KB xz — well under the 3.7 MB tape budget.
