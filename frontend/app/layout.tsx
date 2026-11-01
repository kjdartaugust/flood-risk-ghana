import type { Metadata, Viewport } from "next";
import SiteHeader from "@/components/SiteHeader";
import { AuthProvider } from "@/lib/auth";
// MapLibre's styles first, so ours can override them.
import "maplibre-gl/dist/maplibre-gl.css";
import "./globals.css";

export const metadata: Metadata = {
  title: {
    default: "FloodWatch Ghana — will it flood here?",
    template: "%s · FloodWatch Ghana",
  },
  description:
    "Check the flood risk of any place in Accra before you buy, build or rent, and get a phone alert before your trotro route floods.",
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  viewportFit: "cover",
  // The on-screen keyboard pushes the search sheet up instead of covering it.
  interactiveWidget: "resizes-content",
  colorScheme: "light dark",
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#f4f6f9" },
    { media: "(prefers-color-scheme: dark)", color: "#0a0e15" },
  ],
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <AuthProvider>
          <SiteHeader />
          {children}
        </AuthProvider>
      </body>
    </html>
  );
}
