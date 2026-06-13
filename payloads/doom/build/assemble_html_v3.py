#!/usr/bin/env python3
"""assemble_html_v3.py — v3 of assemble_html2.py: builds dist/doom_cassette_v3.html
from the v3 engine pack (pack/doom_pack_v3.*, WebAudio SFX + localStorage
savegames + attract-demo boot) + freedoom_e1_v3.wad (full Freedoom Phase 1
Episode 1, E1M1-E1M9, real DS* sound effects, music dropped; see
trim_freedoom_v3.py).

v1 (dist/doom_cassette.html) and v2 (dist/doom_cassette_v2.html) are frozen and
untouched. Same rawpack carrier as v2: Module={wasmBinary,wadBinary}; the v3
pre-js (pre_wad_v3.js, already linked into doom_pack_v3.js) sets Module.preRun
itself to serve the IWAD and restore/mirror savegames.

Budget (frozen, from measured tape10 physics @ 5281.7 effective bps):
  lzma(preset 9) of this file — HARD CAP 1.60 MB, TARGET 1.50 MB.

Run with /usr/bin/python3 (pyenv 3.10 lacks _lzma for the size report).
"""
import gzip
import json
import lzma
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import rawpack  # noqa: E402

DIST = os.path.join(HERE, "..", "dist")
# Optional argv[1] overrides the output path (default: dist/doom_cassette_v3.html).
OUT = sys.argv[1] if len(sys.argv) > 1 else os.path.join(DIST, "doom_cassette_v3.html")

HARD_CAP_LZMA = int(1.60 * 1024 * 1024)   # 1,677,721 B
TARGET_LZMA = int(1.50 * 1024 * 1024)     # 1,572,864 B
EFFECTIVE_BPS = 5281.7                    # measured, tape10 run1 (incl. framing)

engine_js = open(os.path.join(HERE, "pack", "doom_pack_v3.js"), "rb").read()
wasm = open(os.path.join(HERE, "pack", "doom_pack_v3.wasm"), "rb").read()
# WAD path is overridable via DOOM_V3_WAD.  SHIP DEFAULT = freedoom_e1_v3b_vault.wad:
# the v3b trimmer (trim_freedoom_v3b.py STEPS 1-5) shaved a smaller IWAD off v3
# for ~2 min more physical-C90 tape margin (44.77 -> 42.62 min); the _vault WAD
# then splices THE MAGNETIC VAULT custom E1M1 (level/integrate_level.py) over
# the stock E1M1 hangar (E1M2-E1M9 untouched).  The custom map's lump-set is
# 108 KB SMALLER than the stock E1M1, so after lzma the dist HTML is ~30 KB
# smaller than the pre-vault v3b artifact (1.395 MB vs 1.424 MB) -- the tape
# margin only improves.  The carrier/engine are unchanged; only the embedded WAD
# bytes differ.  FALLBACKS: DOOM_V3_WAD=.../freedoom_e1_v3b.wad rebuilds the
# pre-vault (stock E1M1) artifact; .../freedoom_e1_v3.wad rebuilds the pre-trim v3.
_wad_path = os.environ.get(
    "DOOM_V3_WAD", os.path.join(HERE, "freedoom_e1_v3b_vault.wad"))
wad = open(_wad_path, "rb").read()

assert max(engine_js) < 0x80, "engine JS not pure ASCII"
assert not re.search(rb"</[sS][cC][rR][iI][pP][tT]|<!--", engine_js), \
    "engine JS contains </script or <!-- (would need escaping)"
assert b"\r" not in engine_js

block_w, perm_w = rawpack.make_block(wasm, "w")
block_i, perm_i = rawpack.make_block(wad, "i")

license_1252 = open(os.path.join(HERE, "miniwad", "COPYING.adoc"),
                    encoding="utf-8").read().encode("cp1252")
assert b"--" not in license_1252, "license text would break the HTML comment"

head_comment = (b"""<!--
CASSETTE-AI :: DOOM ON A CASSETTE, v3
This single HTML file (wasm engine + game data, raw bytes in a windows-1252
carrier) was stored as audio on one side of a C90 compact cassette at a
measured 5281.7 effective bps and decoded back. https://github.com/magnusgille

v3: the full Freedoom Phase 1 EPISODE 1 (all nine maps E1M1-E1M9, full
bestiary, every placed weapon), WebAudio sound effects (music lives on side B
of the tape, as actual music), savegames that persist across page reloads
(localStorage), and the title-screen attract demo loop.

Engine: doomgeneric by ozkl (https://github.com/ozkl/doomgeneric), GPL-2.0.
  Complete corresponding source (engine + the build/assembly scripts that made
  this file) accompanies the tape: side B carries the source archive, per the
  GPL-2.0 written-offer provision. Backend: doomgeneric_wasm_v3.c (GPL-2.0).
Game data: trimmed from Freedoom: Phase 1 v0.13.0 (https://freedoom.github.io/),
  Episode 1 complete; textures/flats/sprites budgeted (front-rotation-only
  sprites, Jaguar-DOOM style); sound effects kept, music lumps dropped.
  BSD 3-clause license, reproduced verbatim below as required for binary
  redistribution:

""" + license_1252 + b"""
-->""")

