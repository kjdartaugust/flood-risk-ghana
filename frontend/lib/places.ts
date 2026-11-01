// Place search: any street, market or neighbourhood, not just the few named
// flood hotspots the API knows. Photon (photon.komoot.io) is OpenStreetMap
// data with search-as-you-type, free and key-free; it's biased towards Accra
// and kept inside Ghana.
export interface Place {
  name: string;
  /** The area it's in, e.g. "Okaikoi South". Empty when unknown. */
  detail: string;
  lat: number;
  lng: number;
}

const PHOTON = "https://photon.komoot.io";
const NEAR_ACCRA = "lat=5.6&lon=-0.2";
const GHANA = "bbox=-3.3,4.5,1.3,11.2";

interface PhotonFeature {
  geometry: { coordinates: [number, number] };
  properties: Record<string, string | undefined>;
}

function toPlace(f: PhotonFeature): Place {
  const p = f.properties;
  const [lng, lat] = f.geometry.coordinates;
  return {
    name: p.name || [p.housenumber, p.street].filter(Boolean).join(" ") || "Unnamed place",
    detail: p.district ?? p.city ?? p.county ?? p.state ?? "",
    lat,
    lng,
  };
}

/** Places matching `q`, best first; the same name nearby appears once. */
export async function searchPlaces(q: string, signal?: AbortSignal): Promise<Place[]> {
  const res = await fetch(
    `${PHOTON}/api/?q=${encodeURIComponent(q)}&limit=8&lang=en&${NEAR_ACCRA}&${GHANA}`,
    { signal }
  );
  if (!res.ok) throw new Error(`place search answered ${res.status}`);
  const { features } = (await res.json()) as { features: PhotonFeature[] };
  const seen = new Set<string>();
  return features.map(toPlace).filter((p) => {
    // "Kaneshie Market", its bus stop and its car park are one place to a person.
    const key = `${p.name}|${p.lat.toFixed(2)}|${p.lng.toFixed(2)}`;
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  }).slice(0, 6);
}

/** A human name for a spot someone tapped, or null if there's nothing nearby. */
export async function nameOf(lat: number, lng: number): Promise<string | null> {
  try {
    const res = await fetch(`${PHOTON}/reverse?lat=${lat}&lon=${lng}&lang=en`);
    if (!res.ok) return null;
    const { features } = (await res.json()) as { features: PhotonFeature[] };
    const p = features[0] && toPlace(features[0]);
    return p ? `Near ${p.name}` : null;
  } catch {
    return null;
  }
}

/** Known Accra flood spots, offered before anyone types. Same points the API
 * uses for "near the … flood hotspot" (backend/app/services/geo.py). */
export const HOTSPOTS: Place[] = [
  { name: "Kaneshie", detail: "Flood hotspot", lat: 5.562, lng: -0.236 },
  { name: "Circle", detail: "Flood hotspot", lat: 5.571, lng: -0.205 },
  { name: "Adabraka", detail: "Flood hotspot", lat: 5.562, lng: -0.211 },
  { name: "Alajo", detail: "Flood hotspot", lat: 5.592, lng: -0.216 },
];
