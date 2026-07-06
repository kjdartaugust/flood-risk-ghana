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
- Train model: `python -m app.ml.train --kind logistic|lightgbm` → writes `app/ml/artifacts/flood_model.pkl`

Frontend (run from `frontend/`): `npm run dev` · `npm run build` · `npm run typecheck`.

## Architecture (the parts that span files)

**Risk scoring pipeline.** Six normalised (0–1) features per H3 cell — elevation, slope, drainage, imperviousness, historical-flood-density, recent-rainfall — defined in `app/ml/features.py` (`TileFeatures`, `FEATURE_ORDER`, `BASELINE_WEIGHTS`). Two scorers share these features:
- Transparent weighted baseline (`weighted_score`).
- ML classifier (`app/ml/model.py` `RiskModel`) — loads a persisted sklearn/LightGBM pipeline if present, else **falls back to the weighted baseline**. So the API always works, even with no trained artifact. `FEATURE_ORDER` is the contract between training and inference — keep it in sync.

**Two scoring paths** (`app/services/risk.py`): fast path reads precomputed `risk_tiles` (populated by ETL `build_tiles`); on a miss it *synthesises* features on the fly (distance-to-hotspot proxy + live PostGIS queries for historical density and recent rainfall) and penalises confidence. Results are Redis-cached.

**H3 everywhere.** `app/services/geo.py` wraps h3 v4 and holds `ACCRA_HOTSPOTS` and `GHANA_BBOX`. Rainfall, tiles, and route corridors all key on the same H3 grid (`H3_RESOLUTION`, default 8) so joins line up. GeoJSON uses lng/lat order; h3 uses lat/lng — `geo.py` is the conversion boundary.

**Route alerts couple the two features** (`app/services/routes_service.py`, `alerts_service.py`): a route's status = f(baseline risk of worst tile it crosses, forecast precip over those tiles). The worker (`app/etl/worker.py`, APScheduler cron `RAINFALL_REFRESH_CRON`) refreshes rainfall then calls `evaluate_and_raise_alerts`, which materialises `RouteAlert` rows and notifies subscribers (`_notify` is a stub — swap for FCM/Twilio).

**ETL is fallback-tolerant by design.** `rainfall.py` uses key-free Open-Meteo (GPM/IMERG is the documented upgrade). `osm_routes.py` tries Overpass, falls back to `SEED_ROUTES`. `terrain.py` uses a `sample_dem` proxy with a clearly-marked hook to swap in real rasterio DEM reads. This keeps dev/CI fully functional offline; real sources plug in at these seams.

**Auth.** Supabase JWT verified in `app/security.py`. Public endpoints (risk, routes, active alerts) are open; only `POST /alerts/subscribe` requires a user. Outside production with no `SUPABASE_JWT_SECRET`, tokens are accepted unverified (dev convenience) — never rely on that in prod.

**Config.** All settings via `app/config.py` (pydantic-settings, env-driven, local-compose defaults). Two DB URLs: async (`DATABASE_URL`, asyncpg — app runtime) and sync (`DATABASE_URL_SYNC`, psycopg — Alembic + entrypoint wait-loop). Redis cache/rate-limit (`app/cache.py`) **fails open** — never let a Redis outage break request handling.

## Conventions

- New API surface: add a Pydantic schema in `app/schemas.py`, a router in `app/api/routes/`, register it in `app/main.py`. Keep business logic in `app/services/`, not routers.
- Any change to risk features must update `FEATURE_ORDER`, `BASELINE_WEIGHTS`, the `RiskTile` columns, and the migration together.
- Frontend talks to the API only through the typed client in `frontend/lib/api.ts`; band→colour mapping (`BAND_COLOR`) lives there too. MapLibre components are client-only (`dynamic(..., { ssr: false })`).
