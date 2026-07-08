from __future__ import annotations

from collections.abc import Sequence

from celery import shared_task
from django.core.management import call_command


def _clean_erp_nrs(erp_nrs: Sequence[str] | None) -> list[str]:
    return [str(erp_nr).strip() for erp_nr in (erp_nrs or []) if str(erp_nr).strip()]


@shared_task(name="shopware.shopware5_sync_products")
def shopware5_sync_products(
    erp_nrs: Sequence[str] | None = None,
    *,
    limit: int | None = None,
    batch_size: int = 50,
    active_only: bool = False,
) -> dict | None:
    command_args = _clean_erp_nrs(erp_nrs)
    command_options = {
        "limit": limit,
        "batch_size": batch_size,
        "active_only": active_only,
    }
    return call_command("shopware5_sync_products", *command_args, **command_options)
