"use client";

import maplibregl, {
  type ExpressionSpecification,
  type FillLayerSpecification,
  type GeoJSONSource,
  type LayerSpecification,
  type Map as MLMap,
  type Marker,
  type PaddingOptions,
} from "maplibre-gl";
import { useEffect, useRef } from "react";
import { api, type RouteLines, type RouteSummary } from "@/lib/api";
import { ROUTE_COLOR } from "@/lib/rain";
import { RISK_COLOR } from "@/lib/risk";

// OpenFreeMap: OpenStreetMap streets and place names, free and with no key.
// The old basemap was a demo world map — country outlines only, no detail
// past zoom 6 — so over Accra there was nothing to recognise.
const STYLE = {
  light: "https://tiles.openfreemap.org/styles/positron",
  dark: "https://tiles.openfreemap.org/styles/dark",
};
const ACCRA: [number, number] = [-0.205, 5.59];
const DARK = "(prefers-color-scheme: dark)";
const scheme = () => (window.matchMedia(DARK).matches ? "dark" : "light");

// Risk as a glow over the streets, not a patchwork: safe ground stays almost
// clear, and colour and strength rise together towards the worst cells. Open
// water has no score, so it isn't painted at all.
const strength = [
  "case",
  ["==", ["get", "band"], "none"],
  0,
  ["interpolate", ["linear"], ["get", "risk_score"], 0, 0.04, 20, 0.1, 40, 0.34, 60, 0.5, 90, 0.6],
];

function riskLayer(dark: boolean): FillLayerSpecification {
  // Over a near-black basemap the same wash turns to mud; go lighter there.
  const k = dark ? 0.6 : 1;
  return {
    id: "risk",
    type: "fill",
    source: "risk",
    paint: {
      "fill-color": [
        "interpolate",
        ["linear"],
        ["get", "risk_score"],
        0, RISK_COLOR.low,
        20, RISK_COLOR.low,
        32, RISK_COLOR.moderate,
        48, RISK_COLOR.high,
        66, RISK_COLOR.severe,
        85, RISK_COLOR.extreme,
      ],
      // Fade as you zoom in, so the streets underneath stay readable.
      "fill-opacity": [
        "interpolate",
        ["linear"],
        ["zoom"],
        11, ["*", k, strength],
        16, ["*", 0.55 * k, strength],
      ],
      "fill-outline-color": "rgba(0,0,0,0)",
    },
  } as FillLayerSpecification;
}

// Trotro routes in their live colours: blue when clear, warming with danger.
const ROUTE_LINE_COLOR = [
  "match",
  ["get", "status"],
  "watch", ROUTE_COLOR.watch,
  "warning", ROUTE_COLOR.warning,
  "severe", ROUTE_COLOR.severe,
  ROUTE_COLOR.clear,
] as ExpressionSpecification;

const ROUND = { "line-cap": "round", "line-join": "round" } as const;
const RISKY = ["!=", ["get", "status"], "clear"] as ExpressionSpecification;
const RANK = { clear: 0, watch: 1, warning: 2, severe: 3 };
const OPEN = ["route-open-glow", "route-open-casing", "route-open"];

const isOpen = (id: string | null): ExpressionSpecification => ["==", ["get", "id"], id ?? ""];
const byZoom = (...stops: number[]) =>
  ["interpolate", ["linear"], ["zoom"], ...stops] as ExpressionSpecification;

// Hundreds of routes share Accra's main roads. On a dry day they're a quiet
// network under the risk colours; where flooding is expected they thicken and
// warm up, on top; the open route sits above everything.
function routeLayers(dark: boolean, selected: string | null): LayerSpecification[] {
  const casing = dark ? "#0a0e15" : "#ffffff";
  return [
    {
      id: "routes",
      type: "line",
      source: "routes",
      filter: ["!", RISKY],
      layout: ROUND,
      paint: {
        "line-color": ROUTE_COLOR.clear,
        "line-opacity": dark ? 0.62 : 0.5,
        "line-width": byZoom(10, 0.8, 13, 1.8, 16, 4),
      },
    },
    {
      id: "routes-risk-casing",
      type: "line",
      source: "routes",
      filter: RISKY,
      layout: ROUND,
      paint: { "line-color": casing, "line-width": byZoom(10, 4, 13, 7, 16, 12) },
    },
    {
      id: "routes-risk",
      type: "line",
      source: "routes",
      filter: RISKY,
      layout: { ...ROUND, "line-sort-key": ["get", "rank"] },
      paint: { "line-color": ROUTE_LINE_COLOR, "line-width": byZoom(10, 2, 13, 4, 16, 7) },
    },
    {
      // A soft halo under whichever route is open.
      id: "route-open-glow",
      type: "line",
      source: "routes",
      filter: isOpen(selected),
      layout: ROUND,
      paint: {
        "line-color": ROUTE_LINE_COLOR,
        "line-width": byZoom(10, 14, 15, 30),
        "line-blur": 8,
        "line-opacity": 0.45,
      },
    },
    {
      id: "route-open-casing",
      type: "line",
      source: "routes",
      filter: isOpen(selected),
      layout: ROUND,
      paint: { "line-color": casing, "line-width": byZoom(10, 6, 14, 11, 17, 16) },
    },
    {
      id: "route-open",
      type: "line",
      source: "routes",
      filter: isOpen(selected),
      layout: ROUND,
      paint: { "line-color": ROUTE_LINE_COLOR, "line-width": byZoom(10, 3, 14, 6.5, 17, 11) },
    },
    {
      // Invisible and wide, so a thumb can land on a route that's flooding.
      // Only those: on a dry day a tap anywhere is close to some route, and
      // it should check the place.
      id: "routes-risk-hit",
      type: "line",
      source: "routes",
      filter: RISKY,
      paint: { "line-color": "#000", "line-opacity": 0, "line-width": 24 },
    },
  ];
}

