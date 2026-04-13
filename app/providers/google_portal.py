from app.providers.page_provider import PageReviewProvider


class GoogleReviewsPortalProvider(PageReviewProvider):
    platform = "google"
    default_auth_required_selectors = [
        "input[type='email']",
        "input[type='password']",
        "[data-view-id='signIn']",
    ]
    default_selectors = {
        "review_card": [
            "[data-review-id]",
            "[data-testid='review-card']",
            "[role='listitem']",
        ],
        "reviewer_name": [
            "[data-testid='reviewer-name']",
            "[class*='reviewer']",
            "h3",
        ],
        "rating": [
            "[aria-label*='star']",
            "[role='img'][aria-label]",
        ],
        "review_text": [
            "[data-testid='review-text']",
            "[class*='review-text']",
            "span",
        ],
        "review_date": [
            "time",
            "[data-testid='review-date']",
            "[class*='date']",
        ],
        "owner_reply_text": [
            "[data-testid='owner-reply-text']",
            "[class*='owner-reply']",
        ],
        "owner_reply_date": [
            "[data-testid='owner-reply-date']",
            "[class*='reply-date']",
        ],
        "load_more": [
            "button:has-text('More reviews')",
            "button:has-text('Load more')",
        ],
    }
