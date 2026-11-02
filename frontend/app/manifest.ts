import type { MetadataRoute } from "next";

/** What makes FloodWatch installable: Android and desktop offer "Install app",
 * and on iPhone "Add to Home Screen" opens it full screen, which is also the
 * only way an iPhone lets a website send notifications (iOS 16.4 and later). */
export default function manifest(): MetadataRoute.Manifest {
  return {
    id: "/",
    name: "FloodWatch Ghana",
    short_name: "FloodWatch",
    description:
      "Will it flood here? Flood risk for any place in Accra, and a phone alert before your trotro route floods.",
    start_url: "/",
    scope: "/",
    display: "standalone",
    background_color: "#f4f6f9",
    theme_color: "#f4f6f9",
    categories: ["weather", "travel", "navigation"],
    icons: [
      { src: "/icons/icon-192.png", sizes: "192x192", type: "image/png", purpose: "any" },
      { src: "/icons/icon-512.png", sizes: "512x512", type: "image/png", purpose: "any" },
      {
        src: "/icons/icon-maskable-512.png",
        sizes: "512x512",
        type: "image/png",
        purpose: "maskable",
      },
    ],
    // A long press on the home-screen icon goes straight to these.
    shortcuts: [
      {
        name: "Trotro flood alerts",
        short_name: "Alerts",
        url: "/routes",
        icons: [{ src: "/icons/icon-192.png", sizes: "192x192", type: "image/png" }],
      },
    ],
  };
}
