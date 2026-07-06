import type { Metadata } from "next";
import Link from "next/link";
import "./globals.css";
import "maplibre-gl/dist/maplibre-gl.css";

export const metadata: Metadata = {
  title: "FloodWatch Ghana",
  description:
    "Flood-risk scoring for Ghana + trotro route flood alerts. Check before you buy, build, or travel.",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body>
        <div className="app">
          <header className="topbar">
            <span className="logo">🌊</span>
            <h1>FloodWatch Ghana</h1>
            <nav>
              <Link href="/">Risk Map</Link>
              <Link href="/routes">Trotro Alerts</Link>
              <Link href="/about">About</Link>
            </nav>
          </header>
          {children}
        </div>
      </body>
    </html>
  );
}
