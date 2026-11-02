"""Trotro route endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.cache import rate_limit
from app.db import get_db
from app.schemas import RouteForecastResponse, RouteSummary
from app.services import routes_service as svc

router = APIRouter(prefix="/routes", tags=["routes"],
                   dependencies=[Depends(rate_limit)])


@router.get("", response_model=list[RouteSummary],
            summary="Trotro routes with current flood status")
async def get_routes(db: AsyncSession = Depends(get_db)) -> list[RouteSummary]:
    return await svc.list_routes(db)


@router.get("/lines", response_class=Response,
            responses={200: {"content": {"application/geo+json": {}}}},
            summary="Every route's line, as GeoJSON")
async def get_lines(request: Request, db: AsyncSession = Depends(get_db)) -> Response:
    """Apart from GET /routes, which changes as the rain does: the lines change
    only with a deploy, so a browser can keep them and ask again by ETag."""
    body, etag = await svc.route_lines(db)
    headers = {"ETag": etag, "Cache-Control": "public, max-age=600"}
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers=headers)
    return Response(body, media_type="application/geo+json", headers=headers)


@router.get("/{route_id}/forecast", response_model=RouteForecastResponse,
            summary="Flood forecast for a route")
async def get_forecast(
    route_id: str,
    horizon: int = Query(default=12, ge=1, le=24),
    db: AsyncSession = Depends(get_db),
) -> RouteForecastResponse:
    try:
        return await svc.route_forecast(db, route_id, horizon)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
