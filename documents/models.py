from pathlib import Path

from django.core.validators import FileExtensionValidator
from django.db import models
from django.db.models import Q
from django.template import Context, Template
from django.utils.text import slugify
from django.utils.translation import gettext_lazy as _

from core.models import BaseModel


def document_template_upload_to(instance: "Document", filename: str) -> str:
    extension = Path(filename).suffix.lower() or ".html"
    filename_slug = slugify(instance.slug or instance.title or instance.document_type) or "document-template"
    return f"documents/templates/{filename_slug}{extension}"


def document_source_docx_upload_to(instance: "Document", filename: str) -> str:
    """Store a DOCX or RTF source file with its original format extension."""

    filename_slug = slugify(instance.slug or instance.title or instance.document_type) or "document-source"
    extension = Path(filename).suffix.lower()
    if extension not in {".docx", ".rtf"}:
        extension = ".docx"
    return f"documents/sources/{filename_slug}{extension}"


def document_cover_pdf_upload_to(instance: "Document", filename: str) -> str:
    slug = slugify(instance.slug or instance.title or "cover") or "cover"
    return f"documents/pdfs/{slug}-cover.pdf"


def document_end_pdf_upload_to(instance: "Document", filename: str) -> str:
    slug = slugify(instance.slug or instance.title or "end") or "end"
    return f"documents/pdfs/{slug}-end.pdf"


class DocumentType(BaseModel):
    """Configurable document type identified by the code stored on documents."""

    DEFAULT_DEFINITIONS = (
        ("price_list", _("Preisliste")),
        ("order_form", _("Bestellschein")),
        ("terms", _("AGB")),
        ("privacy", _("Datenschutzerklärung")),
        ("imprint", _("Impressum")),
        ("other", _("Sonstiges")),
    )

    code = models.SlugField(max_length=40, unique=True, verbose_name=_("Kennung"))
    name = models.CharField(max_length=120, verbose_name=_("Name"))
    settings = models.JSONField(
        blank=True,
        default=dict,
        verbose_name=_("Einstellungen"),
        help_text=_("Freie Einstellungen dieses Dokumenttyps als JSON-Objekt."),
    )
    is_active = models.BooleanField(default=True, db_index=True, verbose_name=_("Aktiv"))

    class Meta:
        verbose_name = _("Dokumenttyp")
        verbose_name_plural = _("Dokumenttypen")
        ordering = ("name", "code")

    def __str__(self) -> str:
        return self.name

    @classmethod
    def ensure_defaults(cls) -> None:
        for code, name in cls.DEFAULT_DEFINITIONS:
            cls.objects.get_or_create(
                code=code,
                defaults={"name": name, "settings": {}, "is_active": True},
            )


