from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class QrcodesConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "qrcodes"
    verbose_name = _("QR-Codes")
