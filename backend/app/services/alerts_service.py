"""Alert generation, retrieval and subscription.

`evaluate_and_raise_alerts` is called after each rainfall refresh (by the local
worker, or in production by the cron-driven `refresh_cycle`): it walks every
route forecast and materialises RouteAlert rows for any route that reaches
'warning' or 'severe'. Subscribers are then notified — Web Push for
channel="push" (see `app.services.push`), in-app only for channel="web".

Raising the alert and delivering it are deliberately decoupled: the row is the
product, and `GET /alerts` serves it whether or not any push got through.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import logging

from sqlalchemy import delete, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AlertSubscription, RouteAlert, TrotroRoute
from app.schemas import AlertResponse, SubscribeRequest, SubscribeResponse
from app.services.push import is_gone, push_enabled, send_push
from app.services.routes_service import route_forecast

log = logging.getLogger("alerts")

_LEVEL = {"warning": "warning", "severe": "severe"}


def _payload(alert: RouteAlert) -> dict:
    """What the service worker receives and renders as a notification."""
    return {
        "title": f"Flood {alert.level} on your route",
        "body": alert.message,
        "level": alert.level,
        "route_id": alert.route_id,
        "url": "/routes",
    }


async def _notify(db: AsyncSession, sub: AlertSubscription,
                  alert: RouteAlert) -> None:
    """Deliver an alert to one subscriber, by channel.

    Never raises: a delivery problem must not roll back the alert that was just
    raised. The alert is the product; the push is a courtesy on top of it.
    """
    if sub.channel != "push" or not sub.push_subscription:
        # channel="web" is in-app only — the alert is already on GET /alerts.
        log.info("ALERT → user=%s channel=%s route=%s level=%s",
                 sub.user_id, sub.channel, alert.route_id, alert.level)
        return

    status = await send_push(sub.push_subscription, _payload(alert))
    if is_gone(status):
        # The browser revoked or rotated this endpoint. Keeping it means
        # pushing into the void on every cycle from here to eternity.
        log.info("pruning dead push subscription %s (status=%s)", sub.id, status)
        await db.delete(sub)


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
            await _notify(db, sub, alert)
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


def push_subscriber_id(endpoint: str) -> str:
    """Who a subscriber without an account is: their browser's push endpoint.

    Riders get alerts without signing up, so the endpoint stands in for the
    account. It's hashed, prefixed and cut to fit `user_id` (64 chars), so it
    can never collide with a Supabase user id.
    """
    return "push:" + hashlib.sha256(endpoint.encode()).hexdigest()[:59]


async def subscribe(db: AsyncSession, user_id: str,
                    req: SubscribeRequest) -> SubscribeResponse:
    # Now that anyone can subscribe, an unknown route is a 404, not a foreign
    # key violation surfacing as a 500.
    if await db.get(TrotroRoute, req.route_id) is None:
        raise LookupError(f"no route {req.route_id}")
    handle = req.push_subscription.model_dump() if req.push_subscription else None
    # Only promise a notification we can actually deliver.
    delivers = push_enabled() if req.channel == "push" else True

    existing = (await db.execute(select(AlertSubscription).where(
        AlertSubscription.user_id == user_id,
        AlertSubscription.route_id == req.route_id,
        AlertSubscription.channel == req.channel,
    ))).scalar_one_or_none()
    if existing:
        # Re-subscribing is how a browser hands us a *rotated* push endpoint —
        # same user, same route, new handle. Returning early without taking it
        # would pin the row to an endpoint that no longer exists.
        if handle is not None and existing.push_subscription != handle:
            existing.push_subscription = handle
            await db.commit()
        return SubscribeResponse(id=existing.id, route_id=req.route_id,
                                 channel=req.channel, created=False,
                                 delivers=delivers)

    sub = AlertSubscription(user_id=user_id, route_id=req.route_id,
                            channel=req.channel, contact=req.contact,
                            push_subscription=handle)
    db.add(sub)
    await db.commit()
    await db.refresh(sub)
    return SubscribeResponse(id=sub.id, route_id=req.route_id,
                             channel=req.channel, created=True,
                             delivers=delivers)


async def send_test(db: AsyncSession, user_id: str, route_id: str) -> int | None:
    """Push a test notification to this subscriber's alert for a route, by the
    same path a real alert takes: the stored subscription, our VAPID signature,
    the push service, the service worker. So a rider sees it work today instead
    of finding out in the first storm. Returns `send_push`'s result (None =
    delivered); LookupError if they don't follow the route.
    """
    sub = (await db.execute(select(AlertSubscription).where(
        AlertSubscription.user_id == user_id,
        AlertSubscription.route_id == route_id,
        AlertSubscription.channel == "push",
    ))).scalar_one_or_none()
    if sub is None or not sub.push_subscription:
        raise LookupError("this browser doesn't follow that route")
    route = await db.get(TrotroRoute, route_id)
    status = await send_push(sub.push_subscription, {
        "title": "FloodWatch: alerts are on",
        "body": f"You'll get a notification like this if {route.name} "
                "is likely to flood.",
        "level": "test",
        "route_id": route_id,
        "url": "/routes",
    })
    if is_gone(status):
        await db.delete(sub)
        await db.commit()
    return status


async def unsubscribe(db: AsyncSession, user_id: str, route_id: str) -> bool:
    """Stop push alerts for a route. True if there was something to stop."""
    result = await db.execute(delete(AlertSubscription).where(
        AlertSubscription.user_id == user_id,
        AlertSubscription.route_id == route_id,
        AlertSubscription.channel == "push",
    ))
    await db.commit()
    return result.rowcount > 0
