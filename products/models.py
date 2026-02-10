from django.db import models

from core.models import BaseModel


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
    price = models.DecimalField(max_digits=10, decimal_places=2)
    rebate_quantity = models.IntegerField(null=True, blank=True)
    rebate_price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    special_price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    special_start_date = models.DateTimeField(null=True, blank=True)
    special_end_date = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("product", "price")

    def __str__(self) -> str:
        return f"{self.product.erp_nr} {self.price}"


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
