import type { RouteHour } from "@/lib/api";
import { clock, rainSummary } from "@/lib/rain";

/**
 * The coming hours of rain on a route as a row of bars: height is how much
 * rain, colour is what it means for this route. A glance at a trotro stop
 * should be enough.
 */
export default function RainStrip({ hours }: { hours: RouteHour[] }) {
  const summary = rainSummary(hours);
  if (hours.length === 0) return <p className="rain-summary">{summary}</p>;
  // At least 5 mm of headroom, so a drizzle doesn't fill the strip.
  const top = Math.max(5, ...hours.map((h) => h.precip_mm));
  return (
    <div className="rain">
      <div className="rain-bars" role="img" aria-label={summary}>
        {hours.map((h) => (
          <span key={h.at} className="rain-col" title={`${clock(h.at)}: ${h.precip_mm} mm`}>
            <span
              className={`rain-bar ${h.status}`}
              style={{ height: `${Math.max(6, (h.precip_mm / top) * 100)}%` }}
            />
          </span>
        ))}
      </div>
      <div className="rain-axis" aria-hidden="true">
        {hours.map((h, i) => (
          <span key={h.at}>{i % 3 === 0 ? clock(h.at) : ""}</span>
        ))}
      </div>
      <p className="rain-summary">{summary}</p>
    </div>
  );
}
