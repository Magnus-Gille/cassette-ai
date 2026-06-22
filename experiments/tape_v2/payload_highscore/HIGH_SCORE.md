# 🎚️ Cassette-AI High-Score Chase — the payload leaderboard

> The game: as the achievable **bitrate climbs**, what's the most *impressive permissively-licensed thing* you
> can fit on one cassette? Tiers are named after real tape formulations (Type I Normal → Type IV Metal).
> Every headline below is **verified or probable-permissive** with a real, measured/derived on-tape size.
> **The chase is gated on hardware, not payloads** — Bronze + Silver run on the acoustic loop **today**;
> everything from Gold up rides the electrical line-in / stereo climb (UCA222, Jun 18).

| medal | MB | cassette config | now? | headline | wow |
|---|---|---|---|---|---|
| 🥉 Type I — **Bronze** | 0.6–2.0 | C60 mono acoustic @5.8 kbps | ✅ now | **TIC-80** fantasy console (MIT) | 5 |
| 🥈 Type I — **Silver** | 1.0–4.4 | C90 mono acoustic @5.8 kbps | ✅ now | **Human-Knowledge Starter Pack** (18 PD works) | 5 |
| 🏅 Type II — **Gold** | 6–9 | C120 mono / C90 stereo electrical @6.5 kbps | 🔌 climb | **delphi TinyStories-12.8M** — writes stories | 5 |
| 💿 Type II — **Platinum** | 11–14 | C90 stereo electrical @10 kbps | 🔌 climb | **Chess-GPT 25M** — out-plays an engine | 5 |
| 💎 Type IV — **Diamond** | 16–20 | C90 stereo electrical @15 kbps | 🔌 climb | **The Great Library** — 58 PD classics | 5 |
| 🔥 Type IV — **LEGENDARY** | 20–40 | C120 stereo electrical @10–20 kbps | 🌙 dream | *(unfilled at model quality — corpus only)* | — |

---

## 🥉 Bronze — Type I Normal · 0.6–2.0 MB · acoustic, **playable today**
**★ TIC-80 fantasy console** — `MIT` (engine + bundled demo carts), **~1.6 MB on tape**, zero copyleft caveat.
*Pop in the tape and a complete retro computer boots — code/sprite/map/sound/music editors + a player running
Lua/JS/Python/Fennel/Wren carts. A cassette that **is a games console**.* → github.com/nesbox/TIC-80
Runners-up:
- **DDPM-MNIST** (`MIT` ✓) ~2.0 MB — a real diffusion U-Net that *paints* handwritten digits from noise. "A cassette that runs a diffusion model."
- **learned-planner** Sokoban DRC(3,3) (`Apache-2.0` ✓ — best license in the batch) ~1.3 MB int8 — an RNN that demonstrably *plans ahead* (ICML 2024). "A cassette that **thinks**." Small enough to pair with another payload on one side.
- **Octo CHIP-8 IDE** (MIT) + the **101-game CHIP-8 Archive** (`CC0`) ~0.6 MB — a whole public-domain game library on one tape.

## 🥈 Silver — Type I Normal · 1.0–4.4 MB · acoustic, **today**
**★ Human Knowledge Starter Pack** — 18 foundational works (Darwin, Einstein, Plato, Aurelius, Sun Tzu, the
Constitution, Shakespeare, Frankenstein…) — **Public Domain** ✓, **measured 12.33 MB raw → 3.34 MB `xz -9e`**.
*An editorial artifact, not a dump — "the seed of civilization on a cassette."*  → gutenberg.org
Runners-up (all PD, measured):
- **Complete Works of Shakespeare** — 1.68 MB on tape (best wow/size of any single corpus; fits a C60).
- **King James Bible** — 1.06 MB. **Complete Sherlock Holmes** (4 novels + 56 stories) — 1.07 MB.

## 🏅 Gold — Type II Chrome · 6–9 MB · **the electrical climb begins**
**★ delphi-suite/v0-llama2-12.8m** (TinyStories Llama-2, 4096-vocab) **int4 ~6.7 MB** — `MIT` (HF tag; code repo
Apache-2.0 → permissive either way, *probable*).
*14.56M params, but the tiny 4096 SentencePiece vocab means embeddings are only 11% — so it **fits** where
50K-vocab models can't. Runs on a ~20 KB llama2.c engine. **A cassette that writes coherent stories.***
→ huggingface.co/delphi-suite/v0-llama2-12.8m
Runners-up:
- **Piper TTS x_low voice** (`MIT` weights ✓; espeak-ng frontend GPLv3 → ship source side B) ~7 MB — natural VITS speech. "A cassette that **talks back**."
- **v86 + Buildroot Linux** (v86 `BSD-2` ✓; Linux GPL-2.0 → source side B) ~5.5 MB xz — "A cassette that **boots a full 32-bit Linux** to a shell."