class Document(BaseModel):
    class DocumentType(models.TextChoices):
        PRICE_LIST = "price_list", _("Preisliste")
        ORDER_FORM = "order_form", _("Bestellschein")
        TERMS = "terms", _("AGB")
        PRIVACY = "privacy", _("Datenschutzerklärung")
        IMPRINT = "imprint", _("Impressum")
        OTHER = "other", _("Sonstiges")

    class Slug(models.TextChoices):
        PRICE_LIST = "price_list", _("Preisliste")
        ORDER_FORM = "order_form", _("Bestellschein")

    document_type = models.CharField(
        max_length=40,
        default=DocumentType.OTHER,
        db_index=True,
        verbose_name=_("Dokumenttyp"),
        help_text=_("Wird im Dokument-Admin aus den gepflegten Dokumenttypen ausgewählt."),
    )
    slug = models.SlugField(max_length=120, unique=True, verbose_name=_("Slug"))
    title = models.CharField(max_length=255, verbose_name=_("Titel"))
    template_file = models.FileField(
        upload_to=document_template_upload_to,
        blank=True,
        validators=[FileExtensionValidator(["html", "htm"])],
        verbose_name=_("HTML-Template-Datei"),
        help_text=_("Primäre Vorlage. Eine neue Datei wird ohne Container-Neustart beim Rendern geladen."),
    )
    source_docx = models.FileField(
        upload_to=document_source_docx_upload_to,
        blank=True,
        validators=[FileExtensionValidator(["docx", "rtf"])],
        verbose_name=_("DOCX-/RTF-Quelldatei"),
        help_text=_("Optional: zum Herunterladen und Bearbeiten im jeweiligen Programm hinterlegen."),
    )
    html_content = models.TextField(blank=True, default="", verbose_name=_("HTML"))
    css_content = models.TextField(blank=True, default="", verbose_name=_("CSS"))
    price_list_duplicate_categories = models.ManyToManyField(
        "products.Category",
        blank=True,
        limit_choices_to={"is_active": True},
        related_name="price_list_duplicate_documents",
        verbose_name=_("Kategorien mit Doppelauflistung"),
        help_text=_(
            "Artikel aus diesen Kategorien und ihren Unterkategorien dürfen in einer Preisliste "
            "zusätzlich zu ihrer regulären Kategorie erscheinen."
        ),
    )
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
    cover_pdf = models.FileField(
        upload_to=document_cover_pdf_upload_to,
        blank=True,
        validators=[FileExtensionValidator(["pdf"])],
        verbose_name=_("Cover-PDF"),
        help_text=_("Wird dem generierten PDF vorangestellt."),
    )
    end_pdf = models.FileField(
        upload_to=document_end_pdf_upload_to,
        blank=True,
        validators=[FileExtensionValidator(["pdf"])],
        verbose_name=_("End-PDF"),
        help_text=_("Wird dem generierten PDF angehängt."),
    )
    use_jinja2 = models.BooleanField(
        default=True,
        verbose_name=_("Jinja2-Engine"),
        help_text=_("Jinja2 erlaubt DB-Zugriff im Template, z. B. Product.objects.get(erp_nr='123')."),
    )
    shopware_cms_page_id = models.CharField(
        max_length=64,
        blank=True,
        default="",
        verbose_name=_("Shopware Erlebniswelt-ID"),
        help_text=_("Optional: Die Erlebniswelt wird im Dokument-Admin aus Shopware ausgewählt."),
    )
    shopware_media_id = models.CharField(
        max_length=64,
        blank=True,
        default="",
        verbose_name=_("Shopware Media-ID"),
        help_text=_("Die PDF-Mediendatei wird im Dokument-Admin aus Shopware ausgewählt."),
    )
    shopware_media_folder_id = models.CharField(
        max_length=64,
        blank=True,
        default="",
        verbose_name=_("Shopware Medienordner-ID"),
        help_text=_("Optionaler Zielordner der PDF-Datei. Ohne Auswahl bleibt der Ordner in Shopware unverändert."),
    )
    active_version = models.ForeignKey(
        "DocumentVersion",
        on_delete=models.SET_NULL,
        related_name="active_for_documents",
        null=True,
        blank=True,
        editable=False,
        verbose_name=_("Aktive Version"),
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

    def get_document_type_settings(self) -> dict:
        """Return a copy of the selected type's configurable settings."""

        if not self.pk or not self.document_type:
            return {}
        settings = (
            DocumentType.objects.filter(code=self.document_type)
            .values_list("settings", flat=True)
            .first()
        )
        return dict(settings) if isinstance(settings, dict) else {}

    def render(self, context: dict | None = None) -> str:
        render_context = context or {}
        # A document's saved CSS is authoritative.  The service can still pass
        # its default price-list CSS when this field is intentionally empty.
        css_content = self.css_content or render_context.get("css", "")
        ctx = {
            "document": self,
            "document_type_settings": self.get_document_type_settings(),
            **render_context,
            "css": css_content,
        }
        source = self.get_template_source()
        if self.use_jinja2:
            from documents.jinja2_env import build_env
            return build_env().from_string(source).render(**ctx)
        return Template(source).render(Context(ctx))


class DocumentVersion(BaseModel):
    """Immutable template snapshot that can be activated for a document."""

    document = models.ForeignKey(
        Document,
        on_delete=models.CASCADE,
        related_name="versions",
        verbose_name=_("Dokument"),
    )
    version_number = models.PositiveIntegerField(verbose_name=_("Version"))
    label = models.CharField(max_length=255, blank=True, default="", verbose_name=_("Bezeichnung"))
    template_source = models.TextField(verbose_name=_("HTML-Vorlage"))
    css_content = models.TextField(blank=True, default="", verbose_name=_("CSS"))
    use_jinja2 = models.BooleanField(default=True, verbose_name=_("Jinja2-Engine"))
    is_active = models.BooleanField(default=False, db_index=True, verbose_name=_("Aktiv"))
    activated_at = models.DateTimeField(null=True, blank=True, editable=False, verbose_name=_("Aktiviert am"))

    class Meta:
        verbose_name = _("Dokumentversion")
        verbose_name_plural = _("Dokumentversionen")
        ordering = ("document", "-version_number")
        constraints = [
            models.UniqueConstraint(
                fields=("document", "version_number"),
                name="documents_unique_document_version_number",
            ),
            models.UniqueConstraint(
                fields=("document",),
                condition=Q(is_active=True),
                name="documents_one_active_version_per_document",
            ),
        ]

    def __str__(self) -> str:
        label = f" · {self.label}" if self.label else ""
        return f"{self.document} · V{self.version_number}{label}"
