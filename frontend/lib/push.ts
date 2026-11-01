"use client";

import { ApiError, api, SubscribeResponse, TestAlertResult } from "./api";

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
 * Subscribe this browser to push alerts for a route. No account needed: the
 * browser's push subscription is who the server alerts. `token` only matters
 * on deployments with sign-in, to tie alerts to the account instead.
 *
 * Order matters: we ask the *server* for its key before we ask the *user* for
 * permission. Prompting someone for notification access and only then finding
 * out the backend can't send any is a good way to burn a permission you get to
 * ask for exactly once.
 */
export async function enablePush(
  routeId: string,
  token?: string | null
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

async function currentSubscription(): Promise<PushSubscription | null> {
  const reg = await navigator.serviceWorker.getRegistration();
  return (await reg?.pushManager.getSubscription()) ?? null;
}

/**
 * Stop push alerts for a route. The browser keeps its push subscription:
 * other routes may still be using it.
 */
export async function disablePush(
  routeId: string,
  token?: string | null
): Promise<void> {
  if (!pushSupported()) return;
  const sub = await currentSubscription();
  if (sub) await api.unsubscribe({ route_id: routeId, endpoint: sub.endpoint }, token);
}

/**
 * Ask the server for a test alert on a route this browser follows: a real
 * push, by the same path a flood warning takes. A 404 (as ApiError) means this
 * browser isn't subscribed any more.
 */
export async function sendTestPush(
  routeId: string,
  token?: string | null
): Promise<TestAlertResult> {
  if (!pushSupported()) throw new PushUnavailable("unsupported");
  const sub = await currentSubscription();
  if (!sub) throw new ApiError(404, "this browser has no push subscription");
  return api.testAlert({ route_id: routeId, endpoint: sub.endpoint }, token);
}

/**
 * Re-send this browser's push subscription for a route it follows. Browsers
 * rotate push endpoints, and a stale one on the server means alerts quietly
 * stop. Never prompts. False if this browser has no subscription any more,
 * so alerts are off whatever we remembered.
 */
export async function refreshPush(
  routeId: string,
  token?: string | null
): Promise<boolean> {
  if (!pushSupported() || Notification.permission !== "granted") return false;
  const sub = await currentSubscription();
  if (!sub) return false;
  await api.subscribe(
    {
      route_id: routeId,
      channel: "push",
      push_subscription: sub.toJSON() as PushSubscriptionJSON,
    },
    token
  );
  return true;
}

// Which routes this browser follows, so "Alerts on" survives a reload. Only a
// convenience: storage can be blocked or cleared, and then the button forgets.
const FOLLOWED = "floodwatch.alertRoutes";

export function followedRoutes(): Set<string> {
  try {
    return new Set(JSON.parse(localStorage.getItem(FOLLOWED) ?? "[]"));
  } catch {
    return new Set();
  }
}

export function setFollowed(routeId: string, on: boolean): void {
  try {
    const routes = followedRoutes();
    if (on) routes.add(routeId);
    else routes.delete(routeId);
    localStorage.setItem(FOLLOWED, JSON.stringify([...routes]));
  } catch {
    // Storage blocked (private mode): alerts still work, the label just resets.
  }
}
