#!/usr/bin/env python3
"""Assemble the self-contained storyteller.html.

Inlines: emscripten single-file JS glue (WASM already base64 inside it),
the llama2.c stories260K checkpoint (.bin), and the tok512 tokenizer (.bin),
all as base64. Zero runtime network fetches; works over file:// and http://.
"""
import base64
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[3]
BUILD = ROOT / "payloads" / "storyteller" / "build"
DL = ROOT / "payloads" / "built" / "stories260K_dl" / "stories260K"
DIST = ROOT / "payloads" / "storyteller" / "dist"
DIST.mkdir(parents=True, exist_ok=True)

js = (BUILD / "storyteller.js").read_text()
model_b64 = base64.b64encode((DL / "stories260K.bin").read_bytes()).decode()
tok_b64 = base64.b64encode((DL / "tok512.bin").read_bytes()).decode()

HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>A Cassette That Writes Stories</title>
<style>
  :root {
    --bg:#1a1614; --panel:#231d1a; --ink:#f2e9df; --dim:#a99a8c;
    --accent:#d9a441; --tape:#3a2f29; --line:#41352e;
  }
  * { box-sizing:border-box; }
  body {
    margin:0; background:var(--bg); color:var(--ink);
    font-family:"Iowan Old Style","Palatino Linotype",Palatino,Georgia,serif;
    line-height:1.6; padding:2rem 1rem; min-height:100vh;
  }
  .wrap { max-width:680px; margin:0 auto; }
  header { text-align:center; margin-bottom:1.5rem; }
  .reel { font-size:1.7rem; letter-spacing:.18em; color:var(--accent);
    font-family:"Courier New",monospace; text-transform:uppercase; }
  h1 { font-size:2rem; margin:.4rem 0 .2rem; font-weight:600; }
  .sub { color:var(--dim); font-size:.95rem; font-style:italic; }
  .panel {
    background:var(--panel); border:1px solid var(--line);
    border-radius:10px; padding:1.25rem; margin-top:1.25rem;
    box-shadow:0 10px 30px rgba(0,0,0,.4);
  }
  label { display:block; font-size:.82rem; color:var(--dim);
    text-transform:uppercase; letter-spacing:.08em; margin-bottom:.35rem; }
  input[type=text] {
    width:100%; padding:.7rem .8rem; font-size:1.05rem; font-family:inherit;
    background:var(--tape); color:var(--ink);
    border:1px solid var(--line); border-radius:7px;
  }
  input[type=text]:focus { outline:none; border-color:var(--accent); }
  .controls { display:flex; gap:1rem; align-items:flex-end;
    margin-top:1rem; flex-wrap:wrap; }
  .slider-box { flex:1; min-width:200px; }
  input[type=range] { width:100%; accent-color:var(--accent); }
  .temp-val { color:var(--accent); font-family:"Courier New",monospace; }
  button {
    padding:.7rem 1.6rem; font-size:1.05rem; font-family:inherit; cursor:pointer;
    background:var(--accent); color:#1a1614; border:none; border-radius:7px;
    font-weight:600; letter-spacing:.03em;
  }
  button:disabled { opacity:.5; cursor:wait; }
  #story {
    margin-top:1.25rem; padding:1.1rem 1.2rem; min-height:8rem;
    background:#15110f; border:1px solid var(--line); border-radius:8px;
    white-space:pre-wrap; font-size:1.12rem; line-height:1.7;
  }
  #story .cursor { color:var(--accent); animation:blink 1s steps(2) infinite; }
  @keyframes blink { 50% { opacity:0; } }
  .status { color:var(--dim); font-size:.85rem; margin-top:.6rem;
    font-family:"Courier New",monospace; min-height:1.2em; }
  footer { margin-top:2rem; color:var(--dim); font-size:.74rem;
    text-align:center; line-height:1.5; }
  footer a { color:var(--dim); }
