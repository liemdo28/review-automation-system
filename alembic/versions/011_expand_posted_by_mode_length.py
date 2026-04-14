"""Expand posted_by_mode length for replies and reviews."""

from alembic import op
import sqlalchemy as sa


revision = "011"
down_revision = "010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "reviews",
        "posted_by_mode",
        existing_type=sa.String(length=16),
        type_=sa.String(length=32),
    )
    op.alter_column(
        "replies",
        "posted_by_mode",
        existing_type=sa.String(length=16),
        type_=sa.String(length=32),
    )


def downgrade() -> None:
    op.alter_column(
        "replies",
        "posted_by_mode",
        existing_type=sa.String(length=32),
        type_=sa.String(length=16),
    )
    op.alter_column(
        "reviews",
        "posted_by_mode",
        existing_type=sa.String(length=32),
        type_=sa.String(length=16),
    )
