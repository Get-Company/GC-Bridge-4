from __future__ import annotations

from decimal import Decimal
from typing import Any

from django.db.models import Q
from django.utils import timezone

from core.services import BaseService
from microtech.services.artikel import MicrotechArtikelService
from products.models import Price


class MicrotechExpiredSpecialSyncService(BaseService):
    @staticmethod
    def clear_expired_specials(*, now=None) -> tuple[int, set[int]]:
        now = now or timezone.now()
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

    def sync_expired_specials_to_microtech(
        self,
        *,
        erp: Any,
        affected_product_ids: set[int],
        write_base_price_back: bool = False,
    ) -> tuple[int, int]:
        if not affected_product_ids:
            return 0, 0

        default_prices = (
            Price.objects.select_related("product")
            .filter(
                product_id__in=affected_product_ids,
                sales_channel__is_default=True,
            )
            .order_by("product_id")
        )
        if not default_prices.exists():
            return 0, 0

        artikel_service = MicrotechArtikelService(erp=erp)
        updated = 0
        skipped_price_writes = 0
        for price in default_prices:
            erp_nr = str(price.product.erp_nr or "").strip()
            if not erp_nr:
                continue
            if not artikel_service.find(erp_nr):
                continue

            artikel_service.edit()
            if write_base_price_back:
                current_microtech_price = self._to_decimal(artikel_service.get_price())
                if self._is_suspicious_price_ratio(
                    django_price=price.price,
                    microtech_price=current_microtech_price,
                ):
                    skipped_price_writes += 1
                else:
                    artikel_service.set_field("Vk0.Preis", self._format_decimal(price.price))
            artikel_service.set_field("Vk0.SPr", "")
            artikel_service.set_field("Vk0.SVonDat", "")
            artikel_service.set_field("Vk0.SBisDat", "")
            artikel_service.post()
            updated += 1
        return updated, skipped_price_writes

    @staticmethod
    def _format_decimal(value: Decimal | None) -> str:
        if value is None:
            return ""
        return format(value.quantize(Decimal("0.01")), "f")

    @staticmethod
    def _to_decimal(value) -> Decimal | None:
        if value in (None, ""):
            return None
        try:
            return Decimal(str(value))
        except Exception:
            return None

    @staticmethod
    def _is_suspicious_price_ratio(
        *,
        django_price: Decimal | None,
        microtech_price: Decimal | None,
        ratio_threshold: Decimal = Decimal("10"),
    ) -> bool:
        if django_price in (None, Decimal("0")) or microtech_price in (None, Decimal("0")):
            return False
        source = abs(Decimal(django_price))
        target = abs(Decimal(microtech_price))
        lower = min(source, target)
        if lower == 0:
            return False
        higher = max(source, target)
        return (higher / lower) >= ratio_threshold
