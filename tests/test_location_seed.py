from __future__ import annotations

from scripts.seed_locations import LOCATIONS, build_google_source_url


def test_seed_locations_have_unique_slugs():
    slugs = [item["slug"] for item in LOCATIONS]
    assert len(slugs) == len(set(slugs))


def test_build_google_source_url_prefers_canonical_review_url():
    location = {
        "name": "Bakudan Ramen",
        "city": "San Antonio",
        "state": "TX",
        "google_canonical_reviews_url": "https://www.google.com/local/business/1/customers/reviews?hl=en",
    }
    assert build_google_source_url(location) == location["google_canonical_reviews_url"]
