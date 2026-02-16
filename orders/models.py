from decimal import Decimal

from django.db import models
from django.utils.translation import gettext_lazy as _

from core.models import BaseModel
from customer.models import Address, Customer


class Order(BaseModel):
    api_id = models.CharField(max_length=64, unique=True, verbose_name=_("Shopware Bestell-ID"))
    api_delivery_id = models.CharField(
        max_length=64,
        blank=True,
        default="",
        verbose_name=_("Shopware Liefer-ID"),
    )
    api_transaction_id = models.CharField(
        max_length=64,
        blank=True,
        default="",
        verbose_name=_("Shopware Transaktions-ID"),
    )
    sales_channel_id = models.CharField(
        max_length=255,
        blank=True,
        default="",
        verbose_name=_("Verkaufskanal-ID"),
    )
    order_number = models.CharField(
        max_length=255,
        blank=True,
        default="",
        db_index=True,
        verbose_name=_("Bestellnummer"),
    )
    erp_order_id = models.CharField(
        max_length=255,
        blank=True,
        default="",
        verbose_name=_("ERP Vorgangsnummer"),
    )
    description = models.TextField(blank=True, default="", verbose_name=_("Beschreibung"))
    total_price = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00"),
        verbose_name=_("Gesamtpreis"),
    )
    total_tax = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00"),
        verbose_name=_("Steuer gesamt"),
    )
    shipping_costs = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00"),
        verbose_name=_("Versandkosten"),
    )
    payment_method = models.CharField(
        max_length=255,
        blank=True,
        default="",
        verbose_name=_("Zahlungsart"),
    )
    shipping_method = models.CharField(
        max_length=255,
        blank=True,
        default="",
        verbose_name=_("Versandart"),
    )
    order_state = models.CharField(max_length=64, blank=True, default="", verbose_name=_("Bestellstatus"))
    shipping_state = models.CharField(
        max_length=64,
        blank=True,
        default="",
        verbose_name=_("Versandstatus"),
    )
    payment_state = models.CharField(
        max_length=64,
        blank=True,
        default="",
        verbose_name=_("Zahlstatus"),
    )
    purchase_date = models.DateTimeField(null=True, blank=True, verbose_name=_("Bestelldatum"))
    customer = models.ForeignKey(
        Customer,
        related_name="orders",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        verbose_name=_("Kunde"),
    )
    billing_address = models.ForeignKey(
        Address,
        related_name="billing_orders",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        verbose_name=_("Rechnungsanschrift"),
    )
    shipping_address = models.ForeignKey(
        Address,
        related_name="shipping_orders",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        verbose_name=_("Lieferanschrift"),
    )

    class Meta:
        verbose_name = _("Bestellung")
        verbose_name_plural = _("Bestellungen")
        ordering = ("-purchase_date", "-created_at")

    def __str__(self) -> str:
        return self.order_number or self.api_id


class OrderDetail(BaseModel):
    order = models.ForeignKey(
        Order,
        on_delete=models.CASCADE,
        related_name="details",
        verbose_name=_("Bestellung"),
    )
    api_id = models.CharField(max_length=64, blank=True, default="", verbose_name=_("Shopware Position-ID"))
    erp_nr = models.CharField(max_length=255, blank=True, default="", verbose_name=_("ERP-Nummer"))
    name = models.CharField(max_length=255, blank=True, default="", verbose_name=_("Bezeichnung"))
    unit = models.CharField(max_length=64, blank=True, default="", verbose_name=_("Einheit"))
    quantity = models.IntegerField(default=0, verbose_name=_("Menge"))
    unit_price = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00"),
        verbose_name=_("Einzelpreis"),
    )
    total_price = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00"),
        verbose_name=_("Gesamtpreis"),
    )
    tax = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name=_("Steuer"),
    )

    class Meta:
        verbose_name = _("Bestellposition")
        verbose_name_plural = _("Bestellpositionen")
        ordering = ("order", "id")

    def __str__(self) -> str:
        return f"{self.order_id} | {self.name or self.erp_nr or self.api_id}"
