# Candidate tape payloads

Staging area for the **software artifacts we want to store on a cassette** — the things a
decoded tape would actually contain. Sources are mirrored locally so the encode→tape→decode
loop has a stable, offline-pinned set of inputs.

**Everything here is downloaded by `fetch_payloads.sh` and is gitignored** (large binaries,
re-fetchable from the upstreams below). Run:

```bash
bash payloads/fetch_payloads.sh          # fetch everything
bash payloads/fetch_payloads.sh llm      # only the tape-fitting + over-budget models
bash payloads/fetch_payloads.sh doom     # only the DOOM payload
```

The script is idempotent (skips files already present) and never aborts the whole run on a
single source failure — it logs per-item OK/FAIL to `payloads/fetch_manifest.txt`.

---

## A. LLM models that FIT a cassette (`llm_tape_fit/`)

Byte-exact budget on this project's measured link: ~70 KB (C60) · ~106 KB (C90) · ~141 KB (C120),
up to ~2× with soft-FEC/low-PAPR headroom. A **small vocab/output alphabet** is what makes a
model fit (embedding tables dominate tiny models).

| Dir | Model | int4 size | License | Source |
|---|---|---|---|---|
| `stories260K/` | karpathy TinyStories, 512-vocab — ✅ runs, writes stories | 150 KB int4 / **1.07 MB FP32** (no-quant option at the new rates) | **MIT** | `karpathy/tinyllamas` (subfolder `stories260K/`) |
| `mnist/` | ONNX-zoo handwritten-digit classifier — ✅ runs | 25.5 KB | **Apache-2.0** (spike-corrected, was misfiled MIT) | onnx/models `validated/.../mnist/model/mnist-12.onnx` |
| `delphi-v0-mamba-200k/` | TinyStories Mamba (state-space) | 479 KB | ⚠️ **none declared** | `delphi-suite/v0-mamba-200k` |
| `delphi-v0-llama2-100k/` | TinyStories llama2 | 147 KB + tokenizer | **MIT** ⚠️ HF-metadata-only, no LICENSE file | `delphi-suite/v0-llama2-100k` |
| `delphi-stories-llama2-50k/` | TinyStories llama2 (very weak) | **~178 KB incl. tokenizer** (spike-corrected, was ~25 KB) | **Apache-2.0** ⚠️ HF-metadata-only | `delphi-suite/stories-llama2-50k` |

> Spike notes (2026-06-11, `~/mimir/research/cassette-ai/2026-06-11-tiny-permissive-llms.md`):
> int4 on sub-1M models is untested and may degrade quality — **FP16/FP32 is safer and now affordable**
> at the 4910/5791 rates. chess-gpt is really **6.58M params (~3.3 MB int4)** — the first
> qualitatively-beyond-babble payload; fits a whole C90 at 5791, or a C120.

## B. DOOM payload (`doom/`)

The "this cassette contains DOOM — engine and all" artifact. Engine→WASM (~150–250 KB
compressed) + a minimal WAD ⇒ ~250–370 KB total ⇒ fits one C90 side at the proven 934 bps.

| Item | What | License | Source |
|---|---|---|---|
| `doomgeneric/` | portable DOOM engine, easy WASM target | **GPL-2.0** | github.com/ozkl/doomgeneric |
| `freedoom-0.13.0.zip` | free IWAD (freedoom1.wad + freedoom2.wad) | **BSD** | freedoom/freedoom release v0.13.0 |

> `miniwad` (the ~80–120 KB minimal IWAD floated in STATUS.md) has no stable canonical
> download — Freedoom is the fetchable WAD here; a hand-trimmed minimal IWAD is a build step,
> not a download.

## C. Over-budget model candidates (`llm_over_budget/`)

Researched in MODELS.md — don't fit one cassette today, kept as future / QAT-ternary /
longer-tape candidates.

| Dir | Model | License | Source |
|---|---|---|---|
| `chess-gpt-4.5M/` | plays chess (PGN), int4 ~3.2 MB | **MIT** | `derickio/chess-gpt-4.5M` |
| `ddpm-mnist/` | diffusion that *generates* digits | **MIT** | `1aurent/ddpm-mnist` |
| `shakespeare-rnn/` | char-level Shakespeare | **MIT** | `gnsepili/shakespeare-rnn` |
| `folk-rnn/` | composes Irish tunes in ABC | **MIT** | github.com/IraKorshunova/folk-rnn |

## License watch-outs (do NOT ship in a product)
- `roneneldan/TinyStories-*` model repos — **NO license declared**.
- `fxmarty/resnet-tiny-mnist` — **GPL-3.0** (copyleft).
- `delphi-suite/v0-mamba-200k` — **none declared** (research use only).
- DOOM engine is **GPL-2.0**: commercially distributable, but source must accompany the binary
  (on-brand: binary side A, source side B).
