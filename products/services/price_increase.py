from __future__ import annotations

from dataclasses import dataclass

from django.db import transaction
from django.utils import timezone

from core.services import BaseService
from products.models import Price, PriceIncrease, PriceIncreaseItem
from products.signals import price_increase_applied
from shopware.models import ShopwareSettings


@dataclass(frozen=True)
class PriceIncreaseRestoreResult:
    restored_price_count: int
    erp_nrs: tuple[str, ...]
    regenerated_special_price_count: int
    cleared_direct_special_price_count: int


class PriceIncreaseService(BaseService):
    model = PriceIncrease

    @staticmethod
    def get_default_sales_channel() -> ShopwareSettings:
        sales_channel = ShopwareSettings.objects.filter(is_default=True, is_active=True).order_by("pk").first()
        if sales_channel is None:
            raise ValueError("Kein aktiver Standard-Verkaufskanal konfiguriert.")
        return sales_channel

    def sync_items(self, instance: PriceIncrease) -> int:
        sales_channel = instance.sales_channel or self.get_default_sales_channel()
        if instance.sales_channel_id != sales_channel.id:
            instance.sales_channel = sales_channel
            instance.save(update_fields=["sales_channel", "updated_at"])

        prices = list(
            Price.objects.select_related("product", "sales_channel")
            .filter(sales_channel=sales_channel, product__is_active=True)
            .order_by("product__erp_nr", "pk")
        )
        source_price_ids = []
        for source_price in prices:
            source_price_ids.append(source_price.id)
            PriceIncreaseItem.objects.update_or_create(
                price_increase=instance,
                source_price=source_price,
                defaults={
                    "product": source_price.product,
                    "unit": str(source_price.product.unit or ""),
                    "current_price": source_price.price,
                    "current_rebate_quantity": source_price.rebate_quantity,
                    "current_rebate_price": source_price.rebate_price,
                },
            )

        instance.items.exclude(source_price_id__in=source_price_ids).delete()
        instance.positions_synced_at = timezone.now()
        instance.save(update_fields=["positions_synced_at", "updated_at"])
        return len(prices)

    @staticmethod
    def _get_blocking_issue_messages(item: PriceIncreaseItem) -> list[str]:
        return [
            str(issue["message"])
            for issue in item.get_pricing_check_issues()
            if issue.get("blocks_apply")
        ]

    def _validate_items_before_apply(self, items: list[PriceIncreaseItem]) -> None:
        invalid_items: list[str] = []
        for item in items:
            issue_messages = self._get_blocking_issue_messages(item)
            if not issue_messages:
                continue
            invalid_items.append(f"{item.product.erp_nr}: {issue_messages[0]}")

        if invalid_items:
            preview = "; ".join(invalid_items[:5])
            if len(invalid_items) > 5:
                preview = f"{preview}; +{len(invalid_items) - 5} weitere Position(en)"
            raise ValueError(
                "Die Preiserhoehung enthaelt blockierende Preispruefungen und kann nicht uebernommen werden: "
                f"{preview}"
            )

    @staticmethod
    def _get_applied_items(instance: PriceIncrease) -> list[PriceIncreaseItem]:
        if instance.status != PriceIncrease.Status.APPLIED:
            raise ValueError("Nur bereits uebernommene Preiserhoehungen koennen wiederhergestellt werden.")
        if not instance.sales_channel_id:
            raise ValueError("Die Preiserhoehung hat keinen Standard-Verkaufskanal.")

        items = list(
            instance.items.select_related("source_price", "product")
            .order_by("product__erp_nr", "id")
        )
        if not items:
            raise ValueError("Die Preiserhoehung enthaelt keine Positionen.")
        return items

    @transaction.atomic
    def restore_applied(self, instance: PriceIncrease) -> PriceIncreaseRestoreResult:
        """Restore saved targets; clear direct specials and recalculate percentage specials."""
        from products.services.product_auto_sync import disable_product_auto_sync

        items = self._get_applied_items(instance)
        self._validate_items_before_apply(items)

        updated_price_ids: list[int] = []
        erp_nrs: list[str] = []
        regenerated_special_price_count = 0
        cleared_direct_special_price_count = 0
        with disable_product_auto_sync():
            for item in items:
                source_price = item.source_price
                source_price.price = item.effective_new_price
                source_price.rebate_quantity = item.current_rebate_quantity
                source_price.rebate_price = item.effective_new_rebate_price
                if source_price.special_percentage not in (None, 0):
                    regenerated_special_price_count += 1
                elif source_price.special_price is not None:
                    source_price.special_price = None
                    source_price.special_start_date = None
                    source_price.special_end_date = None
                    cleared_direct_special_price_count += 1
                source_price.save()
                updated_price_ids.append(source_price.id)

                erp_nr = str(item.product.erp_nr or "").strip()
                if erp_nr:
                    erp_nrs.append(erp_nr)

            # Rebuild all derived sales-channel prices using the existing
            # price-factor logic, while suppressing generic auto-sync jobs.
            price_increase_applied.send(
                sender=self.__class__,
                price_increase_id=instance.id,
                updated_price_ids=updated_price_ids,
            )

        return PriceIncreaseRestoreResult(
            restored_price_count=len(updated_price_ids),
            erp_nrs=tuple(dict.fromkeys(erp_nrs)),
            regenerated_special_price_count=regenerated_special_price_count,
            cleared_direct_special_price_count=cleared_direct_special_price_count,
        )

    @transaction.atomic
    def apply(self, instance: PriceIncrease) -> int:
        if instance.status == PriceIncrease.Status.APPLIED:
            raise ValueError("Diese Preiserhoehung wurde bereits uebernommen.")
        if not instance.sales_channel_id:
            raise ValueError("Es ist kein Standard-Verkaufskanal hinterlegt.")

        items = list(
            instance.items.select_related("source_price", "product")
            .order_by("product__erp_nr", "id")
        )
        if not items:
            raise ValueError("Die Preiserhoehung enthaelt keine Positionen.")
        self._validate_items_before_apply(items)

        updated_price_ids: list[int] = []
        for item in items:
            source_price = item.source_price
            source_price.price = item.effective_new_price
            source_price.rebate_quantity = item.current_rebate_quantity
            source_price.rebate_price = item.effective_new_rebate_price
            source_price.save()
            updated_price_ids.append(source_price.id)

        instance.status = PriceIncrease.Status.APPLIED
        instance.applied_at = timezone.now()
        instance.save(update_fields=["status", "applied_at", "updated_at"])

        transaction.on_commit(
            lambda: price_increase_applied.send(
                sender=self.__class__,
                price_increase_id=instance.id,
                updated_price_ids=updated_price_ids,
            )
        )
        return len(updated_price_ids)
