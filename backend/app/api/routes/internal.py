"""Internal ETL trigger, for an external scheduler.

Render's free tier has no background workers, so `app.etl.worker` (APScheduler)
never runs in production: rainfall was never refreshed, `rainfall_recent_mm`
stayed 0, and `evaluate_and_raise_alerts` never fired. Half the product was
static.

This endpoint is the free-tier substitute — GitHub Actions (`.github/workflows/
refresh.yml`) calls it on a schedule and the work happens inside the web service
we already pay nothing for. The refresh takes a couple of minutes, so it runs as
a background task and the endpoint returns 202 immediately; a scheduler that has
to hold a two-minute HTTP connection open is a scheduler that will time out.

Auth is a shared secret, not a user JWT — there is no user here. Unset
`CRON_SECRET` disables the endpoint outright rather than leaving it open.
"""
from __future__ import annotations

import logging
import secrets

from fastapi import APIRouter, BackgroundTasks, Header, HTTPException, status

from app.config import settings
from app.db import SessionLocal
from app.etl.rainfall import refresh_rainfall
from app.services.alerts_service import evaluate_and_raise_alerts

log = logging.getLogger("api.internal")

router = APIRouter(prefix="/internal", tags=["internal"])


def _authorise(key: str | None) -> None:
    if not settings.cron_secret:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "refresh endpoint disabled — CRON_SECRET is not set",
        )
    # Constant-time: a plain `!=` leaks the secret one byte at a time to anyone
    # who can measure response latency.
    if not key or not secrets.compare_digest(key, settings.cron_secret):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "bad cron key")


async def refresh_cycle() -> None:
    """Pull rainfall, then re-evaluate route flood alerts against it."""
    try:
        async with SessionLocal() as db:
            rows = await refresh_rainfall(db)
        async with SessionLocal() as db:
            raised = await evaluate_and_raise_alerts(db)
        log.info("refresh done: %d rainfall rows, %d alerts raised", rows, raised)
    except Exception:
        # A background task that dies silently is a scheduled job that looks
        # healthy while doing nothing — which is the bug we are fixing.
        log.exception("refresh cycle failed")
        raise


@router.post("/refresh", status_code=status.HTTP_202_ACCEPTED)
async def trigger_refresh(
    background: BackgroundTasks,
    x_cron_key: str | None = Header(default=None, alias="X-Cron-Key"),
) -> dict:
    """Kick off a rainfall + alert-evaluation cycle. Returns immediately."""
    _authorise(x_cron_key)
    background.add_task(refresh_cycle)
    log.info("refresh accepted")
    return {"status": "accepted"}
