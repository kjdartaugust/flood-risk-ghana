"use client";

import { useEffect } from "react";

/** The service worker on every visit, not only on "Alert me": it's what lets
 * Android offer to install FloodWatch, and it shows a page that says so when
 * there's no connection, instead of the browser's error. */
export default function RegisterSW() {
  useEffect(() => {
    if ("serviceWorker" in navigator) {
      navigator.serviceWorker.register("/sw.js").catch(() => {
        // No worker: the site works the same, it just can't install or push.
      });
    }
  }, []);
  return null;
}
