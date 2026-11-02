"""trotro_routes.ref and .forecast — real OSM lines, with their rain stored on them

The 5 hand-drawn stand-in routes give way to Accra's ~280 trotro lines from
OpenStreetMap. Judging each one with its own forecast query would be hundreds
of round trips per request, so each rain refresh stores a route's coming hours
on the route itself.

Revision ID: 0005_route_forecast
Revises: 0004_refresh_runs
Create Date: 2026-11-02
"""
from alembic import op
import sqlalchemy as sa

revision = "0005_route_forecast"
down_revision = "0004_refresh_runs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("trotro_routes", sa.Column("ref", sa.String(length=20), nullable=True))
    op.add_column("trotro_routes", sa.Column("forecast", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("trotro_routes", "forecast")
    op.drop_column("trotro_routes", "ref")
