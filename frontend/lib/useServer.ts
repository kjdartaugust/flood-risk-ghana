"use client";

import { useCallback, useEffect, useState } from "react";
import { api } from "./api";

export type ServerState = "ready" | "waking" | "down";

/**
 * Is the API awake? The free server sleeps after 15 idle minutes and takes
 * about a minute to wake. Without this, the first visitor after a quiet spell
 * sees an empty map and no reason why. Starts "ready", so a warm server never
 * flashes a notice. An awake server answers /health in 2–3 s (it pings a
 * database across the Atlantic), so "waking" waits 5 s before showing.
 */
export function useServer(): { state: ServerState; retry: () => void } {
  const [state, setState] = useState<ServerState>("ready");
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let settled = false;
    const slow = setTimeout(() => !settled && setState("waking"), 5000);
    api
      .health()
      .then(() => setState("ready"))
      .catch(() => setState("down"))
      .finally(() => {
        settled = true;
        clearTimeout(slow);
      });
    return () => {
      settled = true;
      clearTimeout(slow);
    };
  }, [attempt]);

  const retry = useCallback(() => setAttempt((n) => n + 1), []);
  return { state, retry };
}
