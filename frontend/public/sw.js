/* FloodWatch service worker — renders route flood alerts pushed from the API.
 *
 * This runs with no page open, which is the entire point: a commuter finds out
 * their route is flooding at 6am without having FloodWatch on screen.
 *
 * The payload shape is set by `_payload()` in backend/app/services/alerts_service.py.
 */

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
