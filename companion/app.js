/* app.js — MAGNETIC VAULT Field Decoder.
   Record lossless PCM, show live line quality, and decode a cassette data tape
   to bytes via the WASM build of the Rust `cassette-codec` core.

   Graceful degradation: if the WASM module isn't built yet, record + quality
   still work; decode is disabled with a clear note. */

const $ = (id) => document.getElementById(id);
const ui = {
  status: $("statusLine"), counter: $("counter"), scope: $("scope"),
  rec: $("recBtn"), stop: $("stopBtn"), file: $("fileInput"), dl: $("dlBtn"),
  reelL: $("reelL"), reelR: $("reelR"),
  vuFill: $("vuFill"), clip: $("clipLed"),
  snr: $("snrVal"), lvl: $("lvlVal"), flt: $("fltVal"), lock: $("lockVal"),
  rating: $("rating"), grade: $("gradeVal"),
  decodeStatus: $("decodeStatus"), speed: $("speedVal"), cw: $("cwVal"), bytes: $("bytesVal"),
  hex: $("hexview"), decodeBtn: $("decodeBtn"), saveData: $("saveDataBtn"),
  codecBadge: $("codecBadge"),
};

let state = {
  recording: false, actx: null, node: null, stream: null, analyser: null,
  chunks: [], total: 0, sr: 48000, t0: 0, raf: 0,
  captured: null,   // Float32Array of the current take (mono)
  capturedSr: 48000,
  decoded: null,    // Uint8Array recovered bytes
  manifest: null,
  wasm: null,
  wakeLock: null,
};

// ── load bundled tape manifest + (optional) wasm core ─────────────────────
async function boot() {
  try {
    state.manifest = await (await fetch("floor_manifest.json")).json();
  } catch (e) {
    setStatus("manifest missing");
  }
  try {
    const mod = await import("./pkg/cassette_codec_wasm.js");
    await mod.default(); // init wasm
    state.wasm = mod;
    ui.codecBadge.textContent = "codec: cassette-codec (rust/wasm) ✓";
  } catch (e) {
    ui.codecBadge.textContent = "codec: not built — record/quality only";
    console.warn("wasm core not available:", e);
  }
  refreshButtons();
}

function setStatus(s) { ui.status.textContent = s; }
function refreshButtons() {
  ui.dl.disabled = !state.captured;
  ui.decodeBtn.disabled = !(state.captured && state.wasm && state.manifest);
  ui.saveData.disabled = !state.decoded;
}

// ── screen wake lock ───────────────────────────────────────────────────────
// Keep the screen awake while recording so iOS doesn't dim/lock and throttle the
// AudioWorklet (the cause of the dropped-samples capture). Released on STOP.
async function acquireWakeLock() {
  if (!("wakeLock" in navigator)) return;
  try {
    state.wakeLock = await navigator.wakeLock.request("screen");
    state.wakeLock.addEventListener?.("release", () => { state.wakeLock = null; });
  } catch (e) { /* user setting / low battery can refuse — non-fatal */ }
}
async function releaseWakeLock() {
  try { await state.wakeLock?.release(); } catch (e) {}
  state.wakeLock = null;
}
// re-acquire if the tab was hidden and comes back while still recording
document.addEventListener("visibilitychange", () => {
  if (state.recording && document.visibilityState === "visible" && !state.wakeLock) {
    acquireWakeLock();
  }
});

// Expected signal span from the bundled manifest (end-chirp time, seconds).
function expectedSignalSeconds() {
  const c1 = state.manifest?.tx_chirp1 ?? 0;
  return c1 ? c1 / 48000 : 0; // ~93.8 s for the full-spectrum tape
}

