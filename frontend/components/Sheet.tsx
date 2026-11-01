"use client";

import {
  useEffect,
  useRef,
  useState,
  type CSSProperties,
  type PointerEvent,
  type ReactNode,
} from "react";

export type Snap = "peek" | "half" | "full";

const STOPS: Snap[] = ["peek", "half", "full"];
// The question, the search box and one row of quick picks.
const PEEK = 206;
const DESKTOP = "(min-width: 900px)";

export const isDesktop = () =>
  typeof window !== "undefined" && window.matchMedia(DESKTOP).matches;

/** How tall the sheet stands at each stop, in px. */
export function sheetHeight(snap: Snap): number {
  if (typeof window === "undefined" || snap === "peek") return PEEK;
  return Math.round(window.innerHeight * (snap === "half" ? 0.52 : 0.9));
}

/**
 * Phone: a sheet over the map that you drag between three stops, the way
 * Google and Apple Maps work, with the search box under your thumb. Tap the
 * handle to step it up. Desktop: the same content as a floating side panel.
 */
export default function Sheet({
  snap,
  onSnap,
  label,
  children,
}: {
  snap: Snap;
  onSnap: (s: Snap) => void;
  label: string;
  children: ReactNode;
}) {
  const [drag, setDrag] = useState<number | null>(null);
  const start = useRef<{ y: number; h: number; t: number } | null>(null);
  const [, rerender] = useState(0);

  // Stops are fractions of the window; re-measure when it (or the on-screen
  // keyboard) changes its size.
  useEffect(() => {
    const onResize = () => rerender((n) => n + 1);
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, []);

  function down(e: PointerEvent<HTMLDivElement>) {
    if (isDesktop()) return;
    start.current = { y: e.clientY, h: sheetHeight(snap), t: e.timeStamp };
    e.currentTarget.setPointerCapture(e.pointerId);
  }

  function move(e: PointerEvent<HTMLDivElement>) {
    const s = start.current;
    if (!s) return;
    const h = s.h + (s.y - e.clientY);
    setDrag(Math.max(PEEK - 60, Math.min(h, sheetHeight("full") + 24)));
  }

  function up(e: PointerEvent<HTMLDivElement>) {
    const s = start.current;
    start.current = null;
    setDrag(null);
    if (!s) return;
    const moved = s.y - e.clientY; // upwards is positive
    if (Math.abs(moved) < 6) {
      onSnap(snap === "full" ? "half" : STOPS[STOPS.indexOf(snap) + 1]);
      return;
    }
    const speed = moved / Math.max(e.timeStamp - s.t, 1); // px per ms
    if (Math.abs(speed) > 0.5) {
      // A flick goes one stop in its direction, wherever it was let go.
      const i = STOPS.indexOf(snap) + (speed > 0 ? 1 : -1);
      onSnap(STOPS[Math.max(0, Math.min(STOPS.length - 1, i))]);
      return;
    }
    const h = s.h + moved;
    onSnap(
      STOPS.reduce((a, b) =>
        Math.abs(sheetHeight(b) - h) < Math.abs(sheetHeight(a) - h) ? b : a
      )
    );
  }

  return (
    <section
      className={drag === null ? "sheet" : "sheet dragging"}
      style={{ "--sheet-h": `${drag ?? sheetHeight(snap)}px` } as CSSProperties}
      aria-label={label}
      data-snap={snap}
    >
      <div
        className="sheet-grab"
        onPointerDown={down}
        onPointerMove={move}
        onPointerUp={up}
        onPointerCancel={up}
      >
        <span className="sheet-handle" aria-hidden="true" />
      </div>
      <div className="sheet-body">{children}</div>
    </section>
  );
}
