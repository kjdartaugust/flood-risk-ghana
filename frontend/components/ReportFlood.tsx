"use client";

import { useState } from "react";
import { api } from "@/lib/api";

// Depth in words people use, mapped onto the API's 1–5 severity.
const DEPTHS = [
  { severity: 1, label: "Puddles" },
  { severity: 2, label: "Ankle-deep" },
  { severity: 3, label: "Knee-deep" },
  { severity: 4, label: "Waist-deep" },
  { severity: 5, label: "Deeper" },
];

// The end-to-end write action: persists a community flood report to the DB and
// asks the parent to re-score the point so the effect is visible immediately.
export default function ReportFlood({
  lat,
  lng,
  onReported,
}: {
  lat: number;
  lng: number;
  onReported: () => void;
}) {
  const [open, setOpen] = useState(false);
  const [severity, setSeverity] = useState<number | null>(null);
  const [state, setState] = useState<"idle" | "sending" | "done" | "error">("idle");

  async function submit() {
    if (severity === null) return;
    setState("sending");
    try {
      await api.reportFlood({ lat, lng, severity });
      setState("done");
      onReported();
    } catch {
      setState("error");
    }
  }

  if (state === "done") {
    return (
      <p className="report-done" role="status">
        Thanks. Your report is saved and now counts toward this spot&apos;s risk.
      </p>
    );
  }

  if (!open) {
    return (
      <button type="button" className="report-toggle" onClick={() => setOpen(true)}>
        Seen flooding here? Tell us
      </button>
    );
  }

  return (
    <section className="report" aria-label="Report flooding here">
      <h3>How deep did it get?</h3>
      <div className="depths" role="radiogroup" aria-label="Flood depth">
        {DEPTHS.map((d) => (
          <button
            key={d.severity}
            type="button"
            role="radio"
            aria-checked={severity === d.severity}
            className={severity === d.severity ? "chip selected" : "chip"}
            onClick={() => setSeverity(d.severity)}
          >
            {d.label}
          </button>
        ))}
      </div>
      <button
        type="button"
        className="btn block"
        onClick={submit}
        disabled={severity === null || state === "sending"}
      >
        {state === "sending" ? "Saving…" : "Send report"}
      </button>
      {state === "error" && (
        <p className="form-error" role="alert">
          Couldn&apos;t save that. Check your connection and try again.
        </p>
      )}
    </section>
  );
}
