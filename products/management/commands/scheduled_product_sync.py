from __future__ import annotations

from decimal import Decimal

from django.core.management import call_command
from django.core.management.base import BaseCommand
from django.db.models import Q
from django.utils import timezone

from microtech.services.artikel import MicrotechArtikelService
from microtech.services.connection import microtech_connection
from products.models import Price


class Command(BaseCommand):
    help = (
        "Scheduler command: sync products from Microtech to Django, clear expired specials, "
        "update Microtech specials, and sync everything to Shopware."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--limit",
            type=int,
            default=None,
            help="Optionales Limit fuer den Lauf (Debug/Test).",
        )
        parser.add_argument(
            "--exclude-inactive",
            action="store_true",
            help="Inaktive Microtech-Artikel beim Import ausschliessen.",
        )

    def handle(self, *args, **options):
        limit = options.get("limit")
        include_inactive = not options.get("exclude_inactive", False)

        self.stdout.write("1/4 Microtech -> Django import starten")
        call_command(
            "microtech_sync_products",
            all=True,
            include_inactive=include_inactive,
            preserve_is_active=True,
            limit=limit,
        )

        self.stdout.write("2/4 Abgelaufene Sonderpreise in Django bereinigen")
        expired_count, affected_product_ids = self._clear_expired_specials(now=timezone.now())
        self.stdout.write(
            f"Abgelaufene Sonderpreise bereinigt: {expired_count} Preiszeile(n), "
            f"{len(affected_product_ids)} Produkt(e)."
        )

        self.stdout.write("3/4 Microtech fuer abgelaufene Sonderpreise aktualisieren")
        updated_microtech = self._sync_expired_specials_to_microtech(affected_product_ids)
        self.stdout.write(f"Microtech aktualisiert: {updated_microtech} Produkt(e).")

        self.stdout.write("4/4 Django -> Shopware sync starten")
        call_command(
            "shopware_sync_products",
            all=True,
            limit=limit,
        )
        self.stdout.write(self.style.SUCCESS("Scheduled Product Sync erfolgreich abgeschlossen."))

    @staticmethod
    def _clear_expired_specials(*, now):
        expired_filter = Q(special_percentage__isnull=False) | Q(special_price__isnull=False)
        expired_qs = Price.objects.filter(special_end_date__lt=now).filter(expired_filter)
        affected_product_ids = set(expired_qs.values_list("product_id", flat=True))
        updated = expired_qs.update(
            special_percentage=None,
            special_price=None,
            special_start_date=None,
            special_end_date=None,
        )
        return updated, affected_product_ids

    def _sync_expired_specials_to_microtech(self, affected_product_ids: set[int]) -> int:
        if not affected_product_ids:
            return 0

        default_prices = (
            Price.objects.select_related("product")
            .filter(
                product_id__in=affected_product_ids,
                sales_channel__is_default=True,
            )
            .order_by("product_id")
        )
        if not default_prices.exists():
            return 0

        updated = 0
        with microtech_connection() as erp:
            artikel_service = MicrotechArtikelService(erp=erp)
            for price in default_prices:
                erp_nr = str(price.product.erp_nr or "").strip()
                if not erp_nr:
                    continue
                if not artikel_service.find(erp_nr):
                    continue

                artikel_service.edit()
                artikel_service.set_field("Vk0.Preis", self._format_decimal(price.price))
                artikel_service.set_field("Vk0.SPr", "")
                artikel_service.set_field("Vk0.SVonDat", "")
                artikel_service.set_field("Vk0.SBisDat", "")
                artikel_service.post()
                updated += 1

        return updated

    @staticmethod
    def _format_decimal(value: Decimal | None) -> str:
        if value is None:
            return ""
        return format(value.quantize(Decimal("0.01")), "f")

