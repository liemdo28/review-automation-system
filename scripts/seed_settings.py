"""
Seed default ReviewSettings for all active locations.
Run once after applying migration 002.

Usage:
    python scripts/seed_settings.py
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.database import SyncSessionLocal
from app.models.location import Location
from app.models.review_settings import ReviewSettings
from app.config import settings as app_settings

DEFAULT_BRAND_TONE = (
    "Professional, warm, and concise. Sound human and genuine. "
    "Thank customers for positive reviews and invite them to return. "
    "For complaints, acknowledge concerns respectfully and move resolution offline."
)


def seed():
    session = SyncSessionLocal()
    try:
        locations = session.query(Location).filter_by(is_active=True).all()
        if not locations:
            print("No active locations found. Run scripts/seed_locations.py first.")
            return

        created = 0
        for loc in locations:
            for platform in ["google", "yelp"]:
                existing = session.query(ReviewSettings).filter_by(
                    store_id=loc.slug, platform=platform
                ).first()
                if existing:
                    print(f"  [skip] {loc.slug} / {platform} — already exists")
                    continue

                setting = ReviewSettings(
                    store_id=loc.slug,
                    platform=platform,
                    auto_reply_google_positive=False,   # OFF by default — enable per store
                    email_alert_enabled=True,
                    manager_email=app_settings.alert_email_to or None,
                    brand_tone=DEFAULT_BRAND_TONE,
                    signature_text=None,
                    active=True,
                )
                session.add(setting)
                created += 1
                print(f"  [add]  {loc.slug} / {platform}")

        session.commit()
        total = session.query(ReviewSettings).count()
        print(f"\nDone. Created {created} new settings rows ({total} total).")
        print("\nTo enable auto-reply for a store, update via:")
        print("  PUT /api/review-settings/{store_id}")
        print('  body: {"platform": "google", "auto_reply_google_positive": true}')

    finally:
        session.close()


if __name__ == "__main__":
    print("Seeding review settings...")
    seed()
