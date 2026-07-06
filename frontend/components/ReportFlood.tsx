"use client";

import { useState } from "react";
import { api } from "@/lib/api";

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
  const [severity, setSeverity] = useState(3);
  const [state, setState] = useState<"idle" | "sending" | "done" | "error">(
    "idle"
  );
  const [msg, setMsg] = useState("");

  async function submit() {
    setState("sending");
    try {
      const r = await api.reportFlood({ lat, lng, severity });
      setMsg(`Saved report #${r.id.slice(0, 8)} in ${r.area_name}.`);
      setState("done");
      onReported();
    } catch (e) {
      setMsg((e as Error).message);
      setState("error");
    }
  }

  return (
    <div className="card">
      <h3>Report flooding here</h3>
      <p className="muted" style={{ marginBottom: 8 }}>
        Seen flooding at this spot? Add a community report — it persists and
        raises the local risk score.
      </p>
      <label className="muted" style={{ fontSize: 13 }}>
        Severity: <strong>{severity}</strong>/5
      </label>
      <input
        type="range"
        min={1}
        max={5}
        value={severity}
        onChange={(e) => setSeverity(Number(e.target.value))}
        style={{ width: "100%", margin: "8px 0" }}
      />
      <button
        className="btn"
        onClick={submit}
        disabled={state === "sending"}
        style={{ width: "100%" }}
      >
        {state === "sending" ? "Saving…" : "Submit report"}
      </button>
      {state === "done" && (
        <p style={{ color: "#4ade80", fontSize: 13, marginTop: 8 }}>✓ {msg}</p>
      )}
      {state === "error" && (
        <p style={{ color: "#f87171", fontSize: 13, marginTop: 8 }}>{msg}</p>
      )}
    </div>
  );
}
