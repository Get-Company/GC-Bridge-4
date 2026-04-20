import calendar
from decimal import Decimal, ROUND_UP

from django.db import models
from django.core.exceptions import ValidationError
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from core.models import BaseModel
from shopware.models import ShopwareSettings


class Tax(BaseModel):
    name = models.CharField(max_length=64, verbose_name=_("Steuerbezeichnung"))
    rate = models.DecimalField(max_digits=5, decimal_places=2, verbose_name=_("Steuersatz (%)"))
    shopware_id = models.CharField(
        max_length=64,
        blank=True,
        default="",
        verbose_name=_("Shopware Steuer-ID"),
    )

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
    def filename(self) -> str:
        return self._extract_filename(self.path)

    @property
    def url(self) -> str:
        from django.conf import settings

        base_url = getattr(settings, "MICROTECH_IMAGE_BASE_URL", "") or getattr(settings, "CDN_PREFIX", "")
        filename = self.filename
        if base_url and filename:
            return f"{base_url.rstrip('/')}/{filename.lstrip('/')}"
        return self.path

    def __str__(self) -> str:
        return self.alt_text or self.path

    @staticmethod
    def _extract_filename(value: str | None) -> str:
        if not value:
            return ""
        return str(value).replace("\\", "/").rstrip("/").split("/")[-1]


class PropertyGroup(BaseModel):
    external_key = models.CharField(
        max_length=255,
        blank=True,
        default="",
        db_index=True,
        verbose_name=_("Externe Referenz"),
    )
    name = models.CharField(max_length=255, verbose_name=_("Name"))

    class Meta:
        verbose_name = _("Attributgruppe")
        verbose_name_plural = _("Attributgruppen")
        ordering = ("name",)

    def __str__(self) -> str:
        return self.name


class PropertyValue(BaseModel):
    external_key = models.CharField(
        max_length=255,
        blank=True,
        default="",
        db_index=True,
        verbose_name=_("Externe Referenz"),
    )
    group = models.ForeignKey(
        PropertyGroup,
        on_delete=models.CASCADE,
        related_name="values",
        verbose_name=_("Attributgruppe"),
    )
    name = models.CharField(max_length=255, verbose_name=_("Wert"))

    class Meta:
        verbose_name = _("Attributwert")
        verbose_name_plural = _("Attributwerte")
        ordering = ("group__name", "name")
        constraints = [
            models.UniqueConstraint(
                fields=("group", "name"),
                name="unique_property_value_per_group",
            )
        ]

    def __str__(self) -> str:
        return f"{self.group}: {self.name}"


class Product(BaseModel):
    shopware_image_sync_hash = models.CharField(
        max_length=64,
        blank=True,
        default="",
        verbose_name=_("Shopware Bild-Sync-Hash"),
    )
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
    customs_tariff_number = models.CharField(
        max_length=32, blank=True, default="",
        verbose_name=_("Statistische Warennummer"),
    )
    weight_gross = models.DecimalField(
        max_digits=10, decimal_places=4, null=True, blank=True,
        verbose_name=_("Bruttogewicht (kg)"),
    )
    weight_net = models.DecimalField(
        max_digits=10, decimal_places=4, null=True, blank=True,
        verbose_name=_("Nettogewicht (kg)"),
    )
    tax = models.ForeignKey(
        Tax,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        verbose_name=_("Steuer"),
    )
    categories = models.ManyToManyField(Category, blank=True, verbose_name=_("Kategorien"))
    images = models.ManyToManyField(Image, blank=True, verbose_name=_("Bilder"))
    properties = models.ManyToManyField(
        PropertyValue,
        through="ProductProperty",
        blank=True,
        verbose_name=_("Attribute"),
    )

    class Meta:
        verbose_name = _("Produkt")
        verbose_name_plural = _("Produkte")
        ordering = ("erp_nr", "name")

    def __str__(self) -> str:
        return f"{self.erp_nr} - {self.name}"

    def get_ordered_product_images(self) -> list["ProductImage"]:
        if hasattr(self, "ordered_product_images"):
            ordered_product_images = [product_image for product_image in self.ordered_product_images if product_image.image_id]
        else:
            ordered_product_images = list(self.product_images.select_related("image").order_by("order", "id"))

        # Backward compatibility: older data may still be linked through the legacy images M2M field.
        known_image_ids = {product_image.image_id for product_image in ordered_product_images if product_image.image_id}
        fallback_images = self.images.exclude(pk__in=known_image_ids).order_by("id")
        next_order = max((product_image.order for product_image in ordered_product_images), default=0)
        for offset, image in enumerate(fallback_images, start=1):
            ordered_product_images.append(
                ProductImage(
                    product=self,
                    image=image,
                    order=next_order + offset,
                )
            )

        return ordered_product_images

    def get_images(self) -> list[Image]:
        return [product_image.image for product_image in self.get_ordered_product_images() if product_image.image]

    @property
    def first_image(self) -> Image | None:
        images = self.get_images()
        return images[0] if images else None


