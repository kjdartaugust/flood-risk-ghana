"use client";

import { BAND_COLOR, RiskPoint } from "@/lib/api";

function Feature({ label, value }: { label: string; value: number }) {
  const pct = Math.round(value * 100);
  return (
    <div className="feature-row">
      <div className="k">
        <span>{label}</span>
        <span className="muted">{pct}%</span>
      </div>
      <div className="bar">
        <span style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}

export default function RiskPanel({
  risk,
  loading,
}: {
  risk: RiskPoint | null;
  loading: boolean;
}) {
  if (loading) return <div className="card spinner">Scoring location…</div>;
  if (!risk)
    return (
      <div className="card muted">
        Search an area or click anywhere on the map to get a flood-risk score.
      </div>
    );

  const c = risk.components;
  return (
    <>
      <div className="card">
        <h3>Flood-risk score</h3>
        <div className="score" style={{ color: BAND_COLOR[risk.band] }}>
          {risk.risk_score.toFixed(0)}
          <span style={{ fontSize: 18, color: "var(--muted)" }}>/100</span>
        </div>
        <span
          className="band-pill"
          style={{ background: BAND_COLOR[risk.band] }}
        >
          {risk.band.toUpperCase()}
        </span>
        <p className="muted" style={{ marginTop: 10 }}>{risk.advice}</p>
        <p className="muted">
          Confidence {(risk.confidence * 100).toFixed(0)}% · model{" "}
          {risk.model_version}
          {risk.nearest_hotspot ? ` · near ${risk.nearest_hotspot}` : ""}
        </p>
      </div>

      <div className="card">
        <h3>Risk drivers</h3>
        <Feature label="Low elevation" value={c.elevation} />
        <Feature label="Flat / poor runoff" value={c.slope} />
        <Feature label="Poor drainage" value={c.drainage} />
        <Feature label="Built-up (impervious)" value={c.imperviousness} />
        <Feature label="Historical flooding" value={c.historical_flood_density} />
        <div className="feature-row muted">
          Recent rainfall: {c.recent_rainfall_mm.toFixed(1)} mm (24h)
        </div>
      </div>

      <div className="card muted" style={{ fontSize: 12 }}>
        H3 {risk.h3_index} · res {risk.resolution} · {risk.lat.toFixed(4)},{" "}
        {risk.lng.toFixed(4)}
      </div>
    </>
  );
}
