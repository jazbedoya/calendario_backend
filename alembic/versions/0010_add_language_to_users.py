"""add language to users

Revision ID: 0010
Revises: 0009
Create Date: 2026-06-09
"""
from alembic import op
import sqlalchemy as sa

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("language", sa.String(5), nullable=False, server_default="es"),
    )


def downgrade() -> None:
    op.drop_column("users", "language")
