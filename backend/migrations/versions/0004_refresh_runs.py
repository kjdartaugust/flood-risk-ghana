"""refresh_runs — one row per scheduled refresh, so its outcome is visible

The refresh runs as a background task after a 202, on a host whose logs may be
out of reach. Recording each run makes "did it save any rain?" answerable from
outside, at GET /internal/refresh.

Revision ID: 0004_refresh_runs
Revises: 0003_server_keys
Create Date: 2026-10-31
"""
from alembic import op
import sqlalchemy as sa

revision = "0004_refresh_runs"
down_revision = "0003_server_keys"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "refresh_runs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rainfall_rows", sa.Integer(), nullable=True),
        sa.Column("alerts_raised", sa.Integer(), nullable=True),
        sa.Column("error", sa.String(length=300), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("refresh_runs")
