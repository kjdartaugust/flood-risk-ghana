"use client";

import maplibregl, {
  type FillLayerSpecification,
  type GeoJSONSource,
  type Map as MLMap,
  type Marker,
  type PaddingOptions,
} from "maplibre-gl";
import { useEffect, useRef } from "react";
import { api } from "@/lib/api";
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

const RISK_LAYER = {
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
    "fill-opacity": ["interpolate", ["linear"], ["zoom"], 11, strength, 16, ["*", 0.55, strength]],
    "fill-outline-color": "rgba(0,0,0,0)",
  },
} as FillLayerSpecification;

export interface Spot {
  lat: number;
  lng: number;
}

export default function RiskMap({
  pin,
  pinColor,
  focus,
  padding,
  onPick,
}: {
  pin: Spot | null;
  pinColor?: string;
  /** Fly here whenever `seq` changes; zoom in only for searches, not taps. */
  focus: (Spot & { seq: number; zoomIn: boolean }) | null;
  /** Room taken by the sheet or panel, so a focused spot isn't hidden under it. */
  padding: PaddingOptions;
  onPick: (lat: number, lng: number) => void;
}) {
  const box = useRef<HTMLDivElement>(null);
  const map = useRef<MLMap | null>(null);
  const marker = useRef<Marker | null>(null);
  const tiles = useRef<GeoJSON.FeatureCollection>({ type: "FeatureCollection", features: [] });
  const pick = useRef(onPick);
  pick.current = onPick;

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

    // A new style (light ⇄ dark) wipes our layer, so add it back each time.
    m.on("style.load", () => {
      if (!m.getSource("risk")) m.addSource("risk", { type: "geojson", data: tiles.current });
      if (!m.getLayer("risk")) {
        // Under the labels, so place names stay on top of the colour.
        const firstLabel = m.getStyle().layers.find((l) => l.type === "symbol")?.id;
        m.addLayer(RISK_LAYER, firstLabel);
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
    m.on("click", (e) => pick.current(e.lngLat.lat, e.lngLat.lng));

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
      </div>
    </div>
  );
}
