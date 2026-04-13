"""Seed the 4 restaurant locations into the database."""
import sys
import os
from urllib.parse import quote_plus
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.database import SyncSessionLocal
from app.models.location import Location
from app.models.review_source import ReviewSource

LOCATIONS = [
    {
        "slug": "raw-sushi-stockton",
        "name": "Raw Sushi Bistro",
        "address": "10742 Trinity Pkwy, Ste D, Stockton, CA 95219",
        "city": "Stockton",
        "state": "CA",
        "yelp_url": "https://www.yelp.com/biz/raw-sushi-bistro-stockton-2",
    },
    {
        "slug": "bakudan-bandera",
        "name": "Bakudan Ramen (Bandera)",
        "address": "11309 Bandera Rd, Ste 111, San Antonio, TX 78254",
        "city": "San Antonio",
        "state": "TX",
        "yelp_url": "https://www.yelp.com/biz/bakudan-ramen-san-antonio-3",
    },
    {
        "slug": "bakudan-rim",
        "name": "Bakudan Ramen (The Rim)",
        "address": "17619 La Cantera Pkwy, Ste 208, San Antonio, TX 78257",
        "city": "San Antonio",
        "state": "TX",
        "yelp_url": "https://www.yelp.com/biz/bakudan-ramen-san-antonio",
    },
    {
        "slug": "bakudan-stone-oak",
        "name": "Bakudan Ramen (Stone Oak)",
        "address": "22506 U.S. Hwy 281 N, Ste 106, San Antonio, TX 78258",
        "city": "San Antonio",
        "state": "TX",
        "yelp_url": "https://www.yelp.com/biz/bakudan-ramen-san-antonio-2",
    },
]


def build_google_source_url(location: dict) -> str:
    query = " ".join(
        part for part in [location["name"], location.get("city"), location.get("state"), "reviews"] if part
    )
    return f"https://www.google.com/search?q={quote_plus(query)}"


def ensure_review_sources(session, location: Location, location_data: dict) -> None:
    google_source = session.query(ReviewSource).filter_by(location_id=location.id, platform="google").first()
    if not google_source:
        session.add(
            ReviewSource(
                location_id=location.id,
                platform="google",
                source_url=build_google_source_url(location_data),
                source_label=f"{location.name} Google Reviews",
                auth_mode="manual_session",
                session_status="reauth_required",
                settings={"max_reviews": 50},
                is_active=True,
            )
        )

    yelp_source = session.query(ReviewSource).filter_by(location_id=location.id, platform="yelp").first()
    if not yelp_source and location_data.get("yelp_url"):
        session.add(
            ReviewSource(
                location_id=location.id,
                platform="yelp",
                source_url=location_data["yelp_url"],
                source_label=f"{location.name} Yelp Reviews",
                auth_mode="public_or_session",
                session_status="active",
                settings={"max_reviews": 50},
                is_active=True,
            )
        )


def seed():
    session = SyncSessionLocal()
    try:
        for loc_data in LOCATIONS:
            existing = session.query(Location).filter_by(slug=loc_data["slug"]).first()
            if existing:
                print(f"  [skip] {loc_data['slug']} already exists")
                ensure_review_sources(session, existing, loc_data)
                continue
            loc = Location(**loc_data)
            session.add(loc)
            session.flush()
            ensure_review_sources(session, loc, loc_data)
            print(f"  [add]  {loc_data['slug']} - {loc_data['name']}")
        session.commit()
        print(f"\nDone. {session.query(Location).count()} locations in database.")
    finally:
        session.close()


if __name__ == "__main__":
    print("Seeding locations...")
    seed()