class ProductImage(BaseModel):
    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name="product_images",
        verbose_name=_("Produkt"),
    )
    image = models.ForeignKey(
        Image,
        on_delete=models.CASCADE,
        related_name="product_images",
        verbose_name=_("Bild"),
    )
    order = models.PositiveIntegerField(default=1, db_index=True, verbose_name=_("Reihenfolge"))

    class Meta:
        verbose_name = _("Produktbild")
        verbose_name_plural = _("Produktbilder")
        ordering = ("product", "order", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("product", "image"),
                name="unique_product_image_assignment",
            )
        ]

    def __str__(self) -> str:
        return f"{self.product.erp_nr} | {self.order} | {self.image.path}"


class ProductProperty(BaseModel):
    external_key = models.CharField(
        max_length=255,
        blank=True,
        default="",
        db_index=True,
        verbose_name=_("Externe Referenz"),
    )
    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name="product_properties",
        verbose_name=_("Produkt"),
    )
    value = models.ForeignKey(
        PropertyValue,
        on_delete=models.CASCADE,
        related_name="product_properties",
        verbose_name=_("Attributwert"),
    )

    class Meta:
        verbose_name = _("Produktattribut")
        verbose_name_plural = _("Produktattribute")
        ordering = ("product__erp_nr", "value__group__name", "value__name")
        constraints = [
            models.UniqueConstraint(
                fields=("product", "value"),
                name="unique_product_property_assignment",
            )
        ]

    def __str__(self) -> str:
        return f"{self.product.erp_nr} | {self.value.group.name}: {self.value.name}"


class Price(BaseModel):
    TRACKED_HISTORY_FIELDS = (
        "price",
        "rebate_quantity",
        "rebate_price",
        "special_percentage",
        "special_price",
        "special_start_date",
        "special_end_date",
    )

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
    special_percentage = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name=_("Sonderpreis (%)"),
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

    @staticmethod
    def _round_up_5ct(value: Decimal) -> Decimal:
        step = Decimal("0.05")
        return (value / step).to_integral_value(rounding=ROUND_UP) * step

    def save(self, *args, **kwargs):
        previous_state = None
        is_create = self.pk is None
        if not is_create:
            previous_state = (
                type(self).objects.filter(pk=self.pk)
                .values(*self.TRACKED_HISTORY_FIELDS)
                .first()
            )

        if self.special_percentage and self.price:
            self.special_price = self._round_up_5ct(
                self.price * (Decimal("100") - self.special_percentage) / Decimal("100")
            )
            now = timezone.now()
            if not self.special_start_date:
                self.special_start_date = now
            if not self.special_end_date:
                next_month = (now.month % 12) + 1
                year = now.year + (1 if next_month == 1 else 0)
                last_day = calendar.monthrange(year, next_month)[1]
                self.special_end_date = now.replace(
                    year=year, month=next_month, day=last_day,
                    hour=23, minute=59, second=59, microsecond=0,
                )
        elif self.special_price is None:
            self.special_price = None
            self.special_start_date = None
            self.special_end_date = None
        super().save(*args, **kwargs)
        self._create_history_entry(previous_state=previous_state, is_create=is_create)

    def _create_history_entry(self, *, previous_state: dict | None, is_create: bool) -> None:
        current_state = {field: getattr(self, field) for field in self.TRACKED_HISTORY_FIELDS}
        changed_fields = [
            field
            for field in self.TRACKED_HISTORY_FIELDS
            if previous_state is None or previous_state.get(field) != current_state.get(field)
        ]

        if not changed_fields:
            return

        PriceHistory.objects.create(
            price_entry=self,
            change_type=PriceHistory.ChangeType.CREATED if is_create else PriceHistory.ChangeType.UPDATED,
            changed_fields=", ".join(changed_fields),
            price=current_state["price"],
            rebate_quantity=current_state["rebate_quantity"],
            rebate_price=current_state["rebate_price"],
            special_percentage=current_state["special_percentage"],
            special_price=current_state["special_price"],
            special_start_date=current_state["special_start_date"],
            special_end_date=current_state["special_end_date"],
        )

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


