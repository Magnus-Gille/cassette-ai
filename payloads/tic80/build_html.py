#!/usr/bin/env python3
"""Assemble a single self-contained "TIC-80 fantasy console on a cassette" HTML.

Inlines the official TIC-80 WASM engine + JS loader + bundled MIT demo carts as
base64 (ZERO runtime network fetches). Works over file:// AND http://.

How the cart is fed to the engine, zero-network
------------------------------------------------
The TIC-80 Emscripten entry (`emsStart`, src/system/sdl/main.c) only boots a
cart if argv[1] ends in ".tic". It then *fetches* that URL via
FS.createPreloadedFile (XHR). So we:
  1. wrap each source cart (.lua/.js/.fnl/...) into a real .tic cartridge
     (CODE chunk type 5, or CODE_ZIP type 16 / zlib for carts > 64 KB);
  2. install an XMLHttpRequest shim that returns the *embedded* cart bytes for
     the "cart.tic" URL instead of going to the network;
  3. boot with Module.arguments = ["cart.tic"] and Module.wasmBinary = <bytes>.
Switching carts reloads the page (clean Emscripten module each time) with the
chosen cart in the URL hash; on load it auto-boots that cart.

Source assets: payloads/built/tic80/{engine,carts,LICENSE}
Output:        payloads/tic80/dist/tic80_console.html
"""
import base64
import json
import os
import re
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "..", "built", "tic80")
ENGINE = os.path.join(SRC, "engine")
CARTS = os.path.join(SRC, "carts")
OUT = os.path.join(HERE, "dist", "tic80_console.html")

CHUNK_CODE = 5
CHUNK_CODE_ZIP = 16


def make_tic(src_bytes):
    """Wrap raw cart source into a minimal .tic cartridge (one code chunk)."""
    if len(src_bytes) < 65536:
        size = len(src_bytes)
        hdr = bytes([CHUNK_CODE, size & 0xFF, (size >> 8) & 0xFF, 0])
        return hdr + src_bytes
    comp = zlib.compress(src_bytes, 9)
    if len(comp) >= 65536:
        raise ValueError("cart too large even compressed")
    hdr = bytes([CHUNK_CODE_ZIP, len(comp) & 0xFF, (len(comp) >> 8) & 0xFF, 0])
    return hdr + comp


# ---- engine ---------------------------------------------------------------
with open(os.path.join(ENGINE, "tic80.js"), encoding="utf-8", errors="replace") as f:
    tic80_js = f.read()
with open(os.path.join(ENGINE, "tic80.wasm"), "rb") as f:
    wasm_b64 = base64.b64encode(f.read()).decode("ascii")

# ---- carts ----------------------------------------------------------------
PREFERRED = [
    "tetris.lua", "quest.lua", "car.lua", "p3d.lua", "fire.lua",
    "palette.lua", "bpp.lua", "music.lua", "sfx.lua", "font.lua",
    "luademo.lua", "fenneldemo.fnl", "jsdemo.js", "wrendemo.wren",
    "rubydemo.rb", "schemedemo.scm",
]


def meta(txt, key):
    m = re.search(r'^\s*(?:--|//|;+|#)\s*' + key + r':\s*(.+)$', txt, re.M | re.I)
    return m.group(1).strip() if m else ""


files = [c for c in PREFERRED if os.path.exists(os.path.join(CARTS, c))]
files += [c for c in sorted(os.listdir(CARTS)) if c not in files]

carts = []
for fn in files:
    p = os.path.join(CARTS, fn)
    if not os.path.isfile(p):
        continue
    with open(p, "rb") as f:
        raw = f.read()
    head = raw[:2000].decode("utf-8", errors="replace")
    carts.append({
        "file": fn,
        "title": meta(head, "title") or fn,
        "author": meta(head, "author") or "unknown",
        "script": meta(head, "script") or fn.rsplit(".", 1)[-1],
        "b64": base64.b64encode(make_tic(raw)).decode("ascii"),
    })

with open(os.path.join(SRC, "LICENSE"), encoding="utf-8", errors="replace") as f:
    license_text = f.read()

HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>TIC-80 on a Cassette &mdash; The Magnetic Vault</title>
<style>
  :root{
    --bg:#0b0d1a; --panel:#15182b; --ink:#e6e7ef; --dim:#8b8fb0;
    --accent:#41a6f6; --accent2:#ffcd75; --line:#2a2e4a;
    --mono:ui-monospace,'SF Mono',Menlo,Consolas,monospace;
  }
  *{box-sizing:border-box}
  html,body{margin:0;height:100%}
  body{
    background:radial-gradient(1200px 600px at 50% -10%, #1b2140 0%, var(--bg) 60%), var(--bg);
    color:var(--ink); font-family:var(--mono); display:flex; min-height:100%;
    flex-direction:column; align-items:center;
  }
  header{width:100%;max-width:960px;padding:22px 20px 8px;text-align:center}
  h1{margin:0;font-size:clamp(20px,4vw,30px);letter-spacing:.5px}
  h1 .tic{color:var(--accent)}
  .sub{color:var(--dim);font-size:12.5px;margin-top:6px;line-height:1.5}
  .wrap{width:100%;max-width:960px;padding:0 20px 28px;flex:1;display:flex;
        flex-direction:column;gap:16px}
  .stage{position:relative;background:#000;border:1px solid var(--line);
    border-radius:10px;overflow:hidden;aspect-ratio:240/136;width:100%;
    box-shadow:0 10px 40px rgba(0,0,0,.5), inset 0 0 0 1px #000;}
  canvas{width:100%;height:100%;display:block;image-rendering:pixelated;background:#1a1c2c}
  #overlay{position:absolute;inset:0;display:flex;flex-direction:column;
    align-items:center;justify-content:center;gap:14px;cursor:pointer;
    background:linear-gradient(180deg,#11142a,#070812);color:var(--ink);
    text-align:center;padding:20px;}
  #overlay .big{font-size:clamp(16px,3vw,22px);font-weight:700}
  #overlay .now{color:var(--accent2);font-size:13px}
  #overlay .hint{color:var(--dim);font-size:11.5px;max-width:520px;line-height:1.5}
  .play-btn{border:1px solid var(--accent);color:var(--accent);background:transparent;
    padding:10px 22px;border-radius:999px;font-family:var(--mono);font-size:14px;
    cursor:pointer;transition:.15s;}
  .play-btn:hover{background:var(--accent);color:#000}
  .bar{display:flex;gap:10px;flex-wrap:wrap;align-items:center}
  .bar label{color:var(--dim);font-size:12px}
  select,button.ctl{font-family:var(--mono);font-size:13px;background:var(--panel);
    color:var(--ink);border:1px solid var(--line);border-radius:7px;padding:8px 12px;cursor:pointer;}
  select{min-width:220px}
  button.ctl:hover{border-color:var(--accent)}
  .carts{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:8px}
  .cart{background:var(--panel);border:1px solid var(--line);border-radius:8px;
    padding:9px 11px;cursor:pointer;transition:.12s;text-align:left;}
  .cart:hover{border-color:var(--accent);transform:translateY(-1px)}
  .cart.active{border-color:var(--accent2);box-shadow:0 0 0 1px var(--accent2)}
  .cart .t{font-size:13px;font-weight:700;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
  .cart .a{font-size:10.5px;color:var(--dim);margin-top:2px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
  .cart .s{font-size:9.5px;color:var(--accent);margin-top:3px;text-transform:uppercase;letter-spacing:.5px}
  details{background:var(--panel);border:1px solid var(--line);border-radius:8px;padding:8px 12px;font-size:11px;color:var(--dim)}
  details summary{cursor:pointer;color:var(--ink);font-size:12px}
  pre{white-space:pre-wrap;font-size:10.5px;color:var(--dim);margin:8px 0 0}
  .keys{font-size:11px;color:var(--dim);line-height:1.6}
  .keys b{color:var(--ink)}
  footer{font-size:10.5px;color:var(--dim);text-align:center;padding:4px 20px 20px;line-height:1.6}
  a{color:var(--accent)}
</style>
</head>
<body>
<header>
  <h1><span class="tic">TIC-80</span> &mdash; a fantasy console on a cassette</h1>
  <div class="sub">The official TIC-80 WebAssembly engine and a shelf of MIT demo
    carts, decoded off magnetic tape and running entirely in your browser.<br>
    No network. No server. One file.</div>
</header>

<div class="wrap">
  <div class="stage">
    <canvas id="canvas" oncontextmenu="event.preventDefault()" tabindex="-1"></canvas>
    <div id="overlay">
      <div class="big">&#9654; INSERT CART</div>
      <div class="now" id="ovNow"></div>
      <button class="play-btn" id="playBtn">CLICK TO BOOT</button>
      <div class="hint">Click to power on the console and run the selected cart.
        Audio and keyboard start on click (browser autoplay rules).</div>
    </div>
  </div>

  <div class="bar">
    <label for="cartsel">CART:</label>
    <select id="cartsel"></select>
    <button class="ctl" id="loadBtn">&#9654; RUN</button>
    <span class="keys" id="status"></span>
  </div>

  <div class="carts" id="cartgrid"></div>

  <details>
    <summary>Controls</summary>
    <div class="keys" style="margin-top:8px">
      <b>D-pad</b>: Arrow keys &nbsp;|&nbsp; <b>A</b>: Z / X &nbsp;|&nbsp;
      <b>B</b>: A / S &nbsp;|&nbsp; <b>Gamepad</b>: plug it in, it maps automatically.<br>
      Click the screen first to capture keyboard + sound. Press a cart below to switch.
    </div>
  </details>

  <details>
    <summary>License &amp; credits</summary>
    <pre id="licblk"></pre>
  </details>
</div>

<footer id="foot"></footer>

<script>
// ===== embedded payload =====================================================
const TIC_CARTS = __CARTS_JSON__;            // each .b64 is a real .tic cartridge
const TIC_LICENSE = __LICENSE_JSON__;
const WASM_B64 = "__WASM_B64__";
const CART_URL = "cart.tic";                 // the URL the engine will "fetch"

function b64ToBytes(b64){
  const bin = atob(b64), len = bin.length, out = new Uint8Array(len);
  for(let i=0;i<len;i++) out[i] = bin.charCodeAt(i);
  return out;
}
const WASM_BYTES = b64ToBytes(WASM_B64);

// ===== UI ===================================================================
const sel = document.getElementById('cartsel');
const grid = document.getElementById('cartgrid');
const overlay = document.getElementById('overlay');
const ovNow = document.getElementById('ovNow');
const statusEl = document.getElementById('status');
let selectedIdx = 0;

function escapeHtml(s){return String(s).replace(/[&<>"']/g,m=>(
  {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m]));}

TIC_CARTS.forEach((c,i)=>{
  const o = document.createElement('option');
  o.value = i; o.textContent = `${c.title}  (${c.script})`;
  sel.appendChild(o);
  const card = document.createElement('div');
  card.className = 'cart';
  card.innerHTML =
    `<div class="t">${escapeHtml(c.title)}</div>`+
    `<div class="a">${escapeHtml(c.author)}</div>`+
    `<div class="s">${escapeHtml(c.script)}</div>`;
  card.addEventListener('click',()=>{ pick(i); boot(); });
  grid.appendChild(card);
});

function pick(i){
  selectedIdx = i; sel.value = i;
  ovNow.textContent = `> ${TIC_CARTS[i].title}`;
  [...grid.children].forEach((el,j)=>el.classList.toggle('active', j===i));
}
sel.addEventListener('change',()=>pick(+sel.value));
document.getElementById('loadBtn').addEventListener('click',boot);
document.getElementById('playBtn').addEventListener('click',boot);

(function initPick(){
  const hash = decodeURIComponent((location.hash||'').replace('#',''));
  const qp = new URLSearchParams(location.search).get('cart');
  const want = qp || hash;
  let idx = 0;
  if(want){ const f = TIC_CARTS.findIndex(c=>c.file===want); if(f>=0) idx = f; }
  pick(idx);
})();

document.getElementById('licblk').textContent =
  TIC_LICENSE + "\n\n--- Engine ---\nTIC-80 fantasy console, (c) 2017 Vadim "+
  "Grigoruk and contributors (MIT). Official v1.1.2837 HTML/WASM build.\n\n"+
  "--- Carts (all MIT, from the TIC-80 repo /demos) ---\n"+
  TIC_CARTS.map(c=>`  ${c.title}  —  ${c.author}`).join("\n");

document.getElementById('foot').innerHTML =
  "TIC-80 engine MIT &copy; 2017 Vadim Grigoruk &amp; contributors. "+
  "Demo carts MIT (TIC-80 /demos). "+
  "Bundled for the cassette-ai project &mdash; decode-and-run, no network.";

// ===== XHR shim: feed the embedded cart bytes for CART_URL ==================
// The TIC-80 Emscripten loader fetches argv[1] (cart.tic) via
// FS.createPreloadedFile -> XHR. We intercept that one request and return the
// embedded cartridge bytes, so nothing ever leaves the page.
(function installCartShim(){
  const RealXHR = window.XMLHttpRequest;
  function ShimXHR(){
    this._real = new RealXHR();
    this._fake = false;
    const self = this;
    ['addEventListener','removeEventListener','setRequestHeader',
     'getAllResponseHeaders','getResponseHeader','abort','overrideMimeType']
      .forEach(m=>{ this[m]=function(){ return self._real[m] && self._real[m].apply(self._real,arguments); }; });
  }
  ShimXHR.prototype.open = function(method,url){
    this._url = url;
    if(String(url).indexOf(CART_URL) >= 0){ this._fake = true; return; }
    return this._real.open.apply(this._real, arguments);
  };
  ShimXHR.prototype.send = function(){
    const self = this;
    if(self._fake){
      self.readyState = 4; self.status = 200;
      self.response = window.__TIC_CART_BYTES.buffer.slice(0);
      self.responseText = undefined;
      setTimeout(function(){
        if(typeof self.onload === 'function') self.onload({target:self});
        if(typeof self.onreadystatechange === 'function') self.onreadystatechange({target:self});
      }, 0);
      return;
    }
    const r = self._real;
    ['onload','onerror','onreadystatechange','onprogress','responseType']
      .forEach(k=>{ if(self[k] !== undefined) r[k] = self[k]; });
    Object.defineProperty(self,'status',{get:()=>r.status,configurable:true});
    Object.defineProperty(self,'response',{get:()=>r.response,configurable:true});
    Object.defineProperty(self,'responseText',{get:()=>r.responseText,configurable:true});
    Object.defineProperty(self,'readyState',{get:()=>r.readyState,configurable:true});
    return r.send.apply(r, arguments);
  };
  Object.defineProperty(ShimXHR.prototype,'responseType',{
    set(v){ this._rt = v; if(this._real) this._real.responseType = v; },
    get(){ return this._rt; }
  });
  window.XMLHttpRequest = ShimXHR;
})();

// ===== boot =================================================================
let booted = false;

function boot(){
  if(booted){                       // reload for a clean Emscripten module
    location.hash = '#'+TIC_CARTS[selectedIdx].file;
    location.reload();
    return;
  }
  booted = true;
  overlay.style.display = 'none';
  const cart = TIC_CARTS[selectedIdx];
  statusEl.textContent = 'booting '+cart.title+' …';
  window.__TIC_CART_BYTES = b64ToBytes(cart.b64);   // bytes the XHR shim returns

  window.Module = {
    canvas: document.getElementById('canvas'),
    arguments: [CART_URL],            // *.tic -> engine boots straight into it
    wasmBinary: WASM_BYTES,           // no fetch of tic80.wasm
    locateFile: function(p){ return p; },
    print: function(t){ console.log('[tic80]', t); },
    printErr: function(t){ console.warn('[tic80]', t); },
    onRuntimeInitialized: function(){
      statusEl.textContent = 'running: '+cart.title+'  (click screen for input)';
      document.getElementById('canvas').focus();
    }
  };

  const s = document.createElement('script');
  s.text = TIC80_LOADER;            // defined at end of this script block
  document.body.appendChild(s);
}

window.addEventListener('load',()=>{
  if(location.hash && location.hash.length>1) setTimeout(boot, 60);
});

const TIC80_LOADER = __TIC80_JS__;
</script>
</body>
</html>
"""

HTML = HTML.replace("__CARTS_JSON__", json.dumps(carts))
HTML = HTML.replace("__LICENSE_JSON__", json.dumps(license_text))
HTML = HTML.replace("__WASM_B64__", wasm_b64)
HTML = HTML.replace("__TIC80_JS__", json.dumps(tic80_js))

os.makedirs(os.path.dirname(OUT), exist_ok=True)
with open(OUT, "w", encoding="utf-8") as f:
    f.write(HTML)

print("wrote", OUT)
print("carts:", len(carts))
for c in carts:
    print("  ", c["file"], c["title"], "/", c["author"])
print("size bytes:", len(HTML.encode("utf-8")))
