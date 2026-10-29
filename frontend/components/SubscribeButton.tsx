"use client";

import { useState } from "react";
import { useAuth } from "@/lib/auth";
import { PushUnavailable, enablePush, pushSupported } from "@/lib/push";

// Say what actually went wrong. "Something went wrong" tells a user nothing
// about whether to try again, change a setting, or give up.
const BLOCKED: Record<string, string> = {
  unsupported: "This browser can't do push notifications.",
  denied: "Notifications are blocked — allow them in your browser settings.",
  "server-off": "Push isn't switched on for this deployment yet.",
};

export default function SubscribeButton({ routeId }: { routeId: string }) {
  const { session, token, configured } = useAuth();
  const [state, setState] = useState<"idle" | "working" | "on">("idle");
  const [note, setNote] = useState<string | null>(null);

  if (!configured || !pushSupported()) return null;

  if (!session) {
    return <span className="muted sub-hint">Sign in to get alerts</span>;
  }

  async function subscribe() {
    setState("working");
    setNote(null);
    try {
      const res = await enablePush(routeId, token!);
      setState("on");
      // The server stored the subscription but has no VAPID keys, so nothing
      // will actually arrive. Better to admit that than fake a green tick.
      if (!res.delivers) setNote("Saved — but the server can't send pushes yet.");
    } catch (e) {
      setState("idle");
      setNote(
        e instanceof PushUnavailable
          ? BLOCKED[e.reason]
          : "Couldn't subscribe. Try again."
      );
    }
  }

  return (
    <div className="sub">
      <button
        className="btn ghost sm"
        onClick={subscribe}
        disabled={state !== "idle"}
      >
        {state === "on"
          ? "🔔 Alerts on"
          : state === "working"
            ? "Subscribing…"
            : "🔔 Alert me"}
      </button>
      {note && <span className="muted sub-hint">{note}</span>}
    </div>
  );
}
