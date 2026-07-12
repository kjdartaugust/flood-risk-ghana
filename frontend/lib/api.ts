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

export interface RouteSummary {
  id: string;
  name: string;
  from_stop: string | null;
  to_stop: string | null;
  baseline_risk: number;
  current_status: "clear" | "watch" | "warning" | "severe";
  active_alert: boolean;
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

async function get<T>(path: string): Promise<T> {
  const res = await fetch(`${API}${path}`, { cache: "no-store" });
  if (!res.ok) throw new Error(`API ${res.status}: ${await res.text()}`);
  return res.json() as Promise<T>;
}

async function post<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${API}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    cache: "no-store",
  });
  if (!res.ok) throw new Error(`API ${res.status}: ${await res.text()}`);
  return res.json() as Promise<T>;
}

export const api = {
  riskPoint: (lat: number, lng: number) =>
    get<RiskPoint>(`/risk/point?lat=${lat}&lng=${lng}`),
  riskArea: (name: string) =>
    get<RiskPoint>(`/risk/area?name=${encodeURIComponent(name)}`),
  riskTiles: (bbox: string, res = 8) =>
    get<{ features: GeoJSON.Feature[]; count: number }>(
      `/risk/tiles?bbox=${bbox}&res=${res}`
    ),
  routes: () => get<RouteSummary[]>(`/routes`),
  alerts: () => get<Alert[]>(`/alerts`),
  reportFlood: (r: {
    lat: number;
    lng: number;
    severity: number;
    note?: string;
  }) => post<FloodReport>(`/reports`, r),
  recentReports: (limit = 100) =>
    get<FloodReport[]>(`/reports/recent?limit=${limit}`),
};

export const BAND_COLOR: Record<Band, string> = {
  none: "#64748b",
  low: "#2dc937",
  moderate: "#a8c700",
  high: "#e7b416",
  severe: "#db7b2b",
  extreme: "#cc3232",
};

export const fetcher = (path: string) => get(path);