// ── recording ─────────────────────────────────────────────────────────────
async function startRec() {
  try {
    state.stream = await navigator.mediaDevices.getUserMedia({
      audio: {
        channelCount: 1, echoCancellation: false, noiseSuppression: false,
        autoGainControl: false, sampleRate: 48000,
      },
    });
  } catch (e) {
    setStatus("MIC DENIED"); return;
  }
  state.actx = new (window.AudioContext || window.webkitAudioContext)({ sampleRate: 48000 });
  state.sr = state.actx.sampleRate;
  await state.actx.audioWorklet.addModule("recorder-worklet.js");
  const src = state.actx.createMediaStreamSource(state.stream);
  state.node = new AudioWorkletNode(state.actx, "rec-proc");
  state.analyser = state.actx.createAnalyser();
  state.analyser.fftSize = 1024;
  src.connect(state.analyser);
  src.connect(state.node);
  // worklet output isn't routed to speakers (avoid feedback)

  state.chunks = []; state.total = 0;
  state.node.port.onmessage = (e) => {
    state.chunks.push(e.data);
    state.total += e.data.length;
  };

  state.recording = true; state.t0 = performance.now();
  acquireWakeLock();                              // keep screen awake → no dropouts
  ui.rec.setAttribute("aria-pressed", "true");
  ui.stop.disabled = false; ui.rec.disabled = true;
  ui.reelL.classList.add("spin"); ui.reelR.classList.add("spin");
  setStatus("● RECORDING — keep app open");
  ui.rating.dataset.grade = ""; ui.grade.textContent = "·";
  liveLoop();
}

function stopRec() {
  if (!state.recording) return;
  state.recording = false;
  releaseWakeLock();
  cancelAnimationFrame(state.raf);
  ui.reelL.classList.remove("spin"); ui.reelR.classList.remove("spin");
  ui.rec.setAttribute("aria-pressed", "false");
  ui.stop.disabled = true; ui.rec.disabled = false;
  try { state.node.disconnect(); state.stream.getTracks().forEach(t => t.stop()); } catch (e) {}

  // assemble one contiguous Float32 buffer (lossless)
  const buf = new Float32Array(state.total);
  let off = 0;
  for (const c of state.chunks) { buf.set(c, off); off += c.length; }
  state.captured = buf; state.capturedSr = state.sr;
  state.actx.close();
  const durS = buf.length / state.sr;
  const wallS = (performance.now() - state.t0) / 1000;

  // Guard 1 — dropped samples: AudioWorklet under-delivered vs wall clock
  // (iOS throttling). If captured audio is much shorter than elapsed time, warn.
  if (wallS > 4 && durS < wallS * 0.9) {
    setStatus(`⚠ DROPPED AUDIO — captured ${durS.toFixed(1)}s of ${wallS.toFixed(0)}s`);
    setDecode("recording lost samples (screen throttling). Keep the app foreground & screen on, re-record.", "err");
  }
  // Guard 2 — too short to hold both sync chirps (the truncated-capture failure)
  else if (expectedSignalSeconds() && durS < expectedSignalSeconds() + 2) {
    setStatus(`⚠ TOO SHORT — ${durS.toFixed(1)}s (need ≥ ${(expectedSignalSeconds()+2).toFixed(0)}s through the end chirp)`);
    setDecode("recording likely missing the end chirp — record through the final down-sweep.", "err");
  } else {
    setStatus(`CAPTURED ${durS.toFixed(1)}s`);
  }
  drawScope(buf, true);
  postQuality(buf, state.sr);
  refreshButtons();
}

// ── live meters ─────────────────────────────────────────────────────────
function liveLoop() {
  const a = state.analyser;
  const td = new Float32Array(a.fftSize);
  const tick = () => {
    if (!state.recording) return;
    a.getFloatTimeDomainData(td);
    let sum = 0, peak = 0;
    for (let i = 0; i < td.length; i++) { sum += td[i] * td[i]; const x = Math.abs(td[i]); if (x > peak) peak = x; }
    const rms = Math.sqrt(sum / td.length);
    ui.vuFill.style.width = Math.min(100, rms * 320).toFixed(0) + "%";
    ui.clip.classList.toggle("on", peak > 0.98);
    drawScope(td, false);
    const sec = (performance.now() - state.t0) / 1000;
    ui.counter.textContent = sec.toFixed(1).padStart(5, "0");
    // reel takeup illusion: shrink left, grow right
    state.raf = requestAnimationFrame(tick);
  };
  state.raf = requestAnimationFrame(tick);
}

