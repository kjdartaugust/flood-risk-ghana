// Finding a trotro route among Accra's hundreds: by name, and by place.
import type { RouteLines, RouteStatus, RouteSummary } from "./api";

const RANK: Record<RouteStatus, number> = { clear: 0, watch: 1, warning: 2, severe: 3 };

/** Worst flooding first, keeping the order otherwise (sort is stable). */
export function worstFirst(a: RouteSummary, b: RouteSummary): number {
  return RANK[b.current_status] - RANK[a.current_status];
}

/** Worst flooding first, then A to Z. */
export function byConcern(a: RouteSummary, b: RouteSummary): number {
  return worstFirst(a, b) || a.name.localeCompare(b.name);
}

export function atRisk(r: RouteSummary): boolean {
  return r.current_status !== "clear";
}

/** "Accra C.M.B" and "accra cmb" are the same stop to someone typing. */
function fold(s: string): string {
  return s
    .normalize("NFD")
    .replace(/[̀-ͯ]/g, "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, " ")
    .trim();
}

/** Routes whose name has every word typed, start of a word first. */
export function matchRoutes(routes: RouteSummary[], query: string): RouteSummary[] {
  const words = fold(query).split(" ").filter(Boolean);
  if (words.length === 0) return [];
  const scored = routes.flatMap((r) => {
    const name = ` ${fold(r.name)}`;
    if (!words.every((w) => name.includes(w))) return [];
    const starts = words.filter((w) => name.includes(` ${w}`)).length;
    return [{ r, starts }];
  });
  return scored
    .sort((a, b) => b.starts - a.starts || byConcern(a.r, b.r))
    .map((s) => s.r);
}

/** Metres from a point to a segment, flat-earth: fine across a city. */
function toSegment(
  x: number,
  y: number,
  [x1, y1]: number[],
  [x2, y2]: number[],
  k: number
): number {
  const ax = (x1 - x) * k,
    ay = y1 - y,
    bx = (x2 - x) * k,
    by = y2 - y;
  const dx = bx - ax,
    dy = by - ay;
  const len = dx * dx + dy * dy;
  const t = len ? Math.max(0, Math.min(1, -(ax * dx + ay * dy) / len)) : 0;
  return Math.hypot(ax + t * dx, ay + t * dy) * 111_320;
}

/** Ids of the routes passing within `metres` of a spot, nearest first. */
export function routesNear(
  lines: RouteLines | undefined,
  lat: number,
  lng: number,
  metres = 300
): string[] {
  if (!lines) return [];
  const k = Math.cos((lat * Math.PI) / 180);
  const near: [string, number][] = [];
  for (const f of lines.features) {
    const c = f.geometry.coordinates;
    let best = Infinity;
    for (let i = 1; i < c.length && best > 0; i++) {
      best = Math.min(best, toSegment(lng, lat, c[i - 1], c[i], k));
    }
    if (best <= metres) near.push([f.properties.id, best]);
  }
  return near.sort((a, b) => a[1] - b[1]).map(([id]) => id);
}
