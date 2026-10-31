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

A 202 only says a run started. Each run is recorded in `refresh_runs`, and
`GET /internal/refresh` serves the latest — how anyone outside the host can tell
whether it actually saved any rain.

The scheduler can also bring the rain with it. Open-Meteo's free API limits
each IP per day and Render's free tier shares one outbound IP among many apps,
so from here Open-Meteo answers 429 "Daily API request limit exceeded". The
workflow asks `GET /internal/refresh/plan` what to fetch, fetches it from its
own IP, and posts it with the trigger.

There is no user here, so auth isn't a user JWT. Either of these is enough:

* a GitHub Actions OIDC token from `refresh.yml` in the repo this server was
  deployed from (`CRON_GITHUB_REPO`, which Render fills in by itself). GitHub
  signs it, so nothing has to be copied between GitHub and the host: on a fresh
  deploy the schedule just works.
* `CRON_SECRET`, sent as `X-Cron-Key`, for any other scheduler.

With neither configured the endpoint is disabled outright rather than left open.
"""
from __future__ import annotations

import logging
import secrets

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import SessionLocal, get_db
from app.etl.rainfall import openmeteo_url, refresh_rainfall, sample_points, top_tiles
from app.models import RefreshRun
from app.schemas import RefreshPlanResponse, RefreshRequest, RefreshRunResponse
from app.security import bearer, is_github_workflow
from app.services.alerts_service import evaluate_and_raise_alerts
from app.services.push import load_keys

log = logging.getLogger("api.internal")

router = APIRouter(prefix="/internal", tags=["internal"])


async def _authorise(key: str | None, token: str | None) -> None:
    if not settings.cron_secret and not settings.cron_github_repo:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "refresh endpoint disabled — set CRON_GITHUB_REPO or CRON_SECRET",
        )
    # Constant-time: a plain `!=` leaks the secret one byte at a time to anyone
    # who can measure response latency. Bytes, because compare_digest refuses
    # non-ASCII str and a header can carry some.
    if key and settings.cron_secret and secrets.compare_digest(
        key.encode(), settings.cron_secret.encode()
    ):
        return
    if token and settings.cron_github_repo and await is_github_workflow(
        token, settings.cron_github_repo, "refresh.yml"
    ):
        return
    raise HTTPException(status.HTTP_401_UNAUTHORIZED, "bad cron credentials")


async def _start_run() -> int:
    async with SessionLocal() as db:
        run = RefreshRun()
        db.add(run)
        await db.commit()
        return run.id


async def _finish_run(run_id: int, **outcome: object) -> None:
    try:
        async with SessionLocal() as db:
            await db.execute(update(RefreshRun).where(RefreshRun.id == run_id)
                             .values(finished_at=func.now(), **outcome))
            await db.commit()
    except Exception:
        log.exception("could not record how refresh %d went", run_id)


def _summary(exc: Exception) -> str:
    """The error's first line, kept short: GET /internal/refresh is public."""
    first = (str(exc).splitlines() or [""])[0]
    return f"{type(exc).__name__}: {first}"[:300]


async def refresh_cycle(
    run_id: int | None = None,
    fetched: tuple[list, list] | None = None,
) -> None:
    """Pull rainfall (or take what the caller `fetched`), then re-evaluate route
    flood alerts against it, and record how it went."""
    # A no-op once the web app has loaded them; here for the standalone worker.
    await load_keys()
    if run_id is None:
        run_id = await _start_run()
    try:
        async with SessionLocal() as db:
            rows = await refresh_rainfall(db, fetched=fetched)
        async with SessionLocal() as db:
            raised = await evaluate_and_raise_alerts(db)
        log.info("refresh done: %d rainfall rows, %d alerts raised", rows, raised)
    except Exception as exc:
        # A background task that dies silently is a scheduled job that looks
        # healthy while doing nothing — which is the bug we are fixing.
        log.exception("refresh cycle failed")
        await _finish_run(run_id, error=_summary(exc))
        raise
    await _finish_run(run_id, rainfall_rows=rows, alerts_raised=raised)


@router.post("/refresh", status_code=status.HTTP_202_ACCEPTED)
async def trigger_refresh(
    background: BackgroundTasks,
    body: RefreshRequest | None = None,
    x_cron_key: str | None = Header(default=None, alias="X-Cron-Key"),
    creds: HTTPAuthorizationCredentials | None = Depends(bearer),
) -> dict:
    """Kick off a rainfall + alert-evaluation cycle. Returns immediately, with
    the run's id; GET /internal/refresh says how it went."""
    await _authorise(x_cron_key, creds.credentials if creds else None)
    fetched = None
    if body is not None:
        fetched = (body.points, [f.model_dump() for f in body.forecasts])
    run_id = await _start_run()
    background.add_task(refresh_cycle, run_id, fetched)
    log.info("refresh %d accepted (%s)", run_id,
             "rain posted" if fetched else "will fetch rain")
    return {"status": "accepted", "run": run_id}


@router.get("/refresh/plan", response_model=RefreshPlanResponse,
            summary="What to fetch for a refresh")
async def refresh_plan(db: AsyncSession = Depends(get_db)) -> RefreshPlanResponse:
    """For a scheduler that fetches the rain itself and posts it back, because
    Open-Meteo turns this server's shared IP away (see `app.etl.rainfall`).
    Public: the points are tile centroids, which /risk/tiles already serves."""
    points = sample_points(await top_tiles(db))
    return RefreshPlanResponse(points=points, url=openmeteo_url(points))


@router.get("/refresh", response_model=RefreshRunResponse,
            summary="The latest refresh, and whether it saved any rain")
async def latest_refresh(db: AsyncSession = Depends(get_db)) -> RefreshRunResponse:
    """Public on purpose: times, counts and a one-line error, nothing secret."""
    run = (await db.execute(
        select(RefreshRun).order_by(RefreshRun.id.desc()).limit(1)
    )).scalar_one_or_none()
    if run is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no refresh has run yet")
    return RefreshRunResponse.model_validate(run, from_attributes=True)
