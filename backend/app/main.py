"""FastAPI application factory.

Wires routers, CORS, OpenAPI metadata and a lightweight startup check. Auth is
per-endpoint (Supabase JWT) rather than global so the public risk map stays open.
"""
from __future__ import annotations

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import __version__
from app.api.routes import alerts, health, internal, reports, risk, routes_ep
from app.config import settings

logging.basicConfig(level=logging.INFO)

DESCRIPTION = """
**FloodWatch Ghana API** — flood-risk scoring and trotro route flood alerts.

* `risk/*` — per-point, per-area and H3-tile flood-risk scoring.
* `routes/*` — trotro routes with live flood status + forecasts.
* `alerts/*` — active route alerts and subscriptions (Supabase auth).
"""


def create_app() -> FastAPI:
    app = FastAPI(
        title="FloodWatch Ghana",
        version=__version__,
        description=DESCRIPTION,
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
        contact={"name": "FloodWatch Ghana"},
        license_info={"name": "MIT"},
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    p = settings.api_v1_prefix
    app.include_router(health.router, prefix=p)
    app.include_router(risk.router, prefix=p)
    app.include_router(routes_ep.router, prefix=p)
    app.include_router(alerts.router, prefix=p)
    app.include_router(reports.router, prefix=p)
    app.include_router(internal.router, prefix=p)

    @app.get("/", tags=["meta"])
    async def root() -> dict:
        return {"service": "floodwatch-ghana", "version": __version__,
                "docs": "/docs", "api": p}

    return app


app = create_app()
