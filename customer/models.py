from django.db import models
from django.db.models import Q
from django.utils.translation import gettext_lazy as _

from core.models import BaseModel


class Customer(BaseModel):
    erp_nr = models.CharField(max_length=64, unique=True, verbose_name=_("ERP-Nummer"))
    erp_id = models.IntegerField(null=True, blank=True, unique=True, verbose_name=_("ERP-ID"))
    name = models.CharField(max_length=255, blank=True, default="", verbose_name=_("Name"))
    email = models.EmailField(max_length=255, blank=True, default="", verbose_name=_("E-Mail"))
    api_id = models.CharField(max_length=255, blank=True, default="", verbose_name=_("Shopware Kunden-ID"))
    vat_id = models.CharField(max_length=255, blank=True, default="", verbose_name=_("USt-IdNr"))
    is_gross = models.BooleanField(default=True, verbose_name=_("Bruttopreise"))

    class Meta:
        verbose_name = _("Kunde")
        verbose_name_plural = _("Kunden")
        ordering = ("erp_nr",)

    @property
    def shipping_address(self):
        return self.addresses.filter(is_shipping=True).first()

    @property
    def billing_address(self):
        return self.addresses.filter(is_invoice=True).first()

    def set_shipping_address(self, address: "Address") -> None:
        self.addresses.update(is_shipping=False)
        address.is_shipping = True
        address.save(update_fields=["is_shipping", "updated_at"])

    def set_billing_address(self, address: "Address") -> None:
        self.addresses.update(is_invoice=False)
        address.is_invoice = True
        address.save(update_fields=["is_invoice", "updated_at"])

    def __str__(self) -> str:
        return f"{self.erp_nr} | {self.name or '-'}"


class Address(BaseModel):
    customer = models.ForeignKey(
        Customer,
        related_name="addresses",
        on_delete=models.CASCADE,
        verbose_name=_("Kunde"),
    )
    erp_combined_id = models.CharField(
        max_length=255,
        null=True,
        blank=True,
        unique=True,
        verbose_name=_("ERP Kombi-ID"),
    )
    api_id = models.CharField(max_length=255, blank=True, default="", verbose_name=_("Shopware Adress-ID"))
    erp_nr = models.IntegerField(null=True, blank=True, verbose_name=_("ERP-Nummer"))
    erp_ans_id = models.IntegerField(null=True, blank=True, verbose_name=_("Anschrift-ID"))
    erp_ans_nr = models.IntegerField(null=True, blank=True, verbose_name=_("Anschrift-Nummer"))
    erp_asp_id = models.IntegerField(
        null=True,
        blank=True,
        verbose_name=_("Ansprechpartner-ID"),
    )
    erp_asp_nr = models.IntegerField(
        null=True,
        blank=True,
        verbose_name=_("Ansprechpartner-Nummer"),
    )
    name1 = models.CharField(max_length=255, blank=True, default="", verbose_name=_("Name 1"))
    name2 = models.CharField(max_length=255, blank=True, default="", verbose_name=_("Name 2"))
    name3 = models.CharField(max_length=255, blank=True, default="", verbose_name=_("Name 3"))
    department = models.CharField(max_length=255, blank=True, default="", verbose_name=_("Abteilung"))
    street = models.CharField(max_length=255, blank=True, default="", verbose_name=_("Strasse"))
    postal_code = models.CharField(max_length=255, blank=True, default="", verbose_name=_("PLZ"))
    city = models.CharField(max_length=255, blank=True, default="", verbose_name=_("Ort"))
    country_code = models.CharField(max_length=8, blank=True, default="", verbose_name=_("Laendercode"))
    email = models.EmailField(max_length=255, blank=True, default="", verbose_name=_("E-Mail"))
    title = models.CharField(max_length=255, blank=True, default="", verbose_name=_("Titel"))
    first_name = models.CharField(max_length=255, blank=True, default="", verbose_name=_("Vorname"))
    last_name = models.CharField(max_length=255, blank=True, default="", verbose_name=_("Nachname"))
    phone = models.CharField(max_length=255, blank=True, default="", verbose_name=_("Telefon"))
    is_shipping = models.BooleanField(default=False, verbose_name=_("Lieferanschrift"))
    is_invoice = models.BooleanField(default=False, verbose_name=_("Rechnungsanschrift"))

    class Meta:
        verbose_name = _("Adresse")
        verbose_name_plural = _("Adressen")
        ordering = ("customer", "erp_ans_id", "erp_asp_id")
        constraints = [
            models.UniqueConstraint(
                fields=("customer", "erp_ans_id"),
                condition=Q(erp_ans_id__isnull=False),
                name="unique_customer_anschrift",
            ),
        ]

    def save(self, *args, **kwargs):
        if self.erp_nr is not None and self.erp_ans_id is not None:
            parts = [str(self.erp_nr), str(self.erp_ans_id)]
            if self.erp_asp_id is not None:
                parts.append(str(self.erp_asp_id))
            self.erp_combined_id = "-".join(parts)
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"{self.customer.erp_nr} | Ans {self.erp_ans_id or '-'} | {self.city or '-'}"
