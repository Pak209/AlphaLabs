/* AlphaLab PWA service worker.
 *
 * Strategy: network-first with a cache fallback. A live trading-research
 * dashboard should always show the freshest data when online, but still open
 * (from the last cached copy) if the phone briefly drops off the network /
 * Tailscale. Only same-origin GET requests are cached; POSTs and cross-origin
 * requests pass straight through untouched.
 */
const CACHE = "alphalab-v8";

// App shell precached on install so the very first offline open works.
const SHELL = [
  "/",
  "/static/styles.css?v=43",
  "/static/app.js?v=43",
  "/static/manifest.webmanifest",
  "/static/icon-192.png",
  "/static/icon-512.png",
  "/static/apple-touch-icon.png",
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE).then((cache) => cache.addAll(SHELL)).then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (event) => {
  const req = event.request;

  // Only handle same-origin GETs; everything else (POSTs, other origins) is
  // left to the network so we never cache or replay a write.
  if (req.method !== "GET" || new URL(req.url).origin !== self.location.origin) {
    return;
  }

  event.respondWith(
    fetch(req)
      .then((res) => {
        // Cache a copy of successful basic responses for offline fallback.
        if (res && res.status === 200 && res.type === "basic") {
          const copy = res.clone();
          caches.open(CACHE).then((cache) => cache.put(req, copy));
        }
        return res;
      })
      .catch(async () => {
        const cached = await caches.match(req);
        if (cached) return cached;
        // For navigations with nothing cached, fall back to the app shell.
        if (req.mode === "navigate") return caches.match("/");
        return Response.error();
      })
  );
});