function drawScope(samples, full) {
  const cv = ui.scope, g = cv.getContext("2d");
  const W = cv.width, H = cv.height;
  g.clearRect(0, 0, W, H);
  g.fillStyle = "#0c0b08"; g.fillRect(0, 0, W, H);
  g.strokeStyle = "#9fe0a6"; g.lineWidth = 1; g.beginPath();
  const step = Math.max(1, Math.floor(samples.length / W));
  for (let x = 0; x < W; x++) {
    let min = 1, max = -1;
    for (let j = 0; j < step; j++) {
      const v = samples[x * step + j] || 0;
      if (v < min) min = v; if (v > max) max = v;
    }
    const y1 = (1 - (max * 0.9 + 1) / 2) * H;
    const y2 = (1 - (min * 0.9 + 1) / 2) * H;
    g.moveTo(x + 0.5, y1); g.lineTo(x + 0.5, y2);
  }
  g.stroke();
  // center line
  g.strokeStyle = "rgba(159,224,166,.25)"; g.beginPath(); g.moveTo(0, H/2); g.lineTo(W, H/2); g.stroke();
}

// ── line-quality estimate (honest, JS-side) ───────────────────────────────
function postQuality(buf, sr) {
  // RMS / peak / clip over the whole take
  let sum = 0, peak = 0, clip = 0;
  for (let i = 0; i < buf.length; i++) {
    const v = buf[i]; sum += v * v; const a = Math.abs(v);
    if (a > peak) peak = a; if (a > 0.985) clip++;
  }
  const rms = Math.sqrt(sum / Math.max(1, buf.length));
  const clipPct = (100 * clip / Math.max(1, buf.length));
  ui.lvl.textContent = rms.toFixed(3);

  // crude broadband SNR: loud frames (signal) vs quietest frames (noise floor)
  const F = 2048, nf = Math.floor(buf.length / F);
  const energies = [];
  for (let k = 0; k < nf; k++) {
    let s = 0; for (let i = 0; i < F; i++) s += buf[k*F+i] ** 2;
    energies.push(s / F);
  }
  energies.sort((a, b) => a - b);
  if (energies.length > 8) {
    const noise = avg(energies.slice(0, Math.max(1, energies.length >> 3)));
    const sig = avg(energies.slice(-Math.max(1, energies.length >> 2)));
    const snr = 10 * Math.log10((sig + 1e-12) / (noise + 1e-12));
    ui.snr.textContent = isFinite(snr) ? snr.toFixed(1) : "–";
    state._snr = snr;
  } else { ui.snr.textContent = "–"; state._snr = null; }

  ui.clip.classList.toggle("on", clipPct > 0.05);
  ui.flt.textContent = "—"; // full flutter readout = sounder v2
  ui.vuFill.style.width = Math.min(100, rms * 320).toFixed(0) + "%";
  state._clipPct = clipPct;
  gradeNow();
}

const avg = (a) => a.reduce((x, y) => x + y, 0) / a.length;

function gradeNow(lockQuality) {
  // grade from SNR (60%), clip (20%), lock (20%)
  let score = 0.5;
  if (state._snr != null) score = Math.max(0, Math.min(1, (state._snr - 6) / 30));
  let g = score;
  if (state._clipPct > 0.2) g -= 0.25;
  if (lockQuality != null) g = 0.5 * g + 0.5 * Math.max(0, Math.min(1, (lockQuality - 2) / 8));
  const grade = g > 0.8 ? "A" : g > 0.62 ? "B" : g > 0.42 ? "C" : g > 0.22 ? "D" : "F";
  ui.rating.dataset.grade = grade; ui.grade.textContent = grade;
}

