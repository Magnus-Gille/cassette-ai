#!/usr/bin/env python3
"""Build the 'Great Library — Essentials' self-narrating cassette artifact.

Bundles the eSpeak-ng WASM TTS engine (payloads/audiobook/engine/build/) with
a trimmed, "best of the best" public-domain corpus (9 canonical short works /
novellas, see payloads/built/_build_all_corpora.py::GREAT_LIBRARY_ESSENTIALS)
into ONE self-contained HTML file, following the exact technical pattern of
dist/willows_audiobook.html: base64-embedded WASM/data inline, no runtime
fetches, sentence-level playback + highlighting, dark theme — extended with
a simple book-selector screen for multiple titles.

Run: python3 build_great_library_essentials.py
Output: dist/great_library_essentials_audiobook.html
"""
import base64
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
BUILT_DIR = os.path.join(HERE, "..", "built")
ENGINE_DIR = os.path.join(HERE, "engine", "build")
DIST_DIR = os.path.join(HERE, "dist")

sys.path.insert(0, BUILT_DIR)
from _corpus_builder import fetch, verify_and_strip  # noqa: E402
from _build_all_corpora import GREAT_LIBRARY_ESSENTIALS  # noqa: E402

HEADER_RE = re.compile(r'^(chapter|stave|part|book|volume|canto|prologue|epilogue)\b', re.IGNORECASE)


def split_items(body):
    """Split stripped PG body text into header/para items for the reader."""
    blocks = re.split(r'\n\s*\n+', body)
    items = []
    for b in blocks:
        t = re.sub(r'\s+', ' ', b).strip()
        if len(t) < 2:
            continue
        is_header = False
        if len(t) < 80 and (HEADER_RE.match(t) or (t.isupper() and len(t.split()) <= 8)):
            is_header = True
        items.append({"type": "header" if is_header else "para", "text": t})
    return items


def build_books():
    books = []
    for gid, label in GREAT_LIBRARY_ESSENTIALS:
        raw = fetch(gid)
        body, ev = verify_and_strip(gid, raw)
        items = split_items(body)
        title = ev["title"] or label
        author = ev["author"] or ""
        # Trim common PG title suffixes like "; Being a Ghost Story of Christmas"
        books.append({
            "gid": gid,
            "label": label,
            "title": title,
            "author": author,
            "items": items,
        })
    return books


def xz_size(data: bytes) -> int:
    p = subprocess.run(["xz", "-9", "-e", "-c", "-T", "1"], input=data,
                        stdout=subprocess.PIPE, check=True)
    return len(p.stdout)


def main():
    os.makedirs(DIST_DIR, exist_ok=True)
    books = build_books()

    with open(os.path.join(ENGINE_DIR, "espeakng.js"), "r", encoding="utf-8") as f:
        espeak_js = f.read()
    with open(os.path.join(ENGINE_DIR, "espeakng.wasm"), "rb") as f:
        wasm_b64 = base64.b64encode(f.read()).decode("ascii")
    with open(os.path.join(ENGINE_DIR, "espeakng.data"), "rb") as f:
        data_b64 = base64.b64encode(f.read()).decode("ascii")

    books_json = json.dumps(books, ensure_ascii=False, separators=(",", ":"))

    html = HTML_TEMPLATE.format(
        espeak_js=espeak_js,
        wasm_b64=wasm_b64,
        data_b64=data_b64,
        books_json=books_json,
    )

    out_path = os.path.join(DIST_DIR, "great_library_essentials_audiobook.html")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)

    raw_bytes = len(html.encode("utf-8"))
    compressed = xz_size(html.encode("utf-8"))
    net_bps = 4910
    runtime_s = compressed * 8 / net_bps
    c90_side_budget = 1_657_125  # bytes @ 4910 bps for 45 min

    print(f"n_books        = {len(books)}")
    print(f"raw bytes       = {raw_bytes:,}")
    print(f"xz -9e bytes    = {compressed:,}  ({compressed/1024:.1f} KB / {compressed/1e6:.4f} MB)")
    print(f"runtime @ {net_bps} bps = {runtime_s:.1f} s = {runtime_s/60:.2f} min")
    print(f"C90 side budget = {c90_side_budget:,} bytes (45 min)")
    print(f"fits one side?  = {compressed <= c90_side_budget}  "
          f"(margin {c90_side_budget - compressed:,} bytes)")
    print(f"output          = {out_path}")


HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>The Great Library &mdash; Essentials &mdash; a self-narrating cassette</title>
<style>
*, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
html, body {{ height: 100%; background: #1a1a2e; color: #e0d8cc; font-family: Georgia, 'Times New Roman', serif; }}

body {{ display: flex; flex-direction: column; min-height: 100vh; }}

header {{
  padding: 1.5rem 2rem 1rem;
  border-bottom: 1px solid #3a3040;
  background: #12121f;
  flex-shrink: 0;
}}
header h1 {{
  font-size: 1.35rem;
  font-weight: normal;
  color: #c9a86a;
  letter-spacing: 0.04em;
}}
header p.sub {{
  font-size: 0.8rem;
  color: #7a7060;
  margin-top: 0.25rem;
  font-style: italic;
}}

#status-bar {{
  padding: 0.4rem 2rem;
  font-size: 0.78rem;
  color: #8a7060;
  background: #14141f;
  flex-shrink: 0;
  min-height: 1.8rem;
  display: flex;
  align-items: center;
}}

#book-pane {{
  flex: 1;
  overflow-y: auto;
  padding: 2rem;
  scroll-behavior: smooth;
}}

.book-content {{
  max-width: 38rem;
  margin: 0 auto;
  line-height: 1.75;
  font-size: 1.05rem;
}}

.section-header {{
  font-size: 1.1rem;
  color: #c9a86a;
  letter-spacing: 0.1em;
  text-transform: uppercase;
  margin: 2.5rem 0 1.2rem;
  border-bottom: 1px solid #3a3040;
  padding-bottom: 0.4rem;
  font-weight: normal;
}}
.section-header:first-child {{ margin-top: 0; }}

.para {{
  margin-bottom: 1.1rem;
  position: relative;
}}

.sentence {{
  border-radius: 2px;
  transition: background 0.15s, color 0.15s;
}}

.sentence.active {{
  background: #3a3520;
  color: #f5e8b0;
  border-radius: 3px;
  padding: 0 2px;
  margin: 0 -2px;
}}

.para.current-para {{
  border-left: 2px solid #c9a86a44;
  padding-left: 0.75rem;
  margin-left: -0.75rem;
}}

footer {{
  padding: 0.6rem 2rem;
  font-size: 0.72rem;
  color: #50483c;
  background: #12121f;
  border-top: 1px solid #2a2838;
  flex-shrink: 0;
  text-align: center;
}}

#controls {{
  display: flex;
  align-items: center;
  gap: 0.75rem;
  padding: 0.8rem 2rem;
  background: #14141f;
  border-top: 1px solid #2a2838;
  flex-shrink: 0;
  flex-wrap: wrap;
}}

button {{
  background: #2a2838;
  color: #e0d8cc;
  border: 1px solid #4a4060;
  border-radius: 4px;
  padding: 0.4rem 1rem;
  font-family: inherit;
  font-size: 0.88rem;
  cursor: pointer;
  transition: background 0.12s;
}}
button:hover {{ background: #3a3848; }}
button:active {{ background: #4a4858; }}
button:disabled {{ opacity: 0.4; cursor: default; }}

#btn-play {{
  background: #c9a86a22;
  border-color: #c9a86a66;
  color: #c9a86a;
  min-width: 5rem;
}}
#btn-play:hover {{ background: #c9a86a33; }}

.speed-label {{
  font-size: 0.8rem;
  color: #8a7860;
  margin-left: 0.5rem;
}}
#speed-slider {{
  width: 100px;
  accent-color: #c9a86a;
}}
#speed-val {{
  font-size: 0.8rem;
  color: #c9a86a;
  min-width: 2rem;
  text-align: right;
}}

