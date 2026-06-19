"""add performance indexes for events, tasks, calendar_events

Revision ID: 0012
Revises: 0011
Create Date: 2026-06-19
"""
from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Events: composite index for the most common query pattern
    # (list by user, exclude deleted, order by start_at)
    op.create_index(
        "ix_events_user_deleted_start",
        "events",
        ["user_id", "deleted_at", "start_at"],
    )

    # DailyTask: composite for daily task lookup (hot path on app open)
    op.create_index(
        "ix_daily_tasks_user_date",
        "daily_tasks",
        ["user_id", "date"],
    )

    # CalendarEvents: composite for range queries
    op.create_index(
        "ix_calendar_events_user_start",
        "calendar_events",
        ["user_id", "start_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_calendar_events_user_start", table_name="calendar_events")
    op.drop_index("ix_daily_tasks_user_date", table_name="daily_tasks")
    op.drop_index("ix_events_user_deleted_start", table_name="events")
