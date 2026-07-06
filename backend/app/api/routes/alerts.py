"""Route alert + subscription endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.cache import rate_limit
from app.db import get_db
from app.schemas import AlertResponse, SubscribeRequest, SubscribeResponse
from app.security import Principal, require_user
from app.services import alerts_service as svc

router = APIRouter(prefix="/alerts", tags=["alerts"],
                   dependencies=[Depends(rate_limit)])


@router.get("", response_model=list[AlertResponse],
            summary="Active route flood alerts")
async def active_alerts(db: AsyncSession = Depends(get_db)) -> list[AlertResponse]:
    return await svc.list_active_alerts(db)


@router.post("/subscribe", response_model=SubscribeResponse,
             summary="Subscribe to alerts for a route")
async def subscribe(
    req: SubscribeRequest,
    user: Principal = Depends(require_user),
    db: AsyncSession = Depends(get_db),
) -> SubscribeResponse:
    return await svc.subscribe(db, user.id, req)
