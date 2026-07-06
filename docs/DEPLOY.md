# Deploying FloodWatch Ghana

Free-tier stack, three moving parts: **database** (Neon Postgres + PostGIS),
**backend** (Docker → Render web service), and **frontend** (Next.js → Vercel).
No paid upgrades required. Render background workers are *not* free, so the
scheduled ETL worker is omitted from the live deploy (run it locally, or add it
later on a paid plan / external cron).

## 1. Database — Neon

1. Create a project at [neon.tech](https://neon.tech) (free tier). Pick a region
   near your users (e.g. `eu-central-1` / Frankfurt to match the backend).
2. In the Neon **SQL editor** enable PostGIS:
   ```sql
   create extension if not exists postgis;
   ```
3. From **Connection Details**, copy the connection string and build two URLs
   (Neon requires TLS — the app adds `ssl=True` automatically for non-local hosts):
   - `DATABASE_URL` → `postgresql+asyncpg://<user>:<pw>@<host>/<db>`
   - `DATABASE_URL_SYNC` → `postgresql+psycopg://<user>:<pw>@<host>/<db>`

   The **host** is what you print as the live "database" URL, e.g.
   `ep-cool-name-123.eu-central-1.aws.neon.tech`.

Migrations + seed run automatically on backend boot (`entrypoint.sh` →
`alembic upgrade head` → `python -m app.etl.seed`). Data persists across restarts.

## 2. Backend — Render

1. Push this repo to GitHub.
2. Render → **New → Blueprint**, point it at `render.yaml`. It provisions the
   `floodwatch-backend` Docker web service (+ a free Redis key-value store).
3. Fill the `sync: false` secrets in the dashboard:
   - `DATABASE_URL`, `DATABASE_URL_SYNC` — from Neon (step 1).
   - `SUPABASE_JWT_SECRET` — from your Supabase project (only needed for the
     authed subscribe endpoint; public risk/routes/reports work without it).
   - `CORS_ORIGINS` — set to your Vercel origin once the frontend is deployed,
     e.g. `https://your-app.vercel.app` (comma-separated for multiple).
4. Deploy. `REDIS_URL` is wired automatically from the Render Redis service.
   Redis fails open, so the backend runs fine even if it's unavailable.

> Free web services sleep after ~15 min idle and cold-start (~30–50 s) on the
> next request, re-running seed. That's expected on the free tier.

## 3. Frontend — Vercel

- Import the repo, set **Root Directory** = `frontend`.
- Env vars:
  - `NEXT_PUBLIC_API_URL` = the backend `/api/v1` URL (e.g.
    `https://floodwatch-backend.onrender.com/api/v1`).
  - `NEXT_PUBLIC_MAP_STYLE` (optional MapLibre style URL).
  - `NEXT_PUBLIC_SUPABASE_URL`, `NEXT_PUBLIC_SUPABASE_ANON_KEY` (optional, for auth).
- Deploy. Then set the backend's `CORS_ORIGINS` to the resulting Vercel domain
  and redeploy the backend so the browser calls are allowed.

## 4. Post-deploy checks
```bash
curl https://<backend>/api/v1/health
curl "https://<backend>/api/v1/risk/area?name=Kaneshie"
curl https://<backend>/api/v1/routes
```
End-to-end write path (proves the DB persists): open the frontend, click the map
to score a point, then submit a **community flood report**. It writes a
`FloodEvent` to Neon and feeds back into the risk score. Confirm with:
```bash
curl "https://<backend>/api/v1/reports/recent?limit=5"
```

## Redeploy cheatsheet

| Piece    | Auto                              | Manual                                  |
|----------|-----------------------------------|-----------------------------------------|
| Frontend | push to `main` (Vercel)           | `vercel --prod` in `frontend/`          |
| Backend  | push to `main` (`autoDeploy`)     | Render → Manual Deploy → latest commit  |
| Database | n/a (persistent)                  | schema via `alembic upgrade head` on boot |

## Scheduled ETL (optional, not on free tier)
The worker (`app/etl/worker.py`) runs `RAINFALL_REFRESH_CRON` (default 30 min):
refresh rainfall from Open-Meteo/GPM, re-evaluate route alerts. Run it locally
(`python -m app.etl.worker`) or add a paid Render worker / external cron hitting
`python -m app.etl.worker --once`.

## Upgrading the model
```bash
python -m app.ml.train --kind lightgbm    # writes app/ml/artifacts/flood_model.pkl
```
The Dockerfile trains a logistic baseline at build time so inference always works;
rebuild/redeploy the backend image to ship a new artifact.
