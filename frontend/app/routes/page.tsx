"use client";

import useSWR from "swr";
import { Alert, api, RouteSummary } from "@/lib/api";

const STATUS_LABEL: Record<string, string> = {
  clear: "Clear",
  watch: "Watch",
  warning: "Warning",
  severe: "Severe",
};

export default function RoutesPage() {
  const { data: routes, error: rErr } = useSWR<RouteSummary[]>(
    "routes",
    () => api.routes(),
    { refreshInterval: 60_000 }
  );
  const { data: alerts } = useSWR<Alert[]>("alerts", () => api.alerts(), {
    refreshInterval: 60_000,
  });

  return (
    <div className="page">
      <h2>Trotro route flood alerts</h2>
      <p className="muted">
        Live flood status for Accra trotro corridors, combining the flood-risk
        layer with forecast rainfall. Updated every few minutes.
      </p>

      {alerts && alerts.length > 0 && (
        <div className="card">
          <h3>Active alerts</h3>
          {alerts.map((a) => (
            <div className="alert-item" key={a.id}>
              <span className={`status ${a.level}`}>{a.level}</span>
              <strong>{a.route_name}</strong>
              <span className="muted">{a.message}</span>
              <span className="muted">
                ~{a.expected_precip_mm.toFixed(0)} mm expected · risk{" "}
                {a.risk_score.toFixed(0)}/100
              </span>
            </div>
          ))}
        </div>
      )}

      <h3 style={{ marginTop: 22 }}>All routes</h3>
      {rErr && (
        <div className="card" style={{ color: "#f87171" }}>
          Could not load routes — is the backend running and seeded?
        </div>
      )}
      {!routes && !rErr && <div className="spinner">Loading routes…</div>}
      <div className="grid">
        {routes?.map((r) => (
          <div className="route-item" key={r.id}>
            <span className={`status ${r.current_status}`}>
              {STATUS_LABEL[r.current_status] ?? r.current_status}
            </span>
            <strong>{r.name}</strong>
            <span className="muted">
              {r.from_stop} → {r.to_stop}
            </span>
            <span className="muted">
              Baseline risk {r.baseline_risk.toFixed(0)}/100
              {r.active_alert ? " · ⚠ alert active" : ""}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}
