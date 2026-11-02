"use client";

import { Fragment, useEffect, useRef, useState, type KeyboardEvent } from "react";
import type { RouteSummary } from "@/lib/api";
import { HOTSPOTS, Place, searchPlaces } from "@/lib/places";
import { STATUS, shownStatus } from "@/lib/rain";
import { matchRoutes } from "@/lib/routes";
import { BusIcon, CloseIcon, LocateIcon, PinIcon, SearchIcon } from "./icons";

type Option = { kind: "route"; route: RouteSummary } | { kind: "place"; place: Place };

/** Search any place in Ghana as you type, and the trotro routes by their
 * stops; before typing, quick picks. */
export default function PlaceSearch({
  routes = [],
  onPick,
  onRoute,
  onLocate,
  onFocus,
  locating,
}: {
  routes?: RouteSummary[];
  onPick: (p: Place) => void;
  onRoute?: (id: string) => void;
  onLocate: () => void;
  onFocus?: () => void;
  locating?: boolean;
}) {
  const [q, setQ] = useState("");
  const [results, setResults] = useState<Place[]>([]);
  const [status, setStatus] = useState<"idle" | "loading" | "error">("idle");
  const [active, setActive] = useState(-1);
  const input = useRef<HTMLInputElement>(null);
  const typing = q.trim().length >= 2;

  // Routes are already here: they match as you type, no waiting.
  const routeHits = typing && onRoute ? matchRoutes(routes, q).slice(0, 4) : [];
  const options: Option[] = [
    ...routeHits.map((route) => ({ kind: "route" as const, route })),
    ...results.map((place) => ({ kind: "place" as const, place })),
  ];

  useEffect(() => {
    const term = q.trim();
    if (term.length < 2) {
      setResults([]);
      setStatus("idle");
      return;
    }
    const ctl = new AbortController();
    setStatus("loading");
    // Wait for a pause in typing: one request per thought, not per keystroke.
    const t = setTimeout(() => {
      searchPlaces(term, ctl.signal)
        .then((found) => {
          setResults(found);
          setStatus("idle");
        })
        .catch((e: Error) => {
          if (e.name !== "AbortError") setStatus("error");
        });
    }, 250);
    return () => {
      clearTimeout(t);
      ctl.abort();
    };
  }, [q]);

  // The first option is the one Enter takes, whichever list it's from.
  useEffect(() => {
    setActive(options.length ? 0 : -1);
  }, [options.length, q]); // eslint-disable-line react-hooks/exhaustive-deps

  function choose(o: Option) {
    setQ("");
    setResults([]);
    input.current?.blur();
    if (o.kind === "route") onRoute?.(o.route.id);
    else onPick(o.place);
  }

  function onKey(e: KeyboardEvent<HTMLInputElement>) {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setActive((i) => Math.min(i + 1, options.length - 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setActive((i) => Math.max(i - 1, 0));
    } else if (e.key === "Enter" && options[active]) {
      e.preventDefault();
      choose(options[active]);
    } else if (e.key === "Escape") {
      setQ("");
    }
  }

  return (
    <div className="place-search">
      <label className="search-field">
        <SearchIcon />
        <input
          ref={input}
          type="search"
          inputMode="search"
          enterKeyHint="search"
          autoComplete="off"
          spellCheck={false}
          placeholder={onRoute ? "Search a place or trotro stop" : "Search a place in Accra"}
          aria-label="Search a place or trotro route"
          role="combobox"
          aria-expanded={typing && options.length > 0}
          aria-controls="place-results"
          aria-activedescendant={active >= 0 ? `option-${active}` : undefined}
          value={q}
          onChange={(e) => setQ(e.target.value)}
          onKeyDown={onKey}
          onFocus={onFocus}
        />
        {q && (
          <button
            type="button"
            className="icon-btn"
            onClick={() => setQ("")}
            aria-label="Clear search"
          >
            <CloseIcon />
          </button>
        )}
      </label>

      {typing ? (
        <ul id="place-results" className="results" role="listbox" aria-label="Routes and places">
          {options.map((o, i) => {
            // A heading where each kind starts, once there are both.
            const heading =
              routeHits.length === 0
                ? null
                : i === 0
                  ? "Trotro routes"
                  : i === routeHits.length
                    ? "Places"
                    : null;
            const key =
              o.kind === "route" ? o.route.id : `${o.place.name}-${o.place.lat}-${o.place.lng}`;
            return (
              <Fragment key={key}>
                {heading && (
                  <li className="results-group" role="presentation">
                    {heading}
                  </li>
                )}
                <li id={`option-${i}`} role="option" aria-selected={i === active}>
                  <button
                    type="button"
                    className={i === active ? "active" : undefined}
                    onClick={() => choose(o)}
                    onMouseEnter={() => setActive(i)}
                  >
                    <span className="result-icon">
                      {o.kind === "route" ? <BusIcon /> : <PinIcon />}
                    </span>
                    {o.kind === "route" ? (
                      <span>
                        <strong>{o.route.name}</strong>
                        <small className={`route-hint ${shownStatus(o.route)}`}>
                          Trotro route · {STATUS[shownStatus(o.route)].label}
                        </small>
                      </span>
                    ) : (
                      <span>
                        <strong>{o.place.name}</strong>
                        {o.place.detail && <small>{o.place.detail}</small>}
                      </span>
                    )}
                  </button>
                </li>
              </Fragment>
            );
          })}
          {status === "loading" && results.length === 0 && (
            <li className="results-note">Searching places…</li>
          )}
          {status === "error" && (
            <li className="results-note">
              Place search isn&apos;t answering. Tap the map instead.
            </li>
          )}
          {status === "idle" && options.length === 0 && (
            <li className="results-note">
              No match. Try a market, street, area or trotro stop.
            </li>
          )}
        </ul>
      ) : (
        <div className="chips" role="group" aria-label="Quick picks">
          <button
            type="button"
            className="chip chip-accent"
            onClick={onLocate}
            disabled={locating}
          >
            <LocateIcon size={16} />
            {locating ? "Finding you…" : "Where I am"}
          </button>
          {HOTSPOTS.map((p) => (
            <button
              key={p.name}
              type="button"
              className="chip"
              onClick={() => choose({ kind: "place", place: p })}
            >
              {p.name}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
