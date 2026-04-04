"""Google OAuth 2.0 token refresh using httpx."""
import logging
import httpx
from tenacity import retry, stop_after_attempt, wait_fixed

logger = logging.getLogger("review_system.google_auth")

TOKEN_URL = "https://oauth2.googleapis.com/token"


class GoogleAuthError(Exception):
    pass


@retry(stop=stop_after_attempt(3), wait=wait_fixed(2))
async def get_access_token(client_id: str, client_secret: str, refresh_token: str) -> str:
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(TOKEN_URL, data={
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        })

    if resp.status_code != 200:
        raise GoogleAuthError(f"Token refresh failed: {resp.status_code} {resp.text}")

    token = resp.json().get("access_token")
    if not token:
        raise GoogleAuthError("No access_token in response")

    logger.info("Google access token refreshed successfully")
    return token


def get_access_token_sync(client_id: str, client_secret: str, refresh_token: str) -> str:
    """Synchronous version for rq workers."""
    import requests
    resp = requests.post(TOKEN_URL, data={
        "client_id": client_id,
        "client_secret": client_secret,
        "refresh_token": refresh_token,
        "grant_type": "refresh_token",
    }, timeout=30)

    if resp.status_code != 200:
        raise GoogleAuthError(f"Token refresh failed: {resp.status_code} {resp.text}")

    token = resp.json().get("access_token")
    if not token:
        raise GoogleAuthError("No access_token in response")
    return token
