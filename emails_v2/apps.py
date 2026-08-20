from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class EmailsV2Config(AppConfig):
    name = "emails_v2"
    verbose_name = _("E-Mail-Builder v2")

    def ready(self):
        import emails_v2.signals  # noqa
