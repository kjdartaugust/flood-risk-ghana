"use client";

import { useEffect, useState } from "react";

/** Chrome's install offer: held back so the page can make it at a better moment. */
interface InstallPrompt extends Event {
  prompt(): Promise<void>;
  userChoice: Promise<{ outcome: "accepted" | "dismissed" }>;
}

declare global {
  interface Window {
    /** Caught by an inline script in the layout: Chrome can make its offer
     * before React is listening. */
    __fwInstall?: InstallPrompt;
  }
}

export type Install =
  | { kind: "prompt"; install: () => Promise<void> } // Android, desktop Chrome and Edge
  | { kind: "ios" } // iPhone or iPad Safari: Share, then Add to Home Screen
  | { kind: "none" }; // installed already, or this browser can't

export function isIOS(): boolean {
  return (
    /iPad|iPhone|iPod/.test(navigator.userAgent) ||
    // iPadOS asks for desktop sites, and says it's a Mac.
    (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1)
  );
}

/** Opened from the home screen rather than in the browser. */
export function isStandalone(): boolean {
  return (
    window.matchMedia("(display-mode: standalone)").matches ||
    (navigator as Navigator & { standalone?: boolean }).standalone === true
  );
}

/** Whether this iPhone runs at least iOS major.minor, from Safari's user agent
 * ("iPhone OS 16_4"); null if it doesn't say (iPadOS asks as a Mac). */
export function iosAtLeast(major: number, minor: number): boolean | null {
  const m = navigator.userAgent.match(/OS (\d+)_(\d+)/);
  if (!m) return null;
  return Number(m[1]) > major || (Number(m[1]) === major && Number(m[2]) >= minor);
}

/** How this browser can install FloodWatch, if it can. */
export function useInstall(): Install {
  const [offer, setOffer] = useState<InstallPrompt | null>(null);
  const [ios, setIos] = useState(false);

  useEffect(() => {
    setIos(isIOS() && !isStandalone());
    if (window.__fwInstall) setOffer(window.__fwInstall);
    const onOffer = (e: Event) => {
      e.preventDefault();
      setOffer(e as InstallPrompt);
    };
    const onInstalled = () => {
      window.__fwInstall = undefined;
      setOffer(null);
    };
    window.addEventListener("beforeinstallprompt", onOffer);
    window.addEventListener("appinstalled", onInstalled);
    return () => {
      window.removeEventListener("beforeinstallprompt", onOffer);
      window.removeEventListener("appinstalled", onInstalled);
    };
  }, []);

  if (offer) {
    return {
      kind: "prompt",
      install: async () => {
        await offer.prompt();
        // Chrome makes each offer once; a refusal ends this one.
        await offer.userChoice;
        window.__fwInstall = undefined;
        setOffer(null);
      },
    };
  }
  return ios ? { kind: "ios" } : { kind: "none" };
}
