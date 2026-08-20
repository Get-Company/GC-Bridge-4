from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class ShopwareConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "shopware"
    verbose_name = _("Shopware")
