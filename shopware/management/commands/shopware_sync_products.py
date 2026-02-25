from __future__ import annotations

import hashlib
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.core.management.base import BaseCommand, CommandError
from core.admin_utils import log_admin_change
from products.models import Price, Product, Storage
from shopware.models import ShopwareSettings
from shopware.services import ProductService

DEFAULT_TAX_ID = "d391e13bdd95404a885f4ad28ea218e0"
REDUCED_TAX_ID = "be66a53eae3a49829f4a8c5959535501"


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
    log_admin_change(
        user_id=admin_user_id,
        content_type_id=content_type_id,
        object_id=object_id,
        object_repr=object_repr[:200],
        message=message,
    )


def _price_id(product_id: str, rule_id: str, suffix: str) -> str:
    return hashlib.md5(f"{product_id}-{rule_id}-{suffix}".encode("utf-8")).hexdigest()


def _build_standard_price(price: Price, currency_id: str) -> dict:
    return {
        "currencyId": currency_id,
        "gross": price.get_standard_brutto_price(as_float=True),
        "net": price.get_standard_price(as_float=True),
        "linked": True,
    }


def _build_base_price(price: Price, currency_id: str, rule_id: str) -> list[dict]:
    price_payload = {
        "currencyId": currency_id,
        "gross": price.get_current_brutto_price(as_float=True),
        "net": price.get_current_price(as_float=True),
        "linked": True,
        "isSpecialActive": price.is_special_active,
        "ruleId": rule_id,
    }
    if price.is_special_active:
        price_payload["listPrice"] = _build_standard_price(price, currency_id)
    return [price_payload]


def _build_prices_for_channel(product: Product, channel: ShopwareSettings, price: Price) -> list[dict]:
    rule_id = channel.rule_id_price
    currency_id = channel.currency_id
    if not rule_id or not currency_id:
        return []

    standard_price = _build_standard_price(price, currency_id)

    if price.is_special_active:
        return [
            {
                "id": _price_id(product.sku, rule_id, "special"),
                "productId": product.sku,
                "ruleId": rule_id,
                "quantityStart": 1,
                "quantityEnd": None,
                "price": [
                    {
                        "currencyId": currency_id,
                        "gross": price.get_special_brutto_price(as_float=True),
                        "net": price.get_special_price(as_float=True),
                        "linked": True,
                        "listPrice": standard_price,
                    }
                ],
            }
        ]

    if price.rebate_price and price.rebate_quantity:
        if price.rebate_quantity <= 1:
            return [
                {
                    "id": _price_id(product.sku, rule_id, "rebate"),
                    "productId": product.sku,
                    "ruleId": rule_id,
                    "quantityStart": 1,
                    "quantityEnd": None,
                    "price": [
                        {
                            "currencyId": currency_id,
                            "gross": price.get_rebate_brutto_price(as_float=True),
                            "net": price.get_rebate_price(as_float=True),
                            "linked": True,
                        }
                    ],
                }
            ]

        return [
            {
                "id": _price_id(product.sku, rule_id, "standard"),
                "productId": product.sku,
                "ruleId": rule_id,
                "quantityStart": 1,
                "quantityEnd": price.rebate_quantity - 1,
                "price": [standard_price],
            },
            {
                "id": _price_id(product.sku, rule_id, f"rebate-{price.rebate_quantity}"),
                "productId": product.sku,
                "ruleId": rule_id,
                "quantityStart": price.rebate_quantity,
                "quantityEnd": None,
                "price": [
                    {
                        "currencyId": currency_id,
                        "gross": price.get_rebate_brutto_price(as_float=True),
                        "net": price.get_rebate_price(as_float=True),
                        "linked": True,
                    }
                ],
            },
        ]

    return [
        {
            "id": _price_id(product.sku, rule_id, "standard"),
            "productId": product.sku,
            "ruleId": rule_id,
            "quantityStart": 1,
            "quantityEnd": None,
            "price": [standard_price],
        }
    ]


