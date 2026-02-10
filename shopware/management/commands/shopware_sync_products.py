from __future__ import annotations

from django.contrib.admin.models import CHANGE, LogEntry
from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.core.management.base import BaseCommand, CommandError
from products.models import Product, Storage
from shopware.services import ProductService


def _get_admin_user_id() -> int | None:
    user = get_user_model().objects.filter(is_superuser=True).order_by("id").first()
    return user.id if user else None


def _log_admin_error(
    *,
    admin_user_id: int | None,
    content_type_id: int | None,
    message: str,
    object_id: str | None = None,
    object_repr: str = "Shopware Sync",
) -> None:
    if not admin_user_id or not content_type_id:
        return
    LogEntry.objects.log_action(
        user_id=admin_user_id,
        content_type_id=content_type_id,
        object_id=object_id,
        object_repr=object_repr[:200],
        action_flag=CHANGE,
        change_message=message,
    )


def _extract_first_id(payload: dict | None) -> str | None:
    if not isinstance(payload, dict):
        return None
    data = payload.get("data")
    if isinstance(data, list) and data:
        first = data[0]
        if isinstance(first, dict):
            return first.get("id")
    if isinstance(data, dict):
        return data.get("id")
    return None


class Command(BaseCommand):
    help = "Sync products from Django to Shopware6 (updates only)."

    def add_arguments(self, parser):
        parser.add_argument(
            "erp_nrs",
            nargs="*",
            help="ERP-Nummern (productNumber). Wenn leer, nutze --all.",
        )
        parser.add_argument(
            "--all",
            action="store_true",
            help="Alle Produkte synchronisieren.",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=None,
            help="Maximale Anzahl zu synchronisierender Produkte.",
        )

    def handle(self, *args, **options):
        erp_nrs = [nr.strip() for nr in options.get("erp_nrs") or [] if nr.strip()]
        sync_all = options.get("all", False)
        limit = options.get("limit")

        if not erp_nrs and not sync_all:
            raise CommandError("Bitte ERP-Nummern angeben oder --all verwenden.")

        qs = Product.objects.all() if sync_all else Product.objects.filter(erp_nr__in=erp_nrs)
        if limit:
            qs = qs[:limit]

        service = ProductService()
        admin_user_id = _get_admin_user_id()
        content_type_id = ContentType.objects.get_for_model(Product).id if admin_user_id else None

        for product in qs:
            try:
                if not product.sku:
                    result = service.get_by_number(product.erp_nr)
                    sku = _extract_first_id(result)
                    if not sku:
                        _log_admin_error(
                            admin_user_id=admin_user_id,
                            content_type_id=content_type_id,
                            message=f"Shopware SKU not found for productNumber {product.erp_nr}.",
                            object_id=str(product.pk),
                            object_repr=f"Product {product.erp_nr}",
                        )
                        continue
                    product.sku = sku
                    product.save(update_fields=["sku"])

                payload = {
                    "productNumber": product.erp_nr,
                    "active": product.is_active,
                }
                if product.name:
                    payload["name"] = product.name
                if product.description is not None:
                    payload["description"] = product.description
                try:
                    storage = product.storage
                except Storage.DoesNotExist:
                    storage = None
                if storage:
                    payload["stock"] = storage.get_stock

                service.update(product.sku, payload)
            except Exception as exc:
                _log_admin_error(
                    admin_user_id=admin_user_id,
                    content_type_id=content_type_id,
                    message=f"Shopware sync failed for {product.erp_nr}: {exc}",
                    object_id=str(product.pk),
                    object_repr=f"Product {product.erp_nr}",
                )
