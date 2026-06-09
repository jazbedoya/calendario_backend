"""create calendar tables

Revision ID: 0002
Revises: 0001
Create Date: 2026-05-25

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "google_calendar_accounts",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("user_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("google_account_id", sa.String(255), nullable=False),
        sa.Column("google_email", sa.String(255), nullable=False),
        sa.Column("access_token_enc", sa.Text(), nullable=False),
        sa.Column("refresh_token_enc", sa.Text(), nullable=False),
        sa.Column("token_expiry", sa.DateTime(timezone=True), nullable=True),
        sa.Column("scopes", sa.Text(), nullable=False, server_default=""),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "connected_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("user_id", name="uq_google_calendar_accounts_user_id"),
    )
    op.create_index(
        "ix_google_calendar_accounts_user_id",
        "google_calendar_accounts",
        ["user_id"],
        unique=True,
    )

    op.create_table(
        "calendar_events",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("user_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("google_event_id", sa.String(255), nullable=False),
        sa.Column(
            "calendar_id", sa.String(255), nullable=False, server_default="primary"
        ),
        sa.Column("title", sa.String(500), nullable=False, server_default=""),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("start_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "is_all_day", sa.Boolean(), nullable=False, server_default="false"
        ),
        sa.Column("location", sa.String(500), nullable=True),
        sa.Column("layer", sa.String(32), nullable=False, server_default="work"),
        sa.Column(
            "synced_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.UniqueConstraint(
            "user_id", "google_event_id", name="uq_calendar_events_user_google"
        ),
    )
    op.create_index("ix_calendar_events_user_id", "calendar_events", ["user_id"])
    op.create_index("ix_calendar_events_start_at", "calendar_events", ["start_at"])


def downgrade() -> None:
    op.drop_table("calendar_events")
    op.drop_table("google_calendar_accounts")
