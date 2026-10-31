from __future__ import annotations

from django.core.management.base import CommandError
from django.db.models import Prefetch

from core.management.base import MonitoredBaseCommand
from products.models import Product, ProductImage
from shopware.services.product import ProductService
from shopware.services.product_media import ProductMediaSyncService


class Command(MonitoredBaseCommand):
    help = "Prueft WebP-Produktbilder und entfernt danach alte JPG/PNG-Produktbilder."

    def add_arguments(self, parser):
        parser.add_argument("erp_nrs", nargs="*", help="ERP-Nummern; ohne Angabe alle Produkte mit Bildern.")
        parser.add_argument("--limit", type=int, default=None)
        parser.add_argument("--apply", action="store_true", help="Alte Produktbild-Zuordnungen wirklich entfernen.")
        parser.add_argument(
            "--delete-orphans", action="store_true",
            help="Auch alte Bridge-Mediendateien ohne weitere Produktzuordnung entfernen (nur mit --apply).",
        )

    def handle(self, *args, **options):
        if options.get("delete_orphans") and not options.get("apply"):
            raise CommandError("--delete-orphans erfordert --apply.")
        erp_nrs = [str(value).strip() for value in options.get("erp_nrs") or [] if str(value).strip()]
        queryset = Product.objects.filter(product_images__isnull=False).distinct()
        if erp_nrs:
            queryset = queryset.filter(erp_nr__in=erp_nrs)
        queryset = queryset.order_by("erp_nr", "id").prefetch_related(
            Prefetch(
                "product_images",
                queryset=ProductImage.objects.select_related("image").order_by("order", "id"),
                to_attr="ordered_product_images",
            )
        )
        if options.get("limit"):
            queryset = queryset[: options["limit"]]

        service = ProductService()
        media_service = ProductMediaSyncService()
        eligible = skipped = removed_relations = removed_media = 0
        for product in queryset:
            try:
                current_relations, _, _ = media_service.get_product_media_payload(product=product, product_id=product.sku)
                if not product.sku or not current_relations:
                    raise ValueError("Keine Shopware-ID oder keine Produktbilder")
                if product.shopware_image_sync_hash != media_service.build_media_sync_hash(product=product):
                    raise ValueError("WebP-Sync-Hash ist nicht aktuell")

                actual_rows = service.find_product_media_rows_by_product_ids(product_ids=[product.sku])
                actual_relation_ids = {row["id"] for row in actual_rows}
                expected_relation_ids = {row["id"] for row in current_relations}
                if not expected_relation_ids.issubset(actual_relation_ids):
                    raise ValueError("WebP-Produktzuordnungen sind unvollstaendig")

                remote_product = service.get(product.sku)
                remote_data = (remote_product or {}).get("data") or remote_product or {}
                if isinstance(remote_data, list):
                    remote_data = remote_data[0] if remote_data else {}
                if service._entity_field(remote_data, "coverId") != current_relations[0]["id"]:
                    raise ValueError("Shopware-Titelbild ist noch nicht WebP")

                expected_media_ids = [row["mediaId"] for row in current_relations]
                metadata = service.find_media_by_ids(media_ids=expected_media_ids)
                if any(metadata.get(media_id, {}).get("extension") != "webp" for media_id in expected_media_ids):
                    raise ValueError("Mindestens eine WebP-Mediendatei fehlt")

                legacy_ids = {
                    media_service.build_media_id(relation.image.path)
                    for relation in product.get_ordered_product_images() if relation.image
                }
                legacy_rows = [row for row in actual_rows if row["media_id"] in legacy_ids]
                old_metadata = service.find_media_by_ids(media_ids=[row["media_id"] for row in legacy_rows])
                if any(old_metadata.get(row["media_id"], {}).get("extension") not in {"jpg", "jpeg", "png"}
                       for row in legacy_rows):
                    raise ValueError("Altes Medium fehlt oder hat ein anderes Format")

                eligible += 1
                self.stdout.write(f"{product.erp_nr}: {len(legacy_rows)} alte Bildzuordnung(en) gefunden.")
                if not options.get("apply"):
                    continue
                for row in legacy_rows:
                    service.request_delete(f"{service.product_media_base_path}/{row['id']}")
                    removed_relations += 1
                if options.get("delete_orphans"):
                    for media_id in sorted({row["media_id"] for row in legacy_rows}):
                        if not service.find_product_media_rows_by_media_id(media_id=media_id):
                            service.delete_media_by_ids([media_id])
                            removed_media += 1
            except Exception as exc:
                skipped += 1
                self.stderr.write(f"{product.erp_nr}: uebersprungen: {exc}")

        self.stdout.write(
            f"WebP-gepruefte Produkte: {eligible}; uebersprungen: {skipped}; "
            f"entfernte Zuordnungen: {removed_relations}; entfernte Medien: {removed_media}."
        )
        if skipped:
            raise CommandError(f"{skipped} Produkt(e) konnten nicht sicher bereinigt werden.")
