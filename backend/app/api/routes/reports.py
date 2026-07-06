"""Community flood report endpoints (public crowdsourced write path)."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.cache import rate_limit
from app.db import get_db
from app.schemas import (
    FloodReportFeature,
    FloodReportRequest,
    FloodReportResponse,
)
from app.services import reports_service as svc

router = APIRouter(prefix="/reports", tags=["reports"],
                   dependencies=[Depends(rate_limit)])


@router.post("", response_model=FloodReportResponse, status_code=201,
             summary="Report flooding at a location (crowdsourced)")
async def create_report(
    req: FloodReportRequest,
    db: AsyncSession = Depends(get_db),
) -> FloodReportResponse:
    return await svc.create_report(db, req)


@router.get("/recent", response_model=list[FloodReportFeature],
            summary="Recent flood reports (historical + community)")
async def recent(
    limit: int = 100,
    db: AsyncSession = Depends(get_db),
) -> list[FloodReportFeature]:
    return await svc.recent_reports(db, min(limit, 500))