.progress-label {{
  margin-left: auto;
  font-size: 0.78rem;
  color: #6a6050;
}}

#loading-overlay {{
  position: fixed; inset: 0;
  background: #1a1a2eee;
  display: flex; align-items: center; justify-content: center;
  flex-direction: column;
  z-index: 100;
  gap: 1rem;
}}
#loading-overlay p {{
  color: #c9a86a;
  font-size: 1.1rem;
  letter-spacing: 0.05em;
}}
#loading-overlay .sub {{
  color: #6a6050;
  font-size: 0.82rem;
}}
.spinner {{
  width: 36px; height: 36px;
  border: 3px solid #3a3040;
  border-top-color: #c9a86a;
  border-radius: 50%;
  animation: spin 1s linear infinite;
}}
@keyframes spin {{ to {{ transform: rotate(360deg); }} }}

/* ===== Library selector screen ===== */
#library-pane {{
  flex: 1;
  overflow-y: auto;
  padding: 2rem;
}}
.library-list {{
  max-width: 38rem;
  margin: 0 auto;
  display: flex;
  flex-direction: column;
  gap: 0.6rem;
}}
.library-item {{
  background: #20202e;
  border: 1px solid #3a3040;
  border-radius: 6px;
  padding: 0.9rem 1.1rem;
  cursor: pointer;
  transition: background 0.12s, border-color 0.12s;
}}
.library-item:hover {{ background: #2a2a3c; border-color: #c9a86a66; }}
.library-item h3 {{
  font-size: 1.02rem;
  font-weight: normal;
  color: #e0d8cc;
}}
.library-item p {{
  font-size: 0.8rem;
  color: #8a7860;
  margin-top: 0.2rem;
  font-style: italic;
}}
</style>
</head>
<body>

<div id="loading-overlay">
  <div class="spinner"></div>
  <p>Loading eSpeak-ng...</p>
  <p class="sub">Initialising speech engine from tape</p>
</div>

<header>
  <h1 id="app-title">The Great Library &mdash; Essentials</h1>
  <p class="sub" id="app-sub">9 canonical public-domain classics &mdash; a self-narrating cassette</p>
</header>

<div id="status-bar">Initialising...</div>

<div id="library-pane">
  <div class="library-list" id="library-list"></div>
</div>

<div id="book-pane" style="display:none;">
  <div class="book-content" id="book-content"></div>
</div>

<div id="controls" style="display:none;">
  <button id="btn-back">&#8249; Library</button>
  <button id="btn-prev" disabled>&#9664;&#9664; Prev</button>
  <button id="btn-play" disabled>&#9654; Play</button>
  <button id="btn-next" disabled>&#9654;&#9654; Next</button>
  <span class="speed-label">Rate:</span>
  <input type="range" id="speed-slider" min="80" max="300" value="150">
  <span id="speed-val">150</span>
  <span class="progress-label" id="progress-label"></span>
</div>

<footer>
  Narrated by eSpeak-ng (GPLv3) &middot; bundled on the tape &middot; 9 public-domain classics &middot; The Magnetic Vault
</footer>

<script>
// ===== EMBEDDED BINARY DATA =====
const WASM_B64 = "{wasm_b64}";
const DATA_B64 = "{data_b64}";
const BOOKS = {books_json};
</script>

<script>
{espeak_js}
</script>

<script>
// ===== PLAYER =====

function b64toAB(b64) {{
  const bin = atob(b64);
  const buf = new ArrayBuffer(bin.length);
  const u8 = new Uint8Array(buf);
  for (let i = 0; i < bin.length; i++) u8[i] = bin.charCodeAt(i);
  return buf;
}}

function splitSentences(text) {{
  // Split on sentence boundaries, keeping delimiter attached to sentence
  // Don't split on Mr. Mrs. Dr. St. etc.
  const abbrevs = /\\b(Mr|Mrs|Ms|Dr|St|Prof|Jr|Sr|vs|etc|No|Vol|pp|Fig)\\./g;
  // Temporarily replace abbreviation dots with placeholder
  const placeholder = '\\x00';
  let t = text.replace(abbrevs, (m) => m.slice(0,-1) + placeholder);
  // Split on .!? followed by whitespace (or end)
  const parts = t.split(/(?<=[.!?]+)\\s+/);
  // Restore placeholders
  return parts.map(p => p.replace(new RegExp(placeholder, 'g'), '.')).filter(p => p.trim().length > 0);
}}

// Build flat sentence list from book items
// Each sentence: {{ paraIdx, sentIdx, text, dom: <span> }}
let sentences = [];
let paraElements = [];
let currentBookIdx = -1;

function buildLibrary() {{
  const list = document.getElementById('library-list');
  list.innerHTML = '';
  BOOKS.forEach((book, idx) => {{
    const div = document.createElement('div');
    div.className = 'library-item';
    const h3 = document.createElement('h3');
    h3.textContent = book.title;
    const p = document.createElement('p');
    p.textContent = book.author ? `${{book.author}}` : '';
    div.appendChild(h3);
    div.appendChild(p);
    div.addEventListener('click', () => openBook(idx));
    list.appendChild(div);
  }});
}}

function buildBook(book) {{
  const container = document.getElementById('book-content');
  container.innerHTML = '';
  sentences = [];
  paraElements = [];
  let sentGlobal = 0;
  let paraIdx = 0;

  for (const item of book.items) {{
    if (item.type === 'header') {{
      const h = document.createElement('div');
      h.className = 'section-header';
      h.textContent = item.text;
      container.appendChild(h);
    }} else {{
      const paraEl = document.createElement('p');
      paraEl.className = 'para';
      paraEl.dataset.paraIdx = paraIdx;

      const sents = splitSentences(item.text);
      const paraStart = sentGlobal;

      for (let si = 0; si < sents.length; si++) {{
        const span = document.createElement('span');
        span.className = 'sentence';
        span.textContent = sents[si] + (si < sents.length - 1 ? ' ' : '');
        span.dataset.sentIdx = sentGlobal;
        paraEl.appendChild(span);

        sentences.push({{
          paraIdx,
          sentIdx: sentGlobal,
          text: sents[si],
          dom: span
        }});
        sentGlobal++;
      }}

      paraElements.push({{ el: paraEl, start: paraStart, end: sentGlobal - 1 }});
      container.appendChild(paraEl);
      paraIdx++;
    }}
  }}
}}

function openBook(idx) {{
  stop();
  currentBookIdx = idx;
  const book = BOOKS[idx];
  document.getElementById('app-title').textContent = book.title;
  document.getElementById('app-sub').textContent = book.author ? `${{book.author}} \\u2014 a self-narrating cassette` : 'a self-narrating cassette';
  buildBook(book);
  currentSentIdx = 0;
  highlightSentence(0);
  updateProgress();

  document.getElementById('library-pane').style.display = 'none';
  document.getElementById('book-pane').style.display = '';
  document.getElementById('controls').style.display = '';
  document.getElementById('btn-back').style.display = '';
  setStatus(engineReady ? `${{book.title}} \\u2014 ready. Click Play to begin.` : 'Loading eSpeak-ng...');
  setControlsEnabled(engineReady);
}}

function backToLibrary() {{
  stop();
  document.getElementById('library-pane').style.display = '';
  document.getElementById('book-pane').style.display = 'none';
  document.getElementById('controls').style.display = 'none';
  document.getElementById('btn-back').style.display = 'none';
  document.getElementById('app-title').textContent = 'The Great Library \\u2014 Essentials';
  document.getElementById('app-sub').textContent = '9 canonical public-domain classics \\u2014 a self-narrating cassette';
  setStatus(engineReady ? 'Choose a book.' : 'Loading eSpeak-ng...');
}}

// ===== AUDIO ENGINE =====
let M = null;  // Emscripten module
let audioCtx = null;
let currentSentIdx = 0;
let isPlaying = false;
let scheduledEnd = 0;
let pendingSource = null;
let pendingBuf = null;
let pendingSentIdx = -1;
let rateValue = 150;
let engineReady = false;

function setStatus(msg) {{
  document.getElementById('status-bar').textContent = msg;
}}

function setControlsEnabled(on) {{
  document.getElementById('btn-play').disabled = !on;
  document.getElementById('btn-prev').disabled = !on;
  document.getElementById('btn-next').disabled = !on;
}}

function updateProgress() {{
  const label = document.getElementById('progress-label');
  if (sentences.length > 0) {{
    label.textContent = `${{currentSentIdx + 1}} / ${{sentences.length}} sentences`;
  }} else {{
    label.textContent = '';
  }}
}}

function int16ToFloat32(pcm) {{
  const f = new Float32Array(pcm.length);
  for (let i = 0; i < pcm.length; i++) f[i] = pcm[i] / 32768.0;
  return f;
}}

function synthesise(text) {{
  // Encode text + null terminator
  const enc = new TextEncoder();
  const b = enc.encode(text + "\\0");
  const p = M._malloc(b.length);
  M.HEAPU8.set(b, p);
  const n = M._espeak_synth_text(p);
  M._free(p);
  if (n <= 0) return null;
  const pcm = new Int16Array(M.HEAP16.buffer, M._espeak_get_pcm_buf(), n);
  // Copy out (HEAP view might be invalidated)
  const copy = new Int16Array(pcm);
  return copy;
}}

function makeAudioBuf(pcm) {{
  const f32 = int16ToFloat32(pcm);
  const buf = audioCtx.createBuffer(1, f32.length, 22050);
  buf.copyToChannel(f32, 0);
  return buf;
}}

function highlightSentence(idx) {{
  // Remove all highlights
  document.querySelectorAll('.sentence.active').forEach(el => el.classList.remove('active'));
  document.querySelectorAll('.para.current-para').forEach(el => el.classList.remove('current-para'));

  if (idx < 0 || idx >= sentences.length) return;

  const sent = sentences[idx];
  sent.dom.classList.add('active');

  // Highlight parent para
  const paraInfo = paraElements[sent.paraIdx];
  if (paraInfo) paraInfo.el.classList.add('current-para');

  // Scroll into view
  sent.dom.scrollIntoView({{ behavior: 'smooth', block: 'center' }});
}}

function scheduleNext() {{
  if (!isPlaying) return;

  const idx = currentSentIdx;
  if (idx >= sentences.length) {{
    stop();
    setStatus('Finished.');
    return;
  }}

  highlightSentence(idx);
  updateProgress();

  const sent = sentences[idx];
  let pcm;
  if (pendingSentIdx === idx && pendingBuf !== null) {{
    // Use pre-synthesised
    pcm = pendingBuf;
    pendingBuf = null;
    pendingSentIdx = -1;
  }} else {{
    setStatus(`Synthesising: ${{sent.text.substring(0, 60)}}...`);
    pcm = synthesise(sent.text);
  }}

  if (!pcm || pcm.length === 0) {{
    // Skip empty sentence
    currentSentIdx++;
    scheduleNext();
    return;
  }}

  const audioBuf = makeAudioBuf(pcm);
  const src = audioCtx.createBufferSource();
  src.buffer = audioBuf;
  src.connect(audioCtx.destination);

  const now = audioCtx.currentTime;
  const startAt = Math.max(now, scheduledEnd);
  src.start(startAt);
  scheduledEnd = startAt + audioBuf.duration;

  setStatus(`Playing sentence ${{idx + 1}} of ${{sentences.length}}`);

  // Pre-synthesise next sentence in a microtask
  const nextIdx = idx + 1;
  if (nextIdx < sentences.length) {{
    // Synthesise next during playback
    requestAnimationFrame(() => {{
      if (isPlaying && pendingSentIdx !== nextIdx) {{
        pendingBuf = synthesise(sentences[nextIdx].text);
        pendingSentIdx = nextIdx;
      }}
    }});
  }}

  src.onended = () => {{
    if (!isPlaying) return;
    currentSentIdx++;
    scheduleNext();
  }};
}}

function play() {{
  if (!M || currentBookIdx < 0) return;
  if (!audioCtx) {{
    audioCtx = new AudioContext({{ sampleRate: 22050 }});
  }}
  if (audioCtx.state === 'suspended') {{
    audioCtx.resume();
  }}
  isPlaying = true;
  scheduledEnd = 0;
  document.getElementById('btn-play').textContent = '\\u258E\\u258E Pause';
  scheduleNext();
}}

function pause() {{
  isPlaying = false;
  if (audioCtx) audioCtx.suspend();
  document.getElementById('btn-play').textContent = '\\u25B6 Play';
  setStatus('Paused.');
}}

function stop() {{
  isPlaying = false;
  document.getElementById('btn-play').textContent = '\\u25B6 Play';
}}

function goTo(idx) {{
  const wasPlaying = isPlaying;
  stop();
  if (audioCtx) audioCtx.suspend();
  pendingBuf = null;
  pendingSentIdx = -1;
  scheduledEnd = 0;
  currentSentIdx = Math.max(0, Math.min(idx, sentences.length - 1));
  highlightSentence(currentSentIdx);
  updateProgress();
  if (wasPlaying) play();
}}

// ===== INIT =====

async function init() {{
  buildLibrary();
  setStatus('Loading eSpeak-ng...');

  const wasmBinary = b64toAB(WASM_B64);
  const dataBinary = b64toAB(DATA_B64);

  // Configure module before calling espeakng()
  const moduleConfig = {{
    wasmBinary: wasmBinary,
    locateFile: function(path) {{
      return path; // won't be used for wasm (wasmBinary is set)
    }},
    getPreloadedPackage: function(remotePackageName, remotePackageSize) {{
      if (remotePackageName === 'espeakng.data') return dataBinary;
      return null;
    }}
  }};

  try {{
    M = await espeakng(moduleConfig);
    const sr = M._espeak_init();
    M._espeak_set_voice_en();
    engineReady = true;
    setStatus(`eSpeak-ng ready (sample rate: ${{sr}} Hz). Choose a book.`);
    if (currentBookIdx >= 0) setControlsEnabled(true);

    // Hide loading overlay
    document.getElementById('loading-overlay').style.display = 'none';
  }} catch(e) {{
    setStatus('Error loading eSpeak-ng: ' + e.message);
    document.getElementById('loading-overlay').querySelector('p').textContent = 'Error: ' + e.message;
  }}
}}

// Controls
document.getElementById('btn-play').addEventListener('click', () => {{
  if (!M) return;
  if (isPlaying) {{
    pause();
  }} else {{
    play();
  }}
}});

document.getElementById('btn-prev').addEventListener('click', () => {{
  goTo(currentSentIdx - 1);
}});

document.getElementById('btn-next').addEventListener('click', () => {{
  goTo(currentSentIdx + 1);
}});

document.getElementById('btn-back').addEventListener('click', backToLibrary);

// Speed slider (purely cosmetic for rate display — rate is fixed at compile time in eSpeak wrapper)
const slider = document.getElementById('speed-slider');
const speedVal = document.getElementById('speed-val');
slider.addEventListener('input', () => {{
  rateValue = parseInt(slider.value);
  speedVal.textContent = rateValue;
  // Note: eSpeak-ng rate is fixed at 150 wpm (no set_parameter export)
  // Slider is visual only in this build
}});

window.addEventListener('load', init);
</script>
</body>
</html>
"""

if __name__ == "__main__":
    main()
