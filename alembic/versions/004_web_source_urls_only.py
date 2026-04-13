"""backfill web collector urls and remove oauth config dependency

Revision ID: 004
Revises: 003
Create Date: 2026-04-13
"""

from alembic import op

revision = "004"
down_revision = "003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE review_sources AS rs
        SET
            source_url = 'https://www.google.com/search?q=' ||
                replace(trim(loc.name || ' ' || coalesce(loc.city, '') || ' ' || coalesce(loc.state, '') || ' reviews'), ' ', '+'),
            source_label = coalesce(rs.source_label, loc.name || ' Google Reviews'),
            auth_mode = 'manual_session'
        FROM locations AS loc
        WHERE rs.location_id = loc.id
          AND rs.platform = 'google'
          AND (
            rs.source_url IS NULL
            OR rs.source_url = ''
            OR rs.source_url = 'https://business.google.com/locations'
          )
        """
    )


def downgrade() -> None:
    op.execute(
        """
        UPDATE review_sources
        SET source_url = 'https://business.google.com/locations'
        WHERE platform = 'google'
        """
    )
