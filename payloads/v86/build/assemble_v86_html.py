#!/usr/bin/env python3
"""
Assemble a fully self-contained "boots a full Linux PC on a cassette" HTML.

Inlines, with ZERO runtime network fetches (works over file:// AND http):
  - libv86.js               (v86 BSD-2 engine loader)              -> <script>
  - v86.wasm                (the x86->wasm JIT core)               -> base64, fed via wasm_fn
  - seabios.bin             (SeaBIOS firmware, LGPLv3)             -> base64, bios.buffer
  - vgabios.bin             (VGA BIOS, LGPLv3)                     -> base64, vga_bios.buffer
  - linux.iso               (Buildroot Linux, GPL-2.0)            -> base64, cdrom.buffer

Source assets live in payloads/built/v86_linux/ (regenerable via build_v86_linux.sh).
Output: payloads/v86/dist/v86_linux.html
"""
import base64
import os

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.normpath(os.path.join(HERE, "..", "..", "built", "v86_linux"))
OUT = os.path.normpath(os.path.join(HERE, "..", "dist", "v86_linux.html"))

LIBV86 = os.path.join(SRC, "bundle", "build", "libv86.js")
WASM = os.path.join(SRC, "bundle", "build", "v86.wasm")
SEABIOS = os.path.join(SRC, "bundle", "bios", "seabios.bin")
VGABIOS = os.path.join(SRC, "bundle", "bios", "vgabios.bin")
ISO = os.path.join(SRC, "bundle", "linux.iso")


def b64(path):
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode("ascii")


def read_text(path):
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        return f.read()


libv86_js = read_text(LIBV86)
wasm_b64 = b64(WASM)
seabios_b64 = b64(SEABIOS)
vgabios_b64 = b64(VGABIOS)
iso_b64 = b64(ISO)

HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>A Full Linux PC, Booted From a Cassette &middot; cassette-ai</title>
<style>
  :root {{
    --bg: #0a0c10;
    --panel: #11151c;
    --ink: #d7dde6;
    --dim: #6b7585;
    --accent: #4fd1c5;
    --rust: #d98b5f;
    --line: #1d2530;
  }}
  * {{ box-sizing: border-box; }}
  html, body {{ margin: 0; background: var(--bg); color: var(--ink);
    font-family: ui-monospace, SFMono-Regular, "SF Mono", Menlo, Consolas, monospace; }}
  .wrap {{ max-width: 1000px; margin: 0 auto; padding: 28px 20px 60px; }}
  header {{ border-bottom: 1px solid var(--line); padding-bottom: 18px; margin-bottom: 22px; }}
  h1 {{ font-size: 22px; letter-spacing: .5px; margin: 0 0 6px; font-weight: 600; }}
  h1 .reel {{ color: var(--rust); }}
  .sub {{ color: var(--dim); font-size: 13px; line-height: 1.5; max-width: 70ch; }}
  .status {{ margin: 16px 0; font-size: 13px; color: var(--accent); min-height: 18px; }}
  .status.err {{ color: #e06c75; }}
  .stage {{ background: var(--panel); border: 1px solid var(--line); border-radius: 10px;
    padding: 14px; }}
  .stage h2 {{ font-size: 12px; text-transform: uppercase; letter-spacing: 1.5px;
    color: var(--dim); margin: 0 0 10px; font-weight: 600; }}
  #screen_container {{ display: inline-block; background: #000; border-radius: 6px;
    overflow: hidden; line-height: 0; }}
  #screen_container > div {{ white-space: pre; font: 14px/1.05 "Courier New", monospace;
    color: #e8e8e8; }}
  #screen_container > canvas {{ display: none; }}
  .term-wrap {{ margin-top: 16px; }}
  #serial {{ width: 100%; height: 360px; background: #05070a; color: #b8f1c0;
    border: 1px solid var(--line); border-radius: 6px; padding: 12px;
    font: 12px/1.4 ui-monospace, Menlo, monospace; resize: vertical; outline: none; }}
  .hint {{ color: var(--dim); font-size: 12px; margin-top: 8px; }}
  footer {{ margin-top: 34px; padding-top: 16px; border-top: 1px solid var(--line);
    color: var(--dim); font-size: 11px; line-height: 1.6; }}
  footer b {{ color: var(--ink); font-weight: 600; }}
  a {{ color: var(--accent); }}
