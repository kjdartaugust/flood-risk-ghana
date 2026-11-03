# Deploying FloodWatch Ghana

Free-tier stack, three moving parts: **database** (Neon Postgres + PostGIS),
**backend** (Docker → Render web service), and **frontend** (Next.js → Vercel).
No paid upgrades required. Render background workers are *not* free, so the
rain checks run in GitHub Actions instead, started on time by a free cron-job.org
job (section 5).

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

## 5. Rain checks on time — cron-job.org

The rain + alert cycle runs in GitHub Actions (`.github/workflows/refresh.yml`; see
"Scheduled refresh" in the README). GitHub's own schedule can't be relied on: it
runs scheduled workflows late, or skips them, when it's busy (on 2–3 Nov 2026 only
2 of 8 ran). So a free [cron-job.org](https://cron-job.org) job starts the workflow
every 3 hours through GitHub's API, and the workflow's own schedule stays as the
fallback.

1. **A key that can only start workflows.** GitHub → Settings → Developer settings
   → Personal access tokens → **Fine-grained tokens** → Generate new token.
   - Repository access: **Only select repositories**, then this repo.
   - Permissions: **Actions: Read and write**. Nothing else.
   - Expiration: your call, up to a year. The timer stops when the key expires.

   The key (`github_pat_…`) is shown once: paste it straight into step 2.
2. **The job.** cron-job.org → **Create cronjob**:
   - URL: `https://api.github.com/repos/kjdartaugust/flood-risk-ghana/actions/workflows/refresh.yml/dispatches`
     (on a fork, your own owner/repo).
   - Schedule: **Custom**, with the crontab expression `17 */3 * * *` (minute 17 of
     every third hour).
   - Advanced: time zone **UTC** (also Ghana time). A new job takes the account's
     time zone, which may be a different one, and the job would then run on that
     zone's hours. Request method **POST**; a header named `Authorization` whose
     value is `Bearer ` followed by the key; request body `{"ref":"main"}`.
     cron-job.org then suggests a `Content-Type` header for JSON; GitHub doesn't
     need one.
   - Notifications: on when the job fails, so an expired key gets noticed.
3. **Test run.** GitHub answers `204`, and a `workflow_dispatch` run of **refresh**
   appears in the Actions tab. `401` means the key is wrong or has expired; `403` or
   `404` means it can't run workflows on this repo.

Runs never overlap (the workflow's `concurrency` group), so when the timer and the
fallback fire together, one simply waits for the other.

## Redeploy cheatsheet

| Piece    | Auto                              | Manual                                  |
|----------|-----------------------------------|-----------------------------------------|
| Frontend | push to `main` (Vercel)           | `vercel --prod` in `frontend/`          |
| Backend  | push to `main` (`autoDeploy`)     | Render → Manual Deploy → latest commit  |
| Database | n/a (persistent)                  | schema via `alembic upgrade head` on boot |

## Rain checks locally
`app/etl/worker.py` runs the same cycle on `RAINFALL_REFRESH_CRON` (default 30 min)
for local development: `python -m app.etl.worker`, or `--once` for a single run.
Production doesn't deploy it (no free background workers) and uses section 5.

## Upgrading the model
```bash
python -m app.ml.train --kind lightgbm    # writes app/ml/artifacts/flood_model.pkl
```
The Dockerfile trains a logistic baseline at build time so inference always works;
rebuild/redeploy the backend image to ship a new artifact.
