from app.providers.page_provider import PageReviewProvider


class YelpReviewsProvider(PageReviewProvider):
    platform = "yelp"
    default_auth_required_selectors = [
        "[class*='captcha']",
        "[id*='captcha']",
    ]
    default_selectors = {
        "review_card": [
            "[data-review-id]",
            "[class*='review']",
        ],
        "reviewer_name": [
            "[data-testid*='user'] a",
            ".user-name a",
            "a[href*='/user_details']",
        ],
        "rating": [
            "[role='img'][aria-label]",
            "[aria-label*='star']",
        ],
        "review_text": [
            "p[lang]",
            "[class*='comment'] span[lang]",
            "[class*='review-content'] p",
        ],
        "review_date": [
            "time",
            "[class*='date']",
        ],
        "owner_reply_text": [
            "[class*='business-owner'] + div",
            "[class*='comment-from-business']",
        ],
        "owner_reply_date": [
            "[class*='business-owner'] time",
            "[class*='comment-from-business'] time",
        ],
        "load_more": [
            "button:has-text('more reviews')",
            "a:has-text('more reviews')",
        ],
    }
