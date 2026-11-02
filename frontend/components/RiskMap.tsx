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
import { api, type RouteSummary } from "@/lib/api";
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

function routeLayers(dark: boolean, selected: string | null): LayerSpecification[] {
  return [
    {
      // A soft halo under whichever route is open.
      id: "routes-glow",
      type: "line",
      source: "routes",
      filter: ["==", ["get", "id"], selected ?? ""],
      layout: ROUND,
      paint: {
        "line-color": ROUTE_LINE_COLOR,
        "line-width": ["interpolate", ["linear"], ["zoom"], 10, 14, 15, 30],
        "line-blur": 8,
        "line-opacity": 0.45,
      },
    },
    {
      // A casing so the line reads over any colour of risk underneath.
      id: "routes-casing",
      type: "line",
      source: "routes",
      layout: ROUND,
      paint: {
        "line-color": dark ? "#0a0e15" : "#ffffff",
        "line-width": ["interpolate", ["linear"], ["zoom"], 10, 5, 14, 10, 17, 16],
      },
    },
    {
      id: "routes-line",
      type: "line",
      source: "routes",
      layout: ROUND,
      paint: {
        "line-color": ROUTE_LINE_COLOR,
        "line-width": ["interpolate", ["linear"], ["zoom"], 10, 2.5, 14, 6, 17, 11],
      },
    },
    {
      // Invisible and wide: a thumb doesn't have to land on a 3px line.
      id: "routes-hit",
      type: "line",
      source: "routes",
      paint: { "line-color": "#000", "line-opacity": 0, "line-width": 26 },
    },
  ];
}

function routesGeoJSON(routes: RouteSummary[]): GeoJSON.FeatureCollection {
  return {
    type: "FeatureCollection",
    features: routes
      // `?? []`: the site can go live a few minutes before the API that sends paths.
      .filter((r) => (r.path ?? []).length >= 2)
      .map((r) => ({
        type: "Feature",
        properties: { id: r.id, name: r.name, status: r.current_status },
        geometry: { type: "LineString", coordinates: r.path },
      })),
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
  routes,
  route,
  fit,
  padding,
  onPick,
  onRoute,
}: {
  pin: Spot | null;
  pinColor?: string;
  /** Fly here whenever `seq` changes; zoom in only for searches, not taps. */
  focus: (Spot & { seq: number; zoomIn: boolean }) | null;
  routes: RouteSummary[];
  /** The open route, drawn with a halo. */
  route: string | null;
  /** Frame this line whenever `seq` changes. */
  fit: { path: [number, number][]; seq: number } | null;
  /** Room taken by the sheet or panel, so a focused spot isn't hidden under it. */
  padding: PaddingOptions;
  onPick: (lat: number, lng: number) => void;
  onRoute: (id: string) => void;
}) {
  const box = useRef<HTMLDivElement>(null);
  const map = useRef<MLMap | null>(null);
  const marker = useRef<Marker | null>(null);
  const tiles = useRef<GeoJSON.FeatureCollection>({ type: "FeatureCollection", features: [] });
  const lines = useRef<GeoJSON.FeatureCollection>(routesGeoJSON(routes));
  const open = useRef(route);
  const pick = useRef(onPick);
  const tapRoute = useRef(onRoute);
  pick.current = onPick;
  tapRoute.current = onRoute;

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
      // Under the labels, so place names stay on top of the colour.
      const firstLabel = m.getStyle().layers.find((l) => l.type === "symbol")?.id;
      if (!m.getSource("risk")) m.addSource("risk", { type: "geojson", data: tiles.current });
      if (!m.getLayer("risk")) m.addLayer(riskLayer(scheme() === "dark"), firstLabel);
      if (!m.getSource("routes")) m.addSource("routes", { type: "geojson", data: lines.current });
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

    // A tap on (or near) a route opens the route; anywhere else checks the spot.
    m.on("click", (e) => {
      if (m.getLayer("routes-hit")) {
        const { x, y } = e.point;
        const near = m.queryRenderedFeatures(
          [
            [x - 8, y - 8],
            [x + 8, y + 8],
          ],
          { layers: ["routes-hit"] }
        );
        const id = near[0]?.properties?.id;
        if (id) {
          tapRoute.current(String(id));
          return;
        }
      }
      pick.current(e.lngLat.lat, e.lngLat.lng);
    });
    m.on("mouseenter", "routes-hit", () => {
      m.getCanvas().style.cursor = "pointer";
    });
    m.on("mouseleave", "routes-hit", () => {
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
    lines.current = routesGeoJSON(routes);
    (map.current?.getSource("routes") as GeoJSONSource | undefined)?.setData(lines.current);
  }, [routes]);

  useEffect(() => {
    open.current = route;
    const m = map.current;
    if (m?.getLayer("routes-glow")) m.setFilter("routes-glow", ["==", ["get", "id"], route ?? ""]);
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
    const bounds = new maplibregl.LngLatBounds(fit.path[0], fit.path[0]);
    for (const p of fit.path) bounds.extend(p);
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
      </div>
    </div>
  );
}
