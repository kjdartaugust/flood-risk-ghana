"use client";

import { useState, type ReactNode } from "react";
import type { RouteSummary } from "@/lib/api";
import { STATUS, shownStatus } from "@/lib/rain";
import { ChevronIcon } from "./icons";

/** A compact list of routes, one tap each: the ones through a spot on the
 * map, the ones on a road you tapped, the ones matching a search. Long lists
 * show their first `limit` until asked for the rest. */
export default function RouteRows({
  title,
  routes,
  limit = Infinity,
  open,
  renderOpen,
  onOpen,
}: {
  title?: string;
  routes: RouteSummary[];
  limit?: number;
  /** A route to show in full where its row would be. */
  open?: string | null;
  renderOpen?: (r: RouteSummary) => ReactNode;
  onOpen: (id: string) => void;
}) {
  const [all, setAll] = useState(false);
  const shown = all ? routes : routes.slice(0, limit);
  return (
    <section className="route-rows" aria-label={title ?? "Trotro routes"}>
      {title && <h3>{title}</h3>}
      <ul>
        {shown.map((r) => {
          if (r.id === open && renderOpen) return <li key={r.id}>{renderOpen(r)}</li>;
          const s = shownStatus(r);
          return (
            <li key={r.id}>
              <button type="button" className="route-row" onClick={() => onOpen(r.id)}>
                <span className={`row-dot ${s}`} aria-hidden="true" />
                <span className="row-name">{r.name}</span>
                <span className={`row-status ${s}`}>{STATUS[s].label}</span>
                <ChevronIcon />
              </button>
            </li>
          );
        })}
      </ul>
      {shown.length < routes.length && (
        <button type="button" className="btn ghost sm more" onClick={() => setAll(true)}>
          Show all {routes.length}
        </button>
      )}
    </section>
  );
}
