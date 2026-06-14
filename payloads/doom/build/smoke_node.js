// smoke_node.js — headless sanity check for doom.js (SINGLE_FILE, ENVIRONMENT=web)
// Shims just enough DOM for the engine to boot under node, runs ~120 frames,
// then inspects the last putImageData frame for non-black pixels.
'use strict';

let lastFrame = null;
let frames = 0;
const W = 320, H = 200;

const fakeCtx = {
  createImageData: (w, h) => ({ width: w, height: h, data: new Uint8ClampedArray(w * h * 4) }),
  putImageData: (img) => { lastFrame = img.data; frames++; },
};
const fakeCanvas = {
  width: 0, height: 0,
  getContext: () => fakeCtx,
  addEventListener: () => {},
  getBoundingClientRect: () => ({ left: 0, top: 0, width: W, height: H }),
};

globalThis.window = globalThis;
globalThis.document = {
  getElementById: (id) => (id === 'canvas' ? fakeCanvas : null),
  querySelector: () => fakeCanvas,
  addEventListener: () => {},
  createElement: () => fakeCanvas,
  documentElement: {},
  body: {},
};
globalThis.addEventListener = globalThis.addEventListener || (() => {});
globalThis.removeEventListener = globalThis.removeEventListener || (() => {});
globalThis.requestAnimationFrame = (cb) => setTimeout(() => cb(performance.now()), 8);
globalThis.devicePixelRatio = 1;
globalThis.screen = { width: W, height: H };
if (!('userAgent' in (globalThis.navigator || {}))) {
  try { globalThis.navigator = { userAgent: 'node-smoke' }; } catch (_) { /* node has one */ }
}

// Quieten the engine's copious startup logging; keep a transcript.
const logLines = [];
const realLog = console.log.bind(console);
const realErr = console.error.bind(console);
console.log = (...a) => { logLines.push(a.join(' ')); };
console.error = (...a) => { logLines.push('[err] ' + a.join(' ')); };

function finish(code, msg) {
  console.log = realLog; console.error = realErr;
  const interesting = logLines.filter(l =>
    /DOOM|W_Init|playing|version|Error|err\]|wad|WAD|Init/i.test(l)).slice(0, 12);
  realLog(interesting.join('\n'));
  realLog(`frames_drawn=${frames}`);
  if (lastFrame) {
    let nonBlack = 0;
    for (let i = 0; i < lastFrame.length; i += 4) {
      if (lastFrame[i] || lastFrame[i + 1] || lastFrame[i + 2]) nonBlack++;
    }
    realLog(`last_frame_nonblack_px=${nonBlack}/${W * H}`);
    if (code === 0 && nonBlack < 1000) { code = 1; msg = 'frame nearly all black'; }
  } else if (code === 0) { code = 1; msg = 'no frame ever drawn'; }
  realLog(code === 0 ? `SMOKE PASS ${msg}` : `SMOKE FAIL: ${msg}`);
  process.exit(code);
}

process.on('uncaughtException', (e) => {
  if (e === 'unwind' || (e && e.message === 'unwind')) return; // emscripten main-loop handoff
  finish(1, 'uncaught: ' + (e && e.stack ? e.stack.split('\n')[0] : String(e)));
});

setTimeout(() => finish(frames > 30 ? 0 : 1,
  frames > 30 ? '(engine booted, main loop ran)' : 'too few frames'), 25000);

require('./doom.js');
