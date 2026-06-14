# Tiny models for cassette-AI — candidates, sizes, licenses

Cassette byte-exact budget (this project's measured link, ~20 net B/s):
**~70 KB (C60) · ~106 KB (C90) · ~141 KB (C120)**, up to ~2× with the soft-FEC/low-PAPR
headroom. The binding rule across all of these: **a small VOCAB/output alphabet is what
makes a model fit** — embedding tables dominate tiny models.

## Built / verified here
| Model | What | Size (int4) | Fits | License | Status |
|---|---|---|---|---|---|
| **stories260K** (karpathy) | TinyStories text gen, 512-vocab | **150 KB** (129 KB gz) | C120 today / C90 headroom | **MIT** | ✅ runs (`chat.py`), writes stories |
| **mnist-12.onnx** (onnx zoo) | classifies handwritten digits | **25.5 KB** | any tape | **MIT** | ✅ runs (verified: bar→1, seven→7) |
| **delphi v0-mamba-200k** | TinyStories, Mamba (state-space) | 479 KB | ✗ over one cassette | ⚠️ **none declared** | downloaded; 4096-vocab+64 KB tok bloat |

To re-fetch weights (gitignored): `stories260K.pt/.bin tok512.bin/.model` from
`huggingface.co/karpathy/tinyllamas/stories260K`; `mamba_pytorch_model.bin` etc. from
`huggingface.co/delphi-suite/v0-mamba-200k`.

## Other candidates (researched, with licenses)
**Fit a cassette (text, tiny-vocab):**
- `delphi-suite/v0-llama2-100k` — TinyStories llama, int4 147 KB — **MIT**
- `delphi-suite/stories-llama2-50k` — int4 ~25 KB (very weak) — **Apache-2.0**

**Cool but over one cassette (need longer tape / QAT-ternary / vocab reduction):**
- `derickio/chess-gpt-4.5M` — plays chess (PGN) — **MIT** — int4 3.2 MB
- `gnsepili/shakespeare-rnn` — char-level Shakespeare — **MIT** — 14.5 MB
- `1aurent/ddpm-mnist` — diffusion that *generates* digits — **MIT** — ~few MB
- `folk-rnn` (github.com/IraKorshunova) — composes Irish tunes in ABC — **MIT**
- `sander-wood/tunesformer` — great ABC music — **MIT** — 1.4 GB (way out)

**Watch out:** `roneneldan/TinyStories-*` model repos = NO license declared;
`fxmarty/resnet-tiny-mnist` = GPL-3.0 (copyleft — avoid for products).

## Cross-modal pattern
- Easiest genuinely-useful fit = a **classifier** (MNIST 26 KB).
- Generative things that fit = **tiny char/small-vocab models** (stories260K-style).
- Images / music / schematics: hosted models blow the budget — the cassette path is
  **train-your-own-tiny** (char-ABC for music, small VAE/DDPM for 28×28 images, char-level
  on SPICE netlists for "schematics"), or **QAT-ternary** to ~double what fits.

## TinyStories: is it updated?
Original tiny models unchanged since 2023. Newer DATA: **TinyStories V2**
(`noanabeshima/TinyStoriesV2`, GPT-4-only) and **`karpathy/tinystories-gpt4-clean`**
(Feb 2026), both CDLA-Sharing-1.0; plus a multilingual variant (Apache).
