from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class IssuesConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "issues"
    verbose_name = _("Fehlermeldungen")

    def ready(self) -> None:
        from issues import signals  # noqa: F401