css = (b"<style>"
       b"html,body{margin:0;height:100%;background:#000;color:#cfc9bd;"
       b"font:13px/1.5 ui-monospace,Menlo,Consolas,monospace}"
       b"body{display:flex;align-items:center;justify-content:center}"
       b"canvas{width:640px;height:400px;image-rendering:pixelated;background:#000}"
       b"#ov{position:fixed;inset:0;background:#0a0a0a;display:flex;flex-direction:column;"
       b"align-items:center;justify-content:center;text-align:center;gap:12px;z-index:2;"
       b"padding:24px}"
       b"#cass{width:230px;height:140px;border:3px solid #cfc9bd;border-radius:10px;"
       b"position:relative;background:#161616}"
       b"#cass i{position:absolute;top:52px;width:34px;height:34px;border:3px solid #cfc9bd;"
       b"border-radius:50%}"
       b"#cass i.l{left:42px}#cass i.r{right:42px}"
       b"#cass b{position:absolute;top:14px;left:20px;right:20px;height:22px;"
       b"border:2px solid #6b6557;border-radius:4px;font-weight:normal;color:#8a8475;"
       b"font-size:11px;line-height:20px}"
       b"h1{margin:6px 0 0;font-size:42px;letter-spacing:8px;color:#e23b1e;"
       b"text-shadow:0 0 14px #7a1d0a}"
       b"#go{font:inherit;font-size:16px;letter-spacing:2px;padding:12px 26px;cursor:pointer;"
       b"background:#e23b1e;color:#0a0a0a;border:0;border-radius:4px;font-weight:bold}"
       b"#go:hover{background:#ff5a32}"
       b".dim{color:#8a8475;font-size:12px}"
       b"</style>")

splash = (b'<div id="ov">'
          b'<div id="cass"><b>SIDE A &middot; DOOM E1 &middot; v3</b><i class="l"></i>'
          b'<i class="r"></i></div>'
          b'<h1>DOOM</h1>'
          b'<div><b>CASSETTE-AI v3</b> &mdash; the complete Episode 1 (nine maps), '
          b'with sound, decoded from one side of an ordinary audio cassette tape.</div>'
          b'<button id="go">&#9654; INSERT TAPE &amp; PLAY</button>'
          b'<div class="dim">arrows move &middot; ctrl fire &middot; space use/open &middot; '
          b'shift run &middot; tab map &middot; enter/esc menus &middot; '
          b'F2 save &middot; F3 load (saves survive reload)</div>'
          b'<div class="dim">sound effects: WebAudio (music rides side B of the tape) '
          b'&middot; idle on the title screen for the attract demo</div>'
          b'<div class="dim">engine: doomgeneric (GPL-2.0) &middot; '
          b'game data: Freedoom Phase 1 Episode 1 (BSD), trimmed &middot; '
          b'%d KB wasm + %d KB WAD, raw bytes, zero network</div>'
          b'</div>' % (len(wasm) // 1024, len(wad) // 1024))

shell_js = (rawpack.js_decoder().encode("ascii") +
            b"var PW=" + json.dumps(perm_w, separators=(",", ":")).encode() +
            b",PI=" + json.dumps(perm_i, separators=(",", ":")).encode() + b""";
var wasmBin=rawunpack('w',PW),wadBin=rawunpack('i',PI);
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
assert max(shell_js) < 0x80 and not re.search(
    rb"</[sS][cC][rR][iI][pP][tT]|<!--", shell_js)

html = (b'<!DOCTYPE html><html><head><meta charset="windows-1252">'
        b'<title>DOOM on a cassette, v3 &mdash; Cassette-AI</title>\n' +
        head_comment + b"\n" + css + b"</head><body>" +
        splash +
        b'<canvas id="canvas"></canvas>' +
        block_w + block_i +
        b"<script>" + shell_js + b"</script></body></html>\n")

os.makedirs(DIST, exist_ok=True)
open(OUT, "wb").write(html)
print("wrote %s  (%d bytes; wasm %d, wad %d, engine js %d)" %
      (OUT, len(html), len(wasm), len(wad), len(engine_js)))

gz = len(gzip.compress(html, compresslevel=9))
lz = len(lzma.compress(html, preset=9))
secs = lz * 8 / EFFECTIVE_BPS
print("ledger: raw %.1f KB | gzip9 %.1f KB | lzma9 %.1f KB (%.3f MB)" %
      (len(html) / 1024.0, gz / 1024.0, lz / 1024.0, lz / 1048576.0))
print("tape:   %.0f s = %.1f min on side A @ %.1f effective bps" %
      (secs, secs / 60.0, EFFECTIVE_BPS))
print("budget: TARGET 1.50 MB (%d B) %s | HARD CAP 1.60 MB (%d B) %s" %
      (TARGET_LZMA, "OK" if lz <= TARGET_LZMA else "OVER by %.1f KB" % ((lz - TARGET_LZMA) / 1024.0),
       HARD_CAP_LZMA, "OK" if lz <= HARD_CAP_LZMA else "OVER by %.1f KB" % ((lz - HARD_CAP_LZMA) / 1024.0)))
if lz > HARD_CAP_LZMA:
    sys.exit("HARD CAP EXCEEDED — bounce trim_freedoom_v3.py to the next drop rung")
