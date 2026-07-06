"use client";

import dynamic from "next/dynamic";
import { useState } from "react";
import ReportFlood from "@/components/ReportFlood";
import RiskPanel from "@/components/RiskPanel";
import { api, RiskPoint } from "@/lib/api";

// MapLibre touches window → load client-only.
const RiskMap = dynamic(() => import("@/components/RiskMap"), { ssr: false });

export default function Home() {
  const [risk, setRisk] = useState<RiskPoint | null>(null);
  const [loading, setLoading] = useState(false);
  const [query, setQuery] = useState("");
  const [error, setError] = useState<string | null>(null);

  async function score(fn: () => Promise<RiskPoint>) {
    setLoading(true);
    setError(null);
    try {
      setRisk(await fn());
    } catch (e) {
      setError((e as Error).message);
      setRisk(null);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="layout">
      <RiskMap onPick={(lat, lng) => score(() => api.riskPoint(lat, lng))} />
      <aside className="sidebar">
        <form
          className="search"
          onSubmit={(e) => {
            e.preventDefault();
            if (query.trim()) score(() => api.riskArea(query.trim()));
          }}
        >
          <input
            placeholder="Area e.g. Kaneshie, Circle…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
          <button type="submit">Score</button>
        </form>
        {error && (
          <div className="card" style={{ color: "#f87171" }}>
            {error.includes("404")
              ? "Area not found — try Kaneshie, Circle, Adabraka or Alajo."
              : "Could not reach the API. Is the backend running?"}
          </div>
        )}
        <RiskPanel risk={risk} loading={loading} />
        {risk && (
          <ReportFlood
            lat={risk.lat}
            lng={risk.lng}
            onReported={() => score(() => api.riskPoint(risk.lat, risk.lng))}
          />
        )}
      </aside>
    </div>
  );
}
