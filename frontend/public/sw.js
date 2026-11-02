/* FloodWatch service worker — renders route flood alerts pushed from the API,
 * and stands in for the site when there's no connection at all.
 *
 * This runs with no page open, which is the entire point: a commuter finds out
 * their route is flooding at 6am without having FloodWatch on screen.
 *
 * The payload shape is set by `_payload()` in backend/app/services/alerts_service.py.
 */

const OFFLINE = "/offline.html";
const CACHE = "floodwatch-offline-v1";

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE).then((cache) => cache.addAll([OFFLINE, "/icons/icon-192.png"]))
  );
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

// Pages always come from the network: flood risk and rain are only worth
// showing fresh, so nothing else is cached. With no network at all, a page
// that says so instead of the browser's error.
self.addEventListener("fetch", (event) => {
  if (event.request.mode !== "navigate") return;
  event.respondWith(fetch(event.request).catch(() => caches.match(OFFLINE)));
});

self.addEventListener("push", (event) => {
  let data = {};
  try {
    data = event.data ? event.data.json() : {};
  } catch {
    // A push with no/!JSON body still deserves to surface — a silent push is
    // worse than a vague one, and browsers penalise us for not showing anything.
  }

  const title = data.title || "FloodWatch Ghana";
  const options = {
    body: data.body || "Flooding expected on a route you follow.",
    icon: "/icons/icon-192.png",
    // Android's status-bar icon: a white drop, not a grey square.
    badge: "/icons/badge-96.png",
    // Collapse repeat pushes for the same route into one notification rather
    // than stacking six identical warnings over a rainy morning.
    tag: data.route_id || "floodwatch",
    renotify: true,
    data: { url: data.url || "/routes" },
    // A severe alert is worth interrupting for; a warning can wait quietly.
    requireInteraction: data.level === "severe",
  };
  event.waitUntil(self.registration.showNotification(title, options));
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const target = event.notification.data?.url || "/routes";

  event.waitUntil(
    self.clients
      .matchAll({ type: "window", includeUncontrolled: true })
      .then((windows) => {
        // Reuse an open FloodWatch tab if there is one — don't pile up windows.
        for (const client of windows) {
          if (client.url.includes(target) && "focus" in client) {
            return client.focus();
          }
        }
        return self.clients.openWindow(target);
      })
  );
});
