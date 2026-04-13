"""add performance indexes for queue and job hot paths

Revision ID: 005
Revises: 004
Create Date: 2026-04-13
"""

from alembic import op

revision = "005"
down_revision = "004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index("idx_reviews_review_date", "reviews", ["review_date"], unique=False)
    op.create_index("idx_reviews_location_id", "reviews", ["location_id"], unique=False)
    op.create_index("idx_reviews_platform", "reviews", ["platform"], unique=False)
    op.create_index("idx_reviews_is_handled", "reviews", ["is_handled"], unique=False)
    op.create_index(
        "idx_reviews_queue_priority",
        "reviews",
        ["is_handled", "has_owner_reply", "rating", "review_date"],
        unique=False,
    )
    op.create_index("idx_jobs_source_status", "jobs", ["source_id", "status"], unique=False)
    op.create_index("idx_jobs_review_type_status", "jobs", ["review_id", "job_type", "status"], unique=False)
    op.create_index("idx_jobs_source_type_queued", "jobs", ["source_id", "job_type", "queued_at"], unique=False)
    op.create_index("idx_review_sources_active_status", "review_sources", ["is_active", "session_status"], unique=False)
    op.create_index(
        "idx_reply_suggestions_review_created",
        "reply_suggestions",
        ["review_id", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("idx_reply_suggestions_review_created", table_name="reply_suggestions")
    op.drop_index("idx_review_sources_active_status", table_name="review_sources")
    op.drop_index("idx_jobs_source_type_queued", table_name="jobs")
    op.drop_index("idx_jobs_review_type_status", table_name="jobs")
    op.drop_index("idx_jobs_source_status", table_name="jobs")
    op.drop_index("idx_reviews_queue_priority", table_name="reviews")
    op.drop_index("idx_reviews_is_handled", table_name="reviews")
    op.drop_index("idx_reviews_platform", table_name="reviews")
    op.drop_index("idx_reviews_location_id", table_name="reviews")
    op.drop_index("idx_reviews_review_date", table_name="reviews")