class PriceHistory(BaseModel):
    class ChangeType(models.TextChoices):
        CREATED = "created", _("Angelegt")
        UPDATED = "updated", _("Aktualisiert")

    price_entry = models.ForeignKey(
        Price,
        on_delete=models.CASCADE,
        related_name="history_entries",
        verbose_name=_("Preis"),
    )
    change_type = models.CharField(
        max_length=16,
        choices=ChangeType.choices,
        default=ChangeType.UPDATED,
        verbose_name=_("Aenderungstyp"),
    )
    changed_fields = models.CharField(
        max_length=255,
        blank=True,
        default="",
        verbose_name=_("Geaenderte Felder"),
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
    special_percentage = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name=_("Sonderpreis (%)"),
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
        verbose_name = _("Preis-Historie")
        verbose_name_plural = _("Preis-Historie")
        ordering = ("-created_at", "-id")

    def __str__(self) -> str:
        return f"{self.price_entry} | {self.get_change_type_display()} | {self.created_at:%Y-%m-%d %H:%M:%S}"


class PriceIncrease(BaseModel):
    class Status(models.TextChoices):
        DRAFT = "draft", _("Entwurf")
        APPLIED = "applied", _("Uebernommen")

    title = models.CharField(max_length=255, verbose_name=_("Titel"))
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.DRAFT,
        db_index=True,
        verbose_name=_("Status"),
    )
    sales_channel = models.ForeignKey(
        ShopwareSettings,
        on_delete=models.PROTECT,
        related_name="price_increases",
        null=True,
        blank=True,
        verbose_name=_("Standard-Verkaufskanal"),
    )
    general_percentage = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal("2.50"),
        verbose_name=_("Generelle Erhoehung (%)"),
    )
    positions_synced_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name=_("Positionen synchronisiert am"),
    )
    applied_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name=_("Uebernommen am"),
    )

    class Meta:
        verbose_name = _("Preiserhoehung")
        verbose_name_plural = _("Preiserhoehungen")
        ordering = ("-created_at", "-id")

    def __str__(self) -> str:
        return self.title

    def clean(self):
        super().clean()
        if self.sales_channel_id and not self.sales_channel.is_default:
            raise ValidationError({"sales_channel": _("Es darf nur der Standard-Verkaufskanal verwendet werden.")})

    def save(self, *args, **kwargs):
        if not self.sales_channel_id:
            self.sales_channel = ShopwareSettings.objects.filter(is_default=True, is_active=True).order_by("pk").first()
        super().save(*args, **kwargs)

    @property
    def position_count(self) -> int:
        return self.items.count()


class PriceIncreaseItem(BaseModel):
    price_increase = models.ForeignKey(
        PriceIncrease,
        on_delete=models.CASCADE,
        related_name="items",
        verbose_name=_("Preiserhoehung"),
    )
    product = models.ForeignKey(
        Product,
        on_delete=models.PROTECT,
        related_name="price_increase_items",
        verbose_name=_("Produkt"),
    )
    source_price = models.ForeignKey(
        Price,
        on_delete=models.PROTECT,
        related_name="price_increase_items",
        verbose_name=_("Quellpreis"),
    )
    unit = models.CharField(
        max_length=255,
        blank=True,
        default="",
        verbose_name=_("Einheit"),
    )
    current_price = models.DecimalField(max_digits=10, decimal_places=2, verbose_name=_("Aktueller Preis"))
    current_rebate_quantity = models.IntegerField(
        null=True,
        blank=True,
        verbose_name=_("Aktuelle Staffelmenge"),
    )
    current_rebate_price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name=_("Aktueller Staffelpreis"),
    )
    new_price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name=_("Neuer Preis (ed)"),
    )
    new_rebate_price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name=_("neuer Rab.Preis"),
    )

    class Meta:
        verbose_name = _("Preiserhoehungs-Position")
        verbose_name_plural = _("Preiserhoehungs-Positionen")
        ordering = ("product__erp_nr", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("price_increase", "source_price"),
                name="unique_price_increase_item_per_source_price",
            )
        ]

    def __str__(self) -> str:
        return f"{self.price_increase.title} | {self.product.erp_nr}"

    def clean(self):
        super().clean()
        if self.source_price_id and self.product_id and self.source_price.product_id != self.product_id:
            raise ValidationError({"product": _("Produkt und Quellpreis muessen zusammenpassen.")})
        if (
            self.source_price_id
            and self.price_increase_id
            and self.price_increase.sales_channel_id
            and self.source_price.sales_channel_id != self.price_increase.sales_channel_id
        ):
            raise ValidationError({"source_price": _("Der Quellpreis muss zum Standard-Verkaufskanal der Preiserhoehung gehoeren.")})

    def save(self, *args, **kwargs):
        if self.new_price is not None:
            self.new_price = Price._round_up_5ct(Decimal(self.new_price)).quantize(Decimal("0.01"))
        if self.new_rebate_price is not None:
            self.new_rebate_price = Price._round_up_5ct(Decimal(self.new_rebate_price)).quantize(Decimal("0.01"))
        super().save(*args, **kwargs)

    @property
    def suggested_price(self) -> Decimal:
        return self._apply_increase(self.current_price)

    @property
    def suggested_rebate_price(self) -> Decimal | None:
        if self.current_rebate_price is None:
            return None
        return self._apply_increase(self.current_rebate_price)

    @property
    def effective_new_price(self) -> Decimal:
        return self.new_price if self.new_price is not None else self.suggested_price

    @property
    def effective_new_rebate_price(self) -> Decimal | None:
        if self.current_rebate_price is None:
            return None
        return self.new_rebate_price if self.new_rebate_price is not None else self.suggested_rebate_price

    def _apply_increase(self, value: Decimal) -> Decimal:
        factor = Decimal("1.00") + (self.price_increase.general_percentage / Decimal("100"))
        increased = Decimal(value) * factor
        return Price._round_up_5ct(increased).quantize(Decimal("0.01"))
