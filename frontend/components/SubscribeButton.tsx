"use client";

import { useEffect, useState } from "react";
import { useAuth } from "@/lib/auth";
import {
  PushUnavailable,
  disablePush,
  enablePush,
  followedRoutes,
  pushSupported,
  refreshPush,
  setFollowed,
} from "@/lib/push";

// Say what actually went wrong. "Something went wrong" tells a user nothing
// about whether to try again, change a setting, or give up.
const BLOCKED: Record<string, string> = {
  unsupported: "This browser can't do push notifications.",
  denied: "Notifications are blocked — allow them in your browser settings.",
  "server-off": "Push isn't switched on for this deployment yet.",
};

/** One tap, no account: this phone gets a notification if the route floods. */
export default function SubscribeButton({ routeId }: { routeId: string }) {
  // Signed in (where sign-in exists): alerts follow the account. Otherwise null.
  const { token } = useAuth();
  const [supported, setSupported] = useState(false);
  const [state, setState] = useState<"idle" | "working" | "on">("idle");
  const [note, setNote] = useState<string | null>(null);

  // Browser-only checks wait until after mount, so the server-rendered HTML
  // and the first client render agree.
  useEffect(() => {
    setSupported(pushSupported());
    if (!followedRoutes().has(routeId)) return;
    setState("on");
    refreshPush(routeId, token)
      .then((stillOn) => {
        if (!stillOn) {
          setFollowed(routeId, false);
          setState("idle");
        }
      })
      // Offline or the server is waking up: keep showing "on", retry next visit.
      .catch(() => {});
  }, [routeId, token]);

  if (!supported) return null;

  async function toggle() {
    const wasOn = state === "on";
    setState("working");
    setNote(null);
    try {
      if (wasOn) {
        await disablePush(routeId, token);
        setFollowed(routeId, false);
        setState("idle");
        return;
      }
      const res = await enablePush(routeId, token);
      setFollowed(routeId, true);
      setState("on");
      // The server stored the subscription but has no VAPID keys, so nothing
      // will actually arrive. Better to admit that than fake a green tick.
      setNote(
        res.delivers
          ? "You'll get a notification if this route is likely to flood. Tap again to stop."
          : "Saved — but the server can't send pushes yet."
      );
    } catch (e) {
      setState(wasOn ? "on" : "idle");
      setNote(
        e instanceof PushUnavailable
          ? BLOCKED[e.reason]
          : wasOn
            ? "Couldn't stop alerts. Try again."
            : "Couldn't subscribe. Try again."
      );
    }
  }

  return (
    <div className="sub">
      <button
        className="btn ghost sm"
        onClick={toggle}
        disabled={state === "working"}
        aria-pressed={state === "on"}
      >
        {state === "on"
          ? "🔔 Alerts on"
          : state === "working"
            ? "One moment…"
            : "🔔 Alert me"}
      </button>
      {note && <span className="muted sub-hint">{note}</span>}
    </div>
  );
}