def _resolve_tax_id(product: Product) -> str:
    tax = getattr(product, "tax", None)
    if tax and tax.shopware_id:
        return str(tax.shopware_id).strip()
    if tax and tax.rate is not None and Decimal(tax.rate).quantize(Decimal("0.01")) == Decimal("7.00"):
        return REDUCED_TAX_ID
    return DEFAULT_TAX_ID


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
        parser.add_argument(
            "--batch-size",
            type=int,
            default=50,
            help="Batch-Groesse fuer Shopware6 Sync (Default: 50).",
        )

    def handle(self, *args, **options):
        erp_nrs = [nr.strip() for nr in options.get("erp_nrs") or [] if nr.strip()]
        sync_all = options.get("all", False)
        limit = options.get("limit")
        batch_size = options.get("batch_size") or 50

        if not erp_nrs and not sync_all:
            raise CommandError("Bitte ERP-Nummern angeben oder --all verwenden.")

        qs = Product.objects.select_related("tax").all() if sync_all else Product.objects.select_related("tax").filter(erp_nr__in=erp_nrs)
        qs = qs.only("id", "erp_nr", "sku", "name", "description", "is_active", "tax_id", "tax__shopware_id")
        if limit:
            qs = qs[:limit]

        service = ProductService()
        admin_user_id = _get_admin_user_id()
        content_type_id = ContentType.objects.get_for_model(Product).id if admin_user_id else None
        channels = list(ShopwareSettings.objects.filter(is_active=True))
        default_channel = next((ch for ch in channels if ch.is_default), None)

        products = list(qs)
        for offset in range(0, len(products), batch_size):
            batch = products[offset : offset + batch_size]
            missing = [p.erp_nr for p in batch if not p.sku]
            sku_map = service.get_sku_map(missing) if missing else {}

            payloads = []
            payload_products: list[Product] = []
            fallback_products: list[Product] = []
            for product in batch:
                effective_sku = product.sku
                if not effective_sku:
                    resolved_sku = sku_map.get(product.erp_nr)
                    if resolved_sku:
                        effective_sku = resolved_sku
                        product.sku = resolved_sku
                        product.save(update_fields=["sku"])

                prices_by_channel = {
                    price.sales_channel_id: price
                    for price in product.prices.select_related("sales_channel").all()
                    if price.sales_channel_id
                }
                payload = {
                    "productNumber": product.erp_nr,
                    "active": product.is_active,
                    "taxId": _resolve_tax_id(product),
                }
                if effective_sku:
                    payload["id"] = effective_sku
                else:
                    fallback_products.append(product)
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

                if default_channel:
                    default_price = prices_by_channel.get(default_channel.id)
                    if default_price:
                        if default_channel.currency_id and default_channel.rule_id_price:
                            payload["price"] = _build_base_price(
                                default_price,
                                default_channel.currency_id,
                                default_channel.rule_id_price,
                            )
                        else:
                            _log_admin_error(
                                admin_user_id=admin_user_id,
                                content_type_id=content_type_id,
                                message=(
                                    f"Sales-Channel {default_channel.name} fehlt currency_id oder rule_id_price. "
                                    "Preis-Update übersprungen."
                                ),
                                object_id=str(product.pk),
                                object_repr=f"Product {product.erp_nr}",
                            )
                    else:
                        _log_admin_error(
                            admin_user_id=admin_user_id,
                            content_type_id=content_type_id,
                            message=f"Kein Preis für Default-Sales-Channel bei Produkt {product.erp_nr}.",
                            object_id=str(product.pk),
                            object_repr=f"Product {product.erp_nr}",
                        )

                prices_payload = []
                if effective_sku:
                    for channel in channels:
                        price = prices_by_channel.get(channel.id)
                        if not price:
                            _log_admin_error(
                                admin_user_id=admin_user_id,
                                content_type_id=content_type_id,
                                message=f"Kein Preis für Sales-Channel {channel.name} bei Produkt {product.erp_nr}.",
                                object_id=str(product.pk),
                                object_repr=f"Product {product.erp_nr}",
                            )
                            continue
                        if not channel.rule_id_price or not channel.currency_id:
                            _log_admin_error(
                                admin_user_id=admin_user_id,
                                content_type_id=content_type_id,
                                message=f"Sales-Channel {channel.name} fehlt rule_id_price oder currency_id.",
                                object_id=str(product.pk),
                                object_repr=f"Product {product.erp_nr}",
                            )
                            continue
                        prices_payload.extend(_build_prices_for_channel(product, channel, price))
                elif channels:
                    _log_admin_error(
                        admin_user_id=admin_user_id,
                        content_type_id=content_type_id,
                        message=(
                            f"Advanced prices for product {product.erp_nr} übersprungen, "
                            "da SKU im Fallback-Upsert noch nicht vorhanden war."
                        ),
                        object_id=str(product.pk),
                        object_repr=f"Product {product.erp_nr}",
                    )

                if prices_payload:
                    payload["prices"] = prices_payload
                payloads.append(payload)
                payload_products.append(product)

            if not payloads:
                continue

            try:
                cleanup_product_ids = [str(payload.get("id")).strip() for payload in payloads if payload.get("id")]
                cleanup_rule_ids = [str(channel.rule_id_price).strip() for channel in channels if channel.rule_id_price]
                if cleanup_product_ids and cleanup_rule_ids:
                    service.purge_product_prices_by_product_and_rule(
                        product_ids=cleanup_product_ids,
                        rule_ids=cleanup_rule_ids,
                    )
                service.bulk_upsert(payloads)
                if fallback_products:
                    refreshed_map = service.get_sku_map([product.erp_nr for product in fallback_products])
                    for product in fallback_products:
                        resolved_sku = refreshed_map.get(product.erp_nr)
                        if resolved_sku:
                            product.sku = resolved_sku
                            product.save(update_fields=["sku"])
                            continue
                        _log_admin_error(
                            admin_user_id=admin_user_id,
                            content_type_id=content_type_id,
                            message=(
                                f"Shopware SKU konnte nach Fallback-Upsert nicht aufgeloest werden "
                                f"fuer productNumber {product.erp_nr}."
                            ),
                            object_id=str(product.pk),
                            object_repr=f"Product {product.erp_nr}",
                        )
            except Exception as exc:
                for product in payload_products:
                    _log_admin_error(
                        admin_user_id=admin_user_id,
                        content_type_id=content_type_id,
                        message=f"Shopware bulk sync failed for {product.erp_nr}: {exc}",
                        object_id=str(product.pk),
                        object_repr=f"Product {product.erp_nr}",
                    )
