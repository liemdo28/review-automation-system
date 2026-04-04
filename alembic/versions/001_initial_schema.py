"""initial schema

Revision ID: 001
Revises:
Create Date: 2026-04-04
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "locations",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("slug", sa.String(64), unique=True, nullable=False),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("address", sa.Text),
        sa.Column("city", sa.String(64)),
        sa.Column("state", sa.String(2)),
        sa.Column("google_account_id", sa.String(64)),
        sa.Column("google_location_id", sa.String(64)),
        sa.Column("yelp_url", sa.Text),
        sa.Column("is_active", sa.Boolean, server_default="true"),
        sa.Column("fetch_google", sa.Boolean, server_default="true"),
        sa.Column("fetch_yelp", sa.Boolean, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "reviews",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("platform", sa.String(16), nullable=False),
        sa.Column("platform_review_id", sa.String(256), nullable=False),
        sa.Column("location_id", sa.Integer, sa.ForeignKey("locations.id"), nullable=False),
        sa.Column("reviewer_name", sa.String(256)),
        sa.Column("rating", sa.SmallInteger, nullable=False),
        sa.Column("review_text", sa.Text),
        sa.Column("review_date", sa.DateTime(timezone=True)),
        sa.Column("has_existing_reply", sa.Boolean, server_default="false"),
        sa.Column("raw_data", JSONB),
        sa.Column("fetched_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("platform", "platform_review_id", name="uq_review_platform_id"),
    )
    op.create_index("idx_reviews_location_platform", "reviews", ["location_id", "platform"])
    op.create_index("idx_reviews_rating", "reviews", ["rating"])
    op.create_index("idx_reviews_fetched_at", "reviews", ["fetched_at"])

    op.create_table(
        "replies",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("review_id", sa.Integer, sa.ForeignKey("reviews.id"), unique=True, nullable=False),
        sa.Column("ai_reply_text", sa.Text, nullable=False),
        sa.Column("ai_model", sa.String(64)),
        sa.Column("status", sa.String(32), nullable=False, server_default="pending"),
        sa.Column("posted_at", sa.DateTime(timezone=True)),
        sa.Column("error_message", sa.Text),
        sa.Column("retry_count", sa.SmallInteger, server_default="0"),
        sa.Column("is_dry_run", sa.Boolean, server_default="false"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("idx_replies_status", "replies", ["status"])

    op.create_table(
        "jobs",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("job_type", sa.String(32), nullable=False),
        sa.Column("review_id", sa.Integer, sa.ForeignKey("reviews.id")),
        sa.Column("location_id", sa.Integer, sa.ForeignKey("locations.id")),
        sa.Column("status", sa.String(32), nullable=False, server_default="queued"),
        sa.Column("payload", JSONB),
        sa.Column("result", JSONB),
        sa.Column("retry_count", sa.SmallInteger, server_default="0"),
        sa.Column("max_retries", sa.SmallInteger, server_default="3"),
        sa.Column("error_message", sa.Text),
        sa.Column("queued_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
    )
    op.create_index("idx_jobs_status_type", "jobs", ["status", "job_type"])

    op.create_table(
        "fetch_logs",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("location_id", sa.Integer, sa.ForeignKey("locations.id"), nullable=False),
        sa.Column("platform", sa.String(16), nullable=False),
        sa.Column("reviews_found", sa.Integer, server_default="0"),
        sa.Column("new_reviews", sa.Integer, server_default="0"),
        sa.Column("errors", sa.Text),
        sa.Column("duration_ms", sa.Integer),
        sa.Column("fetched_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "email_alerts",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("review_id", sa.Integer, sa.ForeignKey("reviews.id"), nullable=False),
        sa.Column("recipient", sa.String(256), nullable=False),
        sa.Column("subject", sa.Text),
        sa.Column("body", sa.Text),
        sa.Column("sent_at", sa.DateTime(timezone=True)),
        sa.Column("status", sa.String(16), server_default="pending"),
    )


def downgrade() -> None:
    op.drop_table("email_alerts")
    op.drop_table("fetch_logs")
    op.drop_table("jobs")
    op.drop_table("replies")
    op.drop_table("reviews")
    op.drop_table("locations")
