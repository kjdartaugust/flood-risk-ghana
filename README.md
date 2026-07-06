# FloodWatch Ghana 🌊

A production flood-risk platform for Ghana. Two combined features:

1. **Flood-risk scoring & mapping** — check a flood-risk score for any location/area
   in Ghana before buying land, building, living, or starting a business. Built from
   historical flood records, rainfall time-series, elevation/DEM, drainage/slope,
   land cover, and known Accra hotspots (Kaneshie, Circle, Adabraka, Alajo).
2. **Trotro route flood alerts** — combines the risk layer with live/forecast rainfall
   to predict which trotro routes flood before and during rain, and pushes route-level
   warnings to commuters.

## Architecture

```
                    ┌──────────────┐
   Open data ──ETL──▶│  PostGIS     │◀── H3 hex scoring tiles
 (GPM/IMERG,         │  (Supabase)  │
  SRTM DEM,          └──────┬───────┘
  Sentinel LC,              │
  OSM roads)         ┌──────▼───────┐      ┌──────────────┐
                     │  FastAPI     │◀────▶│   Redis      │ cache + rate limit
   ML model ────────▶│  (inference) │      └──────────────┘
 (logistic +         └──────┬───────┘
  gradient boost)           │ OpenAPI / JWT (Supabase Auth)
                     ┌──────▼───────┐
                     │  Next.js +   │  MapLibre GL interactive risk map
                     │  React       │  + trotro route alerts
                     └──────────────┘
```

| Layer     | Tech                                                      |
|-----------|----------------------------------------------------------|
| Frontend  | Next.js 14 (App Router), React, MapLibre GL, TypeScript  |
| Backend   | FastAPI, SQLAlchemy (async), Alembic, Pydantic v2        |
| Data      | Supabase Postgres + PostGIS, H3 hex index, Redis         |
| ML        | scikit-learn (logistic baseline), LightGBM (upgrade)     |
| ETL       | httpx workers, APScheduler cron (rainfall refresh)       |
| Infra     | Docker Compose (local); Neon + Render + Vercel (deploy)  |

## Quick start (local)

```bash
cp .env.example .env          # fill in Supabase + Mapbox/MapLibre keys
docker compose up --build     # postgis + redis + backend + worker + frontend
# backend  → http://localhost:8000  (docs at /docs)
# frontend → http://localhost:3000
```

Run migrations + seed (first boot does this automatically via the backend entrypoint;
to run manually):

```bash
docker compose exec backend alembic upgrade head
docker compose exec backend python -m app.etl.seed
```

## Repo layout

```
flood-risk/
├── backend/                 FastAPI service + ETL + ML
│   ├── app/
│   │   ├── main.py          app factory, routers, middleware
│   │   ├── config.py        pydantic-settings
│   │   ├── db.py            async engine / session
│   │   ├── security.py      Supabase JWT verification
│   │   ├── cache.py         Redis cache + rate limiter
│   │   ├── models.py        SQLAlchemy ORM (PostGIS + H3)
│   │   ├── schemas.py       Pydantic request/response
│   │   ├── api/routes/      health, risk, routes, alerts, auth
│   │   ├── services/        risk scoring, routing, alerting
│   │   ├── ml/              train.py, model.py, features.py
│   │   └── etl/             rainfall, dem, landcover, osm, seed, worker
│   ├── migrations/          Alembic
│   ├── tests/               pytest
│   ├── Dockerfile
│   └── requirements.txt
├── frontend/                Next.js + MapLibre UI
├── docker-compose.yml
├── .github/workflows/ci.yml
├── .env.example
└── README.md
```

## API

OpenAPI docs are served at `/docs` (Swagger) and `/redoc`. Key endpoints:

| Method | Path                              | Purpose                                   |
|--------|-----------------------------------|-------------------------------------------|
| GET    | `/api/v1/health`                  | liveness / readiness                      |
| GET    | `/api/v1/risk/point?lat=&lng=`    | flood-risk score + confidence for a point |
| GET    | `/api/v1/risk/tiles?bbox=&res=`   | H3 risk tiles (GeoJSON) for a bbox        |
| GET    | `/api/v1/risk/area?name=`         | risk for a named area (e.g. Kaneshie)     |
| GET    | `/api/v1/routes`                  | trotro routes with current flood status   |
| GET    | `/api/v1/routes/{id}/forecast`    | route flood forecast from rainfall        |
| GET    | `/api/v1/alerts`                  | active route alerts                       |
| POST   | `/api/v1/alerts/subscribe`        | subscribe a route for push alerts (auth)  |
| POST   | `/api/v1/reports`                 | crowdsourced flood report (persists)      |
| GET    | `/api/v1/reports/recent`          | recent flood reports (historical + community) |

## Live deployment

The whole platform runs on free tiers (Neon + Render + Vercel).

| Piece    | Service          | URL                                                       |
|----------|------------------|-----------------------------------------------------------|
| Frontend | Vercel           | https://floodwatch-ghana-ten.vercel.app                   |
| Backend  | Render (Docker)  | https://floodwatch-backend-dlni.onrender.com/api/v1       |
| Database | Neon Postgres    | `ep-ancient-scene-atrq12o7.c-9.us-east-1.aws.neon.tech`   |

> The exact URLs above are one live instance; anyone redeploying from this repo
> gets their own Vercel/Render/Neon URLs (fill in your own).

> Render's free web service spins down after ~15 min idle; the first request after
> a nap takes ~30–50 s to cold-start (it re-seeds on boot). Keep-alive pinging is a
> deliberately separate later step.

### How to redeploy

- **Frontend (Vercel):** the repo is Git-connected with **Root Directory = `frontend`**,
  so a push to `main` auto-builds and deploys to production. Or run `vercel --prod`
  from `frontend/`. Env: `NEXT_PUBLIC_API_URL` = backend `/api/v1` URL.
- **Backend (Render):** push to `main` → Render auto-deploys from `render.yaml`
  (`autoDeploy: true`), or click **Manual Deploy → Deploy latest commit**. Secrets
  (`DATABASE_URL`, `DATABASE_URL_SYNC`, `CORS_ORIGINS`, `SUPABASE_JWT_SECRET`) are set
  once in the dashboard (`sync: false`). Migrations + seed run automatically on boot.
- **Database (Neon):** no redeploy — persistent. Data survives backend restarts.

Full first-time walkthrough: [`docs/DEPLOY.md`](docs/DEPLOY.md).

## Data sources & licensing

| Source                | Use                          | License              |
|-----------------------|------------------------------|----------------------|
| NASA GPM/IMERG        | rainfall time-series/forecast| NASA open            |
| Copernicus / SRTM DEM | elevation, slope, drainage   | open                 |
| Sentinel-2 land cover | impervious surface           | Copernicus open      |
| OpenStreetMap         | roads + trotro routes        | ODbL                 |
| Ghana Meteo / NADMO   | historical floods, warnings  | where available      |

## Disclaimer

Risk scores are probabilistic estimates for planning support only, not a guarantee.
Always consult NADMO and local authorities for emergency decisions.
