"""add daily_tasks table

Revision ID: 0008
Revises: 0007
Create Date: 2026-05-28

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "daily_tasks",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("date", sa.Date, nullable=False),
        sa.Column("text", sa.String(200), nullable=False),
        sa.Column("done", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("order", sa.Integer, nullable=False, server_default="0"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_daily_tasks_user_date", "daily_tasks", ["user_id", "date"])


def downgrade() -> None:
    op.drop_index("ix_daily_tasks_user_date", table_name="daily_tasks")
    op.drop_table("daily_tasks")
