from __future__ import annotations

from django.core.management import call_command
from django.core.management.base import CommandError

from core.management.base import MonitoredBaseCommand
from products.models import ProductVariantFamily
from shopware.services import ShopwareVariantSyncService


class Command(MonitoredBaseCommand):
    help = "Leitet Shopware-Varianten aus bestehenden Django-Produktattributen ab."

    def add_arguments(self, parser):
        parser.add_argument(
            "families",
            nargs="*",
            help="Technische Schlüssel der Variantenfamilien. Ohne Angabe --all verwenden.",
        )
        parser.add_argument(
            "--all",
            action="store_true",
            help="Alle aktiven Variantenfamilien verarbeiten.",
        )
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Schreibt Parent, Variantenoptionen und Kindzuordnungen nach Shopware.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Erzwingt einen reinen Prüfbericht ohne Shopware-Änderung (Standard ohne --apply).",
        )
        parser.add_argument(
            "--skip-product-sync",
            action="store_true",
            help="Beim Apply den normalen Django-zu-Shopware-Produktsync der Variantenkinder überspringen.",
        )

    def handle(self, *args, **options):
        families = self._families(options)
        apply_changes = bool(options["apply"]) and not bool(options["dry_run"])
        service = ShopwareVariantSyncService()

        resolutions = {family.pk: service.preview(family) for family in families}
        self._write_preview(resolutions.values())
        # A family without axes is a valid cleanup operation: its former child
        # products and configurator settings need to be detached in Shopware.
        invalid = [
            resolution
            for resolution in resolutions.values()
            if not resolution.is_valid and resolution.attributes
        ]
        if invalid:
            raise CommandError("Varianten-Prüfung fehlgeschlagen. Shopware wurde nicht verändert.")
        if not apply_changes:
            self.stdout.write(self.style.SUCCESS("Dry-Run erfolgreich. Für Änderungen erneut mit --apply starten."))
            return

        for family in families:
            resolution = resolutions[family.pk]
            if not options["skip_product_sync"] and resolution.variants:
                erp_nrs = [variant.product.erp_nr for variant in resolution.variants]
                call_command("shopware_sync_products", *erp_nrs, skip_images=True)
            result = service.sync(family, dry_run=False)
            if result.errors:
                raise CommandError("; ".join(result.errors))
            self.stdout.write(
                self.style.SUCCESS(
                    f"{family.slug}: Parent={result.parent_id}, Varianten={result.variant_count}, "
                    f"übersprungen={result.skipped_count}, gelöst={result.detached_count}."
                )
            )

    @staticmethod
    def _families(options) -> list[ProductVariantFamily]:
        slugs = sorted({str(slug).strip() for slug in options["families"] if str(slug).strip()})
        if not slugs and not options["all"]:
            raise CommandError("Variantenfamilie angeben oder --all verwenden.")
        queryset = ProductVariantFamily.objects.select_related("target_category", "default_product")
        if slugs:
            families = list(queryset.filter(slug__in=slugs).order_by("name", "id"))
            found = {family.slug for family in families}
            missing = sorted(set(slugs) - found)
            if missing:
                raise CommandError("Unbekannte Variantenfamilie(n): " + ", ".join(missing))
            return families
        return list(queryset.filter(is_active=True).order_by("name", "id"))

    def _write_preview(self, resolutions) -> None:
        for resolution in resolutions:
            if not resolution.attributes:
                self.stdout.write(f"{resolution.family.slug}: Keine Variantenattribute — Shopware-Cleanup.")
                continue
            self.stdout.write(
                f"{resolution.family.slug}: Varianten={len(resolution.variants)}, "
                f"übersprungen={len(resolution.skipped)}, Fehler={len(resolution.errors)}"
            )
            for skipped in resolution.skipped:
                self.stdout.write(f"  ÜBERSPRUNGEN {skipped.product.erp_nr}: {skipped.reason}")
            for error in resolution.errors:
                self.stdout.write(self.style.ERROR(f"  FEHLER: {error}"))
