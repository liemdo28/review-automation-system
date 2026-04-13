"""Yelp review scraper using Playwright with stealth plugin."""
import asyncio
import logging
import random
import re
from datetime import datetime, timedelta

logger = logging.getLogger("review_system.yelp_scraper")


def parse_date(date_str: str) -> str | None:
    """Convert Yelp date strings to ISO format."""
    if not date_str:
        return None

    date_str = date_str.strip()
    now = datetime.utcnow()

    # Relative dates: "2 days ago", "1 week ago", etc.
    rel = re.match(r"(\d+)\s+(second|minute|hour|day|week|month|year)s?\s+ago", date_str, re.I)
    if rel:
        n = int(rel.group(1))
        unit = rel.group(2).lower()
        deltas = {
            "second": timedelta(seconds=n),
            "minute": timedelta(minutes=n),
            "hour": timedelta(hours=n),
            "day": timedelta(days=n),
            "week": timedelta(weeks=n),
            "month": timedelta(days=n * 30),
            "year": timedelta(days=n * 365),
        }
        return (now - deltas.get(unit, timedelta())).strftime("%Y-%m-%d")

    # Absolute dates: "March 15, 2024" or "3/15/2024"
    for fmt in ("%B %d, %Y", "%b %d, %Y", "%m/%d/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(date_str, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue

    return None


def parse_rating(element_text: str) -> int:
    """Extract star rating from Yelp element text/attributes."""
    # "5 star rating" or "5.0 star rating"
    m = re.search(r"(\d+(?:\.\d+)?)\s*star", element_text, re.I)
    if m:
        return round(float(m.group(1)))
    return 0


async def scrape_yelp_reviews(
    url: str,
    max_reviews: int = 20,
    business_name: str = "",
    location_name: str = "",
) -> tuple[list[dict], dict]:
    """Scrape reviews from a Yelp business page using Playwright stealth."""
    from playwright.async_api import async_playwright
    from playwright_stealth import stealth_async

    reviews = []
    stats = {"total_found": 0, "errors": 0, "captcha_detected": False}

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/122.0.0.0 Safari/537.36"
                ),
                viewport={"width": 1920, "height": 1080},
            )
            page = await context.new_page()
            await stealth_async(page)

            logger.info(f"Navigating to {url}")
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            await asyncio.sleep(random.uniform(2, 4))

            # Check for CAPTCHA
            captcha = await page.query_selector("[class*='captcha'], [id*='captcha']")
            if captcha:
                stats["captcha_detected"] = True
                logger.warning("CAPTCHA detected, aborting scrape")
                await browser.close()
                return reviews, stats

            # Dismiss popups
            for selector in ["button:has-text('Accept')", "button:has-text('Close')", "[aria-label='Close']"]:
                try:
                    btn = await page.query_selector(selector)
                    if btn:
                        await btn.click()
                        await asyncio.sleep(0.5)
                except Exception:
                    pass

            # Scroll to load reviews
            for _ in range(min(max_reviews // 5, 10)):
                await page.evaluate("window.scrollBy(0, 800)")
                await asyncio.sleep(random.uniform(0.8, 1.5))

                # Click "Load more" if available
                try:
                    load_more = await page.query_selector(
                        "button:has-text('more reviews'), a:has-text('more reviews')"
                    )
                    if load_more:
                        await load_more.click()
                        await asyncio.sleep(random.uniform(1, 2))
                except Exception:
                    pass

            # Extract reviews
            review_elements = await page.query_selector_all("[data-review-id], .review, [class*='review__']")
            stats["total_found"] = len(review_elements)
            logger.info(f"Found {len(review_elements)} review elements")

            for i, elem in enumerate(review_elements[:max_reviews]):
                try:
                    review = await _extract_review(page, elem, i)
                    if review and review.get("rating", 0) > 0:
                        reviews.append(review)
                except Exception as e:
                    stats["errors"] += 1
                    logger.debug(f"Error extracting review {i}: {e}")

            await browser.close()

    except Exception as e:
        logger.error(f"Yelp scrape failed: {e}")
        stats["errors"] += 1

    logger.info(f"Scraped {len(reviews)} valid reviews from {url}")
    return reviews, stats


async def _extract_review(page, elem, index: int) -> dict | None:
    """Extract data from a single review element."""
    review = {
        "id": "",
        "reviewer_name": "Anonymous",
        "rating": 0,
        "text": "",
        "date": None,
    }

    # ID
    review_id = await elem.get_attribute("data-review-id")
    review["id"] = review_id or f"yelp-review-{index}"

    # Rating - try multiple strategies
    for selector in [
        "[aria-label*='star']",
        "[class*='star']",
        "[role='img'][aria-label]",
    ]:
        try:
            rating_elem = await elem.query_selector(selector)
            if rating_elem:
                aria = await rating_elem.get_attribute("aria-label") or ""
                rating = parse_rating(aria)
                if rating > 0:
                    review["rating"] = rating
                    break
        except Exception:
            continue

    # Reviewer name
    for selector in [
        "[class*='user-passport'] a",
        "[data-testid*='user'] a",
        "a[href*='/user_details']",
        ".user-name a",
    ]:
        try:
            name_elem = await elem.query_selector(selector)
            if name_elem:
                name = (await name_elem.inner_text()).strip()
                if name:
                    review["reviewer_name"] = name
                    break
        except Exception:
            continue

    # Review text
    for selector in [
        "[class*='comment'] span[lang]",
        "[class*='review-content'] p",
        "p[lang]",
        ".review-content",
    ]:
        try:
            text_elem = await elem.query_selector(selector)
            if text_elem:
                text = (await text_elem.inner_text()).strip()
                if text:
                    review["text"] = text
                    break
        except Exception:
            continue

    # Date
    for selector in [
        "[class*='date']",
        "time",
        "span[class*='responsive-hidden']",
    ]:
        try:
            date_elem = await elem.query_selector(selector)
            if date_elem:
                date_text = (await date_elem.inner_text()).strip()
                parsed = parse_date(date_text)
                if parsed:
                    review["date"] = parsed
                    break
        except Exception:
            continue

    return review
