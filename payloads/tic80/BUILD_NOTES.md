# TIC-80 on a Cassette — self-contained HTML artifact

A whole fantasy console, decoded off tape and running in one HTML file.
Same decode-and-run pattern as the DOOM tape: one file that just runs, **zero
runtime network fetches**, works over `file://` AND `http://`.

## Deliverable

- **`dist/tic80_console.html`** — self-contained. TIC-80 WASM engine + JS loader
  + 16 MIT demo carts, all inline (base64). Boots the console straight into a
  cart; a dropdown + cart grid let you switch carts (each switch reloads the
  page so the Emscripten module starts clean).
- **`build_html.py`** — regenerates the HTML from the tracked source bundle.
- **`verify.mjs`** — standalone Playwright verification (its own isolated
  Chromium).

## Sizes

| measure | bytes | MB |
|---|---|---|
| raw HTML (`tic80_console.html`) | 8,014,302 | **8.014** |
| `xz -9` of the HTML | 2,020,532 | **2.021** |

Component floor: `tic80.wasm` is 5.72 MB raw (the dominant payload); base64
inflation (~33%) is why the single-file HTML xz's to ~2.0 MB even though the
raw `bundle.tar.xz` (binary, not base64) is 1.50 MB.

### Tape tier fit (xz size 2.02 MB)

| tier | budget | fit |
|---|---|---|
| C60 side | 1.24 MB | over |
| C90 side | 1.86 MB | over (by ~0.16 MB) |
| **whole C90** | 3.73 MB | **FITS** |

The self-contained HTML rides the **whole-C90** tier. (The 1.50 MB figure in
`BUILT_PAYLOADS.md` is the raw `bundle.tar.xz`, a different artifact — binary
wasm compressed directly, no base64 wrapper.)

## Engine

- **TIC-80 fantasy console**, official prebuilt HTML/WASM release **v1.1.2837
  (be42d6f)** — `tic80.wasm` (5,716,041 B) + `tic80.js` loader (240,206 B).
  Not built from source; the official `tic80-v1.1-html.zip` release was used.
- Source: `https://github.com/nesbox/TIC-80` releases.

### How it boots a cart with zero network

The TIC-80 Emscripten entry (`emsStart`, `src/system/sdl/main.c`) only boots a
cart when `argv[1]` ends in `.tic`, and then *fetches* that URL via
`FS.createPreloadedFile` (XHR). So the artifact:

1. wraps each source cart into a real **`.tic` cartridge** — `CODE` chunk
   (type 5) for carts < 64 KB, `CODE_ZIP` (type 16, zlib) for larger ones
   (only `quest.lua`, 98.9 KB → 14.6 KB);
2. installs a small **`XMLHttpRequest` shim** that returns the embedded
   cartridge bytes for the `cart.tic` URL — the engine's own fetch never hits
   the wire;
3. boots with `Module.arguments=["cart.tic"]` and `Module.wasmBinary=<bytes>`
   (so `tic80.wasm` is never fetched either).

## Carts bundled (16, all MIT, from the TIC-80 repo `/demos`)

| cart | title | author | lang |
|---|---|---|---|
| tetris.lua | tetris | AlKau (alkau.itch.io) | lua |
| quest.lua | QUEST FOR GLORY | Deck (deck.itch.io) | lua |
| car.lua | ModelRenderer | FlamingPandas | lua |
| p3d.lua | 3D demo | Filippo | lua |
| fire.lua | fire | Filippo | lua |
| palette.lua | palette demo | Nesbox | lua |
| bpp.lua | Blit segment demo | ddelemeny | lua |
| music.lua | Music Demo | Tromino | lua |
| sfx.lua | sfx | Nesbox | lua |
| font.lua | font | Nesbox | lua |
| luademo.lua | Lua template | (template) | lua |
| fenneldemo.fnl | Fennel template | (template) | fennel |
| jsdemo.js | JS template | (template) | js |
| wrendemo.wren | Wren template | (template) | wren |
| rubydemo.rb | Ruby template | (template) | ruby |
| schemedemo.scm | Scheme template | (template) | scheme |

The lead cart on load is **tetris**; the four language-template carts
(lua/fennel/js/wren/ruby/scheme) double as a showcase of TIC-80's language range.

## License

- **Engine:** MIT — TIC-80, © 2017 Vadim Grigoruk & contributors
  (`nesbox/TIC-80/LICENSE`). The MIT text is shipped verbatim inside the HTML
  (the "License & credits" panel).
- **Carts:** MIT — all from the TIC-80 repo's `/demos` directory, covered by the
  repo-wide MIT license. Per-cart authors are listed above and in the HTML.

## Verification (isolated Chromium, served over `python3 -m http.server 8811`)

`verify.mjs` boots tetris (via the play button) plus fire / p3d / palette (via
hash deep-link auto-boot) and checks every cart:

- **Zero external network fetches.** The only request logged is the HTML file
  itself — no `tic80.wasm`, no `tic80.js`, no `cart.tic`, nothing. (`emsStart`'s
  cart fetch is intercepted by the XHR shim before it reaches the wire.)
- **Zero failed requests, zero console errors.** (Note: the lone `unwind`
  pageerror seen during interactive testing is Emscripten's normal main-loop
  yield, not a fault; it does not appear as a console error in the headless run.)
- **The cart renders and animates.** Canvas resizes to the engine's full
  resolution and fills with the SWEETIE-16 palette (non-black = 100% of pixels);
  frames sampled 0.5–0.7 s apart differ → the cart is running, not a static
  splash.

Concrete evidence captured to `dist/`:

- `verify_p3d_late.png` — the **"3D demo" cart running**: an animated, rotating
  3D point-cloud of colored cubes in full 16-color palette, well past the boot
  animation. `animating-after-boot=true`.
- A standalone earlier check showed `fire.lua` rendering the "! FIRE !" screen
  with three animated flame sprites, and `quest.lua` rendering its "score:0"
  HUD — confirming both plain `CODE` and `CODE_ZIP` carts execute.

Summary line from `verify.mjs`:

```
tetris_default: rendered=true extFetches=0 failed=0
fire:           rendered=true extFetches=0 failed=0
p3d:            rendered=true extFetches=0 failed=0
palette:        rendered=true extFetches=0 failed=0
```

## Regenerate

```
python3 payloads/tic80/build_html.py          # -> dist/tic80_console.html
cd payloads/tic80/dist && python3 -m http.server 8811 &
node payloads/tic80/verify.mjs                # isolated Chromium verification
```
