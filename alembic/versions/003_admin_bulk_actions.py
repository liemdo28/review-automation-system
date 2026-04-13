"""admin and bulk actions support

Revision ID: 003
Revises: 002
Create Date: 2026-04-13
"""

from alembic import op
import sqlalchemy as sa

revision = "003"
down_revision = "002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("reviews", sa.Column("is_handled", sa.Boolean(), server_default="false"))
    op.add_column("reviews", sa.Column("handled_at", sa.DateTime(timezone=True)))
    op.add_column("reviews", sa.Column("handled_by", sa.String(length=64)))


def downgrade() -> None:
    op.drop_column("reviews", "handled_by")
    op.drop_column("reviews", "handled_at")
    op.drop_column("reviews", "is_handled")