</style>
</head>
<body>
<div class="wrap">
  <header>
    <div class="reel">&#9678;&nbsp;&nbsp;&#9678;</div>
    <h1>A Cassette That Writes Stories</h1>
    <div class="sub">A tiny language model, decoded from magnetic tape and run in your browser.</div>
  </header>

  <div class="panel">
    <label for="prompt">Begin the story&hellip;</label>
    <input type="text" id="prompt" value="Once upon a time" autocomplete="off">
    <div class="controls">
      <div class="slider-box">
        <label for="temp">Imagination (temperature) &mdash; <span class="temp-val" id="tval">0.8</span></label>
        <input type="range" id="temp" min="0" max="1.4" step="0.05" value="0.8">
      </div>
      <button id="go" disabled>Loading&hellip;</button>
    </div>
    <div id="story"><span class="cursor">&#9614;</span></div>
    <div class="status" id="status">Decoding model from tape&hellip;</div>
  </div>

  <footer>
    stories260K &mdash; a 260K-parameter Llama-2 trained on TinyStories
    (karpathy/tinyllamas, MIT). Inference engine: llama2.c (Andrej Karpathy, MIT),
    compiled to WebAssembly. Everything &mdash; the weights, the tokenizer, and the
    runtime &mdash; is embedded in this single HTML file with zero network fetches.
    Part of the <strong>cassette-ai</strong> project.
  </footer>
</div>

<script>
const MODEL_B64 = "__MODEL_B64__";
const TOK_B64   = "__TOK_B64__";

function b64ToBytes(b64) {
  const bin = atob(b64);
  const out = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
  return out;
}

__GLUE_JS__

(async function () {
  const statusEl = document.getElementById('status');
  const storyEl  = document.getElementById('story');
  const goEl     = document.getElementById('go');
  const promptEl = document.getElementById('prompt');
  const tempEl   = document.getElementById('temp');
  const tvalEl   = document.getElementById('tval');

  tempEl.addEventListener('input', () => { tvalEl.textContent = (+tempEl.value).toFixed(2); });

  let M, gen;
  try {
    M = await createStoryteller();
    const model = b64ToBytes(MODEL_B64);
    const tok   = b64ToBytes(TOK_B64);
    const mptr = M.ccall('st_alloc', 'number', ['number'], [model.length]);
    M.HEAPU8.set(model, mptr);
    const tptr = M.ccall('st_alloc', 'number', ['number'], [tok.length]);
    M.HEAPU8.set(tok, tptr);
    const vocab = M.ccall('st_init', 'number', ['number', 'number'], [mptr, tptr]);
    gen = M.cwrap('st_generate', 'string',
      ['string', 'number', 'number', 'number', 'number']);
    statusEl.textContent = 'Model ready · vocab ' + vocab +
      ' · ' + M.ccall('st_seq_len', 'number', [], []) + ' tokens max';
    goEl.disabled = false;
    goEl.textContent = 'Write';
  } catch (e) {
    statusEl.textContent = 'Failed to load model: ' + e;
    return;
  }

  function write() {
    goEl.disabled = true;
    storyEl.innerHTML = '<span class="cursor">▖</span>';
    statusEl.textContent = 'Spinning the reels…';
    const prompt = promptEl.value;
    const temp = +tempEl.value;
    const seed = (Date.now() & 0xffffffff) >>> 0;
    // run on next frame so the UI repaints to "spinning" first
    setTimeout(() => {
      const t0 = performance.now();
      let text;
      try {
        text = gen(prompt, 256, temp, 0.9, seed);
      } catch (e) {
        statusEl.textContent = 'Generation error: ' + e;
        goEl.disabled = false;
        return;
      }
      const dt = (performance.now() - t0) / 1000;
      // simple typewriter reveal
      storyEl.textContent = '';
      let i = 0;
      const words = text.length;
      function step() {
        if (i < text.length) {
          const chunk = Math.max(1, Math.floor(text.length / 180));
          storyEl.textContent = text.slice(0, i + chunk);
          i += chunk;
          requestAnimationFrame(step);
        } else {
          storyEl.textContent = text;
          const tokGuess = text.trim().split(/\\s+/).length;
          statusEl.textContent = 'Done · ~' + tokGuess + ' words in ' +
            dt.toFixed(2) + 's';
          goEl.disabled = false;
        }
      }
      step();
    }, 30);
  }

  goEl.addEventListener('click', write);
  promptEl.addEventListener('keydown', (e) => { if (e.key === 'Enter') write(); });
})();
</script>
</body>
</html>
"""

html = (HTML
        .replace("__GLUE_JS__", js)
        .replace("__MODEL_B64__", model_b64)
        .replace("__TOK_B64__", tok_b64))

out = DIST / "storyteller.html"
out.write_text(html)
print(f"wrote {out} ({len(html.encode()):,} bytes)")
