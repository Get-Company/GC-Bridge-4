from django.db import models
from django.utils.translation import gettext_lazy as _

from core.models import BaseModel
from products.models import Product


class Email(BaseModel):
    name = models.CharField(max_length=255, verbose_name=_("Name"))
    subject = models.CharField(max_length=255, verbose_name=_("Betreff"))
    introduction = models.TextField(blank=True, verbose_name=_("Einleitung"))
    full_mjml = models.TextField(editable=False, blank=True, verbose_name=_("MJML"))
    html = models.TextField(blank=True, verbose_name=_("HTML"))

    class Meta:
        verbose_name = _("E-Mail")
        verbose_name_plural = _("E-Mails")
        ordering = ("name",)

    def __str__(self) -> str:
        return self.name


class EmailSection(BaseModel):
    email = models.ForeignKey(
        Email,
        on_delete=models.CASCADE,
        related_name="sections",
        verbose_name=_("E-Mail"),
    )
    header = models.CharField(
        max_length=255,
        blank=True,
        verbose_name=_("Abschnitts-Header"),
        help_text=_("Optional. Wird als Trennüberschrift zwischen Produktgruppen angezeigt."),
    )
    position = models.PositiveIntegerField(default=0, db_index=True, verbose_name=_("Position"))

    class Meta:
        verbose_name = _("Abschnitt")
        verbose_name_plural = _("Abschnitte")
        ordering = ("position",)

    def __str__(self) -> str:
        return self.header or f"Abschnitt {self.position}"


class EmailSectionProduct(BaseModel):
    section = models.ForeignKey(
        EmailSection,
        on_delete=models.CASCADE,
        related_name="section_products",
        verbose_name=_("Abschnitt"),
    )
    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name="email_section_products",
        verbose_name=_("Produkt"),
    )
    special_price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name=_("Sonderpreis"),
        help_text=_("Überschreibt den regulären Preis des Produkts für diese E-Mail."),
    )
    position = models.PositiveIntegerField(default=0, db_index=True, verbose_name=_("Position"))

    class Meta:
        verbose_name = _("Produkt")
        verbose_name_plural = _("Produkte")
        ordering = ("position",)

    def __str__(self) -> str:
        return str(self.product)

    def get_display_price(self):
        if self.special_price is not None:
            return self.special_price
        price_obj = self.product.prices.filter(sales_channel__isnull=True).first()
        if price_obj:
            return price_obj.price
        return None
