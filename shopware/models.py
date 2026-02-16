from decimal import Decimal

from django.db import models
from django.db.models import Q
from django.utils.translation import gettext_lazy as _

from core.models import BaseModel


class ShopwareSettings(BaseModel):
    name = models.CharField(max_length=100, unique=True, verbose_name=_("Bezeichnung"))
    sales_channel_id = models.CharField(max_length=255, blank=True, verbose_name=_("Verkaufskanal-ID"))
    tax_high_id = models.CharField(max_length=255, blank=True, verbose_name=_("Steuer-ID hoch"))
    tax_low_id = models.CharField(max_length=255, blank=True, verbose_name=_("Steuer-ID niedrig"))
    currency_id = models.CharField(max_length=255, blank=True, verbose_name=_("Waehrungs-ID"))
    rule_id_price = models.CharField(max_length=255, blank=True, verbose_name=_("Preisregel-ID"))
    price_factor = models.DecimalField(
        max_digits=10,
        decimal_places=4,
        default=Decimal("1.0"),
        verbose_name=_("Preisfaktor"),
    )
    is_default = models.BooleanField(default=False, verbose_name=_("Standardkanal"))
    is_active = models.BooleanField(default=True, verbose_name=_("Aktiv"))

    def save(self, *args, **kwargs):
        if self.is_default:
            ShopwareSettings.objects.filter(is_default=True).exclude(pk=self.pk).update(is_default=False)
        super().save(*args, **kwargs)

    class Meta:
        verbose_name = _("Shopware Konfiguration")
        verbose_name_plural = _("Shopware Konfigurationen")
        constraints = [
            models.UniqueConstraint(
                fields=("is_default",),
                condition=Q(is_default=True),
                name="unique_default_sales_channel",
            )
        ]

    def __str__(self) -> str:
        return self.name
