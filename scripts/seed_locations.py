"""Seed the canonical restaurant locations into the database."""
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
        "google_account_id": "115468214193182088373",
        "google_location_id": "13520279089747024075",
        "yelp_url": "https://www.yelp.com/biz/raw-sushi-bistro-stockton-2",
    },
    {
        "slug": "bakudan-ramen",
        "name": "Bakudan Ramen",
        "address": "17619 La Cantera Pkwy, Ste 208, San Antonio, TX 78257",
        "city": "San Antonio",
        "state": "TX",
        "google_account_id": "115468214193182088373",
        "google_location_id": "4435485907466482087",
        "google_canonical_reviews_url": "https://www.google.com/local/business/4435485907466482087/customers/reviews?knm=0&ih=lu&origin=https%3A%2F%2Fwww.google.com&hl=en",
        "yelp_url": "https://www.yelp.com/biz/bakudan-ramen-san-antonio",
    },
]


def build_google_business_reviews_url(google_location_id: str) -> str:
    return (
        f"https://www.google.com/local/business/{google_location_id}/customers/reviews"
        "?knm=0&ih=lu&origin=https%3A%2F%2Fwww.google.com&hl=en"
    )


def build_google_source_url(location: dict) -> str:
    if location.get("google_canonical_reviews_url"):
        return location["google_canonical_reviews_url"]
    if location.get("google_location_id"):
        return build_google_business_reviews_url(location["google_location_id"])
    query = " ".join(
        part for part in [location["name"], location.get("city"), location.get("state"), "reviews"] if part
    )
    return f"https://www.google.com/search?q={quote_plus(query)}"


def ensure_review_sources(session, location: Location, location_data: dict) -> None:
    google_settings = {"max_reviews": 50}
    if location_data.get("google_shared_review_page_key"):
        google_settings["shared_review_page_key"] = location_data["google_shared_review_page_key"]
        google_settings["shared_review_page_primary"] = bool(location_data.get("google_shared_review_page_primary"))
        google_settings["canonical_google_reviews_url"] = location_data.get("google_canonical_reviews_url")

    google_source_url = build_google_source_url(location_data)
    google_source = session.query(ReviewSource).filter_by(location_id=location.id, platform="google").first()
    if not google_source:
        session.add(
            ReviewSource(
                location_id=location.id,
                platform="google",
                source_url=google_source_url,
                resolved_source_url=google_source_url,
                source_label=f"{location.name} Google Reviews",
                auth_mode="manual_session",
                session_status="reauth_required",
                settings=google_settings,
                is_active=True,
            )
        )
    else:
        google_source.source_url = google_source_url
        if location_data.get("google_shared_review_page_key") or location_data.get("google_location_id"):
            google_source.resolved_source_url = google_source_url
        google_source.settings = {**(google_source.settings or {}), **google_settings}
        google_source.auth_mode = "manual_session"
        google_source.source_label = f"{location.name} Google Reviews"

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
    elif yelp_source and location_data.get("yelp_url"):
        yelp_source.source_url = location_data["yelp_url"]
        yelp_source.source_label = f"{location.name} Yelp Reviews"
        yelp_source.auth_mode = "public_or_session"


def seed():
    session = SyncSessionLocal()
    try:
        for loc_data in LOCATIONS:
            existing = session.query(Location).filter_by(slug=loc_data["slug"]).first()
            if existing:
                existing.name = loc_data["name"]
                existing.address = loc_data["address"]
                existing.city = loc_data.get("city")
                existing.state = loc_data.get("state")
                existing.google_account_id = loc_data.get("google_account_id")
                existing.google_location_id = loc_data.get("google_location_id")
                existing.yelp_url = loc_data.get("yelp_url")
                print(f"  [skip] {loc_data['slug']} already exists")
                ensure_review_sources(session, existing, loc_data)
                continue
            location_fields = {
                "slug": loc_data["slug"],
                "name": loc_data["name"],
                "address": loc_data["address"],
                "city": loc_data.get("city"),
                "state": loc_data.get("state"),
                "google_account_id": loc_data.get("google_account_id"),
                "google_location_id": loc_data.get("google_location_id"),
                "yelp_url": loc_data.get("yelp_url"),
            }
            loc = Location(**location_fields)
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
