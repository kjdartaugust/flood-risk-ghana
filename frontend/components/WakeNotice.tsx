"use client";

import type { ServerState } from "@/lib/useServer";

/** Says why the map is empty while the free server wakes, instead of nothing. */
export default function WakeNotice({
  state,
  retry,
}: {
  state: ServerState;
  retry: () => void;
}) {
  if (state === "ready") return null;
  return (
    <div className="wake" role="status">
      {state === "waking" ? (
        <>
          <span className="spinner" aria-hidden="true" />
          Waking up the flood map. It takes about a minute after a quiet spell.
        </>
      ) : (
        <>
          Can&apos;t reach the flood server right now.
          <button type="button" className="link-btn" onClick={retry}>
            Try again
          </button>
        </>
      )}
    </div>
  );
}
