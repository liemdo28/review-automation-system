"""add auto reply workflow foundation

Revision ID: 008
Revises: 007
Create Date: 2026-04-13
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "008"
down_revision = "007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("reviews", sa.Column("workflow_status", sa.String(length=32), nullable=False, server_default="unreplied"))
    op.add_column("reviews", sa.Column("auto_reply_eligible", sa.Boolean(), nullable=False, server_default=sa.text("false")))
    op.add_column("reviews", sa.Column("auto_reply_decision_reason", sa.Text(), nullable=True))
    op.add_column("reviews", sa.Column("auto_reply_risk_level", sa.String(length=16), nullable=True))
    op.add_column("reviews", sa.Column("escalated", sa.Boolean(), nullable=False, server_default=sa.text("false")))
    op.add_column("reviews", sa.Column("escalation_reason", sa.Text(), nullable=True))
    op.add_column("reviews", sa.Column("posted_by_mode", sa.String(length=16), nullable=True))
    op.add_column("reviews", sa.Column("policy_version", sa.String(length=32), nullable=True))
    op.add_column("reviews", sa.Column("last_auto_decision_at", sa.DateTime(), nullable=True))

    op.add_column("replies", sa.Column("posted_by_mode", sa.String(length=16), nullable=True))
    op.add_column("replies", sa.Column("auto_post_attempts", sa.SmallInteger(), nullable=False, server_default="0"))
    op.add_column("replies", sa.Column("last_auto_post_error", sa.Text(), nullable=True))
    op.add_column("replies", sa.Column("last_auto_post_at", sa.DateTime(), nullable=True))
    op.add_column("replies", sa.Column("decision_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=True))

    op.add_column("locations", sa.Column("auto_reply_settings", postgresql.JSONB(astext_type=sa.Text()), nullable=True))

    op.create_table(
        "app_settings",
        sa.Column("key", sa.String(length=128), nullable=False),
        sa.Column("value", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("key"),
    )

    op.create_index("idx_reviews_workflow_status", "reviews", ["workflow_status"], unique=False)
    op.create_index("idx_reviews_auto_reply_eligible", "reviews", ["auto_reply_eligible"], unique=False)
    op.create_index("idx_reviews_auto_reply_risk_level", "reviews", ["auto_reply_risk_level"], unique=False)

    op.execute(
        """
        UPDATE reviews
        SET workflow_status = CASE
            WHEN is_handled IS TRUE THEN 'handled'
            WHEN has_owner_reply IS TRUE THEN 'replied'
            ELSE 'unreplied'
        END
        """
    )

    op.execute(
        """
        UPDATE replies
        SET posted_by_mode = CASE
            WHEN status = 'posted' THEN 'manual'
            ELSE posted_by_mode
        END
        """
    )

    op.execute(
        """
        INSERT INTO app_settings(key, value, updated_at)
        VALUES (
            'auto_reply_config',
            '{
              "auto_reply_enabled": true,
              "auto_post_phase_enabled": false,
              "auto_reply_google_enabled": true,
              "auto_reply_yelp_enabled": false,
              "auto_reply_min_rating": 5,
              "auto_reply_daily_limit": 20,
              "auto_reply_quiet_hours_start": "",
              "auto_reply_quiet_hours_end": "",
              "auto_reply_confidence_threshold": 0.7,
              "auto_reply_blocked_keywords": [],
              "auto_reply_escalation_emails": [],
              "brand_tone_mode": "gentle_professional",
              "max_auto_post_failures": 3
            }'::jsonb,
            NOW()
        )
        ON CONFLICT (key) DO NOTHING
        """
    )

    op.alter_column("reviews", "workflow_status", server_default=None)
    op.alter_column("reviews", "auto_reply_eligible", server_default=None)
    op.alter_column("reviews", "escalated", server_default=None)
    op.alter_column("replies", "auto_post_attempts", server_default=None)


def downgrade() -> None:
    op.drop_index("idx_reviews_auto_reply_risk_level", table_name="reviews")
    op.drop_index("idx_reviews_auto_reply_eligible", table_name="reviews")
    op.drop_index("idx_reviews_workflow_status", table_name="reviews")

    op.drop_table("app_settings")

    op.drop_column("locations", "auto_reply_settings")

    op.drop_column("replies", "decision_snapshot")
    op.drop_column("replies", "last_auto_post_at")
    op.drop_column("replies", "last_auto_post_error")
    op.drop_column("replies", "auto_post_attempts")
    op.drop_column("replies", "posted_by_mode")

    op.drop_column("reviews", "last_auto_decision_at")
    op.drop_column("reviews", "policy_version")
    op.drop_column("reviews", "posted_by_mode")
    op.drop_column("reviews", "escalation_reason")
    op.drop_column("reviews", "escalated")
    op.drop_column("reviews", "auto_reply_risk_level")
    op.drop_column("reviews", "auto_reply_decision_reason")
    op.drop_column("reviews", "auto_reply_eligible")
    op.drop_column("reviews", "workflow_status")
