"""review ops phase 1 foundation

Revision ID: 002
Revises: 001
Create Date: 2026-04-13
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "002"
down_revision = "001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "review_sources",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("location_id", sa.Integer, sa.ForeignKey("locations.id"), nullable=False),
        sa.Column("platform", sa.String(16), nullable=False),
        sa.Column("source_url", sa.Text, nullable=False),
        sa.Column("source_label", sa.String(128)),
        sa.Column("auth_mode", sa.String(32), server_default="manual_session"),
        sa.Column("session_status", sa.String(32), server_default="unknown"),
        sa.Column("settings", JSONB),
        sa.Column("last_auth_at", sa.DateTime(timezone=True)),
        sa.Column("last_successful_sync_at", sa.DateTime(timezone=True)),
        sa.Column("last_failed_sync_at", sa.DateTime(timezone=True)),
        sa.Column("last_error_message", sa.Text),
        sa.Column("is_active", sa.Boolean, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index(
        "idx_review_sources_location_platform",
        "review_sources",
        ["location_id", "platform"],
    )
    op.create_index(
        "idx_review_sources_session_status",
        "review_sources",
        ["session_status"],
    )

    op.create_table(
        "auth_sessions",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("source_id", sa.Integer, sa.ForeignKey("review_sources.id"), nullable=False),
        sa.Column("platform", sa.String(16), nullable=False),
        sa.Column("session_reference", sa.String(512), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.Column("last_validated_at", sa.DateTime(timezone=True)),
        sa.Column("status", sa.String(32), server_default="active"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index(
        "idx_auth_sessions_source_status",
        "auth_sessions",
        ["source_id", "status"],
    )

    op.create_table(
        "reply_suggestions",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("review_id", sa.Integer, sa.ForeignKey("reviews.id"), nullable=False),
        sa.Column("tone_mode", sa.String(32), nullable=False),
        sa.Column("suggestion_text", sa.Text, nullable=False),
        sa.Column("model_name", sa.String(64)),
        sa.Column("sentiment", sa.String(32)),
        sa.Column("issue_tags", JSONB),
        sa.Column("risk_flags", JSONB),
        sa.Column("confidence_note", sa.Text),
        sa.Column("reason_summary", sa.Text),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("created_by", sa.String(64)),
    )
    op.create_index(
        "idx_reply_suggestions_review_tone",
        "reply_suggestions",
        ["review_id", "tone_mode"],
    )
    op.create_index(
        "idx_reply_suggestions_created_at",
        "reply_suggestions",
        ["created_at"],
    )

    op.add_column("reviews", sa.Column("external_review_id", sa.String(256), nullable=True))
    op.add_column("reviews", sa.Column("source_id", sa.Integer, sa.ForeignKey("review_sources.id")))
    op.add_column("reviews", sa.Column("source_url", sa.Text))
    op.add_column("reviews", sa.Column("detected_owner_reply_text", sa.Text))
    op.add_column("reviews", sa.Column("detected_owner_reply_at", sa.DateTime(timezone=True)))
    op.add_column("reviews", sa.Column("has_owner_reply", sa.Boolean, server_default="false"))
    op.add_column("reviews", sa.Column("raw_payload", JSONB))
    op.add_column("reviews", sa.Column("collected_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("reviews", sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("reviews", sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("idx_reviews_date_platform", "reviews", ["review_date", "platform"])
    op.create_index("idx_reviews_owner_reply", "reviews", ["has_owner_reply"])

    op.add_column("replies", sa.Column("tone_mode", sa.String(32), server_default="gentle_professional"))
    op.add_column("replies", sa.Column("confidence_note", sa.Text))
    op.add_column("replies", sa.Column("reason_summary", sa.Text))
    op.add_column("replies", sa.Column("issue_tags", JSONB))
    op.add_column("replies", sa.Column("risk_flags", JSONB))

    op.add_column("jobs", sa.Column("source_id", sa.Integer, sa.ForeignKey("review_sources.id")))

    op.execute(
        """
        INSERT INTO review_sources (
            location_id, platform, source_url, source_label, auth_mode, session_status, settings, is_active
        )
        SELECT
            id,
            'google',
            'https://business.google.com/locations',
            name || ' Google Reviews',
            'manual_session',
            CASE
                WHEN google_location_id IS NOT NULL THEN 'reauth_required'
                ELSE 'missing'
            END,
            jsonb_build_object(
                'legacy_google_account_id', google_account_id,
                'legacy_google_location_id', google_location_id
            ),
            COALESCE(fetch_google, true)
        FROM locations
        WHERE google_location_id IS NOT NULL
        """
    )
    op.execute(
        """
        INSERT INTO review_sources (
            location_id, platform, source_url, source_label, auth_mode, session_status, settings, is_active
        )
        SELECT
            id,
            'yelp',
            yelp_url,
            name || ' Yelp Reviews',
            'public_or_session',
            'active',
            jsonb_build_object('legacy_yelp_url', yelp_url),
            COALESCE(fetch_yelp, true)
        FROM locations
        WHERE yelp_url IS NOT NULL
        """
    )

    op.execute("UPDATE reviews SET external_review_id = platform_review_id WHERE external_review_id IS NULL")
    op.execute(
        """
        UPDATE reviews
        SET
            has_owner_reply = COALESCE(has_existing_reply, false),
            raw_payload = COALESCE(raw_data, '{}'::jsonb),
            collected_at = COALESCE(fetched_at, created_at, NOW()),
            first_seen_at = COALESCE(created_at, fetched_at, NOW()),
            last_seen_at = COALESCE(fetched_at, created_at, NOW())
        """
    )
    op.execute(
        """
        UPDATE reviews AS r
        SET
            source_id = rs.id,
            source_url = COALESCE(r.source_url, rs.source_url)
        FROM review_sources AS rs
        WHERE rs.location_id = r.location_id
          AND rs.platform = r.platform
        """
    )
    op.execute(
        """
        UPDATE jobs AS j
        SET source_id = rs.id
        FROM reviews AS r
        JOIN review_sources AS rs
          ON rs.location_id = r.location_id
         AND rs.platform = r.platform
        WHERE j.review_id = r.id
        """
    )

    op.alter_column("reviews", "external_review_id", nullable=False)
    op.alter_column("reviews", "collected_at", nullable=False)
    op.alter_column("reviews", "first_seen_at", nullable=False)
    op.alter_column("reviews", "last_seen_at", nullable=False)
    op.create_unique_constraint(
        "uq_review_platform_external_id",
        "reviews",
        ["platform", "external_review_id"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_review_platform_external_id", "reviews", type_="unique")
    op.drop_column("jobs", "source_id")

    op.drop_column("replies", "risk_flags")
    op.drop_column("replies", "issue_tags")
    op.drop_column("replies", "reason_summary")
    op.drop_column("replies", "confidence_note")
    op.drop_column("replies", "tone_mode")

    op.drop_index("idx_reviews_owner_reply", table_name="reviews")
    op.drop_index("idx_reviews_date_platform", table_name="reviews")
    op.drop_column("reviews", "last_seen_at")
    op.drop_column("reviews", "first_seen_at")
    op.drop_column("reviews", "collected_at")
    op.drop_column("reviews", "raw_payload")
    op.drop_column("reviews", "has_owner_reply")
    op.drop_column("reviews", "detected_owner_reply_at")
    op.drop_column("reviews", "detected_owner_reply_text")
    op.drop_column("reviews", "source_url")
    op.drop_column("reviews", "source_id")
    op.drop_column("reviews", "external_review_id")

    op.drop_index("idx_reply_suggestions_created_at", table_name="reply_suggestions")
    op.drop_index("idx_reply_suggestions_review_tone", table_name="reply_suggestions")
    op.drop_table("reply_suggestions")

    op.drop_index("idx_auth_sessions_source_status", table_name="auth_sessions")
    op.drop_table("auth_sessions")

    op.drop_index("idx_review_sources_session_status", table_name="review_sources")
    op.drop_index("idx_review_sources_location_platform", table_name="review_sources")
    op.drop_table("review_sources")
