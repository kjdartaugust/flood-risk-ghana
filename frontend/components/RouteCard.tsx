"use client";

import Link from "next/link";
import type { RouteSummary } from "@/lib/api";
import { STATUS, shownStatus, usually } from "@/lib/rain";
import RainStrip from "./RainStrip";
import SubscribeButton from "./SubscribeButton";
import { CloseIcon } from "./icons";

/** One trotro route: will it flood, what the rain is doing, and "Alert me".
 * The same card in the route list and in the map's panel. */
export default function RouteCard({
  route,
  checked,
  showOnMap,
  inSheet,
  onClose,
}: {
  route: RouteSummary;
  /** "Rain checked 40 min ago". */
  checked?: string | null;
  showOnMap?: boolean;
  /** In the map's panel: a section of it rather than a card of its own. */
  inSheet?: boolean;
  onClose?: () => void;
}) {
  const shown = shownStatus(route);
  const s = STATUS[shown];
  // Absent for a few minutes after a deploy, while the API catches up.
  const hours = route.hours ?? [];
  return (
    <article className={inSheet ? "route-card in-sheet" : "route-card"}>
      <div className="route-top">
        <span className={`status-badge ${shown}`}>
          <span className="dot" aria-hidden="true" />
          {s.label}
        </span>
        <span className="tag">{usually(route.baseline_risk)}</span>
        {onClose && (
          <button type="button" className="icon-btn" onClick={onClose} aria-label="Close route">
            <CloseIcon />
          </button>
        )}
      </div>
      <h2>{route.name}</h2>
      <p className="route-status">{s.line}</p>

      {hours.length > 0 && (
        <section className="route-rain" aria-label="Rain on this route">
          <div className="route-rain-head">
            <h3>Rain, next {hours.length} hours</h3>
            {checked && <span>{checked}</span>}
          </div>
          <RainStrip hours={hours} />
        </section>
      )}

      <div className="route-actions">
        <SubscribeButton routeId={route.id} />
        {showOnMap && (
          <Link href={`/?route=${route.id}`} className="btn ghost sm">
            See on map
          </Link>
        )}
      </div>
    </article>
  );
}
