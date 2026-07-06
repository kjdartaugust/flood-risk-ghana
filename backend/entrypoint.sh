#!/usr/bin/env bash
# Backend container entrypoint: wait for DB, migrate, seed (first boot), serve.
set -euo pipefail

echo "⏳ waiting for Postgres..."
python - <<'PY'
import os, time, psycopg
url = os.environ.get("DATABASE_URL_SYNC", "")
for i in range(30):
    try:
        psycopg.connect(url, connect_timeout=3).close()
        print("✅ postgres ready"); break
    except Exception as e:
        print(f"  retry {i+1}/30: {e}"); time.sleep(2)
else:
    raise SystemExit("postgres never became ready")
PY

echo "▶ running migrations"
alembic upgrade head

if [ "${RUN_SEED:-true}" = "true" ]; then
  echo "▶ seeding (idempotent)"
  python -m app.etl.seed || echo "seed skipped/failed (non-fatal)"
fi

echo "🚀 starting API"
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}"
