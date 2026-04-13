from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from app.config import settings
from app.providers.base import (
    ProviderAuthRequiredError,
    ProviderConfigError,
    ProviderFetchError,
    ProviderReview,
    ReviewProvider,
)


class PageReviewProvider(ReviewProvider):
    default_selectors: dict[str, Any] = {}
    default_auth_required_selectors: list[str] = []

    def _effective_source_url(self) -> str | None:
        return getattr(self.source, "effective_source_url", None) or getattr(self.source, "resolved_source_url", None) or self.source.source_url

    async def validate_session(self) -> tuple[bool, str]:
        source_url = self._effective_source_url()
        if not source_url:
            raise ProviderConfigError("Source URL is missing")

        auth_mode = (self.source.auth_mode or "").lower()
        if auth_mode in {"manual_session", "session_required"} and not self._storage_state_path():
            return False, "reauth_required"

        from playwright.async_api import async_playwright

        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(headless=True, **self._browser_launch_kwargs())
            context = await browser.new_context(**self._browser_context_kwargs())
            page = await context.new_page()
            try:
                response = await page.goto(source_url, wait_until="domcontentloaded", timeout=45000)
                await asyncio.sleep(1.5)
                if await self._looks_blocked(page, response):
                    return False, "reauth_required"
                if await self._looks_unauthenticated(page):
                    return False, "reauth_required"
                return True, "active"
            finally:
                await browser.close()

    async def fetch_reviews(self) -> list[ProviderReview]:
        source_url = self._effective_source_url()
        if not source_url:
            raise ProviderConfigError("Source URL is missing")

        from playwright.async_api import async_playwright

        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(headless=True, **self._browser_launch_kwargs())
            context = await browser.new_context(**self._browser_context_kwargs())
            page = await context.new_page()
            try:
                response = await page.goto(source_url, wait_until="domcontentloaded", timeout=45000)
                await asyncio.sleep(2)
                if await self._looks_blocked(page, response):
                    raise ProviderAuthRequiredError(
                        "Source page was blocked; refresh or attach an authorized session before syncing again",
                        details={
                            "source_id": self.source.id,
                            "platform": self.source.platform,
                            "http_status": response.status if response else None,
                        },
                    )
                if await self._looks_unauthenticated(page):
                    raise ProviderAuthRequiredError(
                        "Authorized session is required for this source",
                        details={"source_id": self.source.id, "platform": self.source.platform},
                    )
                await self._load_review_surface(page)
                reviews = await self._extract_reviews(page)
                if not reviews and not self.settings.get("allow_empty_results", False):
                    raise ProviderFetchError(
                        "No review cards were detected on the source page; selectors or access may need attention",
                        retryable=False,
                        details={"source_id": self.source.id, "platform": self.source.platform},
                    )
                return reviews
            except ProviderAuthRequiredError:
                raise
            except ProviderConfigError:
                raise
            except Exception as exc:
                raise ProviderFetchError(str(exc), details={"source_id": self.source.id}) from exc
            finally:
                await browser.close()

    async def _load_review_surface(self, page) -> None:
        scroll_steps = int(self.settings.get("scroll_steps", 6))
        scroll_pause_ms = int(self.settings.get("scroll_pause_ms", 900))
        for _ in range(max(1, scroll_steps)):
            await page.evaluate("window.scrollBy(0, 900)")
            await page.wait_for_timeout(scroll_pause_ms)
        load_more_selector = self._selector_value("load_more")
        if load_more_selector:
            for selector in load_more_selector:
                try:
                    button = await page.query_selector(selector)
                    if button:
                        await button.click()
                        await page.wait_for_timeout(1200)
                except Exception:
                    continue

    async def _extract_reviews(self, page) -> list[ProviderReview]:
        selectors = self._selector_value("review_card")
        if not selectors:
            raise ProviderConfigError(
                "Review card selectors are missing",
                details={"platform": self.source.platform},
            )

        elements = []
        for selector in selectors:
            elements = await page.query_selector_all(selector)
            if elements:
                break

        reviews: list[ProviderReview] = []
        max_reviews = int(self.settings.get("max_reviews", 50))
        for index, element in enumerate(elements[:max_reviews]):
            extracted = await self._extract_single_review(element, index)
            if extracted and extracted.external_review_id:
                reviews.append(extracted)
        return reviews

    async def _extract_single_review(self, element, index: int) -> ProviderReview | None:
        review_id = await self._extract_id(element, index)
        if not review_id:
            return None

        review_text = self.normalize_text(await self._extract_text(element, "review_text"))
        reviewer_name = self.normalize_text(await self._extract_text(element, "reviewer_name"))
        rating_text = self.normalize_text(await self._extract_attr_or_text(element, "rating"))
        review_date_text = self.normalize_text(await self._extract_text(element, "review_date"))
        reply_text = self.normalize_text(await self._extract_text(element, "owner_reply_text"))
        reply_date_text = self.normalize_text(await self._extract_text(element, "owner_reply_date"))

        return ProviderReview(
            external_review_id=review_id,
            platform=self.platform,
            source_url=self._effective_source_url() or self.source.source_url,
            reviewer_name=reviewer_name or "Anonymous",
            rating=self.parse_rating(rating_text),
            review_text=review_text,
            review_date=self.parse_datetime(review_date_text),
            has_owner_reply=bool(reply_text),
            detected_owner_reply_text=reply_text,
            detected_owner_reply_at=self.parse_datetime(reply_date_text),
            raw_payload={
                "reviewer_name": reviewer_name,
                "rating": rating_text,
                "review_text": review_text,
                "review_date": review_date_text,
                "owner_reply_text": reply_text,
                "owner_reply_date": reply_date_text,
            },
        )

    async def _looks_unauthenticated(self, page) -> bool:
        selectors = self.settings.get("auth_required_selectors") or self.default_auth_required_selectors
        for selector in selectors:
            if await page.query_selector(selector):
                return True
        login_url_patterns = self.settings.get("auth_required_url_patterns") or ["login", "signin"]
        page_url = (page.url or "").lower()
        return any(pattern in page_url for pattern in login_url_patterns)

    async def _looks_blocked(self, page, response=None) -> bool:
        blocked_statuses = self.settings.get("blocked_statuses") or [401, 403, 429]
        if response and response.status in blocked_statuses:
            return True

        blocked_selectors = self.settings.get("blocked_selectors") or []
        for selector in blocked_selectors:
            if await page.query_selector(selector):
                return True

        if response and response.status and response.status >= 400:
            return True

        try:
            body_text = (await page.locator("body").inner_text()).strip()
        except Exception:
            body_text = ""

        min_body_text_chars = int(self.settings.get("min_body_text_chars", 25))
        return len(body_text) < min_body_text_chars

    async def _extract_id(self, element, index: int) -> str:
        id_attributes = self.settings.get("review_id_attributes") or ["data-review-id", "data-testid"]
        for attr in id_attributes:
            try:
                value = await element.get_attribute(attr)
                if value:
                    return value.strip()
            except Exception:
                continue

        custom = await self._extract_attr_or_text(element, "review_id")
        if custom:
            return custom.strip()
        return f"{self.platform}-{self.source.id}-{index}"

    async def _extract_text(self, element, key: str) -> str | None:
        selectors = self._selector_value(key)
        for selector in selectors:
            try:
                node = await element.query_selector(selector)
                if not node:
                    continue
                text = (await node.inner_text()).strip()
                if text:
                    return text
            except Exception:
                continue
        return None

    async def _extract_attr_or_text(self, element, key: str) -> str | None:
        selectors = self._selector_value(key)
        default_attributes = ["aria-label", "title", "data-rating"]
        if key == "review_id":
            default_attributes = ["data-review-id", "data-testid", "aria-label", "title"]
        attributes = self.settings.get(f"{key}_attributes") or default_attributes
        for selector in selectors:
            try:
                node = await element.query_selector(selector)
                if not node:
                    continue
                for attr in attributes:
                    value = await node.get_attribute(attr)
                    if value:
                        return value.strip()
                text = (await node.inner_text()).strip()
                if text:
                    return text
            except Exception:
                continue
        return None

    def _selector_value(self, key: str) -> list[str]:
        configured = self.settings.get("selectors", {}).get(key)
        if configured:
            return configured
        default = self.default_selectors.get(key) or []
        return default if isinstance(default, list) else [default]

    def _storage_state_path(self) -> str | None:
        reference = None
        if self.auth_session:
            reference = self.auth_session.session_reference
        if not reference:
            reference = self.settings.get("storage_state_path")
        if not reference:
            return None
        path = Path(reference)
        return str(path) if path.exists() else None

    def _browser_launch_kwargs(self) -> dict[str, Any]:
        proxy_server = self.settings.get("proxy_server")
        if not proxy_server:
            if self.platform == "google":
                proxy_server = settings.google_browser_proxy
            elif self.platform == "yelp":
                proxy_server = settings.yelp_browser_proxy

        if proxy_server:
            return {
                "proxy": {"server": proxy_server},
                "args": [f"--lang={settings.review_browser_locale}", "--disable-blink-features=AutomationControlled"],
            }
        return {"args": [f"--lang={settings.review_browser_locale}", "--disable-blink-features=AutomationControlled"]}

    def _browser_context_kwargs(self) -> dict[str, Any]:
        context_kwargs = {
            "viewport": {"width": 1600, "height": 1200},
            "locale": settings.review_browser_locale,
            "timezone_id": settings.review_browser_timezone,
            "extra_http_headers": {"Accept-Language": f"{settings.review_browser_locale},en;q=0.9"},
        }
        storage_state = self._storage_state_path()
        if storage_state:
            context_kwargs["storage_state"] = storage_state
        return context_kwargs
