from django.db import models
from django.utils.translation import gettext_lazy as _


class BaseModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True, editable=False, verbose_name=_("Angelegt am"))
    updated_at = models.DateTimeField(auto_now=True, editable=False, verbose_name=_("Aktualisiert am"))

    class Meta:
        abstract = True
