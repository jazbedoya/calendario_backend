"""add composite indexes for calendar_events layer filter and context_entries date range

Revision ID: 0013
Revises: 0012
Create Date: 2026-06-20
"""
from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # CalendarEvent: filter by layer within a user's events
    op.create_index(
        "ix_calendar_events_user_layer_start",
        "calendar_events",
        ["user_id", "layer", "start_at"],
    )

    # ContextEntry: date range queries per user
    op.create_index(
        "ix_context_entries_user_date",
        "context_entries",
        ["user_id", "date"],
    )


def downgrade() -> None:
    op.drop_index("ix_context_entries_user_date", table_name="context_entries")
    op.drop_index("ix_calendar_events_user_layer_start", table_name="calendar_events")
