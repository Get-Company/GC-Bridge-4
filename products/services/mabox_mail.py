from __future__ import annotations

import csv
import os
from datetime import datetime
from io import StringIO

from django.conf import settings
from django.core.mail import EmailMessage, get_connection
from django.utils import timezone

from core.services.base import BaseService
from products.models import MaboxExportSettings
from products.services.mabox_export import MaboxExportService


class MaboxExportMailError(RuntimeError):
    pass


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


class MaboxExportScheduleService(BaseService):
    model = MaboxExportSettings
    task_name = "products.send_mabox_export_email"
    periodic_task_name = "Mabox Produktexport monatlich versenden"

    def synchronize(self, config_id: int = 1) -> None:
        from django_celery_beat.models import CrontabSchedule, PeriodicTask

        config = self.model.objects.filter(pk=config_id).first()
        if config is None:
            PeriodicTask.objects.filter(name=self.periodic_task_name).update(enabled=False)
            return

        schedule, _created = CrontabSchedule.objects.get_or_create(
            minute=str(config.send_minute),
            hour=str(config.send_hour),
            day_of_week="*",
            day_of_month=str(config.send_day),
            month_of_year="*",
            timezone=settings.TIME_ZONE,
        )
        PeriodicTask.objects.update_or_create(
            name=self.periodic_task_name,
            defaults={
                "task": self.task_name,
                "crontab": schedule,
                "interval": None,
                "solar": None,
                "clocked": None,
                "args": "[]",
                "kwargs": "{}",
                "queue": "bulk",
                "enabled": bool(config.is_active and config.recipients),
                "description": (
                    "Erzeugt den aktuellen Mabox-CSV-Export und versendet ihn per E-Mail. "
                    "Zeitplan und Empfänger werden unter Produkte → Mabox-Export gepflegt."
                ),
            },
        )


class MaboxExportMailService(BaseService):
    model = MaboxExportSettings

    def send(self, *, test_mode: bool = False, now: datetime | None = None) -> dict[str, object]:
        config = self.model.load()
        recipients = config.recipients
        if not recipients:
            raise MaboxExportMailError("Es ist kein Mabox-E-Mail-Empfänger konfiguriert.")
        if not config.is_active and not test_mode:
            return {"status": "skipped", "reason": "disabled"}

        now = now or timezone.now()
        if not test_mode and self._was_sent_this_month(config=config, now=now):
            return {"status": "skipped", "reason": "already_sent_this_month"}

        try:
            csv_content = MaboxExportService().render_csv()
            row_count = max(0, sum(1 for _row in csv.reader(StringIO(csv_content))) - 1)
            message = self.build_message(
                config=config,
                csv_content=csv_content,
                recipients=recipients,
                now=now,
                test_mode=test_mode,
            )
            sent_count = message.send(fail_silently=False)
            if sent_count != 1:
                raise MaboxExportMailError("Der E-Mail-Backend hat keinen erfolgreichen Versand gemeldet.")
        except Exception as exc:
            self.model.objects.filter(pk=config.pk).update(last_error=str(exc))
            raise

        update_values = {
            "last_error": "",
            "last_row_count": row_count,
        }
        if not test_mode:
            update_values["last_sent_at"] = now
        self.model.objects.filter(pk=config.pk).update(**update_values)
        return {
            "status": "sent",
            "test_mode": test_mode,
            "recipients": recipients,
            "rows": row_count,
            "filename": self._filename(now),
        }

    def build_message(
        self,
        *,
        config: MaboxExportSettings,
        csv_content: str,
        recipients: list[str],
        now: datetime,
        test_mode: bool,
    ) -> EmailMessage:
        context = {
            "date": timezone.localtime(now).strftime("%d.%m.%Y"),
            "month": timezone.localtime(now).strftime("%m/%Y"),
        }
        subject = self._render_text(config.subject, context)
        if test_mode:
            subject = f"[TEST] {subject}"
        body = self._render_text(config.message, context)
        email = EmailMessage(
            subject=subject,
            body=body,
            from_email=config.from_email or self._default_from_email(),
            to=recipients,
            connection=self._email_connection(),
        )
        email.attach(self._filename(now), csv_content.encode("utf-8"), "text/csv")
        return email

    @staticmethod
    def _render_text(value: str, context: dict[str, str]) -> str:
        rendered = str(value or "")
        for name, replacement in context.items():
            rendered = rendered.replace(f"{{{name}}}", replacement)
        return rendered

    @staticmethod
    def _filename(now: datetime) -> str:
        return f"products_export_mabox_{timezone.localtime(now).date().isoformat()}.csv"

    @staticmethod
    def _was_sent_this_month(*, config: MaboxExportSettings, now: datetime) -> bool:
        if config.last_sent_at is None:
            return False
        last_sent = timezone.localtime(config.last_sent_at)
        current = timezone.localtime(now)
        return (last_sent.year, last_sent.month) == (current.year, current.month)

    @staticmethod
    def _default_from_email() -> str:
        value = os.getenv("DEFAULT_FROM_EMAIL", getattr(settings, "DEFAULT_FROM_EMAIL", "")).strip()
        if not value:
            raise MaboxExportMailError("DEFAULT_FROM_EMAIL ist nicht konfiguriert.")
        return value

    @staticmethod
    def _email_connection():
        backend = os.getenv(
            "EMAIL_BACKEND",
            getattr(settings, "EMAIL_BACKEND", "django.core.mail.backends.smtp.EmailBackend"),
        ).strip()
        if backend != "django.core.mail.backends.smtp.EmailBackend":
            return get_connection(backend=backend)

        use_tls = _env_bool("EMAIL_USE_TLS", getattr(settings, "EMAIL_USE_TLS", False))
        use_ssl = _env_bool("EMAIL_USE_SSL", getattr(settings, "EMAIL_USE_SSL", False))
        if use_tls and use_ssl:
            raise MaboxExportMailError("EMAIL_USE_TLS und EMAIL_USE_SSL dürfen nicht gleichzeitig aktiv sein.")
        return get_connection(
            backend=backend,
            host=os.getenv("EMAIL_HOST", getattr(settings, "EMAIL_HOST", "localhost")),
            port=int(os.getenv("EMAIL_PORT", getattr(settings, "EMAIL_PORT", 25))),
            username=os.getenv("EMAIL_HOST_USER", getattr(settings, "EMAIL_HOST_USER", "")),
            password=os.getenv("EMAIL_HOST_PASSWORD", getattr(settings, "EMAIL_HOST_PASSWORD", "")),
            use_tls=use_tls,
            use_ssl=use_ssl,
            timeout=int(os.getenv("EMAIL_TIMEOUT", "30")),
        )
