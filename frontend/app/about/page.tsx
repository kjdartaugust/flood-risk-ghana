export default function AboutPage() {
  return (
    <div className="page">
      <h2>About FloodWatch Ghana</h2>
      <p className="muted">
        FloodWatch estimates flood risk for any location in Ghana so people can
        check before buying land, building, renting, or starting a business — and
        warns trotro commuters which routes flood before and during rain.
      </p>

      <div className="card">
        <h3>How the score works</h3>
        <p className="muted">
          Each ~0.7 km² H3 hex cell is scored from six drivers: low elevation,
          flat slope / poor runoff, poor drainage, imperviousness (built-up land),
          density of historical flooding nearby, and recent rainfall. A transparent
          weighted model gives the baseline; a gradient-boosted classifier upgrades
          it as labelled data grows. Every score ships with a confidence value.
        </p>
      </div>

      <div className="card">
        <h3>Data sources</h3>
        <ul className="muted">
          <li>NASA GPM/IMERG &amp; Open-Meteo — rainfall (observed + forecast)</li>
          <li>Copernicus / SRTM DEM — elevation, slope, drainage</li>
          <li>Sentinel-2 land cover — imperviousness</li>
          <li>OpenStreetMap — roads and trotro routes</li>
          <li>NADMO / Ghana Meteo &amp; reported events — historical floods</li>
        </ul>
      </div>

      <div className="card">
        <h3>Disclaimer</h3>
        <p className="muted">
          Risk scores are probabilistic estimates for planning support only, not a
          guarantee. Always consult NADMO and local authorities for emergency
          decisions.
        </p>
      </div>
    </div>
  );
}
