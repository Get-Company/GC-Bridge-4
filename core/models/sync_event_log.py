from __future__ import annotations

from django.db import models
from django.utils.translation import gettext_lazy as _


class SyncEventLog(models.Model):
    """Persistenter Audit-Trail nur für fehlgeschlagene/übersprungene Sync-Items."""

    class Status(models.TextChoices):
        ERROR = "error", _("Fehler")
        SKIPPED = "skipped", _("Übersprungen")

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    task = models.CharField(max_length=120, db_index=True, verbose_name=_("Task"))
    run_id = models.CharField(max_length=64, blank=True, default="", db_index=True)
    entity = models.CharField(max_length=120, blank=True, default="")
    target = models.CharField(max_length=40, blank=True, default="")
    step = models.CharField(max_length=120, blank=True, default="")
    status = models.CharField(max_length=16, choices=Status.choices)
    message = models.TextField(blank=True, default="")
    payload = models.JSONField(null=True, blank=True)

    class Meta:
        verbose_name = _("Sync-Ereignis")
        verbose_name_plural = _("Sync-Ereignisse")
        ordering = ("-created_at",)

    def __str__(self) -> str:
        return f"[{self.status}] {self.task} {self.entity}".strip()
