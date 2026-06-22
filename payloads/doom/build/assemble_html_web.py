#!/usr/bin/env python3
"""assemble_html_web.py — a WEB-HOSTABLE build of the v3 DOOM artifact.

Why this exists (separate from assemble_html_v3.py):
  The tape build (doom_cassette_v3.html) stores the wasm+wad as a RAW
  windows-1252 byte carrier — optimal for the cassette (near-zero lzma penalty).
  That relies on the document being decoded as windows-1252, which the
  `<meta charset="windows-1252">` tag requests. But an HTTP `Content-Type`
  charset OVERRIDES the meta tag, and GitHub Pages (and most static hosts) serve
  .html as `charset=utf-8` — which mangles every 0x80-0xFF byte into U+FFFD and
  corrupts the payload, so the wasm fails to compile (CompileError "unknown type
  form"). It works fine over file:// (no HTTP header) but not over https://.

  This build sidesteps the whole problem by embedding the SAME wasm + wad as
  base64 (pure ASCII), which survives any charset. Larger on disk (base64 is
  +33%), but there is no tape/lzma budget on the web. The engine, the custom
  Magnetic Vault WAD, the WebAudio SFX, saves, and the splash/controls are
  byte-identical to v3 — only the carrier changes.

Output: dist/doom_cassette_web.html  (argv[1] overrides).
Run with any python3.
"""
import base64
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DIST = os.path.join(HERE, "..", "dist")
OUT = sys.argv[1] if len(sys.argv) > 1 else os.path.join(DIST, "doom_cassette_web.html")

engine_js = open(os.path.join(HERE, "pack", "doom_pack_v3.js"), "rb").read()
wasm = open(os.path.join(HERE, "pack", "doom_pack_v3.wasm"), "rb").read()
_wad_path = os.environ.get(
    "DOOM_V3_WAD", os.path.join(HERE, "freedoom_e1_v3b_vault.wad"))
wad = open(_wad_path, "rb").read()

assert max(engine_js) < 0x80, "engine JS not pure ASCII"
assert not re.search(rb"</[sS][cC][rR][iI][pP][tT]|<!--", engine_js), \
    "engine JS contains </script or <!-- (would need escaping)"
assert b"\r" not in engine_js

license_1252 = open(os.path.join(HERE, "miniwad", "COPYING.adoc"),
                    encoding="utf-8").read().encode("cp1252")
assert b"--" not in license_1252, "license text would break the HTML comment"

head_comment = (b"""<!--
CASSETTE-AI :: DOOM ON A CASSETTE, v3 (web build)
This is the WEB-HOSTABLE twin of doom_cassette_v3.html -- the single HTML file
(wasm engine + game data) that was stored as audio on one side of a C90 compact
cassette and decoded back. The tape build uses a raw windows-1252 byte carrier;
this build base64-encodes the same payload so it survives being served as utf-8.
https://github.com/Magnus-Gille/cassette-ai

Engine: doomgeneric by ozkl (https://github.com/ozkl/doomgeneric), GPL-2.0.
  Complete corresponding source accompanies the tape (side B) and the repo.
Game data: trimmed from Freedoom: Phase 1 v0.13.0 (https://freedoom.github.io/),
  Episode 1 complete, with THE MAGNETIC VAULT custom E1M1. BSD 3-clause license,
  reproduced verbatim below as required for binary redistribution:

""" + license_1252 + b"""
-->""")

css = (b"<style>"
       # moodboard reskin (mid-century print x cassette j-card x Bauhaus); zero-network,
       # so type is a heavy system stack + monospace (no web fonts) -- palette + hard edges
       # + hard offset shadows carry the look, matching the Magnetic Vault landing page.
       b":root{--cream:#f4efe6;--ink:#1a1712;--cobalt:#2c3192;--marigold:#f2b417;"
       b"--teal:#1f9e8f;--vermillion:#e8772e;--red:#e23b30;--pink:#e8447a;"
       b"--mono:'Space Mono',ui-monospace,Menlo,Consolas,monospace;"
       b"--sans:'Helvetica Neue',Arial,sans-serif}"
       b"html,body{margin:0;height:100%;background:var(--cream);color:var(--ink);"
       b"font:13px/1.6 var(--mono)}"
       b"body{display:flex;align-items:center;justify-content:center}"
       b"canvas{width:640px;height:400px;image-rendering:pixelated;background:#000;"
       b"border:4px solid var(--ink);box-shadow:10px 10px 0 var(--cobalt)}"
       b"#ov{position:fixed;inset:0;background:var(--cream);display:flex;flex-direction:column;"
       b"align-items:center;justify-content:center;text-align:center;gap:16px;z-index:2;padding:28px}"
       b"#ov::before{content:'';position:fixed;top:0;left:0;right:0;height:8px;z-index:3;"
       b"background:linear-gradient(90deg,var(--cobalt) 0 14.3%,var(--teal) 14.3% 28.6%,"
       b"var(--marigold) 28.6% 42.9%,var(--pink) 42.9% 57.1%,var(--vermillion) 57.1% 71.4%,"
       b"var(--red) 71.4% 85.7%,var(--cobalt) 85.7% 100%)}"
       b"#cass{width:240px;height:148px;border:3px solid var(--ink);position:relative;"
       b"background:var(--marigold);box-shadow:7px 7px 0 var(--ink)}"
       b"#cass i{position:absolute;top:58px;width:34px;height:34px;border:3px solid var(--ink);"
       b"border-radius:50%;background:var(--cream)}"
       b"#cass i.l{left:46px}#cass i.r{right:46px}"
       b"#cass b{position:absolute;top:14px;left:18px;right:18px;height:22px;"
       b"border:2px solid var(--ink);font-weight:700;color:var(--ink);background:var(--cream);"
       b"font-size:10px;line-height:20px;letter-spacing:.1em}"
       b"h1{margin:6px 0 0;font-family:var(--sans);font-weight:900;font-size:76px;"
       b"letter-spacing:-.02em;line-height:.9;color:var(--vermillion);text-shadow:5px 5px 0 var(--ink)}"
       b".lede{max-width:54ch;font-size:13px;color:var(--ink)}"
       b"#go{font:inherit;font-weight:700;font-size:14px;letter-spacing:.18em;text-transform:uppercase;"
       b"padding:14px 30px;cursor:pointer;background:var(--ink);color:var(--cream);"
       b"border:3px solid var(--ink);box-shadow:6px 6px 0 var(--vermillion)}"
       b"#go:hover{background:var(--vermillion);color:var(--ink);box-shadow:6px 6px 0 var(--ink)}"
       b".dim{color:#6b6456;font-size:11px;letter-spacing:.04em;max-width:62ch}"
       b"</style>")

