FROM python:3.12-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

# System deps for GeoAlchemy/shapely (GEOS) and psycopg build.
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgeos-dev libpq-dev bash curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .
RUN chmod +x entrypoint.sh

# Train a baseline model artifact at build time so inference works out of the box.
RUN python -m app.ml.train --kind logistic || true

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
    CMD curl -fsS http://localhost:8000/api/v1/health || exit 1

CMD ["./entrypoint.sh"]
