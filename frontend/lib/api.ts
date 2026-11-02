// Typed client for the FloodWatch API.
const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000/api/v1";

// "none" is open water (sea/lagoon) — not a low score, an undefined question.
export type Band = "none" | "low" | "moderate" | "high" | "severe" | "extreme";

export interface RiskPoint {
  lat: number;
  lng: number;
  h3_index: string;
  resolution: number;
  risk_score: number;
  band: Band;
  confidence: number;
  components: {
    elevation: number;
    slope: number;
    drainage: number;
    imperviousness: number;
    historical_flood_density: number;
    recent_rainfall_mm: number;
  };
  model_version: string;
  nearest_hotspot: string | null;
  advice: string;
}

export type RouteStatus = "clear" | "watch" | "warning" | "severe";

/** One forecast hour on a route: the wettest cell it crosses. */
export interface RouteHour {
  at: string;
  precip_mm: number;
  status: RouteStatus;
}

export interface RouteSummary {
  id: string;
  name: string;
  from_stop: string | null;
  to_stop: string | null;
  baseline_risk: number;
  current_status: RouteStatus;
  active_alert: boolean;
  /** The coming hours of rain the status was judged on. Empty until the
   * first rain check after the route was added. */
  hours: RouteHour[];
}

/** Every route's line, from OpenStreetMap. Apart from the statuses because it
 * only changes with a deploy, so the browser keeps it. */
export type RouteLines = GeoJSON.FeatureCollection<
  GeoJSON.LineString,
  { id: string; name: string }
>;

/** The latest scheduled rain check, and whether it saved anything. */
export interface RefreshRun {
  id: number;
  started_at: string;
  finished_at: string | null;
  rainfall_rows: number | null;
  alerts_raised: number | null;
  error: string | null;
}

export interface Alert {
  id: string;
  route_id: string;
  route_name: string;
  level: string;
  message: string;
  expected_precip_mm: number;
  risk_score: number;
  starts_at: string;
  expires_at: string;
}

export interface SubscribeRequest {
  route_id: string;
  channel: "web" | "push";
  /** Exactly what `PushManager.subscribe()` returned — passed through verbatim. */
  push_subscription?: PushSubscriptionJSON;
}

export interface SubscribeResponse {
  id: string;
  route_id: string;
  channel: string;
  created: boolean;
  /** False ⇒ stored, but the server can't actually push. Don't promise a ping. */
  delivers: boolean;
}

export interface TestAlertResult {
  sent: boolean;
  /** The push service's refusal, if any. 404/410: the browser dropped it. */
  status: number | null;
}

export interface FloodReport {
  id: string;
  lat: number;
  lng: number;
  severity: number;
  area_name: string;
  occurred_on: string;
  created?: boolean;
  source?: string;
}

/** Thrown so callers can branch on status (404 = unknown area, 503 = push off). */
export class ApiError extends Error {
  constructor(readonly status: number, message: string) {
    super(message);
    this.name = "ApiError";
  }
}

async function request<T>(
  path: string,
  init?: RequestInit,
  token?: string | null
): Promise<T> {
  const res = await fetch(`${API}${path}`, {
    cache: "no-store",
    ...init,
    headers: {
      ...init?.headers,
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
  });
  if (!res.ok) throw new ApiError(res.status, `API ${res.status}: ${await res.text()}`);
  return res.json() as Promise<T>;
}

const get = <T,>(path: string, token?: string | null) =>
  request<T>(path, undefined, token);

const post = <T,>(path: string, body: unknown, token?: string | null) =>
  request<T>(
    path,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    },
    token
  );

export const api = {
  /** Slow only when the free server is waking from sleep (about a minute). */
  health: () => get<{ status: string; db: boolean }>(`/health`),
  riskPoint: (lat: number, lng: number) =>
    get<RiskPoint>(`/risk/point?lat=${lat}&lng=${lng}`),
  riskArea: (name: string) =>
    get<RiskPoint>(`/risk/area?name=${encodeURIComponent(name)}`),
  riskTiles: (bbox: string, res = 8) =>
    get<{ features: GeoJSON.Feature[]; count: number }>(
      `/risk/tiles?bbox=${bbox}&res=${res}`
    ),
  routes: () => get<RouteSummary[]>(`/routes`),
  /** ~60 kB compressed; the browser's own cache keeps it between visits. */
  routeLines: () => request<RouteLines>(`/routes/lines`, { cache: "default" }),
  alerts: () => get<Alert[]>(`/alerts`),
  /** 503 when the server has no VAPID keys — push is simply off. */
  vapidKey: () => get<{ public_key: string }>(`/alerts/vapid-key`),
  /** No account needed for push: the push subscription itself is the identity. */
  subscribe: (body: SubscribeRequest, token?: string | null) =>
    post<SubscribeResponse>(`/alerts/subscribe`, body, token),
  unsubscribe: (
    body: { route_id: string; endpoint: string },
    token?: string | null
  ) => post<{ removed: boolean }>(`/alerts/unsubscribe`, body, token),
  /** A real push to this browser's subscription for the route, right now. */
  testAlert: (
    body: { route_id: string; endpoint: string },
    token?: string | null
  ) => post<TestAlertResult>(`/alerts/test`, body, token),
  reportFlood: (r: {
    lat: number;
    lng: number;
    severity: number;
    note?: string;
  }) => post<FloodReport>(`/reports`, r),
  lastRainCheck: () => get<RefreshRun>(`/internal/refresh`),
  recentReports: (limit = 100) =>
    get<FloodReport[]>(`/reports/recent?limit=${limit}`),
};


export const fetcher = (path: string) => get(path);
