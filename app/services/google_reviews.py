"""Google Business Profile API v4 client."""
import logging
import httpx
import requests
from tenacity import retry, stop_after_attempt, wait_fixed
from typing import Any

logger = logging.getLogger("review_system.google_reviews")

BASE_URL = "https://mybusiness.googleapis.com/v4"


class GoogleReviewAPIError(Exception):
    pass


def _headers(access_token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"}


# ── Async versions (for fetch worker) ───────────────────────────────────────

@retry(stop=stop_after_attempt(3), wait=wait_fixed(2))
async def list_reviews(access_token: str, account_id: str, location_id: str) -> list[dict[str, Any]]:
    url = f"{BASE_URL}/accounts/{account_id}/locations/{location_id}/reviews"
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(url, headers=_headers(access_token))

    if resp.status_code != 200:
        raise GoogleReviewAPIError(f"List reviews failed: {resp.status_code} {resp.text}")

    return resp.json().get("reviews", [])


@retry(stop=stop_after_attempt(3), wait=wait_fixed(2))
async def reply_to_review(
    access_token: str, account_id: str, location_id: str, review_id: str, comment: str
) -> dict[str, Any]:
    url = f"{BASE_URL}/accounts/{account_id}/locations/{location_id}/reviews/{review_id}/reply"
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.put(url, headers=_headers(access_token), json={"comment": comment})

    if resp.status_code not in (200, 201):
        raise GoogleReviewAPIError(f"Reply failed: {resp.status_code} {resp.text}")

    logger.info(f"Reply posted to review {review_id}")
    return resp.json()


# ── Sync versions (for rq workers) ──────────────────────────────────────────

@retry(stop=stop_after_attempt(3), wait=wait_fixed(2))
def reply_to_review_sync(
    access_token: str, account_id: str, location_id: str, review_id: str, comment: str
) -> dict[str, Any]:
    url = f"{BASE_URL}/accounts/{account_id}/locations/{location_id}/reviews/{review_id}/reply"
    resp = requests.put(url, headers=_headers(access_token), json={"comment": comment}, timeout=30)

    if resp.status_code not in (200, 201):
        raise GoogleReviewAPIError(f"Reply failed: {resp.status_code} {resp.text}")

    logger.info(f"Reply posted to review {review_id}")
    return resp.json()
