"use client";

import useSWR from "swr";
import RouteCard from "@/components/RouteCard";
import WakeNotice from "@/components/WakeNotice";
import { Alert, api, RouteSummary } from "@/lib/api";
import { useRainCheck } from "@/lib/useRainCheck";
import { useServer } from "@/lib/useServer";

export default function RoutesPage() {
  const server = useServer();
  const checked = useRainCheck();
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
        {checked && <p className="freshness">{checked}</p>}
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
        {routes?.map((r) => <RouteCard key={r.id} route={r} showOnMap />)}
      </div>
    </main>
  );
}