/** The lines, each carrying its route's live status. */
function routesGeoJSON(lines: RouteLines | null, routes: RouteSummary[]): GeoJSON.FeatureCollection {
  const status = new Map(routes.map((r) => [r.id, r.current_status]));
  return {
    type: "FeatureCollection",
    features: (lines?.features ?? []).map((f) => {
      const s = status.get(f.properties.id) ?? "clear";
      return { ...f, properties: { ...f.properties, status: s, rank: RANK[s] } };
    }),
  };
}

export interface Spot {
  lat: number;
  lng: number;
}

export default function RiskMap({
  pin,
  pinColor,
  focus,
  lines,
  routes,
  route,
  fit,
  padding,
  onPick,
  onRoutes,
}: {
  pin: Spot | null;
  pinColor?: string;
  /** Fly here whenever `seq` changes; zoom in only for searches, not taps. */
  focus: (Spot & { seq: number; zoomIn: boolean }) | null;
  lines: RouteLines | null;
  /** Live statuses, to colour the lines by. */
  routes: RouteSummary[];
  /** The open route, drawn with a halo. */
  route: string | null;
  /** Frame this line whenever `seq` changes. */
  fit: { path: number[][]; seq: number } | null;
  /** Room taken by the sheet or panel, so a focused spot isn't hidden under it. */
  padding: PaddingOptions;
  onPick: (lat: number, lng: number) => void;
  /** A tap on routes where flooding is expected: their ids, worst first. */
  onRoutes: (ids: string[]) => void;
}) {
  const box = useRef<HTMLDivElement>(null);
  const map = useRef<MLMap | null>(null);
  const marker = useRef<Marker | null>(null);
  const tiles = useRef<GeoJSON.FeatureCollection>({ type: "FeatureCollection", features: [] });
  const drawn = useRef<GeoJSON.FeatureCollection>(routesGeoJSON(lines, routes));
  const open = useRef(route);
  const pick = useRef(onPick);
  const tapRoutes = useRef(onRoutes);
  pick.current = onPick;
  tapRoutes.current = onRoutes;

  useEffect(() => {
    const desktop = window.matchMedia("(min-width: 900px)").matches;
    const m = new maplibregl.Map({
      container: box.current!,
      style: STYLE[scheme()],
      center: ACCRA,
      zoom: desktop ? 12 : 11.4,
      attributionControl: false,
      dragRotate: false,
      pitchWithRotate: false,
      touchPitch: false,
    });
    map.current = m;
    m.touchZoomRotate.disableRotation();
    // The tiles carry their own credit (OpenFreeMap, OpenMapTiles,
    // OpenStreetMap). Full text on desktop; behind the standard "i" on phones.
    m.addControl(
      new maplibregl.AttributionControl({ compact: !desktop }),
      desktop ? "bottom-right" : "top-right"
    );
    // Phones pinch; zoom buttons are for mice.
    if (desktop) m.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");

    // A new style (light ⇄ dark) wipes our layers, so add them back each time.
    m.on("style.load", () => {
      // Over every road and building, under the labels after them, so place
      // names stay on top of the colour. Not simply under the first label:
      // the dark style draws water names before its roads, and that buried
      // the routes under the streets.
      const layers = m.getStyle().layers;
      const lastShape = layers.map((l) => l.type !== "symbol").lastIndexOf(true);
      const firstLabel = layers[lastShape + 1]?.id;
      if (!m.getSource("risk")) m.addSource("risk", { type: "geojson", data: tiles.current });
      if (!m.getLayer("risk")) m.addLayer(riskLayer(scheme() === "dark"), firstLabel);
      if (!m.getSource("routes")) m.addSource("routes", { type: "geojson", data: drawn.current });
      for (const layer of routeLayers(scheme() === "dark", open.current)) {
        if (!m.getLayer(layer.id)) m.addLayer(layer, firstLabel);
      }
    });

    let timer: ReturnType<typeof setTimeout> | undefined;
    const refresh = () => {
      clearTimeout(timer);
      timer = setTimeout(async () => {
        const b = m.getBounds();
        const bbox = [b.getWest(), b.getSouth(), b.getEast(), b.getNorth()]
          .map((n) => n.toFixed(4))
          .join(",");
        try {
          const data = await api.riskTiles(bbox, 8);
          tiles.current = { type: "FeatureCollection", features: data.features };
          (m.getSource("risk") as GeoJSONSource | undefined)?.setData(tiles.current);
        } catch {
          // Server still waking; the page says so, and the next move retries.
        }
      }, 150);
    };
    m.on("load", () => {
      // Compact credits start expanded until the first drag, right across the
      // legend on a phone; start them folded instead.
      const credits = box.current?.querySelector(".maplibregl-ctrl-attrib");
      credits?.classList.remove("maplibregl-compact-show");
      credits?.removeAttribute("open");
      refresh();
    });
    m.on("moveend", refresh);

    // A tap on a route where flooding is expected opens it (or, on a shared
    // road, offers the routes there); anywhere else checks the spot.
    m.on("click", (e) => {
      if (m.getLayer("routes-risk-hit")) {
        const { x, y } = e.point;
        const hits = m.queryRenderedFeatures(
          [
            [x - 6, y - 6],
            [x + 6, y + 6],
          ],
          { layers: ["routes-risk-hit"] }
        );
        const ids = hits
          .sort((a, b) => (b.properties?.rank ?? 0) - (a.properties?.rank ?? 0))
          .map((f) => String(f.properties?.id));
        if (ids.length) {
          tapRoutes.current([...new Set(ids)]);
          return;
        }
      }
      pick.current(e.lngLat.lat, e.lngLat.lng);
    });
    m.on("mouseenter", "routes-risk-hit", () => {
      m.getCanvas().style.cursor = "pointer";
    });
    m.on("mouseleave", "routes-risk-hit", () => {
      m.getCanvas().style.cursor = "";
    });

    const dark = window.matchMedia(DARK);
    const restyle = () => m.setStyle(STYLE[scheme()]);
    dark.addEventListener("change", restyle);
    return () => {
      dark.removeEventListener("change", restyle);
      clearTimeout(timer);
      m.remove();
      map.current = null;
    };
  }, []);

  useEffect(() => {
    drawn.current = routesGeoJSON(lines, routes);
    (map.current?.getSource("routes") as GeoJSONSource | undefined)?.setData(drawn.current);
  }, [lines, routes]);

  useEffect(() => {
    open.current = route;
    const m = map.current;
    for (const id of OPEN) if (m?.getLayer(id)) m.setFilter(id, isOpen(route));
  }, [route]);

  useEffect(() => {
    const m = map.current;
    if (!m) return;
    if (!pin) {
      marker.current?.remove();
      marker.current = null;
      return;
    }
    if (!marker.current) {
      const el = document.createElement("div");
      el.className = "pin";
      el.innerHTML = '<span class="pin-pulse"></span><span class="pin-dot"></span>';
      marker.current = new maplibregl.Marker({ element: el });
    }
    marker.current.getElement().style.setProperty("--pin", pinColor ?? "var(--brand)");
    marker.current.setLngLat([pin.lng, pin.lat]).addTo(m);
  }, [pin?.lat, pin?.lng, pinColor]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    const m = map.current;
    if (!m || !focus) return;
    m.flyTo({
      center: [focus.lng, focus.lat],
      // Close enough to read the streets, far enough to see the neighbourhood.
      zoom: focus.zoomIn ? Math.max(m.getZoom(), 13) : m.getZoom(),
      padding,
      essential: true,
      duration: 1100,
    });
  }, [focus?.seq]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    const m = map.current;
    if (!m || !fit || fit.path.length < 2) return;
    const [lng, lat] = fit.path[0];
    const bounds = new maplibregl.LngLatBounds([lng, lat], [lng, lat]);
    for (const [x, y] of fit.path) bounds.extend([x, y]);
    const room = 28;
    m.fitBounds(bounds, {
      padding: {
        top: padding.top + room,
        bottom: padding.bottom + room,
        left: padding.left + room,
        right: padding.right + room,
      },
      maxZoom: 14.5,
      duration: 900,
    });
  }, [fit?.seq]); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <div className="map">
      <div ref={box} className="map-canvas" />
      <div className="legend" aria-hidden="true">
        <span className="legend-title">Flood risk</span>
        <span className="legend-bar" />
        <span className="legend-scale">
          <span>Lower</span>
          <span>Higher</span>
        </span>
        <span className="legend-route">
          <i />
          Trotro route
        </span>
        {routes.some((r) => r.current_status !== "clear") && (
          <span className="legend-route risky">
            <i />
            Flooding expected
          </span>
        )}
      </div>
    </div>
  );
}
