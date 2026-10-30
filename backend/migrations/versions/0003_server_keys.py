"""server_keys — keys the server mints for itself, starting with the VAPID pair

So Web Push works on a fresh deploy without anyone generating keys and pasting
them into the host's environment. VAPID_* env vars still win when set.

Revision ID: 0003_server_keys
Revises: 0002_push_subscription
Create Date: 2026-10-30
"""
from alembic import op
import sqlalchemy as sa

revision = "0003_server_keys"
down_revision = "0002_push_subscription"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "server_keys",
        sa.Column("name", sa.String(length=40), primary_key=True),
        sa.Column("value", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("server_keys")
