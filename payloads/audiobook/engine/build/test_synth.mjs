import espeakngFactory from './espeakng.js';

async function main() {
  const Module = await espeakngFactory();

  // Wait for runtime ready
  await new Promise(resolve => {
    if (Module.calledRun) resolve();
    else Module.onRuntimeInitialized = resolve;
  });

  const sampleRate = Module.ccall('espeak_init', 'number', [], []);
  console.log('Sample rate:', sampleRate);

  Module.ccall('espeak_set_voice_en', 'number', [], []);

  const text = "Hello, this is a cassette.";
  // Write text to wasm memory
  const encoded = new TextEncoder().encode(text + '\0');
  const ptr = Module._malloc(encoded.length);
  Module.HEAPU8.set(encoded, ptr);

  const numSamples = Module.ccall('espeak_synth_text', 'number', ['number'], [ptr]);
  Module._free(ptr);

  const pcmPtr = Module.ccall('espeak_get_pcm_buf', 'number', [], []);
  const pcm = new Int16Array(Module.HEAP16.buffer, pcmPtr, numSamples);

  let peak = 0;
  for (let i = 0; i < numSamples; i++) {
    const abs = Math.abs(pcm[i]);
    if (abs > peak) peak = abs;
  }

  console.log('Sample count:', numSamples);
  console.log('Peak amplitude:', peak);
  console.log('Non-silent:', peak > 0 ? 'YES' : 'NO');
}

main().catch(console.error);
