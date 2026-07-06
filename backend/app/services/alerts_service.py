"""Alert generation, retrieval and subscription.

`evaluate_and_raise_alerts` is called by the ETL worker after each rainfall
refresh: it walks every route forecast and materialises RouteAlert rows for any
route that reaches 'warning' or 'severe'. Subscribers are then notified via the
(pluggable) notifier — here a log/webhook stub ready for FCM/SMS.
"""
from __future__ import annotations

import datetime as dt
import logging

from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AlertSubscription, RouteAlert, TrotroRoute
from app.schemas import AlertResponse, SubscribeRequest, SubscribeResponse
from app.services.routes_service import route_forecast

log = logging.getLogger("alerts")

_LEVEL = {"warning": "warning", "severe": "severe"}


async def _notify(sub: AlertSubscription, alert: RouteAlert) -> None:
    """Deliver an alert to a subscriber. Stub: replace with FCM / Twilio."""
    log.info("ALERT → user=%s channel=%s route=%s level=%s",
             sub.user_id, sub.channel, alert.route_id, alert.level)


async def evaluate_and_raise_alerts(db: AsyncSession) -> int:
    """Recompute route forecasts and raise/expire alerts. Returns # raised."""
    now = dt.datetime.now(dt.UTC)
    # expire stale alerts
    await db.execute(update(RouteAlert)
                     .where(RouteAlert.expires_at < now, RouteAlert.active.is_(True))
                     .values(active=False))
    routes = (await db.execute(select(TrotroRoute))).scalars().all()
    raised = 0
    for route in routes:
        fc = await route_forecast(db, route.id)
        peak = max(fc.points, key=lambda p: p.risk_score, default=None)
        if peak is None or peak.status not in _LEVEL:
            continue
        exists = (await db.execute(text(
            "SELECT count(*) FROM route_alerts "
            "WHERE route_id=:id AND active AND level=:lvl"),
            {"id": route.id, "lvl": peak.status})).scalar()
        if exists:
            continue
        alert = RouteAlert(
            route_id=route.id, level=peak.status,
            message=f"{route.name}: {fc.summary}",
            expected_precip_mm=peak.precip_mm, risk_score=peak.risk_score,
            starts_at=now, expires_at=now + dt.timedelta(hours=6),
            payload={"peak_at": peak.at.isoformat()},
        )
        db.add(alert)
        await db.flush()
        subs = (await db.execute(select(AlertSubscription)
                .where(AlertSubscription.route_id == route.id))).scalars().all()
        for sub in subs:
            await _notify(sub, alert)
        raised += 1
    await db.commit()
    return raised


async def list_active_alerts(db: AsyncSession) -> list[AlertResponse]:
    stmt = text(
        """
        SELECT a.id, a.route_id, r.name, a.level, a.message,
               a.expected_precip_mm, a.risk_score, a.starts_at, a.expires_at
        FROM route_alerts a JOIN trotro_routes r ON r.id = a.route_id
        WHERE a.active ORDER BY a.risk_score DESC
        """
    )
    rows = (await db.execute(stmt)).all()
    return [AlertResponse(
        id=r[0], route_id=r[1], route_name=r[2], level=r[3], message=r[4],
        expected_precip_mm=r[5], risk_score=r[6], starts_at=r[7], expires_at=r[8],
    ) for r in rows]


async def subscribe(db: AsyncSession, user_id: str,
                    req: SubscribeRequest) -> SubscribeResponse:
    existing = (await db.execute(select(AlertSubscription).where(
        AlertSubscription.user_id == user_id,
        AlertSubscription.route_id == req.route_id,
        AlertSubscription.channel == req.channel,
    ))).scalar_one_or_none()
    if existing:
        return SubscribeResponse(id=existing.id, route_id=req.route_id,
                                 channel=req.channel, created=False)
    sub = AlertSubscription(user_id=user_id, route_id=req.route_id,
                            channel=req.channel, contact=req.contact)
    db.add(sub)
    await db.commit()
    await db.refresh(sub)
    return SubscribeResponse(id=sub.id, route_id=req.route_id,
                             channel=req.channel, created=True)
