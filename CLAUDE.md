# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

FloodWatch Ghana — a flood-risk platform with two coupled features:
1. **Flood-risk scoring/mapping** — a per-location risk score (0–100 + band + confidence) for anywhere in Ghana, served as an interactive H3-hex map.
2. **Trotro route flood alerts** — combines the static risk layer with forecast rainfall to flag which routes flood, and pushes alerts.

Monorepo: `backend/` (FastAPI + PostGIS + ETL + ML) and `frontend/` (Next.js 14 App Router + MapLibre).

## Commands

Local stack (Docker): `docker compose up --build` — starts postgis, redis, backend (:8000, docs at `/docs`), worker, frontend (:3000). The backend `entrypoint.sh` waits for Postgres, runs `alembic upgrade head`, then seeds.

Common tasks are wrapped in the `Makefile`: `make up|down|logs|seed|test|lint|train`.

Backend (run from `backend/`, deps in repo-root `.venv`):
- Tests: `pytest -q` · single test: `pytest tests/test_features.py::test_bands_are_ordered`
- `test_features.py` and `test_api.py` need **no DB**; DB-backed paths are exercised in CI where PostGIS is up.
- Lint: `ruff check app` (autofix `--fix`)
- Migrate: `alembic upgrade head` · new migration: `alembic revision -m "msg"` (hand-edit; see `migrations/versions/0001_initial.py`)
- Seed: `python -m app.etl.seed` (idempotent — events → tiles → routes, in that order)
- Train model: `python -m app.ml.train --kind logistic|lightgbm` → writes `app/ml/artifacts/flood_model.pkl`, and prints spatially-blocked CV AUC for both the model and the weighted baseline
- Rebuild terrain from live sources: `python -m app.etl.build_terrain` → rewrites the committed `data/accra_terrain.csv` (a few minutes; the DEM pull is quota-throttled and cached). Only needed when refreshing the inputs — seeding reads the committed CSV.

Frontend (run from `frontend/`): `npm run dev` · `npm run build` · `npm run typecheck`.

## Architecture (the parts that span files)

**Risk scoring pipeline.** Six normalised (0–1) features per H3 cell — elevation, slope, drainage, imperviousness, historical-flood-density, recent-rainfall — defined in `app/ml/features.py` (`TileFeatures`, `FEATURE_ORDER`, `BASELINE_WEIGHTS`). Two scorers share these features:
- Transparent weighted baseline (`weighted_score`) — uses all of `FEATURE_ORDER`.
- ML classifier (`app/ml/model.py` `RiskModel`) — loads a persisted sklearn/LightGBM pipeline if present, else **falls back to the weighted baseline**. So the API always works, even with no trained artifact.

**`MODEL_FEATURE_ORDER` is the training/inference contract, and it is deliberately *not* `FEATURE_ORDER`.** It omits `hist_flood_density`, which is a kernel over the recorded flood incidents — the same records any label set is built from. Feeding it to a fitted model is target leakage. The baseline may use it (a hand-specified index isn't fitted to those labels); a fitted model may not. `TileFeatures.vector()` serves the baseline, `.model_vector()` serves the model.

**The four static features are real measurements, not proxies** (`backend/data/accra_terrain.csv`, built by `app/etl/build_terrain.py`): Copernicus DEM elevation/slope, HAND against the OSM waterway network for drainage, OSM building density for imperviousness. The CSV is committed so seed/CI need no network. **A land mask matters more than it sounds:** open water is flat, at 0 m, and 0 m above drainage — a perfect flood cell to any terrain index — so unmasked, the map rates the Gulf of Guinea "extreme". See `docs/DATA.md` for provenance, limitations, and the honest (spatially-blocked) validation numbers.

**Two scoring paths** (`app/services/risk.py`): fast path reads precomputed `risk_tiles` (populated by ETL `build_tiles`); on a miss it *synthesises* features on the fly (distance-to-hotspot proxy + live PostGIS queries for historical density and recent rainfall) and penalises confidence. Results are Redis-cached.

**H3 everywhere.** `app/services/geo.py` wraps h3 v4 and holds `ACCRA_HOTSPOTS` and `GHANA_BBOX`. Rainfall, tiles, and route corridors all key on the same H3 grid (`H3_RESOLUTION`, default 8) so joins line up. GeoJSON uses lng/lat order; h3 uses lat/lng — `geo.py` is the conversion boundary.

**Route alerts couple the two features** (`app/services/routes_service.py`, `alerts_service.py`): a route's status = f(baseline risk of worst tile it crosses, forecast precip over those tiles). `refresh_cycle` refreshes rainfall then calls `evaluate_and_raise_alerts`, which materialises `RouteAlert` rows and notifies subscribers (`_notify` is a stub — swap for FCM/Twilio).

**The scheduled ETL runs two ways, from one code path.** Locally, `app/etl/worker.py` (APScheduler, `RAINFALL_REFRESH_CRON`). In production, Render's free plan has **no background workers**, so the worker isn't deployed at all — instead GitHub Actions cron (`.github/workflows/refresh.yml`) POSTs to `/api/v1/internal/refresh` (shared secret `CRON_SECRET`, 202 + background task). Both call the same `refresh_cycle` in `app/api/routes/internal.py`, so they can't drift. If you add work to the cycle, add it there.

**ETL is fallback-tolerant by design.** `rainfall.py` uses key-free Open-Meteo (GPM/IMERG is the documented upgrade). `osm_routes.py` tries Overpass, falls back to `SEED_ROUTES`. `terrain.py` reads the committed terrain CSV, falling back to a distance-to-hotspot proxy for cells outside it. This keeps dev/CI fully functional offline; real sources plug in at these seams. **Overpass requires an identifying User-Agent** (`app/etl/osm_terrain.UA`) — without it Apache answers 406 and the fallback fires silently, which is exactly what happened to `osm_routes` for months.

**Auth.** Supabase JWT verified in `app/security.py`. Public endpoints (risk, routes, active alerts) are open; only `POST /alerts/subscribe` requires a user. Outside production with no `SUPABASE_JWT_SECRET`, tokens are accepted unverified (dev convenience) — never rely on that in prod.

**Config.** All settings via `app/config.py` (pydantic-settings, env-driven, local-compose defaults). Two DB URLs: async (`DATABASE_URL`, asyncpg — app runtime) and sync (`DATABASE_URL_SYNC`, psycopg — Alembic + entrypoint wait-loop). Redis cache/rate-limit (`app/cache.py`) **fails open** — never let a Redis outage break request handling.

## Conventions

- New API surface: add a Pydantic schema in `app/schemas.py`, a router in `app/api/routes/`, register it in `app/main.py`. Keep business logic in `app/services/`, not routers.
- Any change to risk features must update `FEATURE_ORDER`, `MODEL_FEATURE_ORDER`, `BASELINE_WEIGHTS`, the `RiskTile` columns, the migration, and `app/etl/build_terrain.py` together.
- The risk grid bakes in both the terrain data and the model, so `seed.py` re-tiles whenever a tile's `model_version` differs from the current model. **Bump the model version when you change the features**, or production will keep serving scores from the old ones.
- Frontend talks to the API only through the typed client in `frontend/lib/api.ts`; band→colour mapping (`BAND_COLOR`) lives there too. MapLibre components are client-only (`dynamic(..., { ssr: false })`).
