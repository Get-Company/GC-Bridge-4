from __future__ import annotations

from pathlib import Path

from django.conf import settings
from django.core.validators import FileExtensionValidator
from django.db import models
from django.utils.text import slugify
from django.utils.translation import gettext_lazy as _

from core.models import BaseModel


def issue_error_upload_to(instance: "Issue", filename: str) -> str:
    extension = Path(filename).suffix.lower() or ".txt"
    issue_slug = slugify(instance.title or "issue") or "issue"
    return f"issues/{issue_slug}/error{extension}"


def issue_attachment_upload_to(instance: "IssueAttachment", filename: str) -> str:
    extension = Path(filename).suffix.lower()
    issue_slug = slugify(instance.issue.title or "issue") or "issue"
    file_slug = slugify(Path(filename).stem) or "attachment"
    return f"issues/{issue_slug}/attachments/{file_slug}{extension}"


class IssueCategory(BaseModel):
    name = models.CharField(max_length=120, unique=True, verbose_name=_("Name"))
    description = models.TextField(blank=True, default="", verbose_name=_("Beschreibung"))
    color = models.CharField(max_length=20, blank=True, default="#64748b", verbose_name=_("Farbe"))
    is_active = models.BooleanField(default=True, db_index=True, verbose_name=_("Aktiv"))

    class Meta:
        verbose_name = _("Issue-Kategorie")
        verbose_name_plural = _("Issue-Kategorien")
        ordering = ("name",)

    def __str__(self) -> str:
        return self.name


class Issue(BaseModel):
    class Status(models.TextChoices):
        OPEN = "open", _("Offen")
        IN_PROGRESS = "in_progress", _("In Bearbeitung")
        WAITING = "waiting", _("Wartet")
        RESOLVED = "resolved", _("Erledigt")
        CLOSED = "closed", _("Geschlossen")

    class Priority(models.TextChoices):
        LOW = "low", _("Niedrig")
        NORMAL = "normal", _("Normal")
        HIGH = "high", _("Hoch")
        URGENT = "urgent", _("Dringend")

    title = models.CharField(
        max_length=255,
        verbose_name=_("Kurzbeschreibung"),
        help_text=_("Ein kurzer Satz reicht. Details, Link oder Screenshots koennen unten ergaenzt werden."),
    )
    category = models.ForeignKey(
        IssueCategory,
        on_delete=models.SET_NULL,
        related_name="issues",
        null=True,
        blank=True,
        verbose_name=_("Kategorie"),
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.OPEN,
        db_index=True,
        verbose_name=_("Status"),
    )
    priority = models.CharField(
        max_length=20,
        choices=Priority.choices,
        default=Priority.NORMAL,
        db_index=True,
        verbose_name=_("Prioritaet"),
    )
    reported_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="reported_issues",
        null=True,
        blank=True,
        editable=False,
        verbose_name=_("Gemeldet von"),
    )
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="assigned_issues",
        null=True,
        blank=True,
        verbose_name=_("Zugewiesen an"),
    )
    description = models.TextField(
        blank=True,
        default="",
        verbose_name=_("Beschreibung"),
        help_text=_("Optional: Was ist passiert? Was wurde erwartet?"),
    )
    source_url = models.URLField(
        max_length=500,
        blank=True,
        default="",
        verbose_name=_("Link"),
        help_text=_("Optional: Seite, Admin-Link, Shopware-Link oder externe Referenz."),
    )
    error_text = models.TextField(
        blank=True,
        default="",
        verbose_name=_("Fehlertext"),
        help_text=_("Optional: Fehlermeldung, Stacktrace oder kopierter Logauszug."),
    )
    error_file = models.FileField(
        upload_to=issue_error_upload_to,
        blank=True,
        validators=[FileExtensionValidator(["txt", "log", "json", "xml", "html", "csv"])],
        verbose_name=_("Fehlertext-Datei"),
        help_text=_("Optional: Datei mit Fehlermeldung oder Logauszug."),
    )

    class Meta:
        verbose_name = _("Issue")
        verbose_name_plural = _("Issues")
        ordering = ("-created_at", "-id")

    def __str__(self) -> str:
        return self.title


class IssueAttachment(BaseModel):
    class AttachmentType(models.TextChoices):
        SCREENSHOT = "screenshot", _("Screenshot")
        ERROR_FILE = "error_file", _("Fehlerdatei")
        OTHER = "other", _("Sonstiges")

    issue = models.ForeignKey(
        Issue,
        on_delete=models.CASCADE,
        related_name="attachments",
        verbose_name=_("Issue"),
    )
    attachment_type = models.CharField(
        max_length=20,
        choices=AttachmentType.choices,
        default=AttachmentType.SCREENSHOT,
        verbose_name=_("Art"),
    )
    file = models.FileField(
        upload_to=issue_attachment_upload_to,
        validators=[
            FileExtensionValidator(["png", "jpg", "jpeg", "webp", "gif", "pdf", "txt", "log", "json"])
        ],
        verbose_name=_("Datei"),
        help_text=_("Screenshot, PDF oder Fehlerdatei."),
    )
    caption = models.CharField(max_length=255, blank=True, default="", verbose_name=_("Hinweis"))

    class Meta:
        verbose_name = _("Issue-Anhang")
        verbose_name_plural = _("Issue-Anhaenge")
        ordering = ("created_at", "id")

    def __str__(self) -> str:
        return self.caption or Path(self.file.name).name
