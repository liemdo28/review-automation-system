from __future__ import annotations

import re
from urllib.parse import parse_qs, quote_plus, urlparse

from app.providers.base import ProviderFetchError
from app.providers.page_provider import PageReviewProvider


class GoogleReviewsPortalProvider(PageReviewProvider):
    platform = "google"
    default_auth_required_selectors = [
        "input[type='email']",
        "input[type='password']",
        "[data-view-id='signIn']",
        "a:has-text('Sign in')",
        "button:has-text('Sign in')",
    ]
    default_selectors = {
        "review_card": [
            ".kx2i0d",
        ],
        "review_id": [
            ".KuKPRc",
        ],
        "reviewer_name": [
            "article a[jsname='xs1xe']",
            "article .N0c6q",
        ],
        "rating": [
            "article [role='img'][aria-label*='sao']",
            "article [role='img'][aria-label*='star']",
        ],
        "review_text": [
            "article [jsname='PBWx0c']",
            "article [jsname='lvvS4b']",
        ],
        "review_date": [
            "article .KEfuhb",
        ],
        "owner_reply_text": [
            ".UP87Yb [jsname='PBWx0c']",
            ".UP87Yb [jsname='lvvS4b']",
        ],
        "owner_reply_date": [
            ".UP87Yb .B5xEsb",
        ],
    }

    async def _load_review_surface(self, page) -> None:
        if "/local/business/" in (page.url or "") and "/customers/reviews" in (page.url or ""):
            await page.wait_for_selector(".kx2i0d", timeout=30000)
            return

        review_surface_url = await self._resolve_business_reviews_url(page)
        if not review_surface_url:
            raise ProviderFetchError(
                "Could not open the Google business review surface from the configured source page",
                retryable=False,
                details={"source_id": self.source.id, "platform": self.source.platform},
            )

        await page.goto(review_surface_url, wait_until="domcontentloaded", timeout=45000)
        await page.wait_for_selector(".kx2i0d", timeout=30000)

        scroll_steps = int(self.settings.get("scroll_steps", 6))
        scroll_pause_ms = int(self.settings.get("scroll_pause_ms", 900))
        for _ in range(max(1, scroll_steps)):
            await page.evaluate("window.scrollBy(0, 1100)")
            await page.wait_for_timeout(scroll_pause_ms)

    async def _resolve_business_reviews_url(self, page) -> str | None:
        listing_id = await self._resolve_listing_id(page)
        if not listing_id:
            return None
        return (
            f"https://www.google.com/local/business/{listing_id}/customers/reviews"
            "?knm=0&ih=lu&origin=https%3A%2F%2Fwww.google.com&hl=en"
        )

    async def _resolve_listing_id(self, page) -> str | None:
        candidate_texts: list[str] = []

        async def capture_response(response) -> None:
            url = response.url
            if "MapsMerchantStatusService.GetMerchantStatus" not in url and "preview/place" not in url:
                return
            try:
                candidate_texts.append(await response.text())
            except Exception:
                return

        page.on("response", capture_response)
        target_url = self._maps_search_url(page.url or self._effective_source_url() or self.source.source_url)
        if target_url and target_url != page.url:
            await page.goto(target_url, wait_until="domcontentloaded", timeout=45000)
        await page.wait_for_timeout(6000)

        for payload in candidate_texts:
            listing_id = self._extract_listing_id(payload)
            if listing_id:
                return listing_id
        return None

    def _maps_search_url(self, source_url: str | None) -> str | None:
        if not source_url:
            return None

        parsed = urlparse(source_url)
        if "google.com" not in parsed.netloc:
            return None
        if "/maps/place/" in parsed.path or "/maps/search/" in parsed.path:
            return source_url

        query = parse_qs(parsed.query).get("q", [""])[0].strip()
        if not query:
            return None
        return f"https://www.google.com/maps/search/{quote_plus(query)}"

    def _extract_listing_id(self, payload: str) -> str | None:
        patterns = [
            r'\[\[null,"-?\d+"\],null,null,"(\d{8,})","/g/',
            r',null,null,"(\d{8,})","/g/',
        ]
        for pattern in patterns:
            match = re.search(pattern, payload)
            if match:
                return match.group(1)
        return None
