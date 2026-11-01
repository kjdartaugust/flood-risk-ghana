"use client";

import useSWR from "swr";
import SubscribeButton from "@/components/SubscribeButton";
import WakeNotice from "@/components/WakeNotice";
import { Alert, api, RouteSummary } from "@/lib/api";
import { useServer } from "@/lib/useServer";

// What each status means for someone about to board, in their words.
const STATUS: Record<RouteSummary["current_status"], { label: string; line: string }> = {
  clear: { label: "Clear", line: "No flooding expected in the next 12 hours." },
  watch: { label: "Watch", line: "Rain on the way. Minor flooding possible, so allow extra time." },
  warning: { label: "Warning", line: "Flooding likely at low points. Expect delays." },
  severe: { label: "Severe", line: "Severe flooding expected. Avoid the peak if you can." },
};

/** What the route is like in heavy rain, whatever today's forecast says. Was a
 * bare "Baseline risk 97/100" beside "Clear", which read as a contradiction. */
function usually(baseline: number): string {
  if (baseline >= 60) return "Passes known flood spots";
  if (baseline >= 40) return "Has some low points";
  return "Mostly high ground";
}

export default function RoutesPage() {
  const server = useServer();
  const { data: routes, error } = useSWR<RouteSummary[]>("routes", () => api.routes(), {
    refreshInterval: 60_000,
  });
  const { data: alerts } = useSWR<Alert[]>("alerts", () => api.alerts(), {
    refreshInterval: 60_000,
  });

  return (
    <main className="page">
      <WakeNotice {...server} />
      <header className="page-head">
        <p className="eyebrow">Trotro flood alerts</p>
        <h1>Know before you board.</h1>
        <p className="lede">
          Live flood status for Accra trotro routes, from the flood map and the rain forecast,
          checked every 3 hours. Tap “Alert me” and this phone gets a notification when your
          route is likely to flood. No account needed.
        </p>
      </header>

      {alerts && alerts.length > 0 && (
        <section className="alerts" aria-label="Active alerts">
          {alerts.map((a) => (
            <div key={a.id} className={`alert-banner ${a.level}`}>
              <strong>{a.route_name}</strong>
              <span>{a.message}</span>
              <small>About {a.expected_precip_mm.toFixed(0)} mm of rain expected</small>
            </div>
          ))}
        </section>
      )}

      {error && (
        <div className="note">
          Couldn&apos;t load the routes
          {server.state === "waking" ? " while the server wakes up." : ". Try again in a moment."}
        </div>
      )}

      <div className="route-list">
        {!routes && !error && [0, 1, 2, 3].map((i) => <div key={i} className="route-card skeleton" />)}
        {routes?.map((r) => {
          const s = STATUS[r.current_status] ?? STATUS.clear;
          return (
            <article key={r.id} className="route-card">
              <div className="route-top">
                <span className={`status-badge ${r.current_status}`}>
                  <span className="dot" aria-hidden="true" />
                  {s.label}
                </span>
                <span className="tag">{usually(r.baseline_risk)}</span>
              </div>
              <h2>{r.name}</h2>
              <p className="route-line">
                {r.from_stop} → {r.to_stop}
              </p>
              <p className="route-status">{s.line}</p>
              <SubscribeButton routeId={r.id} />
            </article>
          );
        })}
      </div>
    </main>
  );
}
