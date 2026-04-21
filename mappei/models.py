from decimal import Decimal

from django.db import models
from django.utils.translation import gettext_lazy as _

from core.models import BaseModel
from products.models import Product


class MappeiProduct(BaseModel):
    artikelnr = models.CharField(
        max_length=32,
        unique=True,
        db_index=True,
        verbose_name=_("Artikelnummer"),
    )
    name = models.CharField(
        max_length=255,
        blank=True,
        default="",
        verbose_name=_("Name"),
    )
    url = models.CharField(
        max_length=512,
        blank=True,
        default="",
        verbose_name=_("URL"),
    )
    vpe_menge = models.PositiveIntegerField(
        null=True,
        blank=True,
        verbose_name=_("VPE Menge"),
    )
    vpe_einheit = models.CharField(
        max_length=64,
        blank=True,
        default="",
        verbose_name=_("VPE Einheit"),
    )
    image_url = models.CharField(
        max_length=512,
        blank=True,
        default="",
        verbose_name=_("Bild-URL"),
    )
    hat_staffel = models.BooleanField(
        default=False,
        verbose_name=_("Hat Staffelpreise"),
    )
    last_scraped_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name=_("Zuletzt gescrapt"),
    )

    class Meta:
        verbose_name = _("Mappei Produkt")
        verbose_name_plural = _("Mappei Produkte")
        ordering = ("artikelnr",)

    def __str__(self) -> str:
        return f"{self.artikelnr} – {self.name}" if self.name else self.artikelnr

    def get_latest_snapshot(self) -> "MappeiPriceSnapshot | None":
        return self.price_snapshots.order_by("-scraped_at").first()


class MappeiPriceSnapshot(BaseModel):
    """One record per price change. Only created when prices differ from the previous snapshot."""

    product = models.ForeignKey(
        MappeiProduct,
        on_delete=models.CASCADE,
        related_name="price_snapshots",
        verbose_name=_("Mappei Produkt"),
    )
    scraped_at = models.DateTimeField(
        verbose_name=_("Gescrapt am"),
    )
    preis = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        verbose_name=_("Preis (netto)"),
    )
    staffelpreismenge_min = models.PositiveIntegerField(
        null=True,
        blank=True,
        verbose_name=_("Staffelmenge min (Stück)"),
    )
    staffelpreismenge_max = models.PositiveIntegerField(
        null=True,
        blank=True,
        verbose_name=_("Staffelmenge max (Stück)"),
    )
    staffelpreis_min = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name=_("Staffelpreis min"),
    )
    staffelpreis_max = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name=_("Staffelpreis max"),
    )
    partial_success = models.BooleanField(
        default=False,
        verbose_name=_("Teilweise erfolgreich"),
        help_text=_("Staffelmengen konnten nicht berechnet werden (VPE fehlte)."),
    )

    PRICE_FIELDS = (
        "preis",
        "staffelpreismenge_min",
        "staffelpreismenge_max",
        "staffelpreis_min",
        "staffelpreis_max",
    )

    class Meta:
        verbose_name = _("Mappei Preissnapshot")
        verbose_name_plural = _("Mappei Preissnapshots")
        ordering = ("-scraped_at",)

    def __str__(self) -> str:
        return f"{self.product.artikelnr} | {self.scraped_at:%Y-%m-%d} | {self.preis} €"

    @classmethod
    def create_if_changed(
        cls,
        product: MappeiProduct,
        scraped_at,
        preis: Decimal,
        staffelpreismenge_min: int | None,
        staffelpreismenge_max: int | None,
        staffelpreis_min: Decimal | None,
        staffelpreis_max: Decimal | None,
        partial_success: bool = False,
    ) -> "MappeiPriceSnapshot | None":
        """Create a snapshot only if prices differ from the latest existing snapshot."""
        latest = product.get_latest_snapshot()
        new_values = {
            "preis": preis,
            "staffelpreismenge_min": staffelpreismenge_min,
            "staffelpreismenge_max": staffelpreismenge_max,
            "staffelpreis_min": staffelpreis_min,
            "staffelpreis_max": staffelpreis_max,
        }
        if latest is not None:
            old_values = {field: getattr(latest, field) for field in cls.PRICE_FIELDS}
            if old_values == new_values:
                return None

        return cls.objects.create(
            product=product,
            scraped_at=scraped_at,
            partial_success=partial_success,
            **new_values,
        )


class MappeiProductMapping(BaseModel):
    mappei_product = models.OneToOneField(
        MappeiProduct,
        on_delete=models.CASCADE,
        related_name="mapping",
        verbose_name=_("Mappei Produkt"),
    )
    product = models.ForeignKey(
        Product,
        on_delete=models.PROTECT,
        related_name="mappei_mappings",
        verbose_name=_("Internes Produkt"),
    )
    factor = models.DecimalField(
        max_digits=10,
        decimal_places=4,
        null=True,
        blank=True,
        verbose_name=_("Faktor"),
        help_text=_("Umrechnungsfaktor Mappei-VPE → interne Einheit. Leer lassen wenn 1:1."),
    )

    class Meta:
        verbose_name = _("Mappei Produkt-Mapping")
        verbose_name_plural = _("Mappei Produkt-Mappings")
        ordering = ("mappei_product__artikelnr",)

    def __str__(self) -> str:
        return f"{self.mappei_product.artikelnr} → {self.product.erp_nr}"
