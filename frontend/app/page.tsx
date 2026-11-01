"use client";

import dynamic from "next/dynamic";
import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import PlaceSearch from "@/components/PlaceSearch";
import RiskResult, { ResultSkeleton } from "@/components/RiskResult";
import Sheet, { isDesktop, sheetHeight, type Snap } from "@/components/Sheet";
import WakeNotice from "@/components/WakeNotice";
import { BellIcon, ChevronIcon } from "@/components/icons";
import { api, type RiskPoint } from "@/lib/api";
import { nameOf } from "@/lib/places";
import { HEADLINE, RISK_COLOR } from "@/lib/risk";
import { useServer } from "@/lib/useServer";

// MapLibre touches window → load client-only.
const RiskMap = dynamic(() => import("@/components/RiskMap"), {
  ssr: false,
  loading: () => <div className="map map-placeholder" />,
});

interface Spot {
  lat: number;
  lng: number;
  name: string;
}

export default function Home() {
  const server = useServer();
  const [spot, setSpot] = useState<Spot | null>(null);
  const [risk, setRisk] = useState<RiskPoint | null>(null);
  const [status, setStatus] = useState<"idle" | "loading" | "error">("idle");
  const [snap, setSnap] = useState<Snap>("peek");
  const [focus, setFocus] = useState<(Spot & { seq: number; zoomIn: boolean }) | null>(null);
  const [locating, setLocating] = useState(false);
  const [toast, setToast] = useState<string | null>(null);
  const latest = useRef(0);

  const score = useCallback(async (s: Spot) => {
    // Only the most recent pick may land: a slow answer for the previous spot
    // must not overwrite the current one.
    const ticket = ++latest.current;
    setRisk(null);
    setStatus("loading");
    try {
      const r = await api.riskPoint(s.lat, s.lng);
      if (ticket === latest.current) {
        setRisk(r);
        setStatus("idle");
      }
    } catch {
      if (ticket === latest.current) setStatus("error");
    }
  }, []);

  const select = useCallback(
    (s: Spot, zoomIn: boolean) => {
      setSpot(s);
      setFocus((f) => ({ ...s, zoomIn, seq: (f?.seq ?? 0) + 1 }));
      setSnap("half");
      void score(s);
    },
    [score]
  );

  // Every answer has its own link, to send on WhatsApp or open again later.
  useEffect(() => {
    if (!spot) return;
    const at = `${spot.lat.toFixed(5)},${spot.lng.toFixed(5)}`;
    window.history.replaceState(null, "", `/?at=${at}&name=${encodeURIComponent(spot.name)}`);
  }, [spot]);

  // Opening such a link goes straight to that answer.
  useEffect(() => {
    const p = new URLSearchParams(window.location.search);
    const [lat, lng] = (p.get("at") ?? "").split(",").map(Number);
    if (Number.isFinite(lat) && Number.isFinite(lng) && p.get("at")) {
      select({ lat, lng, name: p.get("name") || "Shared place" }, true);
    }
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (!toast) return;
    const t = setTimeout(() => setToast(null), 3200);
    return () => clearTimeout(t);
  }, [toast]);

  const tapped = useCallback(
    (lat: number, lng: number) => {
      select({ lat, lng, name: "Dropped pin" }, false);
      // Put a name to the spot when there's one nearby; keep it if the user
      // has already moved on.
      void nameOf(lat, lng).then((name) => {
        if (name) {
          setSpot((s) => (s && s.lat === lat && s.lng === lng ? { ...s, name } : s));
        }
      });
    },
    [select]
  );

  function locate() {
    if (!("geolocation" in navigator)) {
      setToast("This browser can't share its location.");
      return;
    }
    setLocating(true);
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        setLocating(false);
        select({ lat: pos.coords.latitude, lng: pos.coords.longitude, name: "Where you are" }, true);
      },
      () => {
        setLocating(false);
        setToast("Couldn't get your location. Search or tap the map instead.");
      },
      { enableHighAccuracy: true, timeout: 10_000, maximumAge: 60_000 }
    );
  }

  async function share() {
    if (!spot || !risk) return;
    const text = `${spot.name}: ${HEADLINE[risk.band]} (FloodWatch Ghana)`;
    const url = window.location.href;
    if (navigator.share) {
      try {
        await navigator.share({ title: "FloodWatch Ghana", text, url });
      } catch {
        // Closing the share sheet isn't an error worth reporting.
      }
      return;
    }
    try {
      await navigator.clipboard.writeText(`${text} ${url}`);
      setToast("Link copied");
    } catch {
      setToast("Couldn't copy the link.");
    }
  }

  // Keep a focused spot clear of the sheet (phone) or panel (desktop).
  const padding = isDesktop()
    ? { top: 90, left: 450, right: 40, bottom: 40 }
    : { top: 80, left: 24, right: 24, bottom: sheetHeight("half") + 16 };

  return (
    <main className="mapview">
      <RiskMap
        pin={spot}
        pinColor={risk ? RISK_COLOR[risk.band] : undefined}
        focus={focus}
        padding={padding}
        onPick={tapped}
      />
      <WakeNotice {...server} />
      {toast && (
        <div className="toast" role="status">
          {toast}
        </div>
      )}

      <Sheet snap={snap} onSnap={setSnap} label="Check a place">
        {/* Once there's an answer on screen, the question has done its job. */}
        <h1 className={spot ? "visually-hidden" : "sheet-title"}>Will it flood here?</h1>
        <PlaceSearch
          onPick={(p) => select({ lat: p.lat, lng: p.lng, name: p.name }, true)}
          onLocate={locate}
          onFocus={() => {
            if (!isDesktop()) setSnap("full");
          }}
          locating={locating}
        />

        {spot && status === "loading" && <ResultSkeleton place={spot.name} />}
        {spot && status === "error" && (
          <div className="note">
            Couldn&apos;t check this spot
            {server.state === "waking" ? " while the server wakes up." : "."}
            <button type="button" className="link-btn" onClick={() => score(spot)}>
              Try again
            </button>
          </div>
        )}
        {spot && risk && (
          <RiskResult place={spot.name} risk={risk} onShare={share} onReported={() => score(spot)} />
        )}

        {!spot && (
          <div className="intro">
            <p>
              Check any place in Accra before you buy land, build or rent. Search above, or tap
              the map.
            </p>
            <Link href="/routes" className="promo">
              <span className="promo-icon">
                <BellIcon size={20} />
              </span>
              <span>
                <strong>Trotro flood alerts</strong>
                <small>A phone alert before your route floods. No account needed.</small>
              </span>
              <ChevronIcon />
            </Link>
          </div>
        )}
      </Sheet>
    </main>
  );
}
