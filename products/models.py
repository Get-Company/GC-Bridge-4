from decimal import Decimal

from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from core.models import BaseModel
from shopware.models import ShopwareSettings


class Tax(BaseModel):
    name = models.CharField(max_length=64, verbose_name=_("Steuerbezeichnung"))
    rate = models.DecimalField(max_digits=5, decimal_places=2, verbose_name=_("Steuersatz (%)"))

    class Meta:
        verbose_name = _("Steuer")
        verbose_name_plural = _("Steuern")
        ordering = ("name",)

    def __str__(self) -> str:
        return f"{self.name} ({self.rate}%)"


class Category(BaseModel):
    name = models.CharField(max_length=128, verbose_name=_("Name"))
    slug = models.SlugField(max_length=160, unique=True, verbose_name=_("Slug"))
    parent = models.ForeignKey(
        "self",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        verbose_name=_("Oberkategorie"),
    )

    class Meta:
        verbose_name = _("Kategorie")
        verbose_name_plural = _("Kategorien")
        ordering = ("name",)

    def __str__(self) -> str:
        return self.name


class Image(BaseModel):
    path = models.CharField(max_length=255, verbose_name=_("Bildpfad"))
    alt_text = models.CharField(max_length=255, blank=True, verbose_name=_("Alternativtext"))

    class Meta:
        verbose_name = _("Bild")
        verbose_name_plural = _("Bilder")
        ordering = ("id",)

    @property
    def url(self) -> str:
        from django.conf import settings

        prefix = getattr(settings, "CDN_PREFIX", "")
        if prefix:
            return f"{prefix.rstrip('/')}/{self.path.lstrip('/')}"
        return self.path

    def __str__(self) -> str:
        return self.alt_text or self.path


class Product(BaseModel):
    sku = models.CharField(
        max_length=64,
        unique=True,
        blank=True,
        null=True,
        verbose_name=_("Artikelnummer (SKU)"),
    )
    erp_nr = models.CharField(max_length=64, unique=True, verbose_name=_("ERP-Nummer"))
    gtin = models.CharField(max_length=32, blank=True, verbose_name=_("GTIN"))
    name = models.CharField(max_length=255, null=True, blank=True, verbose_name=_("Name"))
    sort_order = models.PositiveIntegerField(default=1000, verbose_name=_("Sortierung"))
    description = models.TextField(null=True, blank=True, verbose_name=_("Beschreibung"))
    description_short = models.TextField(
        null=True,
        blank=True,
        verbose_name=_("Kurzbeschreibung"),
    )
    is_active = models.BooleanField(default=True, verbose_name=_("Aktiv"))
    factor = models.IntegerField(null=True, blank=True, verbose_name=_("Faktor"))
    unit = models.CharField(max_length=255, null=True, blank=True, verbose_name=_("Einheit"))
    min_purchase = models.IntegerField(null=True, blank=True, verbose_name=_("Mindestabnahme"))
    purchase_unit = models.IntegerField(null=True, blank=True, verbose_name=_("Kaufeinheit"))
    tax = models.ForeignKey(
        Tax,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        verbose_name=_("Steuer"),
    )
    categories = models.ManyToManyField(Category, blank=True, verbose_name=_("Kategorien"))
    images = models.ManyToManyField(Image, blank=True, verbose_name=_("Bilder"))

    class Meta:
        verbose_name = _("Produkt")
        verbose_name_plural = _("Produkte")
        ordering = ("erp_nr", "name")

    def __str__(self) -> str:
        return f"{self.erp_nr} - {self.name}"


class Price(BaseModel):
    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name="prices",
        verbose_name=_("Produkt"),
    )
    sales_channel = models.ForeignKey(
        ShopwareSettings,
        on_delete=models.CASCADE,
        related_name="prices",
        null=True,
        blank=True,
        verbose_name=_("Verkaufskanal"),
    )
    price = models.DecimalField(max_digits=10, decimal_places=2, verbose_name=_("Preis"))
    rebate_quantity = models.IntegerField(null=True, blank=True, verbose_name=_("Staffelmenge"))
    rebate_price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name=_("Staffelpreis"),
    )
    special_price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name=_("Sonderpreis"),
    )
    special_start_date = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name=_("Sonderpreis ab"),
    )
    special_end_date = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name=_("Sonderpreis bis"),
    )

    class Meta:
        verbose_name = _("Preis")
        verbose_name_plural = _("Preise")
        ordering = ("product", "sales_channel", "price")
        constraints = [
            models.UniqueConstraint(
                fields=("product", "sales_channel"),
                name="unique_price_per_sales_channel",
            )
        ]

    @property
    def is_special_active(self) -> bool:
        now = timezone.now()
        if self.special_price and self.special_start_date and self.special_end_date:
            return self.special_start_date <= now <= self.special_end_date
        return False

    def get_current_price(self, *, as_float: bool = False):
        price = self.special_price if self.is_special_active else self.price
        return self._format_price(price, as_float)

    def get_current_brutto_price(self, *, as_float: bool = False):
        price = self.get_current_price(as_float=False)
        return self._format_price(price * self._tax_factor(), as_float)

    def get_standard_price(self, *, as_float: bool = False):
        return self._format_price(self.price, as_float)

    def get_standard_brutto_price(self, *, as_float: bool = False):
        return self._format_price(self.price * self._tax_factor(), as_float)

    def get_special_price(self, *, as_float: bool = False):
        if not self.is_special_active:
            return None
        return self._format_price(self.special_price, as_float)

    def get_special_brutto_price(self, *, as_float: bool = False):
        if not self.is_special_active:
            return None
        return self._format_price(self.special_price * self._tax_factor(), as_float)

    def get_rebate_price(self, *, as_float: bool = False):
        return self._format_price(self.rebate_price, as_float)

    def get_rebate_brutto_price(self, *, as_float: bool = False):
        if self.rebate_price is None:
            return None
        return self._format_price(self.rebate_price * self._tax_factor(), as_float)

    def _tax_factor(self) -> Decimal:
        if self.product.tax:
            return self.product.tax.rate / Decimal("100") + Decimal("1")
        return Decimal("1")

    @staticmethod
    def _format_price(value, as_float: bool):
        if value is None:
            return None
        rounded_value = Decimal(value).quantize(Decimal("0.01"))
        return float(rounded_value) if as_float else rounded_value

    def __str__(self) -> str:
        channel_name = self.sales_channel.name if self.sales_channel else "default"
        return f"{self.product.erp_nr} | {channel_name}: {self.price}"


class Storage(BaseModel):
    product = models.OneToOneField(
        Product,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="storage",
        verbose_name=_("Produkt"),
    )
    stock = models.IntegerField(null=True, blank=True, verbose_name=_("Bestand"))
    location = models.CharField(max_length=255, null=True, blank=True, verbose_name=_("Lagerort"))
    virtual_stock = models.PositiveIntegerField(default=0, verbose_name=_("Virtueller Bestand"))

    @property
    def get_stock(self) -> int:
        return self.virtual_stock if self.virtual_stock > 0 else (self.stock or 0)

    class Meta:
        verbose_name = _("Lagerbestand")
        verbose_name_plural = _("Lagerbestaende")
        ordering = ("product",)
