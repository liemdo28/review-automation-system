"""support shared auth sessions and resolved source urls

Revision ID: 006
Revises: 005
Create Date: 2026-04-13
"""

from alembic import op
import sqlalchemy as sa

revision = "006"
down_revision = "005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("auth_sessions", sa.Column("share_scope", sa.String(length=16), nullable=False, server_default="source"))
    op.add_column("auth_sessions", sa.Column("shared_key", sa.String(length=255), nullable=True))
    op.add_column("auth_sessions", sa.Column("source_url_override", sa.Text(), nullable=True))
    op.add_column("review_sources", sa.Column("resolved_source_url", sa.Text(), nullable=True))

    op.create_index(
        "idx_auth_sessions_platform_scope_status",
        "auth_sessions",
        ["platform", "share_scope", "status"],
        unique=False,
    )
    op.create_index("idx_auth_sessions_shared_key", "auth_sessions", ["shared_key"], unique=False)

    op.execute(
        """
        UPDATE auth_sessions
        SET
            share_scope = 'source',
            shared_key = 'source:' || source_id::text
        WHERE share_scope IS NULL OR shared_key IS NULL
        """
    )
    op.alter_column("auth_sessions", "share_scope", server_default=None)


def downgrade() -> None:
    op.drop_index("idx_auth_sessions_shared_key", table_name="auth_sessions")
    op.drop_index("idx_auth_sessions_platform_scope_status", table_name="auth_sessions")
    op.drop_column("review_sources", "resolved_source_url")
    op.drop_column("auth_sessions", "source_url_override")
    op.drop_column("auth_sessions", "shared_key")
    op.drop_column("auth_sessions", "share_scope")
