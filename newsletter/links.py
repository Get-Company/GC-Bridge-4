"""Links to the Shopware newsletter management form."""
from urllib.parse import urlencode, urlsplit, urlunsplit

from django.conf import settings


def unsubscribe_url(email: str = "") -> str:
    # The fragment is consumed by the Shopware form, never by an unsubscribe GET.
    # It also keeps personal form data out of shared page caches and server logs.
    base = getattr(settings, "NEWSLETTER_MANAGEMENT_URL", "") or (
        settings.NEWSLETTER_STOREFRONT_URL.rstrip("/") + "/Newsletter/"
    )
    parts = urlsplit(base)
    if parts.scheme not in {"http", "https"} or not parts.netloc:
        raise ValueError("Die Newsletter-Verwaltungsseite muss eine vollständige HTTP(S)-URL sein.")
    return urlunsplit((parts.scheme, parts.netloc, parts.path, parts.query,
                      urlencode({"option": "unsubscribe", "email": email or ""})))
