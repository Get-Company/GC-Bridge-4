from django.db import models

from core.models import BaseModel


class Product(BaseModel):
    sku = models.CharField(max_length=64, unique=True)
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ("sku",)

    def __str__(self) -> str:
        return f"{self.sku} - {self.name}"