// ── decode ────────────────────────────────────────────────────────────────
async function decode() {
  if (!state.captured || !state.wasm || !state.manifest) return;
  setDecode("syncing + decoding…", "work");
  ui.decodeBtn.disabled = true;
  await new Promise(r => setTimeout(r, 30)); // let UI paint
  try {
    const samples48 = WavKit.resampleTo48k(state.captured, state.capturedSr);
    const t0 = performance.now();
    const res = state.wasm.decode_floor(samples48, JSON.stringify(state.manifest));
    const ms = (performance.now() - t0).toFixed(0);
    // res: { ok, bytes (Uint8Array), speed, align, cw_failed, n_cw, lock_quality }
    state.decoded = res.bytes;
    ui.speed.textContent = res.speed.toFixed(3);
    ui.cw.textContent = `${res.cw_failed}/${res.n_cw} fail`;
    ui.bytes.textContent = res.bytes.length;
    ui.lock.textContent = res.lock_quality > 3 ? "LOCK" : "weak";
    ui.lock.className = "lock " + (res.lock_quality > 3 ? "on" : "off");
    gradeNow(res.lock_quality);
    renderHex(res.bytes);
    const clean = res.cw_failed === 0;
    // real decks run ~0.85–1.15×; below that the global sync found a spurious
    // end-chirp (truncated capture), not a genuinely slow deck.
    const syncBad = res.speed < 0.85 || res.speed > 1.15 || res.lock_quality < 3;
    let msg;
    if (clean) {
      msg = [`✓ DECODED ${res.bytes.length} bytes · deck ${res.speed.toFixed(3)}× · ${ms} ms`, "ok"];
    } else if (syncBad) {
      // garbage speed / weak lock = couldn't find both chirps → truncated capture
      msg = [`sync failed (speed ${res.speed.toFixed(2)}) — recording is likely truncated. Record through the end chirp.`, "err"];
    } else if (res.cw_failed >= res.n_cw) {
      // synced fine but every codeword lost = acoustic HF rolloff killing the tone bank
      msg = [`synced OK but all data lost — acoustic capture rolls off the high tones this rung needs. Use a wired line-in (or the upcoming R0 acoustic rung).`, "err"];
    } else {
      msg = [`partial: recovered ${res.cw_failed}/${res.n_cw} codewords lost · ${ms} ms`, "err"];
    }
    setDecode(msg[0], msg[1]);
  } catch (e) {
    console.error(e);
    setDecode("decode error: " + e, "err");
  }
  ui.decodeBtn.disabled = false;
  refreshButtons();
}

function setDecode(s, cls) { ui.decodeStatus.textContent = s; ui.decodeStatus.className = "decode__status " + (cls || ""); }

function renderHex(bytes) {
  const lines = [];
  const max = Math.min(bytes.length, 512);
  for (let i = 0; i < max; i += 16) {
    let hex = "", asc = "";
    for (let j = 0; j < 16 && i + j < max; j++) {
      const b = bytes[i + j];
      hex += b.toString(16).padStart(2, "0") + " ";
      asc += (b >= 32 && b < 127) ? String.fromCharCode(b) : ".";
    }
    lines.push(i.toString(16).padStart(6, "0") + "  " + hex.padEnd(48) + " " + asc);
  }
  if (bytes.length > max) lines.push(`… (+${bytes.length - max} bytes)`);
  ui.hex.textContent = lines.join("\n");
}

// ── downloads ──────────────────────────────────────────────────────────────
function download(blob, name) {
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob); a.download = name;
  document.body.appendChild(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(a.href), 2000);
}
function saveWav() {
  if (!state.captured) return;
  download(WavKit.encodeFloat32Wav(state.captured, state.capturedSr),
    `magnetic-vault-${Date.now()}.wav`);
}
function saveData() {
  if (!state.decoded) return;
  download(new Blob([state.decoded], { type: "application/octet-stream" }),
    `decoded-${Date.now()}.bin`);
}

// ── load existing recording ────────────────────────────────────────────────
async function loadFile(file) {
  setStatus("DECODING FILE…");
  try {
    const { samples, sampleRate } = await WavKit.decodeToMono(file);
    state.captured = samples; state.capturedSr = sampleRate;
    setStatus(`LOADED ${(samples.length / sampleRate).toFixed(1)}s @ ${sampleRate}Hz`);
    drawScope(samples, true);
    postQuality(samples, sampleRate);
    refreshButtons();
  } catch (e) {
    setStatus("LOAD FAILED");
    console.error(e);
  }
}

// ── wire up ─────────────────────────────────────────────────────────────────
ui.rec.addEventListener("click", startRec);
ui.stop.addEventListener("click", stopRec);
ui.dl.addEventListener("click", saveWav);
ui.decodeBtn.addEventListener("click", decode);
ui.saveData.addEventListener("click", saveData);
ui.file.addEventListener("change", (e) => { if (e.target.files[0]) loadFile(e.target.files[0]); });

if ("serviceWorker" in navigator) {
  navigator.serviceWorker.register("sw.js").catch(() => {});
}

boot();