</style>
</head>
<body>
<div class="wrap">
  <header>
    <h1><span class="reel">&#9678;</span> A Full Linux PC, Booted From a Cassette <span class="reel">&#9678;</span></h1>
    <div class="sub">
      Everything below &mdash; the x86 CPU emulator, the PC firmware, and an entire
      bootable Linux operating system &mdash; was stored as audio on an ordinary cassette,
      decoded back to bytes, and embedded inline in this single file. No network. No server.
      Press a key in the terminal once it boots. This is part of the <b>cassette-ai</b> project.
    </div>
  </header>

  <div class="status" id="status">Initializing emulator&hellip;</div>

  <div class="stage">
    <h2>VGA console</h2>
    <div id="screen_container">
      <div></div>
      <canvas></canvas>
    </div>
    <div class="term-wrap">
      <h2 style="margin-top:14px">Serial terminal &mdash; click and type</h2>
      <textarea id="serial" spellcheck="false" autocomplete="off"
        placeholder="kernel boot log appears here, then a shell prompt..."></textarea>
      <div class="hint">Buildroot Linux. Try: <code>cat /proc/cpuinfo</code> &middot;
        <code>uname -a</code> &middot; <code>ls /</code></div>
    </div>
  </div>

  <footer>
    <b>How this was built.</b> Engine: <b>v86</b> (npm 0.5.372, BSD-2-Clause &mdash;
    Copyright &copy; 2012 The v86 contributors). Firmware: <b>SeaBIOS</b> + <b>VGABIOS</b>
    (LGPLv3). Operating system: a <b>Buildroot</b> Linux image &mdash; the Linux kernel and
    BusyBox are <b>GPL-2.0</b>. Per the GPL, corresponding source ships alongside this artifact:
    v86 at <a href="https://github.com/copy/v86">github.com/copy/v86</a>,
    Buildroot at <a href="https://buildroot.org/downloads/">buildroot.org/downloads</a>,
    kernel at <a href="https://kernel.org">kernel.org</a>
    (see SOURCE_AND_LICENSES.md in the payload bundle). All binaries are embedded base64;
    this page makes no runtime network requests.
  </footer>
</div>

<!-- ===== inlined v86 engine (libv86.js, BSD-2) ===== -->
<script>
{libv86_js}
</script>

<!-- ===== inlined firmware + OS (base64) + boot ===== -->
<script>
"use strict";
(function () {{
  var statusEl = document.getElementById("status");
  function setStatus(t, err) {{
    statusEl.textContent = t;
    statusEl.className = err ? "status err" : "status";
  }}

  // Decode a base64 string to an ArrayBuffer (no network fetch).
  function b64ToArrayBuffer(b64) {{
    var bin = atob(b64);
    var len = bin.length;
    var bytes = new Uint8Array(len);
    for (var i = 0; i < len; i++) bytes[i] = bin.charCodeAt(i);
    return bytes.buffer;
  }}

  setStatus("Decoding embedded firmware + Linux image…");

  var WASM_B64 = "{wasm_b64}";
  var SEABIOS_B64 = "{seabios_b64}";
  var VGABIOS_B64 = "{vgabios_b64}";
  var ISO_B64 = "{iso_b64}";

  var wasmBuffer = b64ToArrayBuffer(WASM_B64);
  var biosBuffer = b64ToArrayBuffer(SEABIOS_B64);
  var vgaBuffer = b64ToArrayBuffer(VGABIOS_B64);
  var isoBuffer = b64ToArrayBuffer(ISO_B64);

  // Custom wasm loader: instantiate from the inlined buffer instead of fetching.
  // Mirrors v86's default wasm_fn contract: (imports) => Promise<exports>.
  function wasm_fn(imports) {{
    return WebAssembly.instantiate(wasmBuffer, imports).then(function (result) {{
      return result.instance.exports;
    }});
  }}

  setStatus("Starting x86 CPU — booting SeaBIOS → Linux (this can take 10–40s)…");

  var emulator = new V86({{
    wasm_fn: wasm_fn,
    memory_size: 32 * 1024 * 1024,
    vga_memory_size: 2 * 1024 * 1024,
    bios: {{ buffer: biosBuffer }},
    vga_bios: {{ buffer: vgaBuffer }},
    cdrom: {{ buffer: isoBuffer }},
    autostart: true,
    disable_speaker: true,
    screen_container: document.getElementById("screen_container"),
    serial_console: {{
      type: "textarea",
      container: document.getElementById("serial")
    }}
  }});

  // Track boot progress via serial output; flip status when a shell prompt appears.
  var serialBuf = "";
  var booted = false;
  emulator.add_listener("serial0-output-byte", function (byte) {{
    var ch = String.fromCharCode(byte);
    serialBuf += ch;
    if (serialBuf.length > 20000) serialBuf = serialBuf.slice(-20000);
    if (!booted && /(login:|~#|\\/ #|# $|\\$ )/.test(serialBuf)) {{
      booted = true;
      setStatus("✓ Linux booted from cassette — shell ready. Click the terminal and type.");
    }}
  }});

  emulator.add_listener("emulator-loaded", function () {{
    setStatus("Firmware + image loaded — CPU running, kernel booting…");
  }});

  // expose for debugging / verification
  window.__v86 = emulator;
  window.__getSerial = function () {{ return serialBuf; }};
}})();
</script>
</body>
</html>
"""

out = HTML.format(
    libv86_js=libv86_js,
    wasm_b64=wasm_b64,
    seabios_b64=seabios_b64,
    vgabios_b64=vgabios_b64,
    iso_b64=iso_b64,
)

os.makedirs(os.path.dirname(OUT), exist_ok=True)
with open(OUT, "w", encoding="utf-8") as f:
    f.write(out)

print("wrote", OUT)
print("bytes", os.path.getsize(OUT))
