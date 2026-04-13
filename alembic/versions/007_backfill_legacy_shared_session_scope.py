"""backfill legacy shared session scope

Revision ID: 007
Revises: 006
Create Date: 2026-04-13
"""

from alembic import op

revision = "007"
down_revision = "006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE auth_sessions
        SET
            share_scope = 'platform',
            shared_key = 'platform:google'
        WHERE platform = 'google'
          AND (
              session_reference ILIKE '%platform-google.json'
              OR session_reference ILIKE '%google-shared-session.json'
          )
        """
    )
    op.execute(
        """
        UPDATE auth_sessions
        SET
            share_scope = 'platform',
            shared_key = 'platform:yelp'
        WHERE platform = 'yelp'
          AND (
              session_reference ILIKE '%platform-yelp.json'
              OR session_reference ILIKE '%yelp-shared-session.json'
          )
        """
    )


def downgrade() -> None:
    op.execute(
        """
        UPDATE auth_sessions
        SET
            share_scope = 'source',
            shared_key = 'source:' || source_id::text
        WHERE platform = 'google'
          AND (
              session_reference ILIKE '%platform-google.json'
              OR session_reference ILIKE '%google-shared-session.json'
          )
        """
    )
    op.execute(
        """
        UPDATE auth_sessions
        SET
            share_scope = 'source',
            shared_key = 'source:' || source_id::text
        WHERE platform = 'yelp'
          AND (
              session_reference ILIKE '%platform-yelp.json'
              OR session_reference ILIKE '%yelp-shared-session.json'
          )
        """
    )
