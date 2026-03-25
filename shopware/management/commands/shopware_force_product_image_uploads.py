from __future__ import annotations

from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError

from products.models import Product


class Command(BaseCommand):
    help = (
        "Setzt die gespeicherten Shopware-Bild-Hashes zurueck und stoesst danach "
        "einen erneuten Upload der Produktbilder an."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "erp_nrs",
            nargs="*",
            help="ERP-Nummern (productNumber). Wenn leer, nutze --all.",
        )
        parser.add_argument(
            "--all",
            action="store_true",
            help="Alle Produktbilder erneut nach Shopware hochladen.",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=None,
            help="Optionales Limit fuer den anschliessenden Shopware-Sync.",
        )
        parser.add_argument(
            "--batch-size",
            type=int,
            default=50,
            help="Batch-Groesse fuer den anschliessenden Shopware-Sync (Default: 50).",
        )
        parser.add_argument(
            "--only-with-images",
            action="store_true",
            help="Nur Produkte mit mindestens einem Bild zuruecksetzen und synchronisieren.",
        )
        parser.add_argument(
            "--log-images",
            action="store_true",
            help="Aktiviert aussagekraeftige Batch- und Produktlogs fuer den Bild-Sync.",
        )

    def handle(self, *args, **options):
        erp_nrs = [nr.strip() for nr in options.get("erp_nrs") or [] if nr.strip()]
        sync_all = options.get("all", False)
        limit = options.get("limit")
        batch_size = options.get("batch_size") or 50
        only_with_images = options.get("only_with_images", False)
        log_images = options.get("log_images", False)

        if not erp_nrs and not sync_all:
            raise CommandError("Bitte ERP-Nummern angeben oder --all verwenden.")

        queryset = Product.objects.all() if sync_all else Product.objects.filter(erp_nr__in=erp_nrs)
        if only_with_images:
            queryset = queryset.filter(product_images__isnull=False).distinct()
        reset_count = queryset.exclude(shopware_image_sync_hash="").update(shopware_image_sync_hash="")

        self.stdout.write(f"Shopware Bild-Hashes zurueckgesetzt: {reset_count} Produkt(e).")
        self.stdout.write("Starte erneuten Produktbild-Upload nach Shopware...")

        if sync_all:
            call_command(
                "shopware_sync_products",
                all=True,
                limit=limit,
                batch_size=batch_size,
                only_with_images=only_with_images,
                log_images=log_images,
            )
        else:
            call_command(
                "shopware_sync_products",
                *erp_nrs,
                limit=limit,
                batch_size=batch_size,
                only_with_images=only_with_images,
                log_images=log_images,
            )

        self.stdout.write(self.style.SUCCESS("Produktbild-Upload abgeschlossen."))
