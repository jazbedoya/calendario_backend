"""add events deleted_at for soft delete

Revision ID: 0004
Revises: 0003
Create Date: 2026-05-25

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "events",
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    # Index speeds up the most common filter: WHERE deleted_at IS NULL
    op.create_index("ix_events_deleted_at", "events", ["deleted_at"])


def downgrade() -> None:
    op.drop_index("ix_events_deleted_at", table_name="events")
    op.drop_column("events", "deleted_at")
