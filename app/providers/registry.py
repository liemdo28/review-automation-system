from app.providers.base import ProviderConfigError
from app.providers.google_portal import GoogleReviewsPortalProvider
from app.providers.yelp import YelpReviewsProvider


PROVIDER_MAP = {
    "google": GoogleReviewsPortalProvider,
    "yelp": YelpReviewsProvider,
}


def get_provider(source, auth_session=None):
    provider_cls = PROVIDER_MAP.get((source.platform or "").lower())
    if not provider_cls:
        raise ProviderConfigError(
            f"Unsupported review platform: {source.platform}",
            details={"source_id": source.id, "platform": source.platform},
        )
    return provider_cls(source, auth_session=auth_session)
