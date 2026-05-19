from __future__ import annotations

from celery import shared_task
from django.core.management import call_command


@shared_task(name="mappei.scrape_daily_prices")
def scrape_daily_prices(
    *,
    product: str = "",
    limit: int | None = None,
    log_file: str = "",
) -> None:
    call_command(
        "scrape_mappei",
        product=(product or "").strip() or None,
        limit=limit,
        log_file=log_file,
    )
