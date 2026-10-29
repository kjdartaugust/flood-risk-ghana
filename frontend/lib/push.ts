"use client";

import { ApiError, api, SubscribeResponse } from "./api";

/** Why push isn't available — each maps to a different thing to tell the user. */
export type PushBlocker =
  | "unsupported" // browser has no Push API (notably iOS Safari outside a PWA)
  | "denied" // user said no; only they can undo this, in browser settings
  | "server-off"; // no VAPID keys deployed — our problem, not theirs

export class PushUnavailable extends Error {
  constructor(readonly reason: PushBlocker) {
    super(reason);
    this.name = "PushUnavailable";
  }
}

export function pushSupported(): boolean {
  return (
    typeof window !== "undefined" &&
    "serviceWorker" in navigator &&
    "PushManager" in window &&
    "Notification" in window
  );
}

/** The VAPID public key ships as base64url; PushManager wants raw bytes. */
function decodeKey(base64url: string): ArrayBuffer {
  const padded = base64url.padEnd(
    base64url.length + ((4 - (base64url.length % 4)) % 4),
    "="
  );
  const raw = atob(padded.replace(/-/g, "+").replace(/_/g, "/"));
  // Allocate the ArrayBuffer up front: a Uint8Array's `.buffer` is typed
  // ArrayBufferLike, which isn't a BufferSource as far as TS is concerned.
  const buffer = new ArrayBuffer(raw.length);
  const view = new Uint8Array(buffer);
  for (let i = 0; i < raw.length; i++) view[i] = raw.charCodeAt(i);
  return buffer;
}

/**
 * Subscribe this browser to push alerts for a route.
 *
 * Order matters: we ask the *server* for its key before we ask the *user* for
 * permission. Prompting someone for notification access and only then finding
 * out the backend can't send any is a good way to burn a permission you get to
 * ask for exactly once.
 */
export async function enablePush(
  routeId: string,
  token: string
): Promise<SubscribeResponse> {
  if (!pushSupported()) throw new PushUnavailable("unsupported");

  let key: string;
  try {
    key = (await api.vapidKey()).public_key;
  } catch (e) {
    if (e instanceof ApiError && e.status === 503) {
      throw new PushUnavailable("server-off");
    }
    throw e;
  }

  const permission = await Notification.requestPermission();
  if (permission !== "granted") throw new PushUnavailable("denied");

  const reg = await navigator.serviceWorker.register("/sw.js");
  await navigator.serviceWorker.ready;

  // Reuse the existing handle if this browser already has one — re-subscribing
  // with a fresh key would orphan the old endpoint on the push service.
  const existing = await reg.pushManager.getSubscription();
  const sub =
    existing ??
    (await reg.pushManager.subscribe({
      // Chrome requires this: every push must result in a visible notification.
      userVisibleOnly: true,
      applicationServerKey: decodeKey(key),
    }));

  return api.subscribe(
    {
      route_id: routeId,
      channel: "push",
      push_subscription: sub.toJSON() as PushSubscriptionJSON,
    },
    token
  );
}
