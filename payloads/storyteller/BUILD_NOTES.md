# Storyteller — "A Cassette That Writes Stories"

A self-contained HTML artifact: a tiny generative LLM (TinyStories) that runs in the
browser via WebAssembly. Same decode-and-run pattern as the DOOM tape — one HTML file,
**zero runtime network fetches**, works over `file://` AND `http://`.

## Artifact

- **`dist/storyteller.html`** — the shippable, fully self-contained artifact.
  Everything inline as base64: the WASM runtime (llama2.c compiled with emscripten,
  single-file JS), the model checkpoint, and the tokenizer.

## Model chosen: `stories260K` (Karpathy, MIT)

- **Why this one:** of the tape-resident tinies it is **natively in llama2.c export
  format** — the FP32 `stories260K.bin` + `tok512.bin` are on disk, so llama2.c's
  `run.c` reads them directly with **no dequant or HF→llama2.c export step**. That makes
  it the most robust, guaranteed-correct choice (the int4 NPZ bundles and the HF-format
  delphi models would need a custom dequant/export path inside the WASM). It is MIT,
  comfortably fits one C90 side even at FP32, and generates coherent TinyStories prose
  (verified below).
- Arch: dim=64, layers=5, heads=8, kv=4, vocab=512, seq_len=512 (~260K params).
- Source: `karpathy/tinyllamas` HF repo, subfolder `stories260K/`. License **MIT**
  (HF cardData + tag; llama2.c project is MIT).
- Tradeoff noted: stories260K is the "babble tier" of the catalogue — coherent kids'-story
  English but simple. `delphi-llama2-100k` (vocab 4096, MIT) is marginally more varied but
  ships only in HF format here (needs an export step); `delphi-llama2-12.8m` is the truly
  coherent one but at 7.31 MB it overflows a C90 side. stories260K is the best
  drop-in-runnable fit for a single-side tape demo.

## Runtime build (llama2.c → WASM)

- Source: `github.com/karpathy/llama2.c` (`run.c`, MIT) cloned to `tools/llama2.c/`.
- `build/storyteller.c` copies run.c's pure-compute core (forward pass, BPE tokenizer,
  sampler) **verbatim**, and replaces the two file-I/O loaders (mmap checkpoint, fopen
  tokenizer) with **in-memory loaders** so JS hands in the model/tokenizer bytes via the
  WASM heap. Exposes one entry point: `st_init(model_ptr, tok_ptr)` then
  `st_generate(prompt, steps, temperature, topp, seed)` → returns the decoded UTF-8 story.
- Compiled with emscripten:
  ```
  emcc storyteller.c -O3 -ffast-math -o storyteller.js \
    -s MODULARIZE=1 -s EXPORT_NAME=createStoryteller -s SINGLE_FILE=1 \
    -s EXPORTED_FUNCTIONS='[_st_init,_st_generate,_st_alloc,_st_free,_st_seq_len,_malloc,_free]' \
    -s EXPORTED_RUNTIME_METHODS='[ccall,cwrap,HEAPU8,...]' \
    -s ALLOW_MEMORY_GROWTH=1 -s INITIAL_MEMORY=16MB -s ENVIRONMENT=web
  ```
  `SINGLE_FILE=1` inlines the WASM as base64 inside the JS → 72 KB glue, no `.wasm` file.
- `build/assemble_html.py` inlines the glue JS + base64(model.bin) + base64(tok512.bin)
  into the final HTML. The UI: prompt box, temperature slider, "Write" button, typewriter
  reveal of the generated story.

### Reproduce
```
git clone --depth 1 https://github.com/karpathy/llama2.c tools/llama2.c
# model+tokenizer: payloads/built/stories260K/build_stories260K.sh fetches them
source tools/emsdk/emsdk_env.sh
emcc payloads/storyteller/build/storyteller.c -O3 -ffast-math \
  -o payloads/storyteller/build/storyteller.js -s MODULARIZE=1 \
  -s EXPORT_NAME=createStoryteller -s SINGLE_FILE=1 ... (see above)
python3 payloads/storyteller/build/assemble_html.py
```

## Sizes

| measure | bytes | MB |
|---|---|---|
| raw `storyteller.html` | 1,495,948 | **1.43 MB** |
| `xz -9` compressed | 1,020,396 | **0.97 MB** |

**Tape tier fit:** xz 0.97 MB and even the raw 1.43 MB fit **one C90 side (1.86 MB)**.
The xz payload (0.97 MB) also fits **one C60 side (1.24 MB)**. Trivially within a whole
C90 (3.73 MB).

## Verification (proven, not assumed)

- Served over `python3 -m http.server 8813`, loaded in Playwright (Chromium).
- **Zero failed network requests** except `favicon.ico` 404 (expected). No runtime fetch
  of any `.wasm`, `.js`, model, or tokenizer file — `performance.getEntriesByType('resource')`
  was empty; everything came from the inline base64.
- Model loaded in-browser: `st_init` returned vocab 512, seq_len 512; button enabled.
- Clicked "Write" with prompt "Once upon a time", temperature 0.8 → generated a coherent
  129-word TinyStory in **0.09 s**. Sample output:

  > Once upon a time, there was a little girl named Lily. She loved to play with her
  > dolls and pretend they were pictures. One day, Lily saw a big dog feeling delicious.
  > She wanted to play with it, but she couldn't find it. Lily didn't want to play with
  > the dog, but her mom said, "No, it's too hot. It's something else to go." Lily looked
  > at her mom and said, "Mommy, let's go to the park." …

- Screenshot: `dist/.playwright-mcp/storyteller_verify.png` (Playwright output dir).

## License

- **llama2.c** (inference engine): MIT — Andrej Karpathy, github.com/karpathy/llama2.c.
- **stories260K** (weights + tokenizer): MIT — karpathy/tinyllamas (TinyStories).
- Both surfaced in the artifact footer. The build copies run.c's algorithm under MIT.
