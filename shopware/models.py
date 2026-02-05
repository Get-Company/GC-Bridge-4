from django.db import models

from core.models import BaseModel


class ShopwareSettings(BaseModel):
    name = models.CharField(max_length=100, unique=True)
    sales_channel_id = models.CharField(max_length=255, blank=True)
    tax_high_id = models.CharField(max_length=255, blank=True)
    tax_low_id = models.CharField(max_length=255, blank=True)
    currency_id = models.CharField(max_length=255, blank=True)
    rule_id_price = models.CharField(max_length=255, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        verbose_name = "Shopware Settings"
        verbose_name_plural = "Shopware Settings"

    def __str__(self) -> str:
        return self.name
