"""Route alert + subscription endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.cache import rate_limit
from app.config import settings
from app.db import get_db
from app.schemas import (
    AlertResponse,
    SubscribeRequest,
    SubscribeResponse,
    VapidKeyResponse,
)
from app.security import Principal, require_user
from app.services import alerts_service as svc
from app.services.push import push_enabled

router = APIRouter(prefix="/alerts", tags=["alerts"],
                   dependencies=[Depends(rate_limit)])


@router.get("", response_model=list[AlertResponse],
            summary="Active route flood alerts")
async def active_alerts(db: AsyncSession = Depends(get_db)) -> list[AlertResponse]:
    return await svc.list_active_alerts(db)


@router.get("/vapid-key", response_model=VapidKeyResponse,
            summary="Public VAPID key for Web Push subscription")
async def vapid_key() -> VapidKeyResponse:
    """The browser needs this to call `PushManager.subscribe()`.

    Public by design — it's the *public* half, and it's useless without a
    matching signature from the private half we never expose. 503 when push
    isn't configured, so the UI can hide the button instead of offering a
    notification that will never arrive.
    """
    if not push_enabled():
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "push notifications are not configured on this server",
        )
    return VapidKeyResponse(public_key=settings.vapid_public_key)


@router.post("/subscribe", response_model=SubscribeResponse,
             summary="Subscribe to alerts for a route")
async def subscribe(
    req: SubscribeRequest,
    user: Principal = Depends(require_user),
    db: AsyncSession = Depends(get_db),
) -> SubscribeResponse:
    return await svc.subscribe(db, user.id, req)
