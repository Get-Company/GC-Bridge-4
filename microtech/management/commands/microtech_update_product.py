from __future__ import annotations

import logging
from decimal import Decimal
from typing import Any

from django.core.management.base import BaseCommand
from microtech.services import microtech_connection
from products.models import Price, Product
from shopware.models import ShopwareSettings

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Update product(s) in Microtech via GraphQL API using Django data."

    def add_arguments(self, parser):
        parser.add_argument(
            "erp_nrs",
            nargs="+",
            help="ERP-Nummern (ArtNr) der zu aktualisierenden Produkte.",
        )

    def handle(self, *args, **options):
        erp_nrs = options["erp_nrs"]

        with microtech_connection() as erp:
            for erp_nr in erp_nrs:
                try:
                    product = Product.objects.get(erp_nr=erp_nr)
                    self.stdout.write(f"Updating product {erp_nr} in Microtech...")

                    input_data = self._build_input_data(product)
                    result = erp.update_product(erp_nr, input_data)

                    if result.get("status") == "error" or result.get("errorMessage"):
                        msg = result.get("errorMessage") or result.get("message") or "Unknown error"
                        self.stderr.write(self.style.ERROR(f"Error updating {erp_nr}: {msg}"))
                    else:
                        self.stdout.write(self.style.SUCCESS(f"Successfully updated {erp_nr} in Microtech."))

                except Product.DoesNotExist:
                    self.stderr.write(self.style.ERROR(f"Product {erp_nr} not found in Django."))
                except Exception as e:
                    self.stderr.write(self.style.ERROR(f"Failed to update {erp_nr}: {str(e)}"))

    def _build_input_data(self, product: Product) -> dict[str, Any]:
        # Get default sales channel for prices
        default_channel = ShopwareSettings.objects.filter(is_active=True, is_default=True).first()
        price_entry = None
        if default_channel:
            price_entry = Price.objects.filter(product=product, sales_channel=default_channel).first()

        input_data = {
            "name": product.name or "",
            "description": product.description or "",
            "description_short": product.description_short or "",
            "is_active": product.is_active,
            "factor": product.factor,
            "unit": product.unit or "",
            "min_purchase": product.min_purchase,
            "purchase_unit": product.purchase_unit,
            "sort_order": product.sort_order,
        }

        if product.tax:
            # Map tax rate to common Microtech keys
            rate = product.tax.rate
            if rate == Decimal("19.00"):
                input_data["tax_key"] = "M19"
            elif rate == Decimal("7.00"):
                input_data["tax_key"] = "M7"
            else:
                input_data["tax_key"] = product.tax.name

        if price_entry:
            input_data.update({
                "price": str(price_entry.price),
                "rebate_quantity": price_entry.rebate_quantity,
                "rebate_price": str(price_entry.rebate_price) if price_entry.rebate_price else None,
                "special_price": str(price_entry.special_price) if price_entry.special_price else None,
                "special_start_date": price_entry.special_start_date.isoformat() if price_entry.special_start_date else None,
                "special_end_date": price_entry.special_end_date.isoformat() if price_entry.special_end_date else None,
            })

        # Remove None values to avoid sending them if not explicitly needed,
        # but keep empty strings if that's the intent.
        return {k: v for k, v in input_data.items() if v is not None}
