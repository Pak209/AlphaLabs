/* AlphaLab PWA service worker.
 *
 * Strategy: network-first with a cache fallback. A live trading-research
 * dashboard should always show the freshest data when online, but still open
 * (from the last cached copy) if the phone briefly drops off the network /
 * Tailscale. Only same-origin GET requests are cached; POSTs and cross-origin
 * requests pass straight through untouched.
 */
const CACHE = "alphalab-v13";

// App shell precached on install so the very first offline open works.
const SHELL = [
  "/",
  "/static/styles.css?v=46",
  "/static/app.js?v=47",
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

  // Never cache API responses. These carry private operator data — notification
  // preferences, phone numbers, push subscriptions, alerts, and approval state —
  // that must not be persisted to the on-disk cache or served stale. Only the
  // static app shell is cached for offline open; /api/* always hits the network.
  const isApi = new URL(req.url).pathname.startsWith("/api/");

  event.respondWith(
    fetch(req)
      .then((res) => {
        // Cache a copy of successful basic responses for offline fallback, but
        // only for static assets — API responses are never written to the cache.
        if (!isApi && res && res.status === 200 && res.type === "basic") {
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

// --- Web Push -------------------------------------------------------------- //
// An incoming push carries a JSON payload built by the server (title, body,
// url, level). Show it as a system notification. Defensive: a malformed or
// empty payload still produces a generic AlphaLab notification rather than
// throwing inside the SW.
self.addEventListener("push", (event) => {
  let data = {};
  try {
    data = event.data ? event.data.json() : {};
  } catch (err) {
    data = { title: "AlphaLab", body: event.data ? event.data.text() : "" };
  }
  const title = data.title || "AlphaLab alert";
  // Carry the safe routing metadata on the notification so the click handler can
  // deep-link to the exact item (and so the focused tab can highlight it). Only
  // ids/level/source/url travel here — never secrets.
  const options = {
    body: data.body || "",
    tag: data.alert_id ? `alert-${data.alert_id}` : undefined,
    data: {
      url: data.url || "/",
      alert_id: data.alert_id || null,
      related_trade_id: data.related_trade_id || null,
      level: data.level || null,
      source: data.source || null,
    },
    icon: "/static/icon-192.png",
    badge: "/static/icon-192.png",
  };
  event.waitUntil(self.registration.showNotification(title, options));
});

// Clicking a notification focuses an existing tab (navigating it to the alert's
// url) or opens a new one. url is the in-app hash route the server chose:
// /#approvals for sign-off-class alerts, otherwise /#alerts/<id>.
self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const meta = event.notification.data || {};
  const url = meta.url || "/";
  event.waitUntil(
    self.clients.matchAll({ type: "window", includeUncontrolled: true }).then((clientList) => {
      for (const client of clientList) {
        if ("focus" in client) {
          // Navigate the hash for browsers that honor it, but also postMessage the
          // routing metadata: an already-open tab may not fire hashchange when the
          // target route matches its current base, so the app routes + highlights
          // from this message instead of relying on the URL change alone.
          if ("navigate" in client) client.navigate(url).catch(() => {});
          client.postMessage({ type: "notification-click", ...meta });
          return client.focus();
        }
      }
      if (self.clients.openWindow) return self.clients.openWindow(url);
      return undefined;
    })
  );
});
