from django.apps import AppConfig


class EmailsV2Config(AppConfig):
    name = "emails_v2"
    verbose_name = "Email Builder v2"

    def ready(self):
        import emails_v2.signals  # noqa
