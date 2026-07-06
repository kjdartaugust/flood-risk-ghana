"""initial schema: PostGIS extension + core tables

Revision ID: 0001_initial
Revises:
Create Date: 2026-07-05
"""
from alembic import op
import sqlalchemy as sa
import geoalchemy2

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS postgis")

    op.create_table(
        "flood_events",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("occurred_on", sa.Date(), nullable=False),
        sa.Column("area_name", sa.String(length=160), index=True),
        sa.Column("severity", sa.Integer(), server_default="1"),
        sa.Column("source", sa.String(length=120), server_default="unknown"),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("geom", geoalchemy2.types.Geometry("POINT", srid=4326), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_flood_events_geom", "flood_events", ["geom"],
                    postgresql_using="gist")

    op.create_table(
        "rainfall_obs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("h3_index", sa.String(length=20), index=True),
        sa.Column("observed_at", sa.DateTime(timezone=True), index=True),
        sa.Column("horizon", sa.String(length=12), server_default="obs"),
        sa.Column("precip_mm", sa.Float(), server_default="0"),
        sa.Column("source", sa.String(length=60), server_default="open-meteo"),
        sa.UniqueConstraint("h3_index", "observed_at", "horizon", name="uq_rain_cell_ts"),
    )

    op.create_table(
        "risk_tiles",
        sa.Column("h3_index", sa.String(length=20), primary_key=True),
        sa.Column("resolution", sa.Integer(), index=True),
        sa.Column("centroid_lat", sa.Float()),
        sa.Column("centroid_lng", sa.Float()),
        sa.Column("elevation_score", sa.Float(), server_default="0"),
        sa.Column("slope_score", sa.Float(), server_default="0"),
        sa.Column("drainage_score", sa.Float(), server_default="0"),
        sa.Column("imperviousness", sa.Float(), server_default="0"),
        sa.Column("hist_flood_density", sa.Float(), server_default="0"),
        sa.Column("rainfall_recent_mm", sa.Float(), server_default="0"),
        sa.Column("risk_score", sa.Float(), server_default="0"),
        sa.Column("confidence", sa.Float(), server_default="0.5"),
        sa.Column("model_version", sa.String(length=40), server_default="weighted-v1"),
        sa.Column("geom", geoalchemy2.types.Geometry("POLYGON", srid=4326), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_risk_tiles_geom", "risk_tiles", ["geom"], postgresql_using="gist")
    op.create_index("ix_risk_tiles_centroid", "risk_tiles",
                    ["resolution", "centroid_lng", "centroid_lat"])

    op.create_table(
        "trotro_routes",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("osm_id", sa.String(length=40), nullable=True, index=True),
        sa.Column("name", sa.String(length=200), index=True),
        sa.Column("from_stop", sa.String(length=160), nullable=True),
        sa.Column("to_stop", sa.String(length=160), nullable=True),
        sa.Column("geom", geoalchemy2.types.Geometry("LINESTRING", srid=4326), nullable=False),
        sa.Column("baseline_risk", sa.Float(), server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_trotro_routes_geom", "trotro_routes", ["geom"],
                    postgresql_using="gist")

    op.create_table(
        "route_alerts",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("route_id", sa.String(length=36),
                  sa.ForeignKey("trotro_routes.id"), index=True),
        sa.Column("level", sa.String(length=12)),
        sa.Column("message", sa.Text()),
        sa.Column("expected_precip_mm", sa.Float(), server_default="0"),
        sa.Column("risk_score", sa.Float(), server_default="0"),
        sa.Column("active", sa.Boolean(), server_default=sa.true(), index=True),
        sa.Column("starts_at", sa.DateTime(timezone=True)),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.Column("payload", sa.JSON(), server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "alert_subscriptions",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("user_id", sa.String(length=64), index=True),
        sa.Column("route_id", sa.String(length=36),
                  sa.ForeignKey("trotro_routes.id"), index=True),
        sa.Column("channel", sa.String(length=20), server_default="web"),
        sa.Column("contact", sa.String(length=120), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("user_id", "route_id", "channel", name="uq_sub_user_route"),
    )


def downgrade() -> None:
    for t in ("alert_subscriptions", "route_alerts", "trotro_routes",
              "risk_tiles", "rainfall_obs", "flood_events"):
        op.drop_table(t)
