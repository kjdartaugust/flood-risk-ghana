// Rain and time, in the words someone at a trotro stop would use.
import type { RouteHour, RouteStatus } from "./api";

/** "3 pm", in Accra's time (GMT all year). */
export function clock(iso: string): string {
  return new Date(iso)
    .toLocaleTimeString("en-GB", { hour: "numeric", hour12: true, timeZone: "Africa/Accra" })
    .replace(/\s/g, " ");
}

/** "12 min ago", "3 h ago", "yesterday". */
export function ago(iso: string, now = Date.now()): string {
  const min = Math.round((now - new Date(iso).getTime()) / 60_000);
  if (min < 2) return "just now";
  if (min < 60) return `${min} min ago`;
  const h = Math.round(min / 60);
  if (h < 24) return `${h} h ago`;
  return h < 48 ? "yesterday" : `${Math.round(h / 24)} days ago`;
}

/** One line about the coming hours: when the rain starts, and how bad it gets. */
export function rainSummary(hours: RouteHour[]): string {
  if (hours.length === 0) return "No rain forecast yet.";
  const wet = hours.filter((h) => h.precip_mm >= 0.5);
  if (wet.length === 0) return `Dry for the next ${hours.length} hours.`;
  const peak = wet.reduce((a, b) => (b.precip_mm > a.precip_mm ? b : a));
  const kind = peak.precip_mm >= 10 ? "Heavy rain" : peak.precip_mm >= 2 ? "Rain" : "Light rain";
  const start = wet[0] === hours[0] ? `${kind} now` : `${kind} from ${clock(wet[0].at)}`;
  if (peak.precip_mm < 2) return `${start}.`;
  return `${start}, heaviest around ${clock(peak.at)} (${Math.round(peak.precip_mm)} mm).`;
}

/** What each status means for someone about to board. */
export const STATUS: Record<RouteStatus, { label: string; line: string }> = {
  clear: { label: "Clear", line: "No flooding expected in the next 12 hours." },
  watch: { label: "Watch", line: "Rain on the way. Minor flooding possible, so allow extra time." },
  warning: { label: "Warning", line: "Flooding likely at low points. Expect delays." },
  severe: { label: "Severe", line: "Severe flooding expected. Avoid the peak if you can." },
};

/** Route line colours on the map: calm blue when clear, warming with danger. */
export const ROUTE_COLOR: Record<RouteStatus, string> = {
  clear: "#0a66ff",
  watch: "#e0a400",
  warning: "#f76707",
  severe: "#e03131",
};

/** What the route is like in heavy rain, whatever today's forecast says. */
export function usually(baseline: number): string {
  if (baseline >= 60) return "Passes known flood spots";
  if (baseline >= 40) return "Has some low points";
  return "Mostly high ground";
}
