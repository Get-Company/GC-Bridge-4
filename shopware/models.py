from decimal import Decimal

from django.db import models
from django.db.models import Q

from core.models import BaseModel


class ShopwareSettings(BaseModel):
    name = models.CharField(max_length=100, unique=True)
    sales_channel_id = models.CharField(max_length=255, blank=True)
    tax_high_id = models.CharField(max_length=255, blank=True)
    tax_low_id = models.CharField(max_length=255, blank=True)
    currency_id = models.CharField(max_length=255, blank=True)
    rule_id_price = models.CharField(max_length=255, blank=True)
    price_factor = models.DecimalField(max_digits=10, decimal_places=4, default=Decimal("1.0"))
    is_default = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)

    def save(self, *args, **kwargs):
        if self.is_default:
            ShopwareSettings.objects.filter(is_default=True).exclude(pk=self.pk).update(is_default=False)
        super().save(*args, **kwargs)

    class Meta:
        verbose_name = "Shopware Settings"
        verbose_name_plural = "Shopware Settings"
        constraints = [
            models.UniqueConstraint(
                fields=("is_default",),
                condition=Q(is_default=True),
                name="unique_default_sales_channel",
            )
        ]

    def __str__(self) -> str:
        return self.name
