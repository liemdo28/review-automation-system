"""Add review lifecycle fields and new tables: review_analysis, review_actions, review_settings

Revision ID: 002
Revises: 001
Create Date: 2026-04-11
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "002"
down_revision = "001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── Extend reviews table ─────────────────────────────────────────────────
    op.add_column("reviews", sa.Column("review_url", sa.Text, nullable=True))
    op.add_column("reviews", sa.Column("existing_reply_text", sa.Text, nullable=True))
    op.add_column("reviews", sa.Column("status", sa.String(32), nullable=False, server_default="new"))
    op.add_column("reviews", sa.Column("sentiment", sa.String(16), nullable=True))
    op.add_column("reviews", sa.Column("urgency", sa.String(16), nullable=True))
    op.add_column("reviews", sa.Column("is_sensitive", sa.Boolean, nullable=False, server_default="false"))
    op.add_column("reviews", sa.Column("auto_reply_allowed", sa.Boolean, nullable=False, server_default="false"))
    op.add_column("reviews", sa.Column("manager_attention_required", sa.Boolean, nullable=False, server_default="false"))
    op.add_column("reviews", sa.Column("issue_types_json", JSONB, nullable=True))
    op.add_column("reviews", sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()))

    op.create_index("idx_reviews_status", "reviews", ["status"])
    op.create_index("idx_reviews_urgency", "reviews", ["urgency"])

    # ── review_analysis table ────────────────────────────────────────────────
    op.create_table(
        "review_analysis",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("review_id", sa.Integer, sa.ForeignKey("reviews.id"), unique=True, nullable=False),
        sa.Column("sentiment", sa.String(16), nullable=True),
        sa.Column("issue_types_json", JSONB, nullable=True),
        sa.Column("urgency", sa.String(16), nullable=True),
        sa.Column("reply_recommended", sa.Boolean, server_default="true"),
        sa.Column("auto_reply_allowed", sa.Boolean, server_default="false"),
        sa.Column("manager_attention_required", sa.Boolean, server_default="false"),
        sa.Column("summary", sa.Text, nullable=True),
        sa.Column("suggested_reply", sa.Text, nullable=True),
        sa.Column("internal_notes", sa.Text, nullable=True),
        sa.Column("model_name", sa.String(64), nullable=True),
        sa.Column("prompt_version", sa.String(16), nullable=True),
        sa.Column("raw_ai_response_json", JSONB, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # ── review_actions table (audit trail) ───────────────────────────────────
    op.create_table(
        "review_actions",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("review_id", sa.Integer, sa.ForeignKey("reviews.id"), nullable=False),
        sa.Column("action_type", sa.String(32), nullable=False),
        sa.Column("action_status", sa.String(16), nullable=False, server_default="success"),
        sa.Column("action_payload_json", JSONB, nullable=True),
        sa.Column("error_message", sa.Text, nullable=True),
        sa.Column("performed_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("performed_by", sa.String(64), nullable=False, server_default="system"),
    )
    op.create_index("idx_review_actions_review_id", "review_actions", ["review_id"])
    op.create_index("idx_review_actions_type", "review_actions", ["action_type"])
    op.create_index("idx_review_actions_performed_at", "review_actions", ["performed_at"])

    # ── review_settings table ────────────────────────────────────────────────
    op.create_table(
        "review_settings",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("store_id", sa.String(64), nullable=False),
        sa.Column("platform", sa.String(16), nullable=False),
        sa.Column("auto_reply_google_positive", sa.Boolean, server_default="false"),
        sa.Column("email_alert_enabled", sa.Boolean, server_default="true"),
        sa.Column("manager_email", sa.String(256), nullable=True),
        sa.Column("brand_tone", sa.Text, nullable=True),
        sa.Column("signature_text", sa.Text, nullable=True),
        sa.Column("active", sa.Boolean, server_default="true"),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("store_id", "platform", name="uq_settings_store_platform"),
    )


def downgrade() -> None:
    op.drop_table("review_settings")
    op.drop_index("idx_review_actions_performed_at", table_name="review_actions")
    op.drop_index("idx_review_actions_type", table_name="review_actions")
    op.drop_index("idx_review_actions_review_id", table_name="review_actions")
    op.drop_table("review_actions")
    op.drop_table("review_analysis")

    op.drop_index("idx_reviews_urgency", table_name="reviews")
    op.drop_index("idx_reviews_status", table_name="reviews")
    op.drop_column("reviews", "updated_at")
    op.drop_column("reviews", "issue_types_json")
    op.drop_column("reviews", "manager_attention_required")
    op.drop_column("reviews", "auto_reply_allowed")
    op.drop_column("reviews", "is_sensitive")
    op.drop_column("reviews", "urgency")
    op.drop_column("reviews", "sentiment")
    op.drop_column("reviews", "status")
    op.drop_column("reviews", "existing_reply_text")
    op.drop_column("reviews", "review_url")
