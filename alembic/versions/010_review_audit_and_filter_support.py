"""Add review audit fields for negative-review workflow."""

from alembic import op
import sqlalchemy as sa


revision = "010"
down_revision = "009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("reviews", sa.Column("is_flagged", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("reviews", sa.Column("issue_category", sa.String(length=32), nullable=True))
    op.add_column("reviews", sa.Column("severity_level", sa.String(length=16), nullable=True))
    op.add_column("reviews", sa.Column("analysis_summary", sa.Text(), nullable=True))
    op.add_column("reviews", sa.Column("gm_report_sent", sa.Boolean(), nullable=False, server_default=sa.false()))

    op.create_index("idx_reviews_flagged", "reviews", ["is_flagged"], unique=False)
    op.create_index("idx_reviews_severity_level", "reviews", ["severity_level"], unique=False)

    op.execute(
        """
        UPDATE reviews
        SET is_flagged = TRUE
        WHERE rating <= 3
        """
    )

    op.alter_column("reviews", "is_flagged", server_default=None)
    op.alter_column("reviews", "gm_report_sent", server_default=None)


def downgrade() -> None:
    op.drop_index("idx_reviews_severity_level", table_name="reviews")
    op.drop_index("idx_reviews_flagged", table_name="reviews")
    op.drop_column("reviews", "gm_report_sent")
    op.drop_column("reviews", "analysis_summary")
    op.drop_column("reviews", "severity_level")
    op.drop_column("reviews", "issue_category")
    op.drop_column("reviews", "is_flagged")
