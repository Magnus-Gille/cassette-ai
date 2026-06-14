#!/usr/bin/env /usr/bin/python3
"""assemble_html.py — build dist/doom_cassette.html, the single self-contained
cassette artifact: doomgeneric wasm engine + miniwad IWAD inlined as RAW bytes
via the windows-1252 rawpack carrier (lzma +2-5% vs base64's +18-38%).

Layout of the emitted page (everything outside the two rawpack blocks is
ASCII, except the license comment which is valid windows-1252):

  <head>  meta charset=windows-1252, license/attribution comment, css
  <body>  splash overlay (click-to-start; #autostart hash skips the click),
          <canvas id="canvas"> (engine sizes it 320x200 itself),
          <script type="o" id="w"> raw wasm, <script type="o" id="i"> raw WAD,
          one inline ASCII <script>: rawunpack decoder + perm tables +
          Module={wasmBinary, preRun:[FS.writeFile('/doom2.wad')]} +
          the whole closure'd engine JS wrapped in startDoom() (evaluated only
          on start), + a canvas-pixel poller that sets document.title /
          body[data-doom=ok] once the engine is rendering (verification hook).

Inputs : pack/doom_pack.js, pack/doom_pack.wasm (build_split.sh), mini.wad
Output : ../dist/doom_cassette.html
Run with /usr/bin/python3 (pyenv 3.10 lacks _lzma for the size report).
"""
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import rawpack  # noqa: E402

DIST = os.path.join(HERE, "..", "dist")
OUT = os.path.join(DIST, "doom_cassette.html")

engine_js = open(os.path.join(HERE, "pack", "doom_pack.js"), "rb").read()
wasm = open(os.path.join(HERE, "pack", "doom_pack.wasm"), "rb").read()
wad = open(os.path.join(HERE, "mini.wad"), "rb").read()

# -- safety: the engine JS is inlined verbatim in a real <script>; it must be
# ASCII and free of sequences that end the script-data parser state.
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
CASSETTE-AI :: DOOM ON A CASSETTE
This single HTML file (wasm engine + game data, raw bytes in a windows-1252
carrier) was stored as ~9 minutes-per-megabyte of audio on one side of a C60
compact cassette at 2572 net bps and decoded back. https://github.com/magnusgille

Engine: doomgeneric by ozkl (https://github.com/ozkl/doomgeneric), GPL-2.0.
  Complete corresponding source (engine + the build/assembly scripts that made
  this file) accompanies the tape: side B carries the source archive, per the
  GPL-2.0 written-offer provision. Backend: doomgeneric_wasm.c (GPL-2.0).
Game data: miniwad.wad by Simon Howard (https://github.com/fragglet/miniwad),
  built from Freedoom project assets. BSD 3-clause license, reproduced
  verbatim below as required for binary redistribution:

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
          b'<div id="cass"><b>SIDE A &middot; DOOM &middot; 60 min</b><i class="l"></i>'
          b'<i class="r"></i></div>'
          b'<h1>DOOM</h1>'
          b'<div><b>CASSETTE-AI</b> &mdash; this entire game was decoded from one side '
          b'of an ordinary audio cassette tape.</div>'
          b'<button id="go">&#9654; INSERT TAPE &amp; PLAY</button>'
          b'<div class="dim">arrows move &middot; ctrl fire &middot; space use/open &middot; '
          b'shift run &middot; tab map &middot; enter/esc menus</div>'
          b'<div class="dim">engine: doomgeneric (GPL-2.0) &middot; '
          b'game data: miniwad / Freedoom (BSD) &middot; '
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
        b'<title>DOOM on a cassette &mdash; Cassette-AI</title>\n' +
        head_comment + b"\n" + css + b"</head><body>" +
        splash +
        b'<canvas id="canvas"></canvas>' +
        block_w + block_i +
        b"<script>" + shell_js + b"</script></body></html>\n")

os.makedirs(DIST, exist_ok=True)
open(OUT, "wb").write(html)
print("wrote %s  (%d bytes; wasm %d, wad %d, engine js %d)" %
      (OUT, len(html), len(wasm), len(wad), len(engine_js)))
