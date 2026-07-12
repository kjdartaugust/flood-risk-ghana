# Data provenance, and what this model can't tell you

Every number the risk map shows comes from one of the sources below. Where a
signal is weak, this document says so — a flood-risk map that overstates its own
confidence is worse than no map.

## Features (`backend/data/accra_terrain.csv`, 1340 cells, H3 res 8)

Built by `python -m app.etl.build_terrain`, committed to the repo so seeding and
CI need no network. Re-run it when you want to refresh the inputs.

| Feature | Source | How it's derived |
|---|---|---|
| `elevation_score` | Copernicus DEM GLO-90, via the key-free [Open-Meteo Elevation API](https://open-meteo.com/en/docs/elevation-api) | Inverse percentile rank of elevation **among land cells**. Rank-normalised, not divided by a magic constant, so it means "low-lying relative to this city" and survives a change of bounding box. Accra runs 0–186 m. |
| `slope_score` | derived from the DEM | Steepest gradient from a cell to any of its six H3 neighbours, in %. Flat ⇒ 1. |
| `drainage_score` | OSM waterways (2508 ways, 23 712 vertices) + DEM | **HAND** — height above nearest drainage. A cell sitting at the level of the nearest stream or storm drain has nowhere to shed water. HAND 0 m ⇒ 1, ≥ 12 m ⇒ 0. |
| `imperviousness` | OSM building footprints (400 241 centroids) | Percentile rank of building count per cell. |
| `hist_flood_density` | flood incident records (below) | Severity-weighted Gaussian kernel, 2 km bandwidth. **Baseline only — never a model feature.** See "Leakage". |
| `rainfall_recent_norm` | [Open-Meteo forecast API](https://open-meteo.com/) | Live; mm over the lookback window, saturating at 80 mm. Zero in the static grid. |

### The land mask

295 of the 1340 cells are open water. Sea and lagoon surface is dead flat, at
0 m elevation, and 0 m above drainage — which is to say it looks like a *perfect*
flood cell to any terrain index. Before masking, the weighted baseline scored the
Gulf of Guinea "extreme risk", and validation AUC came out at **0.379 — worse
than random**, purely because the ocean dominated the negative class.

A cell is masked as water when it has **no buildings and sits at or below 2 m**.
The DEM returns exactly 0.0 at sea level and nobody builds on water, so this
catches the ocean and open lagoons while keeping low-lying built-up coastal
settlements like Chorkor. *Upgrade seam:* intersect against OSM `natural=water`
polygons for a true mask.

## Labels (`backend/data/accra_flood_incidents.csv`)

45 Greater Accra communities, coordinates geocoded from OpenStreetMap
(Nominatim). 38 are marked `flood_reported=1`: communities recurrently named in
public reporting on Accra flooding. All are anchored to the **3 June 2015 Accra
flood disaster** — one real, city-wide, well-documented event.

**Be clear about what this is.** It is a compilation from public reporting, not
an authoritative registry. Specifically:

- **Per-community dates and severities are not invented.** Every incident carries
  the same date and severity precisely because inventing a plausible-looking
  spread would be fabrication dressed as data.
- **Reporting bias is real and unmeasured.** Flooding in a dense, visible,
  centrally located neighbourhood gets reported; flooding on the periphery may
  not. The label set therefore partly encodes *where journalists are*.
- **A neighbourhood is not a polygon.** A report names "Alajo", not a boundary.
  So cells within 1 km of a reported community are positive, cells beyond 3 km
  from every one are negative, and **the ring between is dropped rather than
  guessed at**.

*Upgrade seam:* NADMO incident records, or UNOSAT/Copernicus EMS Sentinel-1
flood-extent polygons for a specific event, would give true per-cell labels and
replace all of the above.

## Leakage

`hist_flood_density` is a kernel over the same incident records that the labels
are built from. Give it to a fitted classifier and it will score high exactly
where we already know it flooded, then validate beautifully against itself. So:

- it is in `FEATURE_ORDER` — the **transparent weighted baseline** may use it,
  because that baseline is a hand-specified index, not something fitted to those
  labels, and "this place has flooded before" is legitimate evidence in an index;
- it is **excluded from `MODEL_FEATURE_ORDER`** — what any fitted model may see.

## Validation

`python -m app.ml.train --kind logistic` reports **spatially-blocked** CV
(`GroupKFold` over H3 res-5 parent cells, ≈8 km). Flood risk is strongly
spatially autocorrelated: a random split puts a cell's own neighbours in the
training fold and inflates AUC toward meaninglessness. The weighted baseline is
scored on the identical folds, so the two are directly comparable.

Current numbers — 179 positive / 414 negative cells across 7 spatial blocks:

| Model | Spatially-blocked CV AUC |
|---|---|
| Weighted baseline (hand-set priors) | 0.547 |
| Logistic regression | **0.610** |
| LightGBM | 0.624 |

These are modest, and they are honest. For scale, the previous version of this
repo reported **AUC 0.92** — from a trainer that sampled random feature vectors,
labelled them with `BASELINE_WEIGHTS`, and then measured whether logistic
regression could recover a linear function it had just been handed. It could.
That number described nothing about flooding, and it is gone.

### What the model learned

Logistic coefficients on the real features:

```
elevation_score        +0.754    low-lying floods         ← matches hydrology
slope_score            -0.649    flat floods LESS         ← contradicts the baseline
imperviousness         +0.211    paved floods more        ← matches
drainage_score         +0.027    HAND barely matters
rainfall_recent_norm    0.000    constant in the static grid
```

`BASELINE_WEIGHTS` gives flat terrain **+0.14 toward risk**. The data says that
sign is *negative* — in this label set the flooded communities are the built-up
valley floors around the Odaw drains, not the flat outer plain. That
mis-specified prior is a large part of why the hand-tuned index only reaches
0.547, and it is the kind of error that is invisible until the features are real.

The near-zero weight on `drainage_score` is a warning about HAND at this
resolution, not a verdict on HAND: an H3 res-8 cell is ~0.9 km across, which is
coarse relative to the drains that actually flood in Accra.
