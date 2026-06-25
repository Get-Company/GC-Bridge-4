from __future__ import annotations

from celery import shared_task
from django.core.management import call_command


@shared_task(name="newsletter.shopware_sync_recipients")
def shopware_sync_recipients(
    *,
    limit: int | None = None,
    page_size: int = 100,
    status: str = "",
    email: str = "",
    mark_missing: bool = False,
) -> None:
    call_command(
        "shopware_sync_newsletter_recipients",
        limit=limit,
        page_size=page_size,
        status=status,
        email=email,
        mark_missing=mark_missing,
    )
