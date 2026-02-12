from django.db import models
from django.db.models import Q

from core.models import BaseModel


class Customer(BaseModel):
    erp_nr = models.CharField(max_length=64, unique=True)
    erp_id = models.IntegerField(null=True, blank=True, unique=True)
    name = models.CharField(max_length=255, blank=True, default="")
    email = models.EmailField(max_length=255, blank=True, default="")
    api_id = models.CharField(max_length=255, blank=True, default="")
    vat_id = models.CharField(max_length=255, blank=True, default="")
    is_gross = models.BooleanField(default=True)

    class Meta:
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
    )
    erp_combined_id = models.CharField(max_length=255, null=True, blank=True, unique=True)
    api_id = models.CharField(max_length=255, blank=True, default="")
    erp_nr = models.IntegerField(null=True, blank=True)
    erp_ans_id = models.IntegerField(null=True, blank=True)
    erp_ans_nr = models.IntegerField(null=True, blank=True)
    erp_asp_id = models.IntegerField(null=True, blank=True)
    erp_asp_nr = models.IntegerField(null=True, blank=True)
    name1 = models.CharField(max_length=255, blank=True, default="")
    name2 = models.CharField(max_length=255, blank=True, default="")
    name3 = models.CharField(max_length=255, blank=True, default="")
    department = models.CharField(max_length=255, blank=True, default="")
    street = models.CharField(max_length=255, blank=True, default="")
    postal_code = models.CharField(max_length=255, blank=True, default="")
    city = models.CharField(max_length=255, blank=True, default="")
    country_code = models.CharField(max_length=8, blank=True, default="")
    email = models.EmailField(max_length=255, blank=True, default="")
    title = models.CharField(max_length=255, blank=True, default="")
    first_name = models.CharField(max_length=255, blank=True, default="")
    last_name = models.CharField(max_length=255, blank=True, default="")
    phone = models.CharField(max_length=255, blank=True, default="")
    is_shipping = models.BooleanField(default=False)
    is_invoice = models.BooleanField(default=False)

    class Meta:
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
