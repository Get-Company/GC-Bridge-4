from pathlib import Path

from django.core.validators import FileExtensionValidator
from django.db import models
from django.template import Context, Template
from django.utils.text import slugify
from django.utils.translation import gettext_lazy as _

from core.models import BaseModel


def document_template_upload_to(instance: "Document", filename: str) -> str:
    extension = Path(filename).suffix.lower() or ".html"
    filename_slug = slugify(instance.slug or instance.title or instance.document_type) or "document-template"
    return f"documents/templates/{filename_slug}{extension}"


class Document(BaseModel):
    class DocumentType(models.TextChoices):
        PRICE_LIST = "price_list", _("Preisliste")
        ORDER_FORM = "order_form", _("Bestellschein")
        TERMS = "terms", _("AGB")
        PRIVACY = "privacy", _("Datenschutzerklaerung")
        IMPRINT = "imprint", _("Impressum")
        OTHER = "other", _("Sonstiges")

    class Slug(models.TextChoices):
        PRICE_LIST = "price_list", _("Preisliste")
        ORDER_FORM = "order_form", _("Bestellschein")

    document_type = models.CharField(
        max_length=40,
        choices=DocumentType.choices,
        default=DocumentType.OTHER,
        db_index=True,
        verbose_name=_("Dokumenttyp"),
    )
    slug = models.SlugField(max_length=120, unique=True, verbose_name=_("Slug"))
    title = models.CharField(max_length=255, verbose_name=_("Titel"))
    template_file = models.FileField(
        upload_to=document_template_upload_to,
        blank=True,
        validators=[FileExtensionValidator(["html", "htm"])],
        verbose_name=_("HTML-Template-Datei"),
        help_text=_("Primaere Vorlage. Eine neue Datei wird ohne Container-Neustart beim Rendern geladen."),
    )
    html_content = models.TextField(blank=True, default="", verbose_name=_("HTML"))
    css_content = models.TextField(blank=True, default="", verbose_name=_("CSS"))
    is_active = models.BooleanField(default=True, db_index=True, verbose_name=_("Aktiv"))
    pdf_filename = models.CharField(
        max_length=255,
        blank=True,
        default="",
        editable=False,
        verbose_name=_("PDF-Dateiname"),
    )
    pdf_generated_at = models.DateTimeField(
        null=True,
        blank=True,
        editable=False,
        verbose_name=_("PDF erzeugt am"),
    )

    class Meta:
        verbose_name = _("Dokument")
        verbose_name_plural = _("Dokumente")
        ordering = ("document_type", "title")

    def __str__(self) -> str:
        return self.title

    def get_template_source(self) -> str:
        if self.template_file:
            self.template_file.open("rb")
            try:
                return self.template_file.read().decode("utf-8")
            finally:
                self.template_file.close()
        return self.html_content

    def render(self, context: dict | None = None) -> str:
        template_context = {**(context or {}), "document": self, "css": self.css_content}
        return Template(self.get_template_source()).render(Context(template_context))
