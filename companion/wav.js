/* wav.js — lossless 32-bit float WAV encode + any-audio decode to mono f32.
   Global `WavKit` (loaded as a classic script before app.js). */
(function (global) {
  "use strict";

  // Encode mono Float32 PCM -> 32-bit IEEE float WAV Blob (lossless).
  function encodeFloat32Wav(samples, sampleRate) {
    const n = samples.length;
    const bytesPerSample = 4;
    const blockAlign = bytesPerSample; // mono
    const dataSize = n * bytesPerSample;
    const buf = new ArrayBuffer(44 + dataSize);
    const dv = new DataView(buf);
    let p = 0;
    const str = (s) => { for (let i = 0; i < s.length; i++) dv.setUint8(p++, s.charCodeAt(i)); };
    const u32 = (v) => { dv.setUint32(p, v, true); p += 4; };
    const u16 = (v) => { dv.setUint16(p, v, true); p += 2; };
    str("RIFF"); u32(36 + dataSize); str("WAVE");
    str("fmt "); u32(16); u16(3 /* IEEE float */); u16(1 /* mono */);
    u32(sampleRate); u32(sampleRate * blockAlign); u16(blockAlign); u16(32);
    str("data"); u32(dataSize);
    for (let i = 0; i < n; i++) { dv.setFloat32(p, samples[i], true); p += 4; }
    return new Blob([buf], { type: "audio/wav" });
  }

  // Parse a RIFF/WAVE buffer directly (no resample) -> {samples mono, sampleRate}
  // Handles IEEE float32 (fmt 3) and PCM 16/24/32 (fmt 1). Returns null if not WAV.
  function parseWav(arr) {
    const dv = new DataView(arr);
    if (dv.byteLength < 44) return null;
    const tag = (o) => String.fromCharCode(dv.getUint8(o), dv.getUint8(o+1), dv.getUint8(o+2), dv.getUint8(o+3));
    if (tag(0) !== "RIFF" || tag(8) !== "WAVE") return null;
    let p = 12, fmt = null, dataOff = -1, dataLen = 0;
    while (p + 8 <= dv.byteLength) {
      const id = tag(p), sz = dv.getUint32(p + 4, true);
      if (id === "fmt ") {
        fmt = {
          format: dv.getUint16(p + 8, true),
          channels: dv.getUint16(p + 10, true),
          rate: dv.getUint32(p + 12, true),
          bits: dv.getUint16(p + 22, true),
        };
      } else if (id === "data") { dataOff = p + 8; dataLen = sz; }
      p += 8 + sz + (sz & 1);
    }
    if (!fmt || dataOff < 0) return null;
    const ch = fmt.channels, bytes = fmt.bits >> 3;
    const frames = Math.floor(dataLen / (bytes * ch));
    const out = new Float32Array(frames);                 // mono mix
    const channels = Array.from({ length: ch }, () => new Float32Array(frames));
    let o = dataOff;
    for (let i = 0; i < frames; i++) {
      let acc = 0;
      for (let c = 0; c < ch; c++) {
        let v;
        if (fmt.format === 3 && fmt.bits === 32) v = dv.getFloat32(o, true);
        else if (fmt.bits === 16) v = dv.getInt16(o, true) / 32768;
        else if (fmt.bits === 32) v = dv.getInt32(o, true) / 2147483648;
        else if (fmt.bits === 24) {
          const b0 = dv.getUint8(o), b1 = dv.getUint8(o+1), b2 = dv.getUint8(o+2);
          let s = b0 | (b1 << 8) | (b2 << 16); if (s & 0x800000) s |= ~0xffffff;
          v = s / 8388608;
        } else v = 0;
        channels[c][i] = v; acc += v; o += bytes;
      }
      out[i] = acc / ch;
    }
    return { samples: out, channels, sampleRate: fmt.rate };
  }

  // Decode any audio File/ArrayBuffer -> { samples: Float32Array(mono mix),
  // channels: [Float32Array per channel], sampleRate }.
  async function decodeToMono(fileOrBuffer) {
    const arr = fileOrBuffer instanceof ArrayBuffer
      ? fileOrBuffer
      : await fileOrBuffer.arrayBuffer();
    // Prefer exact manual WAV parse (browser decodeAudioData resamples to the
    // context rate, which would corrupt our narrowband tones).
    const wav = parseWav(arr);
    if (wav) return wav;
    // Fallback for compressed formats (m4a/mp3/qta/ogg): decodeAudioData.
    const actx = new (global.AudioContext || global.webkitAudioContext)();
    const audio = await actx.decodeAudioData(arr.slice(0));
    const ch = audio.numberOfChannels;
    const len = audio.length;
    const out = new Float32Array(len);
    const channels = [];
    for (let c = 0; c < ch; c++) channels.push(audio.getChannelData(c).slice(0));
    for (let c = 0; c < ch; c++) {
      const d = channels[c];
      for (let i = 0; i < len; i++) out[i] += d[i] / ch;
    }
    const sr = audio.sampleRate;
    actx.close();
    return { samples: out, channels, sampleRate: sr };
  }

  // High-quality-ish linear+ resample to 48 kHz if needed (decoder expects 48k).
  // Uses Catmull-Rom interpolation — adequate; the decoder's own sync/RS absorb
  // small residue. (The Rust core also has a polyphase resampler used internally.)
  function resampleTo48k(samples, sampleRate) {
    const target = 48000;
    if (sampleRate === target) return samples;
    const ratio = target / sampleRate;
    const outLen = Math.round(samples.length * ratio);
    const out = new Float32Array(outLen);
    const cr = (p0, p1, p2, p3, t) => {
      const t2 = t * t, t3 = t2 * t;
      return 0.5 * ((2 * p1) + (-p0 + p2) * t + (2*p0 - 5*p1 + 4*p2 - p3) * t2 + (-p0 + 3*p1 - 3*p2 + p3) * t3);
    };
    for (let i = 0; i < outLen; i++) {
      const x = i / ratio;
      const i1 = Math.floor(x), t = x - i1;
      const i0 = Math.max(0, i1 - 1), i2 = Math.min(samples.length - 1, i1 + 1), i3 = Math.min(samples.length - 1, i1 + 2);
      out[i] = cr(samples[i0], samples[i1] ?? 0, samples[i2], samples[i3], t);
    }
    return out;
  }

  global.WavKit = { encodeFloat32Wav, decodeToMono, resampleTo48k };
})(window);
