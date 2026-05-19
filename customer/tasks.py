from __future__ import annotations

from celery import shared_task
from django.core.management import call_command


@shared_task(name="customer.microtech_customer_upsert")
def microtech_customer_upsert(
    erp_nr: str = "",
    *,
    customer_id: int | None = None,
) -> None:
    args = [erp_nr.strip()] if erp_nr.strip() else []
    call_command("microtech_customer_upsert", *args, id=customer_id)


@shared_task(name="customer.microtech_customer_lookup")
def microtech_customer_lookup(erp_nr: str = "") -> None:
    cleaned_erp_nr = (erp_nr or "").strip()
    if not cleaned_erp_nr:
        raise ValueError("erp_nr is required.")
    call_command("microtech_customer_lookup", cleaned_erp_nr)