## 💿 Platinum — Type II Chrome · 11–14 MB · electrical @10 kbps
**★ adamkarvonen Chess-GPT** (lichess 8-layer, 25M) **int4 ~12.5 MB** — `MIT` (training repo ✓; weights repo
metadata empty → *probable*, confirm with author before ship).
*Real: 103 MB fp32 → 25.0M params → int4 12.5 MB (32-char chess vocab <1 KB). It actually **plays**: 99.6%
legal moves, beats Stockfish at low levels. **A cassette that out-plays a chess engine.***
→ huggingface.co/adamkarvonen/chess_llms
Runners-up:
- **delphi-suite/v0-llama2-25.6m** int4 ~11.7 MB (MIT probable) — better prose than the 12.8m. "Fill more tape, get better stories."
- **Othello-GPT** (~25.2M, MIT probable) int4 ~12.5 MB — the famous "it has a world model" model; pairs with Chess-GPT as a board-game **world-model double feature**.
- **Piper medium voice** ~14 MB — human-sounding speech, a clear step up.

## 💎 Diamond — Type IV Metal · 16–20 MB · electrical @15 kbps (top of the verified climb)
**★ The Great Library** — 58 public-domain classics (Austen, Dickens, Tolstoy, Dostoevsky, Melville, Twain,
Wilde, Shelley, Stoker, Doyle, Carroll, KJV, Shakespeare…) — **Public Domain** ✓, **measured 60.06 MB raw →
15.84 MB `xz -9e`**. *"The Library of Alexandria on one cassette."*  Size is a free knob — scale it to fill
8–20 MB and beyond. → gutenberg.org
Runners-up: **TinyCode-python** int4 ~17 MB (MIT probable) — "a tape that writes code"; **DDPM-CIFAR10** int4 ~18 MB (Apache ✓) — fits but int4 wrecks color-diffusion quality (near-miss).

## 🔥 LEGENDARY — the 20–40 MB dream (not yet demonstrated)
The electrical path must first prove out at these rates. Currently **unfilled at model quality**: SmolLM2-135M-
Instruct ("a cassette you can **chat** with", Apache-2.0 ✓) needs int2/ternary QAT to fit (~34 MB, no such
checkpoint exists); Q-bert ChessGPT 87.5M only fits at int3 (~33 MB, quality risk); TunesFormer (~45 MB) is
just over. **Only the scalable Great Library corpus reliably reaches the dream tape today.**

---

## 🎯 Gaps = your acquisition targets (high-wow concepts blocked only on license/verification)
- **~3.5 MB "plays Othello"** — `othello-gpt-7M` is perfectly sized but has **no license** anywhere. Chase a licensed 7M Othello reproduction.
- **16–20 MB *model* slot** — only corpora + TinyCode fit cleanly; no verified-permissive story/chat model lands here (roneneldan/TinyStories-8M has **no license**; vocab-trimming it is a build step).
- **20–40 MB dream** — no clean-quality permissive payload exists; needs an int2/ternary QAT checkpoint of SmolLM2-135M or similar.
- **"Plays Atari"** (Decision-Transformer) — **no license** + heavy ALE runtime. Chase a permissive minigrid/Atari DT.
- **"Plays Quake"** (Qwasm + LibreQuake) — asset license/size **unverified** (original Quake .pak is NOT free, must never ship). Needs a real LibreQuake pull.
- **Color image-gen** and **music-gen** at quality — `DDPM-CIFAR10` and `skytnt/midi-model` are clean-licensed but an order of magnitude too big at usable quant.

## ⬇️ Top 5 to fetch + prep next (verified, highest value-per-effort)
1. **delphi-12.8m** int4 (~6.7 MB) — the Gold story headline; grab the 25.6m sibling for Platinum. *(Highest-value model.)*
2. **adamkarvonen chess_llms** 25M int4 (~12.5 MB) — the Platinum headline; confirm MIT with the author.
3. **The Great Library** — assemble the 58-book pre-1928 PD set + lzma (Diamond, ~16 MB; scales to the dream). *Zero license risk, size is a free knob.*
4. **learned-planner** DRC(3,3) (~1.3 MB, Apache ✓) — the cleanest license in the batch; novel "a cassette that plans."
5. **TIC-80** + curated MIT carts (~1.6 MB) — the Bronze headline; trivial to bundle, playable on the acoustic loop **now**.

## 🧠 The lesson the cassette enforces
**Small vocab + task-specialized beats big vocab + general, every time, on bytes-per-coherence.** delphi-12.8m
(14.5M, 4096-vocab) writes prose and fits; GPT-2-small (124M, 50K-vocab) babbles *and* won't even fit at int4.
The tape is a brutal, honest editor: it rewards models whose output alphabet is small (stories, chess, code).

*(Full verified candidate data: `chase_full.json`. Sizes are int4/int8 quant or measured `xz -9e` of the
runnable bundle; licenses verified on the Hugging Face hub / Project Gutenberg where marked ✓.)*
