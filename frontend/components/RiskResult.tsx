"use client";

import Link from "next/link";
import type { CSSProperties } from "react";
import type { RiskPoint } from "@/lib/api";
import {
  HEADLINE,
  PLAN_LABEL,
  RISK_COLOR,
  advice,
  reason,
  sureness,
  type Plan,
} from "@/lib/risk";
import ReportFlood from "./ReportFlood";
import { ShareIcon } from "./icons";

const PLANS: Plan[] = ["buying", "building", "renting"];

/** The answer to "will it flood here?", in words first and numbers second. */
export default function RiskResult({
  place,
  risk,
  onShare,
  onReported,
}: {
  place: string;
  risk: RiskPoint;
  onShare: () => void;
  onReported: () => void;
}) {
  const scored = risk.band !== "none";
  const score = Math.round(risk.risk_score);
  const spot = risk.nearest_hotspot;
  const hotspot =
    scored && risk.risk_score >= 40 && spot && !place.toLowerCase().includes(spot.toLowerCase())
      ? ` Close to the ${spot} flood hotspot.`
      : "";
  const rain = risk.components.recent_rainfall_mm;

  return (
    <article className="result" style={{ "--risk": RISK_COLOR[risk.band] } as CSSProperties}>
      <header className="result-head">
        <div>
          <p className="eyebrow">{place}</p>
          <h2 className="verdict">{HEADLINE[risk.band]}</h2>
        </div>
        <button type="button" className="icon-btn round" onClick={onShare} aria-label="Share this place">
          <ShareIcon />
        </button>
      </header>

      <p className="why">
        {reason(risk)}
        {hotspot}
      </p>

      {scored && (
        <div className="gauge" role="img" aria-label={`Flood risk ${score} out of 100`}>
          <div className="gauge-track">
            <span className="gauge-mark" style={{ left: `${Math.min(Math.max(score, 2), 98)}%` }} />
          </div>
          <div className="gauge-scale">
            <span>Lower</span>
            <strong>
              {score}
              <small> / 100</small>
            </strong>
            <span>Higher</span>
          </div>
        </div>
      )}

      {scored && (
        <section className="plans" aria-label="What it means for you">
          <h3>What it means for you</h3>
          <dl>
            {PLANS.map((p) => (
              <div key={p}>
                <dt>{PLAN_LABEL[p]}</dt>
                <dd>{advice(risk.band, p)}</dd>
              </div>
            ))}
          </dl>
        </section>
      )}

      <p className="trust">
        <span className="trust-dot" aria-hidden="true" />
        {sureness(risk.confidence)}, from ground height, buildings and past floods.{" "}
        <Link href="/about">How this works</Link>
      </p>
      {rain > 0 && (
        <p className="trust">Rain here in the last day: {rain.toFixed(1)} mm.</p>
      )}

      {scored && <ReportFlood lat={risk.lat} lng={risk.lng} onReported={onReported} />}

      <details className="details">
        <summary>Technical details</summary>
        <p>
          Score {risk.risk_score.toFixed(1)} · confidence {Math.round(risk.confidence * 100)}% ·
          model {risk.model_version} · H3 cell {risk.h3_index} (res {risk.resolution}) ·{" "}
          {risk.lat.toFixed(5)}, {risk.lng.toFixed(5)}
        </p>
      </details>
    </article>
  );
}

/** Holds the card's shape while the score loads, so nothing jumps. */
export function ResultSkeleton({ place }: { place: string }) {
  return (
    <div className="result" aria-busy="true" aria-live="polite">
      <p className="eyebrow">{place}</p>
      <div className="skeleton skeleton-title" />
      <div className="skeleton skeleton-line" />
      <div className="skeleton skeleton-line short" />
      <div className="skeleton skeleton-gauge" />
      <span className="visually-hidden">Checking flood risk…</span>
    </div>
  );
}
