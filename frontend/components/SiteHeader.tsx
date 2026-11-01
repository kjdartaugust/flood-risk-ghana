"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import AuthButton from "./AuthButton";
import { Logo } from "./icons";

const NAV = [
  { href: "/", label: "Map", short: "Map" },
  { href: "/routes", label: "Trotro alerts", short: "Alerts" },
  { href: "/about", label: "About", short: "About" },
];

/** Floats over the map on every page, so the map can have the whole screen. */
export default function SiteHeader() {
  const path = usePathname();
  return (
    <header className="site-header">
      <Link href="/" className="brand" aria-label="FloodWatch Ghana, home">
        <Logo />
        <span className="brand-name">
          FloodWatch<span className="brand-place"> Ghana</span>
        </span>
      </Link>
      <nav className="nav" aria-label="Main">
        {NAV.map((n) => {
          const here = n.href === "/" ? path === "/" : path.startsWith(n.href);
          return (
            <Link
              key={n.href}
              href={n.href}
              className={here ? "active" : undefined}
              aria-current={here ? "page" : undefined}
            >
              <span className="long">{n.label}</span>
              <span className="short">{n.short}</span>
            </Link>
          );
        })}
      </nav>
      <AuthButton />
    </header>
  );
}
