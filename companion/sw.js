/* sw.js — offline app shell cache. Bump CACHE on any asset change. */
const CACHE = "mv-field-decoder-v2";
const ASSETS = [
  "./", "index.html", "styles.css", "app.js", "wav.js",
  "recorder-worklet.js", "floor_manifest.json", "manifest.webmanifest",
  "icons/icon.svg",
  "pkg/cassette_codec_wasm.js", "pkg/cassette_codec_wasm_bg.wasm",
];

self.addEventListener("install", (e) => {
  e.waitUntil(
    caches.open(CACHE).then((c) =>
      // best-effort: don't fail install if an optional asset (pkg/*) is missing
      Promise.allSettled(ASSETS.map((a) => c.add(a)))
    ).then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", (e) => {
  e.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k)))
    ).then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (e) => {
  if (e.request.method !== "GET") return;
  e.respondWith(
    caches.match(e.request).then((hit) =>
      hit || fetch(e.request).then((res) => {
        const copy = res.clone();
        caches.open(CACHE).then((c) => c.put(e.request, copy)).catch(() => {});
        return res;
      }).catch(() => hit)
    )
  );
});
