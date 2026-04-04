"""Seed the 4 restaurant locations into the database."""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.database import SyncSessionLocal
from app.models.location import Location

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
        "slug": "bakudan-bandera",
        "name": "Bakudan Ramen (Bandera)",
        "address": "11309 Bandera Rd, Ste 111, San Antonio, TX 78254",
        "city": "San Antonio",
        "state": "TX",
        "google_account_id": "115468214193182088373",
        "google_location_id": "9390782300587134823",
        "yelp_url": "https://www.yelp.com/biz/bakudan-ramen-san-antonio-3",
    },
    {
        "slug": "bakudan-rim",
        "name": "Bakudan Ramen (The Rim)",
        "address": "17619 La Cantera Pkwy, Ste 208, San Antonio, TX 78257",
        "city": "San Antonio",
        "state": "TX",
        "google_account_id": "115468214193182088373",
        "google_location_id": "4435485907466482087",
        "yelp_url": "https://www.yelp.com/biz/bakudan-ramen-san-antonio",
    },
    {
        "slug": "bakudan-stone-oak",
        "name": "Bakudan Ramen (Stone Oak)",
        "address": "22506 U.S. Hwy 281 N, Ste 106, San Antonio, TX 78258",
        "city": "San Antonio",
        "state": "TX",
        "google_account_id": "115468214193182088373",
        "google_location_id": "1599829923443837201",
        "yelp_url": "https://www.yelp.com/biz/bakudan-ramen-san-antonio-2",
    },
]


def seed():
    session = SyncSessionLocal()
    try:
        for loc_data in LOCATIONS:
            existing = session.query(Location).filter_by(slug=loc_data["slug"]).first()
            if existing:
                print(f"  [skip] {loc_data['slug']} already exists")
                continue
            loc = Location(**loc_data)
            session.add(loc)
            print(f"  [add]  {loc_data['slug']} - {loc_data['name']}")
        session.commit()
        print(f"\nDone. {session.query(Location).count()} locations in database.")
    finally:
        session.close()


if __name__ == "__main__":
    print("Seeding locations...")
    seed()
