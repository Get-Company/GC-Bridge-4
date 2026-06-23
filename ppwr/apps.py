from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class PpwrConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "ppwr"
    verbose_name = _("PPWR-Etiketten")
