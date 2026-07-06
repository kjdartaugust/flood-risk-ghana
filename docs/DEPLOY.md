# Deploying FloodWatch Ghana

Three moving parts: **database** (Supabase Postgres + PostGIS), **backend + worker**
(Docker → Fly.io or Render), and **frontend** (Next.js → Vercel or Render).

## 1. Database — Supabase

1. Create a Supabase project. In the SQL editor run:
   ```sql
   create extension if not exists postgis;
   ```
2. Grab two connection strings from **Project → Settings → Database**:
   - `DATABASE_URL` → `postgresql+asyncpg://postgres:<pw>@<host>:5432/postgres`
   - `DATABASE_URL_SYNC` → `postgresql+psycopg://postgres:<pw>@<host>:5432/postgres`
3. Copy the **JWT secret** (Settings → API) into `SUPABASE_JWT_SECRET`, and the
   project URL + anon key for the frontend.

Migrations run automatically on backend boot (`entrypoint.sh` → `alembic upgrade head`
→ seed). To run manually: `alembic upgrade head && python -m app.etl.seed`.

## 2. Redis

Use **Upstash** (free tier) or Fly Redis. Put the URL in `REDIS_URL`. The app fails
open if Redis is down, so this is non-blocking for a first deploy.

## 3. Backend + worker

### Option A — Fly.io
```bash
cd backend
fly launch --no-deploy            # uses fly.toml, primary_region jnb
fly secrets set \
  DATABASE_URL='postgresql+asyncpg://…' \
  DATABASE_URL_SYNC='postgresql+psycopg://…' \
  REDIS_URL='redis://…' \
  SUPABASE_URL='https://…' SUPABASE_JWT_SECRET='…'
fly deploy
# worker as a second process/app:
fly deploy --config fly.worker.toml   # or run the worker command in a Machine
```

### Option B — Render
Push the repo, then **New → Blueprint** and point at `render.yaml`. It provisions
the web service, worker, and Redis. Fill the `sync: false` secrets in the dashboard.
Add a **Cron Job** hitting `python -m app.etl.worker --once` if you prefer cron to
the always-on worker.

## 4. Frontend — Vercel

- Import the repo, set **Root Directory** = `frontend`.
- Env vars: `NEXT_PUBLIC_API_URL` (your backend `/api/v1` URL),
  `NEXT_PUBLIC_MAP_STYLE`, `NEXT_PUBLIC_SUPABASE_URL`, `NEXT_PUBLIC_SUPABASE_ANON_KEY`.
- Deploy. Update backend `CORS_ORIGINS` to the Vercel domain.

## 5. Post-deploy checks
```bash
curl https://<backend>/api/v1/health
curl "https://<backend>/api/v1/risk/area?name=Kaneshie"
curl https://<backend>/api/v1/routes
```
Open the frontend, click the map, search "Circle", and check the Trotro Alerts page.

## Scheduled ETL
The worker runs `RAINFALL_REFRESH_CRON` (default every 30 min): it refreshes
rainfall from Open-Meteo/GPM and re-evaluates route alerts. Tune via env var.

## Upgrading the model
```bash
python -m app.ml.train --kind lightgbm    # writes app/ml/artifacts/flood_model.pkl
```
Rebuild/redeploy the backend image (the Dockerfile trains a logistic baseline at
build time so inference always works).
