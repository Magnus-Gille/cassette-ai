# Built Payloads — fetched, license-verified, quantized, size-measured (2026-06-15)

Every payload below was **fetched, license-checked, built to tape-ready bytes, roundtrip-sanity-checked, and
measured**. Binaries live under `payloads/built/<name>/` (gitignored — regenerable from the committed build
scripts); `meta.json` + build scripts are tracked. Sizes are the **measured** `xz`/quant bundle, not estimates.

## ✅ Ship-clear, built (permissive license verified)

| payload | tier | on-tape | license | the flex | runtime |
|---|---|---|---|---|---|
| delphi-stories-50k | tiny | 0.08 MB | Apache-2.0 | (weak stories) | llama2.c |
| stories260K | tiny | 0.13 MB | MIT | babble stories | llama2.c |
| delphi-llama2-100k | tiny | 0.18 MB | MIT | short stories | llama2.c |
| corpus_great_library_essentials | Bronze | 0.35 MB | Public Domain | trimmed "best of the best" Great Library (9 works, see below) | text |
| **chip8_octo** | Bronze | **0.63 MB** | MIT + CC0 | CHIP-8 console + **101-game** CC0 library | JS (Octo) |
| **learned-planner** | Bronze | **0.79 MB** | Apache-2.0 | "a cassette that **plans**" (Sokoban ConvLSTM) | JAX |
| **ddpm-mnist** | Bronze | **0.99 MB** | MIT | "**paints** digits" (real diffusion U-Net) | diffusers |
| **great_library_essentials_audiobook** | Silver | **1.02 MB** | PD text + espeak GPLv3+source | "**a cassette that reads itself aloud**" — 9 canonical classics + eSpeak-ng WASM TTS, self-contained HTML, sentence-highlighted playback | WASM+text |
| corpus_kjv_bible | Silver | 1.05 MB | Public Domain | the complete Bible | text |
| corpus_sherlock | Silver | 1.07 MB | Public Domain | all 4 novels + 56 stories | text |
| **tic80** | Silver | **1.50 MB** | MIT | "**a games console** on a cassette" (engine + 16 MIT carts) | WASM |
| corpus_shakespeare | Silver | 1.67 MB | Public Domain | the complete works | text |
| **v86_linux** | Silver | **2.54 MB** | GPL+source | "**boots a full Linux PC**" (v86 BSD + Buildroot) | WASM |
| **chess-gpt-4.5M** | Silver | **3.02 MB** | MIT | "**plays chess**" (6.6M, beats Stockfish-low) | nanoGPT |
| corpus_human_knowledge | Gold | 5.07 MB | Public Domain | "seed of civilization" (18 works) | text |
| **delphi-llama2-12.8m** | Gold | **7.31 MB** | MIT | "**writes coherent stories**" | llama2.c |
| **othello-gpt** | Platinum | **11.56 MB** | MIT | "**plays Othello**" (world-model model) | nanoGPT |
| tinycode-python | Platinum | 12.31 MB | MIT | "**writes code**" | transformers |
| delphi-llama2-25.6m | Platinum | 12.70 MB | MIT | better-prose stories | llama2.c |
| **corpus_great_library** | Diamond | **17.16 MB** | Public Domain | "**Library of Alexandria**" (58 classics) | text |

Each model bundle carries int4 **and** int8 variants (int8 for fidelity when the tape budget allows); the
table shows the headline (int4 for models, `xz -9e` for corpora). All roundtrip-checked (`forward_ok`, bounded
dequant error). DOOM (1.47 MB, GPL+source) is already shipped from the earlier campaign.

## 🌙 Built but over-budget (the dream tier — license-clear, just too big yet)
| payload | on-tape | license | note |
|---|---|---|---|
| SmolLM2-135M-Instruct | 43 MB (int3) / 60 MB (int4) | Apache-2.0 | "a cassette you can **chat** with" — needs int2/ternary to reach the ~34 MB dream tape |
| Piper TTS (2 EN voices) | 116 MB | weights MIT/CC0/PD; espeak GPLv3 | "a cassette that **talks**" — voices fit, frontend is heavy + GPL |

## ⛔ Blocked (no verifiable permissive license — NOT built/shipped)
| payload | why | how to unblock |
|---|---|---|
| **chess_llms 25M** (adamkarvonen lichess_8layer) | weights repo has **NO license** (training *code* repo is MIT, but that doesn't license the weights) | ask the author to add a LICENSE / a license tag to the weights repo |
| delphi-mamba-200k | HF repo declares **no license** anywhere (unlike the MIT/Apache delphi Llama2 siblings) | use a licensed state-space model instead |

## Notes
- **Great Library — Essentials (2026-07-01):** the full 58/69-work `corpus_great_library` (17.16 MB) is
  commercially dead at the only real-tape-proven bitrate (4910 bps mono — DOOM's own proven config) — it needs
  ~8 hours of playback, i.e. 5+ full C90 cassettes. `corpus_great_library_essentials` is a curated 9-title
  "best of the best" trim (Alice's Adventures in Wonderland, A Christmas Carol, The Strange Case of Dr Jekyll
  and Mr Hyde, The Metamorphosis, The Fall of the House of Usher, The Masque of the Red Death, The Yellow
  Wallpaper, A Study in Scarlet, The Time Machine — same license verification / `xz -9e` measurement pipeline,
  `payloads/built/_build_all_corpora.py::GREAT_LIBRARY_ESSENTIALS`) sized to fit ONE C90 side alongside the
  eSpeak-ng WASM TTS reader. Bundled artifact: `payloads/audiobook/dist/great_library_essentials_audiobook.html`
  (self-contained, base64-embedded engine, no runtime fetches, book-selector + sentence-highlighted playback —
  same technical pattern as `willows_audiobook.html`) measures **1,021,256 bytes xz -9e** = 27.7 min @ 4910 bps,
  well inside the 1,657,125-byte / 45-min C90-side budget (62% utilization, ~636 KB margin). Playwright-verified:
  engine inits, 0 runtime network fetches, non-silent synth (peak 0.66/1.0) on Play, book-selector + back
  navigation both work. Build: `python3 payloads/audiobook/build_great_library_essentials.py`.
- **The acoustic loop already covers a LOT:** everything ≤ ~3 MB is recordable on the current living-room
  acoustic path **today** — a games console (TIC-80), a Linux PC (v86), a chess engine, a planner, a diffusion
  painter, the complete Shakespeare/Bible/Sherlock, and the story tinies. Gold-and-up rides the electrical climb.
- **Size vs leaderboard estimate:** mostly within ~10%. `human_knowledge` came in 5.07 MB (est 3.34 — fuller
  selection); `ddpm` 0.99 MB (beat the 2 MB est by half); `great_library` 17.16 MB (est 15.84). All honest,
  measured.
- **The Platinum chess headliner is the one real casualty** — license-blocked. But `chess-gpt-4.5M` (MIT) covers
  "plays chess" at Silver, and `othello-gpt` (MIT) covers a board-game world-model at Platinum.
- Corpora sizes are a **free knob** (trim/extend the book list) — `great_library` scales up to fill the dream tape.
