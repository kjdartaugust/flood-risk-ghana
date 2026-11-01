import type { Metadata } from "next";

export const metadata: Metadata = { title: "How it works" };

export default function AboutPage() {
  return (
    <main className="page">
      <header className="page-head">
        <p className="eyebrow">About</p>
        <h1>How FloodWatch works</h1>
        <p className="lede">
          FloodWatch estimates how likely a place in Accra is to flood, so you can check before
          you buy land, build or rent. It also warns trotro riders before their route floods.
        </p>
      </header>

      <section className="card">
        <h2>The score</h2>
        <p>
          Accra is split into hexagons about 900 m across. Each gets a score from 0 to 100 from
          how low the ground sits compared with the rest of the city, how built-up it is, and
          where floods have been reported. A statistical model trained on past floods weighs
          these together.
        </p>
        <p>
          It&apos;s a guide, not a guarantee. Tested on neighbourhoods it had never seen, it
          ranks a flooded place above a dry one about 6 times in 10: better than chance, and we
          would rather say so than oversell it.
        </p>
      </section>

      <section className="card">
        <h2>Trotro alerts</h2>
        <p>
          Every 3 hours FloodWatch fetches the rain forecast for the next day or two. Where heavy
          rain meets a route&apos;s low points, the route is flagged, and every phone that asked
          for alerts gets a notification. No account and no phone number: the alert goes to the
          browser that asked for it.
        </p>
      </section>

      <section className="card">
        <h2>Where the data comes from</h2>
        <ul>
          <li>Ground height: Copernicus DEM, via Open-Meteo</li>
          <li>Streams, drains, buildings and trotro routes: OpenStreetMap</li>
          <li>Rain, observed and forecast: Open-Meteo</li>
          <li>Past floods: public reports of the 3 June 2015 Accra flood</li>
          <li>Map: OpenFreeMap. Place search: Photon by Komoot. Both use OpenStreetMap.</li>
        </ul>
      </section>

      <section className="card">
        <h2>Please note</h2>
        <p>
          Scores are estimates to help you plan, not a guarantee. In an emergency, follow NADMO
          and local authorities.
        </p>
      </section>
    </main>
  );
}
