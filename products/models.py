from decimal import Decimal

from django.db import models
from django.utils import timezone

from core.models import BaseModel
from shopware.models import ShopwareSettings


class Tax(BaseModel):
    name = models.CharField(max_length=64)
    rate = models.DecimalField(max_digits=5, decimal_places=2)

    class Meta:
        ordering = ("name",)

    def __str__(self) -> str:
        return f"{self.name} ({self.rate}%)"


class Category(BaseModel):
    name = models.CharField(max_length=128)
    slug = models.SlugField(max_length=160, unique=True)
    parent = models.ForeignKey("self", on_delete=models.PROTECT, null=True, blank=True)

    class Meta:
        ordering = ("name",)

    def __str__(self) -> str:
        return self.name


class Image(BaseModel):
    path = models.CharField(max_length=255)
    alt_text = models.CharField(max_length=255, blank=True)

    class Meta:
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
    sku = models.CharField(max_length=64, unique=True, blank=True, null=True)
    erp_nr = models.CharField(max_length=64, unique=True)
    gtin = models.CharField(max_length=32, blank=True)
    name = models.CharField(max_length=255, null=True, blank=True)
    sort_order = models.PositiveIntegerField(default=1000)
    description = models.TextField(null=True, blank=True)
    description_short = models.TextField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    factor = models.IntegerField(null=True, blank=True)
    unit = models.CharField(max_length=255, null=True, blank=True)
    min_purchase = models.IntegerField(null=True, blank=True)
    purchase_unit = models.IntegerField(null=True, blank=True)
    tax = models.ForeignKey(Tax, on_delete=models.PROTECT, null=True, blank=True)
    categories = models.ManyToManyField(Category, blank=True)
    images = models.ManyToManyField(Image, blank=True)

    class Meta:
        ordering = ("erp_nr", "name")

    def __str__(self) -> str:
        return f"{self.erp_nr} - {self.name}"


class Price(BaseModel):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="prices")
    sales_channel = models.ForeignKey(
        ShopwareSettings,
        on_delete=models.CASCADE,
        related_name="prices",
        null=True,
        blank=True,
    )
    price = models.DecimalField(max_digits=10, decimal_places=2)
    rebate_quantity = models.IntegerField(null=True, blank=True)
    rebate_price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    special_price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    special_start_date = models.DateTimeField(null=True, blank=True)
    special_end_date = models.DateTimeField(null=True, blank=True)

    class Meta:
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
    )
    stock = models.IntegerField(null=True, blank=True)
    location = models.CharField(max_length=255, null=True, blank=True)
    virtual_stock = models.PositiveIntegerField(default=0)

    @property
    def get_stock(self) -> int:
        return self.virtual_stock if self.virtual_stock > 0 else (self.stock or 0)

    class Meta:
        ordering = ("product",)
