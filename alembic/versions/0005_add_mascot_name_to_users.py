"""add mascot_name to users

Revision ID: 0005
Revises: 0004
Create Date: 2026-05-25

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("mascot_name", sa.String(100), nullable=False, server_default="Tuga"),
    )


def downgrade() -> None:
    op.drop_column("users", "mascot_name")
