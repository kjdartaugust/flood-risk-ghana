"""alert_subscriptions.push_subscription — the browser's Web Push handle

A Web Push subscription is an endpoint URL plus the p256dh/auth encryption
keys. That doesn't fit `contact` (String(120)) and isn't a scalar, so it gets
its own JSON column. Nullable: only channel="push" rows carry one.

Revision ID: 0002_push_subscription
Revises: 0001_initial
Create Date: 2026-07-13
"""
from alembic import op
import sqlalchemy as sa

revision = "0002_push_subscription"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "alert_subscriptions",
        sa.Column("push_subscription", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("alert_subscriptions", "push_subscription")
