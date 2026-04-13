from __future__ import annotations

import re
from urllib.parse import parse_qs, quote_plus, urlparse

from app.config import settings
from app.providers.base import ProviderAuthRequiredError, ProviderFetchError, ProviderPostError
from app.providers.page_provider import PageReviewProvider
from app.services.review_matcher import CandidateReviewCard, find_best_review_match, review_text_snippet
from app.services.ui_posting import capture_failure_artifacts, reply_preview_hash


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

    async def post_reply(self, review, reply_text: str) -> dict:
        if not reply_text.strip():
            raise ProviderPostError("Reply text is empty", retryable=False, details={"review_id": review.id})

        source_url = self._effective_source_url()
        if not source_url:
            raise ProviderPostError("Source URL is missing", retryable=False, details={"review_id": review.id})

        from playwright.async_api import async_playwright

        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(
                headless=settings.ui_posting_headless,
                **self._browser_launch_kwargs(),
            )
            context = await browser.new_context(**self._browser_context_kwargs())
            page = await context.new_page()
            attempt_log = {
                "review_id": review.id,
                "source_id": self.source.id,
                "location_id": review.location_id,
                "platform": self.platform,
                "opened_source_url": source_url,
                "reply_preview_hash": reply_preview_hash(reply_text),
                "reply_preview": reply_text[:120],
                "submit_attempted_at": None,
            }
            try:
                response = await page.goto(source_url, wait_until="domcontentloaded", timeout=45000)
                await page.wait_for_timeout(1500)
                if await self._looks_blocked(page, response):
                    details = await capture_failure_artifacts(
                        page,
                        review_id=review.id,
                        step="blocked_before_post",
                        details=attempt_log,
                    )
                    raise ProviderAuthRequiredError(
                        "Google blocked the posting session; refresh login before retrying.",
                        details=details,
                    )
                if await self._looks_unauthenticated(page):
                    details = await capture_failure_artifacts(
                        page,
                        review_id=review.id,
                        step="unauthenticated_before_post",
                        details=attempt_log,
                    )
                    raise ProviderAuthRequiredError(
                        "Authorized Google session is required before auto posting.",
                        details=details,
                    )

                if not await self._verify_store_identity(page):
                    details = await capture_failure_artifacts(
                        page,
                        review_id=review.id,
                        step="wrong_store_detected",
                        details=attempt_log,
                    )
                    raise ProviderPostError(
                        "The opened Google page does not confidently match the expected store.",
                        retryable=False,
                        details=details,
                    )

                await self._open_reply_to_reviews(page, review.id, attempt_log)
                await self._focus_unreplied_tab(page)
                card, match_result = await self._find_review_card(page, review)
                if not card:
                    await self._focus_all_tab(page)
                    card, match_result = await self._find_review_card(page, review)
                if not card:
                    details = await capture_failure_artifacts(
                        page,
                        review_id=review.id,
                        step="target_review_not_found",
                        details={
                            **attempt_log,
                            "reviewer_name": review.reviewer_name,
                            "review_snippet": review_text_snippet(review.review_text),
                            "match_result": match_result.as_dict() if match_result else None,
                        },
                    )
                    raise ProviderPostError(
                        "Could not locate the target Google review card for posting.",
                        retryable=False,
                        details=details,
                    )

                if await self._card_has_owner_reply(card):
                    return {
                        **attempt_log,
                        "posted": True,
                        "already_replied": True,
                        "verified": True,
                        "matched_reviewer_name": match_result.candidate.reviewer_name if match_result and match_result.candidate else review.reviewer_name,
                    }

                reply_button = await self._find_first_locator(
                    card,
                    [
                        "button:has-text('Reply')",
                        "[role='button']:has-text('Reply')",
                    ],
                )
                if not reply_button:
                    details = await capture_failure_artifacts(
                        page,
                        review_id=review.id,
                        step="reply_button_missing",
                        details={**attempt_log, "match_result": match_result.as_dict() if match_result else None},
                    )
                    raise ProviderPostError(
                        "Reply button is not available on the matched Google review card.",
                        retryable=False,
                        details=details,
                    )

                await reply_button.click()
                editor = await self._wait_for_reply_editor(card, page)
                if not editor:
                    details = await capture_failure_artifacts(
                        page,
                        review_id=review.id,
                        step="reply_editor_missing",
                        details={**attempt_log, "match_result": match_result.as_dict() if match_result else None},
                    )
                    raise ProviderPostError(
                        "Google reply editor did not open for the matched review.",
                        retryable=True,
                        details=details,
                    )

                await self._fill_reply_editor(editor, reply_text)
                if not await self._validate_editor_text(editor, reply_text):
                    await self._fill_reply_editor(editor, reply_text)
                if not await self._validate_editor_text(editor, reply_text):
                    details = await capture_failure_artifacts(
                        page,
                        review_id=review.id,
                        step="reply_text_validation_failed",
                        details={**attempt_log, "match_result": match_result.as_dict() if match_result else None},
                    )
                    raise ProviderPostError(
                        "Reply text could not be validated inside the Google editor.",
                        retryable=False,
                        details=details,
                    )

                attempt_log["submit_attempted_at"] = self._utc_timestamp()
                try:
                    await self._submit_with_keyboard_sequence(page, editor)
                except ProviderPostError as exc:
                    details = await capture_failure_artifacts(
                        page,
                        review_id=review.id,
                        step="submit_controls_missing",
                        details={**attempt_log, "match_result": match_result.as_dict() if match_result else None},
                    )
                    raise ProviderPostError(
                        str(exc),
                        retryable=exc.retryable,
                        details={**details, **(exc.details or {})},
                    ) from exc
                verified = await self._wait_for_post_confirmation(card, page, reply_text)
                if not verified:
                    details = await capture_failure_artifacts(
                        page,
                        review_id=review.id,
                        step="submit_uncertain",
                        details={**attempt_log, "match_result": match_result.as_dict() if match_result else None},
                    )
                    raise ProviderPostError(
                        "Google did not confirm the reply after submit.",
                        retryable=True,
                        details={**details, "verification_required": True},
                    )

                await self._return_to_reviews_list(page)
                return {
                    **attempt_log,
                    "posted": True,
                    "already_replied": False,
                    "verified": True,
                    "matched_reviewer_name": match_result.candidate.reviewer_name if match_result and match_result.candidate else review.reviewer_name,
                    "matched_review_snippet": match_result.candidate.review_text[:120] if match_result and match_result.candidate and match_result.candidate.review_text else review_text_snippet(review.review_text),
                    "match_score": match_result.score if match_result else None,
                    "match_confidence": match_result.confidence if match_result else None,
                    "match_reasons": match_result.reasons if match_result else None,
                }
            finally:
                await browser.close()

    async def _focus_unreplied_tab(self, page) -> None:
        await self._focus_tab(page, ["text=Unreplied", "[role='tab']:has-text('Unreplied')"])

    async def _focus_all_tab(self, page) -> None:
        await self._focus_tab(page, ["text=All", "[role='tab']:has-text('All')"])

    async def _focus_tab(self, page, selectors: list[str]) -> None:
        for selector in selectors:
            try:
                locator = page.locator(selector).first
                if await locator.count():
                    await locator.click(timeout=2000)
                    await page.wait_for_timeout(1200)
                    return
            except Exception:
                continue

    async def _open_reply_to_reviews(self, page, review_id: int, attempt_log: dict) -> None:
        if await self._reply_management_ready(page):
            return

        for _ in range(2):
            reply_to_reviews = await self._find_first_locator(
                page,
                [
                    "button:has-text('Reply to reviews')",
                    "[role='button']:has-text('Reply to reviews')",
                    "[aria-label*='Reply to reviews']",
                ],
            )
            if reply_to_reviews:
                try:
                    await reply_to_reviews.click(timeout=3000)
                    await page.wait_for_timeout(1800)
                    if await self._reply_management_ready(page):
                        return
                except Exception:
                    pass

            await self._load_review_surface(page)
            if await self._reply_management_ready(page):
                return

        details = await capture_failure_artifacts(
            page,
            review_id=review_id,
            step="review_panel_open_failed",
            details=attempt_log,
        )
        raise ProviderPostError(
            "Could not open the Google reviews panel for UI posting.",
            retryable=True,
            details=details,
        )

    async def _reviews_panel_visible(self, page) -> bool:
        tabs = [
            "text=All",
            "[role='tab']:has-text('All')",
            "text=Replied",
            "[role='tab']:has-text('Replied')",
            "text=Unreplied",
            "[role='tab']:has-text('Unreplied')",
        ]
        found = 0
        for selector in tabs:
            try:
                locator = page.locator(selector).first
                if await locator.count():
                    found += 1
            except Exception:
                continue
        return found >= 3

    async def _reply_management_ready(self, page) -> bool:
        if not await self._reviews_panel_visible(page):
            return False
        return await self._reply_actions_visible(page)

    async def _reply_actions_visible(self, page) -> bool:
        action_selectors = [
            ".kx2i0d button:has-text('Reply')",
            ".kx2i0d [role='button']:has-text('Reply')",
            ".kx2i0d button:has-text('Edit')",
            ".kx2i0d [role='button']:has-text('Edit')",
            ".kx2i0d button:has-text('Delete')",
            ".kx2i0d [role='button']:has-text('Delete')",
        ]
        for selector in action_selectors:
            try:
                locator = page.locator(selector).first
                if await locator.count():
                    return True
            except Exception:
                continue
        return False

    async def _verify_store_identity(self, page) -> bool:
        expected_names = [
            getattr(self.source, "expected_store_name", None),
            self.source.source_label.replace("Google Reviews", "").strip() if self.source.source_label else None,
        ]
        expected_names = [name.strip().lower() for name in expected_names if name and name.strip()]
        if not expected_names:
            return True
        try:
            body_text = (await page.locator("body").inner_text()).lower()
        except Exception:
            return False
        return any(name in body_text for name in expected_names)

    async def _find_review_card(self, page, review):
        threshold = float(self.settings.get("ui_posting_match_threshold", settings.ui_posting_match_threshold))
        min_margin = float(self.settings.get("ui_posting_match_margin", settings.ui_posting_match_margin))
        for _ in range(16):
            cards, candidates = await self._collect_visible_review_cards(page)
            match_result = find_best_review_match(
                review,
                candidates,
                threshold=threshold,
                min_margin=min_margin,
            )
            if match_result.matched and match_result.candidate:
                candidate_index = candidates.index(match_result.candidate)
                return cards.nth(candidate_index), match_result
            await self._scroll_review_container(page)
            await page.wait_for_timeout(900)
        return None, match_result if "match_result" in locals() else None

    async def _collect_visible_review_cards(self, page):
        cards = page.locator(".kx2i0d")
        count = await cards.count()
        candidates: list[CandidateReviewCard] = []
        for index in range(count):
            card = cards.nth(index)
            payload = await self._card_payload(card)
            candidates.append(
                CandidateReviewCard(
                    reviewer_name=payload["reviewer"],
                    review_text=payload["text"],
                    rating=self.parse_rating(payload["rating"]),
                    review_date_raw=payload["date"],
                    external_review_id=payload["review_id"],
                    raw_text=payload["raw"],
                    has_owner_reply=payload["has_owner_reply"],
                )
            )
        return cards, candidates

    async def _card_payload(self, card) -> dict[str, str]:
        return await card.evaluate(
            """(node) => {
                const textOf = (selectors) => {
                    for (const selector of selectors) {
                        const found = node.querySelector(selector);
                        if (found && found.innerText) return found.innerText.trim();
                    }
                    return "";
                };
                return {
                    reviewer: textOf(["article a[jsname='xs1xe']", "article .N0c6q"]),
                    text: textOf(["article [jsname='PBWx0c']", "article [jsname='lvvS4b']"]),
                    rating: textOf(["article [role='img'][aria-label*='star']", "article [role='img'][aria-label*='sao']"]),
                    date: textOf(["article .KEfuhb"]),
                    review_id: textOf([".KuKPRc"]),
                    has_owner_reply: Boolean(node.querySelector(".UP87Yb")),
                    raw: (node.innerText || "").trim(),
                };
            }"""
        )

    async def _card_has_owner_reply(self, card) -> bool:
        for selector in [
            ".UP87Yb",
            "button:has-text('Edit')",
            "[role='button']:has-text('Edit')",
            "button:has-text('Delete')",
            "[role='button']:has-text('Delete')",
        ]:
            try:
                locator = card.locator(selector).first
                if await locator.count():
                    return True
            except Exception:
                continue
        return False

    async def _find_first_locator(self, scope, selectors: list[str]):
        for selector in selectors:
            try:
                locator = scope.locator(selector).first
                if await locator.count():
                    return locator
            except Exception:
                continue
        return None

    async def _wait_for_reply_editor(self, card, page):
        selectors = [
            "textarea[aria-label*='Reply publicly']",
            "textarea[placeholder*='Reply publicly']",
            "[role='textbox'][aria-label*='Reply publicly']",
            "[contenteditable='true'][aria-label*='Reply publicly']",
            "[contenteditable='true'][data-placeholder*='Reply publicly']",
        ]
        for _ in range(20):
            label_visible = False
            for label_selector in [
                "text=Reply publicly",
                "label:has-text('Reply publicly')",
                "[aria-label*='Reply publicly']",
            ]:
                try:
                    if await page.locator(label_selector).count():
                        label_visible = True
                        break
                except Exception:
                    continue
            editor = await self._find_first_locator(card, selectors)
            if editor and label_visible:
                return editor
            if label_visible:
                editor = await self._find_first_locator(page, selectors)
            if editor and label_visible:
                return editor
            await page.wait_for_timeout(400)
        return None

    async def _fill_reply_editor(self, editor, reply_text: str) -> None:
        tag_name = (await editor.evaluate("(node) => node.tagName.toLowerCase()")).strip().lower()
        if tag_name == "textarea":
            await editor.fill(reply_text)
            return
        await editor.click()
        await editor.evaluate("(node) => { node.textContent = ''; }")
        await editor.fill(reply_text)

    async def _validate_editor_text(self, editor, reply_text: str) -> bool:
        expected = review_text_snippet(reply_text, limit=180)
        actual = ""
        try:
            tag_name = (await editor.evaluate("(node) => node.tagName.toLowerCase()")).strip().lower()
            if tag_name == "textarea":
                actual = await editor.input_value()
            else:
                actual = await editor.evaluate("(node) => node.innerText || node.textContent || ''")
        except Exception:
            actual = ""
        actual = review_text_snippet(actual, limit=180)
        return bool(actual and expected and (actual == expected or expected in actual or actual in expected))

    async def _submit_with_keyboard_sequence(self, page, editor) -> None:
        try:
            await editor.click()
        except Exception:
            pass
        await page.wait_for_timeout(150)
        if not await self._submit_affordance_visible(page):
            raise ProviderPostError(
                "Google reply submit controls were not detected before keyboard submit.",
                retryable=True,
                details={"step": "submit_controls_missing"},
            )
        await page.wait_for_timeout(250)
        await page.keyboard.press("Tab")
        await page.wait_for_timeout(300)
        await page.keyboard.press("Tab")
        await page.wait_for_timeout(300)
        await page.keyboard.press("Enter")
        await page.wait_for_timeout(2200)

    async def _submit_affordance_visible(self, page) -> bool:
        selectors = [
            "button:has-text('Post')",
            "[role='button']:has-text('Post')",
            "button:has-text('Reply')",
            "[role='button']:has-text('Reply')",
            "button:has-text('Publish')",
            "[role='button']:has-text('Publish')",
        ]
        for selector in selectors:
            try:
                locator = page.locator(selector).first
                if await locator.count():
                    return True
            except Exception:
                continue
        return False

    async def _wait_for_post_confirmation(self, card, page, reply_text: str) -> bool:
        snippet = reply_text.strip()[:60]
        for _ in range(20):
            try:
                card_text = await card.inner_text()
            except Exception:
                card_text = ""
            if snippet and snippet in card_text:
                return True
            if await self._card_has_owner_reply(card):
                return True
            for selector in [
                "text=Edit",
                "[role='button']:has-text('Edit')",
                "text=Delete",
                "[role='button']:has-text('Delete')",
                "text=Reply posted",
                "[role='status']",
            ]:
                try:
                    locator = page.locator(selector).first
                    if await locator.count():
                        return True
                except Exception:
                    continue
            await page.wait_for_timeout(600)
        return False

    async def _return_to_reviews_list(self, page) -> None:
        for selector in [
            "button[aria-label='Close']",
            "[role='button'][aria-label='Close']",
            "button:has-text('Close')",
        ]:
            try:
                locator = page.locator(selector).first
                if await locator.count():
                    await locator.click(timeout=1500)
                    await page.wait_for_timeout(700)
                    return
            except Exception:
                continue
        try:
            await page.keyboard.press("Escape")
            await page.wait_for_timeout(500)
        except Exception:
            return

    async def _scroll_review_container(self, page) -> None:
        await page.evaluate(
            """() => {
                const candidates = [...document.querySelectorAll('div')]
                    .filter((el) => el.scrollHeight > el.clientHeight + 120)
                    .sort((a, b) => (b.scrollHeight - b.clientHeight) - (a.scrollHeight - a.clientHeight));
                const target = candidates[0] || document.scrollingElement || document.body;
                target.scrollTop = Math.min(target.scrollTop + 1100, target.scrollHeight);
            }"""
        )

    def _utc_timestamp(self) -> str:
        from datetime import datetime

        return datetime.utcnow().isoformat()