splash = (b'<div id="ov">'
          b'<div id="cass"><b>SIDE A &middot; DOOM E1 &middot; v3</b><i class="l"></i>'
          b'<i class="r"></i></div>'
          b'<h1>DOOM</h1>'
          b'<div class="lede"><b>CASSETTE-AI v3</b> &mdash; the complete Episode 1 (nine maps), '
          b'with sound, decoded from one side of an ordinary audio cassette tape.</div>'
          b'<button id="go">&#9654; INSERT TAPE &amp; PLAY</button>'
          b'<div class="dim">arrows move/turn &middot; A/D strafe &middot; S (or X / ctrl) fire &middot; '
          b'space use/open &middot; shift run &middot; tab map &middot; enter/esc menus &middot; '
          b'F2 save &middot; F3 load (saves survive reload)</div>'
          b'<div class="dim">sound effects: WebAudio (music rides side B of the tape) '
          b'&middot; idle on the title screen for the attract demo</div>'
          b'<div class="dim">engine: doomgeneric (GPL-2.0) &middot; '
          b'game data: Freedoom Phase 1 Episode 1 (BSD), trimmed &middot; '
          b'%d KB wasm + %d KB WAD, base64 web carrier, zero network</div>'
          b'</div>' % (len(wasm) // 1024, len(wad) // 1024))

wasm_b64 = base64.b64encode(wasm)
wad_b64 = base64.b64encode(wad)

shell_js = (b"""
function b64(s){var bin=atob(s),u=new Uint8Array(bin.length);
for(var i=0;i<bin.length;i++)u[i]=bin.charCodeAt(i);return u;}
var wasmBin=b64(W64),wadBin=b64(I64);
var Module={wasmBinary:wasmBin,wadBinary:wadBin};
function startDoom(){
""" + engine_js + b"""
}
var started=0;
function go(){
 if(started)return; started=1;
 document.getElementById('ov').remove();
 startDoom();
 var cv=document.getElementById('canvas'),t0=Date.now();
 var iv=setInterval(function(){
  try{
   if(cv.width<320)return;
   var d=cv.getContext('2d').getImageData(0,0,320,200).data,n=0;
   for(var i=0;i<d.length;i+=4)if(d[i]|d[i+1]|d[i+2])n++;
   if(n>5000){document.title='DOOM-OK px='+n;document.body.setAttribute('data-doom','ok');clearInterval(iv);}
  }catch(e){}
  if(Date.now()-t0>30000)clearInterval(iv);
 },250);
}
document.getElementById('go').onclick=go;
if(location.hash.indexOf('autostart')>=0)go();
""")
# The base64 blobs go in their own <script> as globals so the engine <script>
# stays pure-ASCII and parser-safe (base64 alphabet has no '<').
b64_js = b"var W64=" + b'"' + wasm_b64 + b'"' + b",I64=" + b'"' + wad_b64 + b'"' + b";"
assert b"</script" not in b64_js.lower() and b"<!--" not in b64_js

html = (b'<!DOCTYPE html><html><head><meta charset="utf-8">'
        b'<title>DOOM on a cassette, v3 &mdash; Cassette-AI</title>\n' +
        head_comment + b"\n" + css + b"</head><body>" +
        splash +
        b'<canvas id="canvas"></canvas>' +
        b"<script>" + b64_js + b"</script>" +
        b"<script>" + shell_js + b"</script></body></html>\n")

os.makedirs(DIST, exist_ok=True)
open(OUT, "wb").write(html)
print("wrote %s  (%d bytes; wasm %d, wad %d, engine js %d)" %
      (OUT, len(html), len(wasm), len(wad), len(engine_js)))
