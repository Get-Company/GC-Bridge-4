from __future__ import annotations

import logging
from typing import Any

from django.core.management.base import BaseCommand, CommandError
from microtech.services import microtech_connection
from products.models import Price, Product
from shopware.models import ShopwareSettings

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Update ONLY product prices in Microtech via GraphQL API using Django data."

    def add_arguments(self, parser):
        parser.add_argument(
            "erp_nrs",
            nargs="*",
            help="Liste von ERP-Nummern (ArtNr).",
        )
        parser.add_argument(
            "--from",
            dest="range_from",
            help="Start einer numerischen ERP-Range (inklusive).",
        )
        parser.add_argument(
            "--to",
            dest="range_to",
            help="Ende einer numerischen ERP-Range (inklusive).",
        )

    def handle(self, *args, **options):
        erp_nrs = options.get("erp_nrs") or []
        range_from = options.get("range_from")
        range_to = options.get("range_to")

        if range_from and range_to:
            erp_nrs.extend(self._generate_range(range_from, range_to))

        if not erp_nrs:
            raise CommandError("Bitte ERP-Nummern oder eine Range (--from und --to) angeben.")

        # De-duplicate while preserving order
        seen = set()
        unique_erp_nrs = [nr for nr in erp_nrs if not (nr in seen or seen.add(nr))]

        with microtech_connection() as erp:
            for erp_nr in unique_erp_nrs:
                try:
                    product = Product.objects.get(erp_nr=erp_nr)
                    input_data = self._get_price_data(product)
                    
                    if not input_data:
                        self.stdout.write(f"Skipping {erp_nr}: No price data found in default channel.")
                        continue

                    self.stdout.write(f"Updating prices for {erp_nr} in Microtech...")
                    result = erp.update_product(erp_nr, input_data)

                    if result.get("status") == "error" or result.get("errorMessage"):
                        msg = result.get("errorMessage") or result.get("message") or "Unknown error"
                        self.stderr.write(self.style.ERROR(f"Error updating {erp_nr}: {msg}"))
                    else:
                        self.stdout.write(self.style.SUCCESS(f"Successfully updated prices for {erp_nr}."))

                except Product.DoesNotExist:
                    self.stderr.write(self.style.ERROR(f"Product {erp_nr} not found in Django."))
                except Exception as e:
                    self.stderr.write(self.style.ERROR(f"Failed to update {erp_nr}: {str(e)}"))

    def _generate_range(self, start: str, end: str) -> list[str]:
        """Generate a list of ERP strings from a numeric range, preserving leading zeros."""
        try:
            start_int = int(start)
            end_int = int(end)
            if start_int > end_int:
                raise ValueError("Start must be less than or equal to end.")
            
            # Determine padding from the start string if it has leading zeros
            padding = len(start) if start.startswith("0") else 0
            
            return [str(i).zfill(padding) for i in range(start_int, end_int + 1)]
        except ValueError as e:
            raise CommandError(f"Ungueltige Range-Parameter: {e}")

    def _get_price_data(self, product: Product) -> dict[str, Any]:
        """Get only price-related fields for UpdateProductInput."""
        default_channel = ShopwareSettings.objects.filter(is_active=True, is_default=True).first()
        if not default_channel:
            return {}

        price_entry = Price.objects.filter(product=product, sales_channel=default_channel).first()
        if not price_entry:
            return {}

        return {
            "price": str(price_entry.price),
            "rebate_quantity": price_entry.rebate_quantity,
            "rebate_price": str(price_entry.rebate_price) if price_entry.rebate_price else None,
        }
