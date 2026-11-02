"use client";

import { useEffect, useMemo, useState } from "react";
import useSWR from "swr";
import RouteCard from "@/components/RouteCard";
import RouteRows from "@/components/RouteRows";
import WakeNotice from "@/components/WakeNotice";
import { CloseIcon, SearchIcon } from "@/components/icons";
import { Alert, api, RouteSummary } from "@/lib/api";
import { keepFollowed } from "@/lib/push";
import { atRisk, byConcern, matchRoutes } from "@/lib/routes";
import { useRainCheck } from "@/lib/useRainCheck";
import { useServer } from "@/lib/useServer";

export default function RoutesPage() {
  const server = useServer();
  const checked = useRainCheck();
  // Statuses move with the rain check, every 3 hours, and as the hours roll on.
  const { data: routes, error } = useSWR<RouteSummary[]>("routes", () => api.routes(), {
    refreshInterval: 300_000,
  });
  const { data: alerts } = useSWR<Alert[]>("alerts", () => api.alerts(), {
    refreshInterval: 300_000,
  });
  const [q, setQ] = useState("");
  // A route opened from one of the lists, shown in full where its row was.
  const [open, setOpen] = useState<{ list: string; id: string } | null>(null);
  const [followed, setFollowed] = useState<Set<string>>(new Set());

  // After mount (it's in this browser's storage), and once the routes are in,
  // so a route that no longer exists is forgotten rather than shown.
  useEffect(() => {
    if (routes) setFollowed(keepFollowed(new Set(routes.map((r) => r.id))));
  }, [routes]);

  const all = useMemo(() => [...(routes ?? [])].sort(byConcern), [routes]);
  const found = q.trim() ? matchRoutes(all, q) : null;
  const yours = all.filter((r) => followed.has(r.id));
  const flooding = all.filter((r) => atRisk(r) && !followed.has(r.id));

  const list = (key: string, title: string, items: RouteSummary[], limit: number) => (
    <RouteRows
      key={key}
      title={title}
      routes={items}
      limit={limit}
      open={open?.list === key ? open.id : null}
      renderOpen={(r) => (
        <RouteCard route={r} checked={checked} showOnMap onClose={() => setOpen(null)} />
      )}
      onOpen={(id) => setOpen({ list: key, id })}
    />
  );

  return (
    <main className="page">
      <WakeNotice {...server} />
      <header className="page-head">
        <p className="eyebrow">Trotro flood alerts</p>
        <h1>Know before you board.</h1>
        <p className="lede">
          Live flood status for {routes ? routes.length : "Accra's"} trotro routes, from the flood
          map and the rain forecast, checked every 3 hours. Find yours, tap “Alert me”, and this
          phone gets a notification when it&apos;s likely to flood. No account needed.
        </p>
        {checked && <p className="freshness">{checked}</p>}
      </header>

      <label className="search-field route-search">
        <SearchIcon />
        <input
          type="search"
          inputMode="search"
          enterKeyHint="search"
          autoComplete="off"
          spellCheck={false}
          placeholder="Find your route: a stop, like Kaneshie"
          aria-label="Find a route by its stops"
          value={q}
          onChange={(e) => setQ(e.target.value)}
        />
        {q && (
          <button type="button" className="icon-btn" onClick={() => setQ("")} aria-label="Clear">
            <CloseIcon />
          </button>
        )}
      </label>

      {alerts && alerts.length > 0 && !found && (
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

      {!routes && !error && (
        <div className="route-list">
          {[0, 1, 2].map((i) => (
            <div key={i} className="route-card skeleton" />
          ))}
        </div>
      )}

      {routes &&
        (found ? (
          found.length ? (
            list(`search:${q}`, found.length === 1 ? "1 route" : `${found.length} routes`, found, 30)
          ) : (
            <p className="note">No route stops at “{q.trim()}”. Try another stop name.</p>
          )
        ) : (
          <>
            {yours.length > 0 && (
              <section className="route-group" aria-label="Your routes">
                <h2>Your routes</h2>
                <div className="route-list">
                  {yours.map((r) => (
                    <RouteCard key={r.id} route={r} checked={checked} showOnMap />
                  ))}
                </div>
              </section>
            )}
            {flooding.length > 0 && list("flooding", "Flooding expected", flooding, 10)}
            {list("all", `All ${all.length} routes`, all, 25)}
          </>
        ))}

      <p className="source">
        Routes from OpenStreetMap, where Accra&apos;s trotro network is mapped stop by stop. Some
        may have changed since they were mapped.
      </p>
    </main>
  );
}
