"use client";

import maplibregl, { Map as MLMap } from "maplibre-gl";
import { useEffect, useRef } from "react";
import { api, BAND_COLOR } from "@/lib/api";

const STYLE =
  process.env.NEXT_PUBLIC_MAP_STYLE ??
  "https://demotiles.maplibre.org/style.json";

// Centre on Greater Accra.
const ACCRA: [number, number] = [-0.2, 5.6];

interface Props {
  onPick: (lat: number, lng: number) => void;
}

export default function RiskMap({ onPick }: Props) {
  const ref = useRef<HTMLDivElement>(null);
  const mapRef = useRef<MLMap | null>(null);

  useEffect(() => {
    if (!ref.current || mapRef.current) return;
    const map = new maplibregl.Map({
      container: ref.current,
      style: STYLE,
      center: ACCRA,
      zoom: 11,
    });
    mapRef.current = map;
    map.addControl(new maplibregl.NavigationControl({}), "top-left");

    map.on("load", () => {
      map.addSource("risk-tiles", {
        type: "geojson",
        data: { type: "FeatureCollection", features: [] },
      });
      map.addLayer({
        id: "risk-fill",
        type: "fill",
        source: "risk-tiles",
        paint: {
          "fill-color": [
            "match",
            ["get", "band"],
            "low", BAND_COLOR.low,
            "moderate", BAND_COLOR.moderate,
            "high", BAND_COLOR.high,
            "severe", BAND_COLOR.severe,
            "extreme", BAND_COLOR.extreme,
            "#888",
          ],
          "fill-opacity": 0.45,
          "fill-outline-color": "rgba(255,255,255,0.25)",
        },
      });
      loadTiles(map);
    });

    map.on("moveend", () => loadTiles(map));
    map.on("click", (e) => onPick(e.lngLat.lat, e.lngLat.lng));

    return () => {
      map.remove();
      mapRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function loadTiles(map: MLMap) {
    const b = map.getBounds();
    const bbox = [
      b.getWest(), b.getSouth(), b.getEast(), b.getNorth(),
    ].map((n) => n.toFixed(4)).join(",");
    try {
      const data = await api.riskTiles(bbox, 8);
      const src = map.getSource("risk-tiles") as maplibregl.GeoJSONSource;
      src?.setData({ type: "FeatureCollection", features: data.features } as any);
    } catch {
      /* backend may be warming up; ignore */
    }
  }

  return (
    <div className="map-wrap">
      <div ref={ref} />
      <div className="legend">
        <strong>Flood risk</strong>
        {(["low", "moderate", "high", "severe", "extreme"] as const).map((b) => (
          <div className="row" key={b}>
            <span className="sw" style={{ background: BAND_COLOR[b] }} />
            {b}
          </div>
        ))}
        <div className="muted" style={{ marginTop: 6 }}>Click map to score a spot</div>
      </div>
    </div>
  );
}
