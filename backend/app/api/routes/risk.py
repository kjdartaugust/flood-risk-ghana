"""Flood-risk scoring endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.cache import rate_limit
from app.config import settings
from app.db import get_db
from app.schemas import RiskPointResponse, RiskTilesResponse
from app.services import risk as risk_svc

router = APIRouter(prefix="/risk", tags=["risk"], dependencies=[Depends(rate_limit)])


@router.get("/point", response_model=RiskPointResponse,
            summary="Flood-risk score for a coordinate")
async def risk_point(
    lat: float = Query(..., ge=4.5, le=11.2, description="Latitude (Ghana)"),
    lng: float = Query(..., ge=-3.3, le=1.3, description="Longitude (Ghana)"),
    db: AsyncSession = Depends(get_db),
) -> RiskPointResponse:
    return await risk_svc.score_point(db, lat, lng)


@router.get("/area", response_model=RiskPointResponse,
            summary="Flood-risk score for a named area")
async def risk_area(
    name: str = Query(..., min_length=2, examples=["Kaneshie"]),
    db: AsyncSession = Depends(get_db),
) -> RiskPointResponse:
    try:
        return await risk_svc.score_area(db, name)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.get("/tiles", response_model=RiskTilesResponse,
            summary="H3 risk tiles (GeoJSON) for a bounding box")
async def risk_tiles(
    bbox: str = Query(..., description="min_lng,min_lat,max_lng,max_lat"),
    res: int = Query(default=settings.h3_resolution, ge=5, le=9),
    db: AsyncSession = Depends(get_db),
) -> RiskTilesResponse:
    try:
        min_lng, min_lat, max_lng, max_lat = (float(x) for x in bbox.split(","))
    except ValueError as e:
        raise HTTPException(
            400, "bbox must be 'min_lng,min_lat,max_lng,max_lat'") from e
    feats = await risk_svc.tiles_in_bbox(db, min_lng, min_lat, max_lng, max_lat, res)
    return RiskTilesResponse(resolution=res, count=len(feats), features=feats)
