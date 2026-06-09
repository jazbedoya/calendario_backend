"""add recurrence to events

Revision ID: 0009
Revises: 0008
Create Date: 2026-06-05

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("events", sa.Column("recurrence_rule", sa.String(16), nullable=True))
    op.add_column(
        "events",
        sa.Column("recurrence_parent_id", sa.Uuid(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_events_recurrence_parent",
        "events",
        "events",
        ["recurrence_parent_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_events_recurrence_parent_id",
        "events",
        ["recurrence_parent_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_events_recurrence_parent_id", table_name="events")
    op.drop_constraint("fk_events_recurrence_parent", "events", type_="foreignkey")
    op.drop_column("events", "recurrence_parent_id")
    op.drop_column("events", "recurrence_rule")
