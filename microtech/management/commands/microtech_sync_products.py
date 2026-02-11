from __future__ import annotations

from decimal import Decimal, InvalidOperation, ROUND_UP

from django.core.management.base import BaseCommand, CommandError
from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType

from microtech.services.artikel import MicrotechArtikelService
from microtech.services.connection import microtech_connection
from microtech.services.lager import MicrotechLagerService
from core.admin_utils import log_admin_change
from products.models import Image, Price, Product, Storage
from shopware.models import ShopwareSettings


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


def _apply_factor(value: Decimal | None, factor: Decimal) -> Decimal | None:
    if value is None:
        return None
    step = Decimal("0.05")
    scaled = value * factor
    rounded = (scaled / step).to_integral_value(rounding=ROUND_UP) * step
    return rounded.quantize(Decimal("0.01"))


def _get_admin_user_id() -> int | None:
    user = get_user_model().objects.filter(is_superuser=True).order_by("id").first()
    return user.id if user else None


def _log_admin_error(
    *,
    admin_user_id: int | None,
    content_type_id: int | None,
    message: str,
    object_id: str | None = None,
    object_repr: str = "Microtech Sync",
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

        if not erp_nrs and not sync_all:
            raise CommandError("Bitte ERP-Nummern angeben oder --all verwenden.")

        admin_user_id = _get_admin_user_id()
        content_type_id = None
        if admin_user_id:
            content_type_id = ContentType.objects.get_for_model(Product).id

        with microtech_connection() as erp:
            artikel_service = MicrotechArtikelService(erp=erp)
            lager_service = MicrotechLagerService(erp=erp)

            if sync_all:
                artikel_service.set_range(from_range="000000", to_range="99999999ZZ", field=artikel_service.index_field)
                if not include_inactive:
                    artikel_service.set_filter({"WShopKz": 1})

                success_count = 0
                error_count = 0
                index = 0

                while not artikel_service.range_eof():
                    if limit and index >= limit:
                        break
                    index += 1
                    try:
                        self._sync_current_record(
                            artikel_service,
                            lager_service,
                            admin_user_id=admin_user_id,
                            content_type_id=content_type_id,
                        )
                        success_count += 1
                    except Exception as exc:
                        error_count += 1
                        _log_admin_error(
                            admin_user_id=admin_user_id,
                            content_type_id=content_type_id,
                            message=f"Microtech sync error: {exc}",
                            object_repr="Microtech Sync (batch)",
                        )
                    artikel_service.range_next()

                return

            if limit:
                erp_nrs = erp_nrs[:limit]

            if not erp_nrs:
                return

            success_count = 0
            error_count = 0

            for index, erp_nr in enumerate(erp_nrs, start=1):
                try:
                    if not artikel_service.find(erp_nr):
                        error_count += 1
                        _log_admin_error(
                            admin_user_id=admin_user_id,
                            content_type_id=content_type_id,
                            message=f"Microtech sync error: Artikel {erp_nr} nicht gefunden.",
                            object_repr=f"Microtech Sync {erp_nr}",
                        )
                        continue

                    self._sync_current_record(
                        artikel_service,
                        lager_service,
                        admin_user_id=admin_user_id,
                        content_type_id=content_type_id,
                    )
                    success_count += 1
                except Exception as exc:
                    error_count += 1
                    _log_admin_error(
                        admin_user_id=admin_user_id,
                        content_type_id=content_type_id,
                        message=f"Microtech sync error for {erp_nr}: {exc}",
                        object_repr=f"Microtech Sync {erp_nr}",
                    )

    def _sync_current_record(self, artikel_service, lager_service, *, admin_user_id=None, content_type_id=None) -> None:
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
            channels = list(ShopwareSettings.objects.filter(is_active=True))
            default_channel = next((ch for ch in channels if ch.is_default), None)
            if not default_channel:
                _log_admin_error(
                    admin_user_id=admin_user_id,
                    content_type_id=content_type_id,
                    message="Kein aktiver Default-Sales-Channel gefunden. Preise wurden nicht aktualisiert.",
                    object_id=str(product.pk),
                    object_repr=f"Product {product.erp_nr}",
                )
            else:
                base_price, _ = Price.objects.update_or_create(
                    product=product,
                    sales_channel=default_channel,
                    defaults={
                        "price": price_value,
                        "rebate_quantity": _to_int(artikel_service.get_rebate_quantity()),
                        "rebate_price": _to_decimal(artikel_service.get_rebate_price()),
                        "special_price": _to_decimal(artikel_service.get_special_price()),
                        "special_start_date": artikel_service.get_special_start_date(),
                        "special_end_date": artikel_service.get_special_end_date(),
                    },
                )

                for channel in channels:
                    if channel.pk == default_channel.pk:
                        continue
                    factor = channel.price_factor or Decimal("1.0")
                    Price.objects.update_or_create(
                        product=product,
                        sales_channel=channel,
                        defaults={
                            "price": _apply_factor(base_price.price, factor),
                            "rebate_quantity": base_price.rebate_quantity,
                            "rebate_price": _apply_factor(base_price.rebate_price, factor),
                            "special_price": _apply_factor(base_price.special_price, factor),
                            "special_start_date": base_price.special_start_date,
                            "special_end_date": base_price.special_end_date,
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
