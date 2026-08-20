from __future__ import annotations

from django.db import models
from django.utils.translation import gettext_lazy as _


class SyncEventLog(models.Model):
    """Persistenter Audit-Trail nur für fehlgeschlagene/übersprungene Sync-Items."""

    class Status(models.TextChoices):
        ERROR = "error", _("Fehler")
        SKIPPED = "skipped", _("Übersprungen")

    created_at = models.DateTimeField(auto_now_add=True, db_index=True, verbose_name=_("Erstellt am"))
    task = models.CharField(max_length=120, db_index=True, verbose_name=_("Task"))
    run_id = models.CharField(max_length=64, blank=True, default="", db_index=True, verbose_name=_("Lauf-ID"))
    entity = models.CharField(max_length=120, blank=True, default="", verbose_name=_("Entität"))
    target = models.CharField(max_length=40, blank=True, default="", verbose_name=_("Zielsystem"))
    step = models.CharField(max_length=120, blank=True, default="", verbose_name=_("Schritt"))
    status = models.CharField(max_length=16, choices=Status.choices, verbose_name=_("Status"))
    message = models.TextField(blank=True, default="", verbose_name=_("Meldung"))
    payload = models.JSONField(null=True, blank=True, verbose_name=_("Nutzdaten"))

    class Meta:
        verbose_name = _("Sync-Ereignis")
        verbose_name_plural = _("Sync-Ereignisse")
        ordering = ("-created_at",)

    def __str__(self) -> str:
        return f"[{self.status}] {self.task} {self.entity}".strip()
