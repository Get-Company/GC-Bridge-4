from __future__ import annotations

from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _

from .base import BaseModel


class DatabaseBackup(BaseModel):
    class Status(models.TextChoices):
        QUEUED = "queued", _("Eingereiht")
        RUNNING = "running", _("Laeuft")
        SUCCEEDED = "succeeded", _("Erfolgreich")
        FAILED = "failed", _("Fehlgeschlagen")

    class RestoreStatus(models.TextChoices):
        NOT_REQUESTED = "not_requested", _("Nicht angefordert")
        QUEUED = "queued", _("Eingereiht")
        RUNNING = "running", _("Laeuft")
        SUCCEEDED = "succeeded", _("Erfolgreich")
        FAILED = "failed", _("Fehlgeschlagen")

    label = models.CharField(max_length=255, blank=True, default="", verbose_name=_("Bezeichnung"))
    table_names = models.JSONField(blank=True, default=list, verbose_name=_("Gesicherte Tabellen"))
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.QUEUED,
        db_index=True,
        verbose_name=_("Backup-Status"),
    )
    file_name = models.CharField(max_length=255, blank=True, default="", verbose_name=_("Dateiname"))
    file_size_bytes = models.PositiveBigIntegerField(default=0, verbose_name=_("Dateigroesse (Bytes)"))
    error_message = models.TextField(blank=True, default="", verbose_name=_("Backup-Fehler"))
    started_at = models.DateTimeField(null=True, blank=True, verbose_name=_("Backup gestartet am"))
    completed_at = models.DateTimeField(null=True, blank=True, verbose_name=_("Backup abgeschlossen am"))
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="requested_database_backups",
        editable=False,
        verbose_name=_("Backup angefordert von"),
    )
    restore_table_names = models.JSONField(blank=True, default=list, verbose_name=_("Wiederhergestellte Tabellen"))
    restore_status = models.CharField(
        max_length=16,
        choices=RestoreStatus.choices,
        default=RestoreStatus.NOT_REQUESTED,
        db_index=True,
        verbose_name=_("Wiederherstellungs-Status"),
    )
    restore_error_message = models.TextField(blank=True, default="", verbose_name=_("Wiederherstellungs-Fehler"))
    restore_requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="requested_database_restores",
        editable=False,
        verbose_name=_("Wiederherstellung angefordert von"),
    )
    restore_started_at = models.DateTimeField(null=True, blank=True, verbose_name=_("Wiederherstellung gestartet am"))
    restore_completed_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name=_("Wiederherstellung abgeschlossen am"),
    )

    class Meta:
        verbose_name = _("Datenbank-Backup")
        verbose_name_plural = _("Datenbank-Backups")
        ordering = ("-created_at", "-id")

    def __str__(self) -> str:
        return self.label or f"Backup #{self.pk or '-'}"
