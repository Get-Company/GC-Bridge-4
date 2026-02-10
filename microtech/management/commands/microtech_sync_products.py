from __future__ import annotations

from decimal import Decimal, InvalidOperation

from django.core.management.base import BaseCommand, CommandError
from loguru import logger

from microtech.services.artikel import MicrotechArtikelService
from microtech.services.connection import microtech_connection
from microtech.services.lager import MicrotechLagerService
from products.models import Image, Price, Product, Storage


def _to_decimal(value):
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None


def _to_int(value):
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


class Command(BaseCommand):
    help = "Sync products from Microtech (Artikel) into Django."

    def add_arguments(self, parser):
        parser.add_argument(
            "erp_nrs",
            nargs="*",
            help="ERP-Nummern (ArtNr). Wenn leer, nutze --all.",
        )
        parser.add_argument(
            "--all",
            action="store_true",
            help="Alle Artikel (optional gefiltert nach WShopKz).",
        )
        parser.add_argument(
            "--include-inactive",
            action="store_true",
            help="Inaktive Artikel mit synchronisieren (ignoriert WShopKz Filter).",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=None,
            help="Maximale Anzahl zu synchronisierender Artikel.",
        )

    def handle(self, *args, **options):
        erp_nrs = [nr.strip() for nr in options.get("erp_nrs") or [] if nr.strip()]
        sync_all = options.get("all", False)
        include_inactive = options.get("include_inactive", False)
        limit = options.get("limit")

        logger.info(
            "Starting Microtech sync. all={}, include_inactive={}, limit={}",
            sync_all,
            include_inactive,
            limit,
        )

        if not erp_nrs and not sync_all:
            raise CommandError("Bitte ERP-Nummern angeben oder --all verwenden.")

        with microtech_connection() as erp:
            logger.info("ERP connection established. Preparing batch.")
            artikel_service = MicrotechArtikelService(erp=erp)
            lager_service = MicrotechLagerService(erp=erp)

            if sync_all:
                artikel_service.set_range(from_range="000000", to_range="99999999ZZ", field=artikel_service.index_field)
                if not include_inactive:
                    artikel_service.set_filter({"WShopKz": 1})
                total = artikel_service.range_count()
                logger.info("Syncing up to {} products (range).", total)

                success_count = 0
                error_count = 0
                index = 0

                while not artikel_service.range_eof():
                    if limit and index >= limit:
                        break
                    index += 1
                    if index == 1 or index % 100 == 0:
                        logger.info("Progress: {}", index)
                    try:
                        self._sync_current_record(artikel_service, lager_service)
                        success_count += 1
                    except Exception as exc:
                        error_count += 1
                        logger.exception("Sync fehlgeschlagen: {}", exc)
                    artikel_service.range_next()

                logger.success(
                    "Sync abgeschlossen. Erfolg: {}, Fehler: {}.",
                    success_count,
                    error_count,
                )
                return

            if limit:
                erp_nrs = erp_nrs[:limit]

            if not erp_nrs:
                logger.warning("Keine Artikel zum Synchronisieren gefunden.")
                return

            logger.info("Syncing {} products.", len(erp_nrs))

            success_count = 0
            error_count = 0

            for index, erp_nr in enumerate(erp_nrs, start=1):
                try:
                    if index == 1 or index % 100 == 0:
                        logger.info("Progress: {}/{}", index, len(erp_nrs))
                    if not artikel_service.find(erp_nr):
                        logger.warning("Artikel {} nicht gefunden.", erp_nr)
                        continue

                    self._sync_current_record(artikel_service, lager_service)
                    success_count += 1
                except Exception as exc:
                    error_count += 1
                    logger.exception("Sync fehlgeschlagen für {}: {}", erp_nr, exc)

            logger.success(
                "Sync abgeschlossen. Erfolg: {}, Fehler: {}.",
                success_count,
                error_count,
            )

    def _sync_current_record(self, artikel_service, lager_service) -> None:
        erp_key = artikel_service.get_erp_nr()
        if not erp_key:
            raise ValueError("Artikel ohne ArtNr gefunden.")

        name = artikel_service.get_name() or ""
        product, _ = Product.objects.get_or_create(
            erp_nr=erp_key,
            defaults={"name": name},
        )

        product.factor = _to_int(artikel_service.get_factor())
        product.is_active = bool(artikel_service.get_is_active())
        product.unit = artikel_service.get_unit()
        product.min_purchase = _to_int(artikel_service.get_min_purchase())
        product.purchase_unit = _to_int(artikel_service.get_purchase_unit())
        product.name = name or product.name
        product.description = artikel_service.get_description()
        product.description_short = artikel_service.get_description_short()
        product.sort_order = _to_int(artikel_service.get_sort_order()) or product.sort_order
        product.save()

        storage, _ = Storage.objects.get_or_create(product=product)
        stock, location = lager_service.get_stock_and_location(art_nr=product.erp_nr)
        storage.stock = stock
        storage.location = location
        storage.save()

        price_value = _to_decimal(artikel_service.get_price())
        if price_value is not None:
            Price.objects.update_or_create(
                product=product,
                defaults={
                    "price": price_value,
                    "rebate_quantity": _to_int(artikel_service.get_rebate_quantity()),
                    "rebate_price": _to_decimal(artikel_service.get_rebate_price()),
                    "special_price": _to_decimal(artikel_service.get_special_price()),
                    "special_start_date": artikel_service.get_special_start_date(),
                    "special_end_date": artikel_service.get_special_end_date(),
                },
            )

        image_names = artikel_service.get_image_list()
        if image_names:
            existing = {img.path: img for img in Image.objects.filter(path__in=image_names)}
            missing = [Image(path=name) for name in image_names if name not in existing]
            if missing:
                Image.objects.bulk_create(missing, ignore_conflicts=True)
                existing = {img.path: img for img in Image.objects.filter(path__in=image_names)}
            product.images.set(list(existing.values()))
        else:
            product.images.clear()
