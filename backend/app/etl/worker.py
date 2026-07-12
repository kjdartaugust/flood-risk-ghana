"""Scheduled ETL worker (APScheduler).

Runs the rainfall refresh on a cron cadence and, after each refresh, re-evaluates
route flood alerts. Deployed as its own container (see docker-compose `worker`);
on Render use a Cron Job that invokes `python -m app.etl.worker --once`.
"""
from __future__ import annotations

import argparse
import asyncio
import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from app.api.routes.internal import refresh_cycle
from app.config import settings

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("worker")


def _run_once() -> None:
    asyncio.run(refresh_cycle())


def _run_scheduler() -> None:
    sched = AsyncIOScheduler(timezone="UTC")
    trigger = CronTrigger.from_crontab(settings.rainfall_refresh_cron)
    sched.add_job(refresh_cycle, trigger, id="rainfall_refresh",
                  max_instances=1, coalesce=True)
    sched.start()
    log.info("worker started; cron=%s", settings.rainfall_refresh_cron)
    loop = asyncio.get_event_loop()
    try:
        loop.run_forever()
    except (KeyboardInterrupt, SystemExit):
        log.info("worker shutting down")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true", help="run one cycle and exit")
    args = ap.parse_args()
    if args.once:
        _run_once()
    else:
        _run_scheduler()
