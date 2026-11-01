"use client";

import { useEffect, useRef, useState, type KeyboardEvent } from "react";
import { HOTSPOTS, Place, searchPlaces } from "@/lib/places";
import { CloseIcon, LocateIcon, PinIcon, SearchIcon } from "./icons";

/** Search any place in Ghana as you type; before typing, quick picks. */
export default function PlaceSearch({
  onPick,
  onLocate,
  onFocus,
  locating,
}: {
  onPick: (p: Place) => void;
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
          setActive(found.length ? 0 : -1);
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

  function pick(p: Place) {
    setQ("");
    setResults([]);
    input.current?.blur();
    onPick(p);
  }

  function onKey(e: KeyboardEvent<HTMLInputElement>) {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setActive((i) => Math.min(i + 1, results.length - 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setActive((i) => Math.max(i - 1, 0));
    } else if (e.key === "Enter" && results[active]) {
      e.preventDefault();
      pick(results[active]);
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
          placeholder="Search a place in Accra"
          aria-label="Search a place"
          role="combobox"
          aria-expanded={typing && results.length > 0}
          aria-controls="place-results"
          aria-activedescendant={active >= 0 ? `place-${active}` : undefined}
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
        <ul id="place-results" className="results" role="listbox" aria-label="Places">
          {status === "loading" && results.length === 0 && (
            <li className="results-note">Searching…</li>
          )}
          {status === "error" && (
            <li className="results-note">
              Place search isn&apos;t answering. Tap the map instead.
            </li>
          )}
          {status === "idle" && results.length === 0 && (
            <li className="results-note">
              No match. Try a market, street or area name.
            </li>
          )}
          {results.map((p, i) => (
            <li
              key={`${p.name}-${p.lat}-${p.lng}`}
              id={`place-${i}`}
              role="option"
              aria-selected={i === active}
            >
              <button
                type="button"
                className={i === active ? "active" : undefined}
                onClick={() => pick(p)}
                onMouseEnter={() => setActive(i)}
              >
                <span className="result-icon">
                  <PinIcon />
                </span>
                <span>
                  <strong>{p.name}</strong>
                  {p.detail && <small>{p.detail}</small>}
                </span>
              </button>
            </li>
          ))}
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
            <button key={p.name} type="button" className="chip" onClick={() => pick(p)}>
              {p.name}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
