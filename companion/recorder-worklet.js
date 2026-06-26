/* recorder-worklet.js — captures raw Float32 PCM frames, sample-accurate.
   Posts each render quantum (128 samples) to the main thread for lossless
   accumulation. This is the clean clock the project's notes fought for. */
class RecProc extends AudioWorkletProcessor {
  process(inputs) {
    const input = inputs[0];
    if (input && input[0]) {
      // copy out of the reused buffer
      this.port.postMessage(input[0].slice(0));
    }
    return true;
  }
}
registerProcessor("rec-proc", RecProc);
