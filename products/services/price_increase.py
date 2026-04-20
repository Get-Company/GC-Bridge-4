from __future__ import annotations

from django.db import transaction
from django.utils import timezone

from core.services import BaseService
from products.models import Price, PriceIncrease, PriceIncreaseItem
from products.signals import price_increase_applied
from shopware.models import ShopwareSettings


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
            .filter(sales_channel=sales_channel)
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
