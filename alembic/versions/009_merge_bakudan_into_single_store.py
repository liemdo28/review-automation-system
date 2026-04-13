"""merge bakudan into a single canonical store

Revision ID: 009
Revises: 008
Create Date: 2026-04-13
"""

from alembic import op
import sqlalchemy as sa

revision = "009"
down_revision = "008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()

    canonical_location_id = conn.execute(sa.text("SELECT id FROM locations WHERE slug = 'bakudan-rim'")).scalar()
    if canonical_location_id is None:
        canonical_location_id = conn.execute(sa.text("SELECT id FROM locations WHERE slug = 'bakudan-ramen'")).scalar()
    if canonical_location_id is None:
        return

    old_location_ids = [
        row[0]
        for row in conn.execute(
            sa.text(
                """
                SELECT id
                FROM locations
                WHERE slug IN ('bakudan-bandera', 'bakudan-stone-oak')
                ORDER BY id
                """
            )
        ).fetchall()
    ]

    google_source_id = conn.execute(
        sa.text(
            """
            SELECT id
            FROM review_sources
            WHERE location_id = :location_id AND platform = 'google'
            ORDER BY id
            LIMIT 1
            """
        ),
        {"location_id": canonical_location_id},
    ).scalar()
    yelp_source_id = conn.execute(
        sa.text(
            """
            SELECT id
            FROM review_sources
            WHERE location_id = :location_id AND platform = 'yelp'
            ORDER BY id
            LIMIT 1
            """
        ),
        {"location_id": canonical_location_id},
    ).scalar()

    for old_location_id in old_location_ids:
        old_google_source = conn.execute(
            sa.text(
                """
                SELECT id FROM review_sources
                WHERE location_id = :location_id AND platform = 'google'
                ORDER BY id
                LIMIT 1
                """
            ),
            {"location_id": old_location_id},
        ).scalar()
        old_yelp_source = conn.execute(
            sa.text(
                """
                SELECT id FROM review_sources
                WHERE location_id = :location_id AND platform = 'yelp'
                ORDER BY id
                LIMIT 1
                """
            ),
            {"location_id": old_location_id},
        ).scalar()

        conn.execute(sa.text("UPDATE reviews SET location_id = :new_id WHERE location_id = :old_id"), {"new_id": canonical_location_id, "old_id": old_location_id})
        conn.execute(sa.text("UPDATE jobs SET location_id = :new_id WHERE location_id = :old_id"), {"new_id": canonical_location_id, "old_id": old_location_id})
        conn.execute(sa.text("UPDATE fetch_logs SET location_id = :new_id WHERE location_id = :old_id"), {"new_id": canonical_location_id, "old_id": old_location_id})

        if old_google_source and google_source_id:
            conn.execute(
                sa.text("UPDATE reviews SET source_id = :new_source WHERE source_id = :old_source"),
                {"new_source": google_source_id, "old_source": old_google_source},
            )
            conn.execute(
                sa.text("UPDATE jobs SET source_id = :new_source WHERE source_id = :old_source"),
                {"new_source": google_source_id, "old_source": old_google_source},
            )
            conn.execute(
                sa.text("UPDATE auth_sessions SET source_id = :new_source WHERE source_id = :old_source"),
                {"new_source": google_source_id, "old_source": old_google_source},
            )

        if old_yelp_source and yelp_source_id:
            conn.execute(
                sa.text("UPDATE reviews SET source_id = :new_source WHERE source_id = :old_source"),
                {"new_source": yelp_source_id, "old_source": old_yelp_source},
            )
            conn.execute(
                sa.text("UPDATE jobs SET source_id = :new_source WHERE source_id = :old_source"),
                {"new_source": yelp_source_id, "old_source": old_yelp_source},
            )
            conn.execute(
                sa.text("UPDATE auth_sessions SET source_id = :new_source WHERE source_id = :old_source"),
                {"new_source": yelp_source_id, "old_source": old_yelp_source},
            )

    conn.execute(
        sa.text(
            """
            UPDATE locations
            SET
                slug = 'bakudan-ramen',
                name = 'Bakudan Ramen'
            WHERE id = :location_id
            """
        ),
        {"location_id": canonical_location_id},
    )

    if google_source_id:
        conn.execute(
            sa.text(
                """
                UPDATE review_sources
                SET source_label = 'Bakudan Ramen Google Reviews'
                WHERE id = :source_id
                """
            ),
            {"source_id": google_source_id},
        )
    if yelp_source_id:
        conn.execute(
            sa.text(
                """
                UPDATE review_sources
                SET source_label = 'Bakudan Ramen Yelp Reviews'
                WHERE id = :source_id
                """
            ),
            {"source_id": yelp_source_id},
        )

    old_source_ids = [
        row[0]
        for row in conn.execute(
            sa.text(
                """
                SELECT id
                FROM review_sources
                WHERE location_id IN (
                    SELECT id FROM locations WHERE slug IN ('bakudan-bandera', 'bakudan-stone-oak')
                )
                """
            )
        ).fetchall()
    ]
    for old_source_id in old_source_ids:
        conn.execute(sa.text("DELETE FROM review_sources WHERE id = :id"), {"id": old_source_id})

    conn.execute(sa.text("DELETE FROM locations WHERE slug IN ('bakudan-bandera', 'bakudan-stone-oak')"))


def downgrade() -> None:
    # Data merge is intentionally irreversible.
    pass
