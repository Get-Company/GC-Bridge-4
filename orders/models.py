from decimal import Decimal

from django.db import models

from core.models import BaseModel
from customer.models import Address, Customer


class Order(BaseModel):
    api_id = models.CharField(max_length=64, unique=True)
    api_delivery_id = models.CharField(max_length=64, blank=True, default="")
    api_transaction_id = models.CharField(max_length=64, blank=True, default="")
    sales_channel_id = models.CharField(max_length=255, blank=True, default="")
    order_number = models.CharField(max_length=255, blank=True, default="", db_index=True)
    description = models.TextField(blank=True, default="")
    total_price = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    total_tax = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    shipping_costs = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    payment_method = models.CharField(max_length=255, blank=True, default="")
    shipping_method = models.CharField(max_length=255, blank=True, default="")
    order_state = models.CharField(max_length=64, blank=True, default="")
    shipping_state = models.CharField(max_length=64, blank=True, default="")
    payment_state = models.CharField(max_length=64, blank=True, default="")
    purchase_date = models.DateTimeField(null=True, blank=True)
    customer = models.ForeignKey(
        Customer,
        related_name="orders",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
    )
    billing_address = models.ForeignKey(
        Address,
        related_name="billing_orders",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    shipping_address = models.ForeignKey(
        Address,
        related_name="shipping_orders",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )

    class Meta:
        ordering = ("-purchase_date", "-created_at")

    def __str__(self) -> str:
        return self.order_number or self.api_id


class OrderDetail(BaseModel):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="details")
    api_id = models.CharField(max_length=64, blank=True, default="")
    erp_nr = models.CharField(max_length=255, blank=True, default="")
    name = models.CharField(max_length=255, blank=True, default="")
    unit = models.CharField(max_length=64, blank=True, default="")
    quantity = models.IntegerField(default=0)
    unit_price = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    total_price = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    tax = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)

    class Meta:
        ordering = ("order", "id")

    def __str__(self) -> str:
        return f"{self.order_id} | {self.name or self.erp_nr or self.api_id}"
