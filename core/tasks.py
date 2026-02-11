from celery import shared_task
from django.core.management import call_command


@shared_task
def microtech_sync_all() -> None:
    call_command("microtech_sync_products", all=True)


@shared_task
def shopware_sync_all() -> None:
    call_command("shopware_sync_products", all=True)


@shared_task
def daily_microtech_shopware_sync() -> None:
    call_command("microtech_sync_products", all=True)
    call_command("shopware_sync_products", all=True)
