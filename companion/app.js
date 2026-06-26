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
  captured: null,   // Float32Array of the current take (mono mix)
  capturedChannels: null, // per-channel Float32Array[] (stereo files → R3)
  capturedSr: 48000,
  decoded: null,    // Uint8Array recovered bytes
  manifest: null,   // floor rung (combinatorial-MFSK)
  manifestR0: null, // R0 DQPSK (survives acoustic)
  manifestR1: null, // R1 DQPSK
  manifestR2: null, // R2 D2X (mono)
  manifestR3: null, // R3 D2X (independent stereo → ~9820)
  wasm: null,
  wakeLock: null,
};

// ── load bundled tape manifests + (optional) wasm core ─────────────────────
async function boot() {
  try {
    state.manifest = await (await fetch("floor_manifest.json")).json();
  } catch (e) {
    setStatus("manifest missing");
  }
  for (const [key, file] of [["manifestR0", "r0_manifest.json"], ["manifestR1", "r1_manifest.json"],
                             ["manifestR2", "r2_manifest.json"], ["manifestR3", "r3_manifest.json"]]) {
    try { state[key] = await (await fetch(file)).json(); } catch (e) { /* optional rung */ }
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
  state.captured = buf; state.capturedSr = state.sr; state.capturedChannels = [buf];
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
  ui.decodeBtn.disabled = true;
  await new Promise(r => setTimeout(r, 30)); // let UI paint
  try {
    const samples48 = WavKit.resampleTo48k(state.captured, state.capturedSr);

    // ── stereo R3 first (independent L/R D2X → ~9820 bps) when we have 2 channels.
    // Acoustic phone captures are mono, so this only fires for a wired stereo file.
    const chans = state.capturedChannels;
    if (state.manifestR3 && state.wasm.decode_d2x && chans && chans.length >= 2) {
      setDecode("trying R3 stereo (L+R)…", "work");
      await new Promise(res => setTimeout(res, 20));
      const t0 = performance.now();
      const L = WavKit.resampleTo48k(chans[0], state.capturedSr);
      const R = WavKit.resampleTo48k(chans[1], state.capturedSr);
      const mL = JSON.stringify(state.manifestR3);
      const mR = JSON.stringify({ ...state.manifestR3, crc32_codewords: state.manifestR3.crc32_codewords_R });
      const dl = state.wasm.decode_d2x(L, mL);
      const dr = state.wasm.decode_d2x(R, mR);
      if (dl.cw_failed === 0 && dr.cw_failed === 0) {
        const ms = (performance.now() - t0).toFixed(0);
        const total = dl.bytes.length + dr.bytes.length;
        state.decoded = (() => { const a = new Uint8Array(total); a.set(dl.bytes, 0); a.set(dr.bytes, dl.bytes.length); return a; })();
        ui.speed.textContent = dl.speed.toFixed(3);
        ui.cw.textContent = `0/${dl.n_cw + dr.n_cw} fail`;
        ui.bytes.textContent = total;
        ui.lock.textContent = "LOCK"; ui.lock.className = "lock on";
        gradeNow(dl.lock_quality);
        renderHex(state.decoded);
        setDecode(`✓ DECODED ${total} bytes via R3 stereo (L+R) · ~9820 bps · deck ${dl.speed.toFixed(3)}× · ${ms} ms`, "ok");
        ui.decodeBtn.disabled = false; refreshButtons();
        return;
      }
    }

    // ── mono ladder, highest-rate-first; first byte-exact wins, else least-bad.
    const rungs = [];
    if (state.manifestR2 && state.wasm.decode_d2x)
      rungs.push({ name: "R2 D2X", net: 3362, fn: "decode_d2x", manifest: state.manifestR2 });
    if (state.manifestR1 && state.wasm.decode_r0)
      rungs.push({ name: "R1 DQPSK", net: 2809, fn: "decode_r0", manifest: state.manifestR1 });
    if (state.manifestR0 && state.wasm.decode_r0)
      rungs.push({ name: "R0 DQPSK", net: 1868, fn: "decode_r0", manifest: state.manifestR0 });
    rungs.push({ name: "floor MFSK", net: 1129, fn: "decode_floor", manifest: state.manifest });

    let best = null;
    for (const r of rungs) {
      setDecode(`trying ${r.name}…`, "work");
      await new Promise(res => setTimeout(res, 20));
      const t0 = performance.now();
      const res = state.wasm[r.fn](samples48, JSON.stringify(r.manifest));
      res._ms = (performance.now() - t0).toFixed(0);
      res._rung = r.name;
      if (res.cw_failed === 0) { best = res; break; }          // byte-exact → done
      // keep the least-bad partial as fallback
      if (!best || res.cw_failed < best.cw_failed) best = res;
    }

    // surface the chosen result
    state.decoded = best.bytes;
    ui.speed.textContent = best.speed.toFixed(3);
    ui.cw.textContent = `${best.cw_failed}/${best.n_cw} fail`;
    ui.bytes.textContent = best.bytes.length;
    ui.lock.textContent = best.lock_quality > 3 ? "LOCK" : "weak";
    ui.lock.className = "lock " + (best.lock_quality > 3 ? "on" : "off");
    gradeNow(best.lock_quality);
    renderHex(best.bytes);

    const clean = best.cw_failed === 0;
    const syncBad = best.speed < 0.85 || best.speed > 1.15 || best.lock_quality < 3;
    let msg;
    if (clean) {
      msg = [`✓ DECODED ${best.bytes.length} bytes via ${best._rung} · deck ${best.speed.toFixed(3)}× · ${best._ms} ms`, "ok"];
    } else if (syncBad) {
      msg = [`sync failed (speed ${best.speed.toFixed(2)}) — recording is likely truncated. Record through the end chirp.`, "err"];
    } else if (best.cw_failed >= best.n_cw) {
      msg = [`synced OK but no rung decoded — capture too degraded (HF rolloff / level). Try a wired line-in or a cleaner deck.`, "err"];
    } else {
      msg = [`partial via ${best._rung}: ${best.cw_failed}/${best.n_cw} codewords lost · ${best._ms} ms`, "err"];
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
    const { samples, channels, sampleRate } = await WavKit.decodeToMono(file);
    state.captured = samples; state.capturedSr = sampleRate;
    state.capturedChannels = channels || [samples];
    const stereo = state.capturedChannels.length >= 2 ? " · stereo (R3 enabled)" : "";
    setStatus(`LOADED ${(samples.length / sampleRate).toFixed(1)}s @ ${sampleRate}Hz${stereo}`);
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
