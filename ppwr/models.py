from django.db import models
from django.utils.text import slugify
from django.utils.translation import gettext_lazy as _

from core.models.base import BaseModel


class PackagingLabel(BaseModel):
    name = models.CharField(max_length=255, verbose_name=_("Name"))
    slug = models.SlugField(max_length=255, unique=True, verbose_name=_("Slug"))
    company = models.ForeignKey(
        "organization.CompanyProfile",
        on_delete=models.PROTECT,
        related_name="packaging_labels",
        default=1,
        verbose_name=_("Firmendaten"),
    )
    qr_code = models.ForeignKey(
        "qrcodes.QrCode",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="packaging_labels",
        verbose_name=_("QR-Code"),
    )
    unique_packaging_id = models.CharField(
        max_length=255,
        verbose_name=_("Eindeutiges Identifikationsmerkmal"),
        help_text=_("Pflichtangabe nach PPWR Art. 11 – eindeutige Kennzeichnung der Verpackungseinheit."),
    )
    canvas_width_mm = models.PositiveSmallIntegerField(
        default=100,
        verbose_name=_("Breite (mm)"),
    )
    canvas_height_mm = models.PositiveSmallIntegerField(
        default=60,
        verbose_name=_("Höhe (mm)"),
    )
    layout_data = models.JSONField(
        default=list,
        verbose_name=_("Layout"),
        help_text=_("Blockpositionen und -größen in mm als JSON. Wird vom Editor verwaltet."),
    )
    pdf_filename = models.CharField(max_length=255, blank=True, default="", verbose_name=_("PDF-Dateiname"))
    pdf_generated_at = models.DateTimeField(null=True, blank=True, verbose_name=_("PDF erstellt am"))
    notes = models.TextField(blank=True, default="", verbose_name=_("Notizen"))

    class Meta:
        verbose_name = _("Verpackungsetikett")
        verbose_name_plural = _("Verpackungsetiketten")
        ordering = ("name",)

    def __str__(self) -> str:
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name) or f"etikett-{self.pk or 'neu'}"
        super().save(*args, **kwargs)


class KonformitaetsErklaerung(BaseModel):
    packaging_label = models.OneToOneField(
        PackagingLabel,
        on_delete=models.CASCADE,
        related_name="konformitaetserklaerung",
        verbose_name=_("Verpackungsetikett"),
    )
    declaration_number = models.CharField(
        max_length=100,
        verbose_name=_("Erklärungsnummer"),
        help_text=_("Anhang VIII, Kopf: Eindeutige Kennnummer der Erklärung."),
    )
    erzeuger_name_anschrift = models.TextField(
        verbose_name=_("Name und Anschrift des Erzeugers"),
        help_text=_("Anhang VIII, Nr. 2: Name, Anschrift und ggf. Bevollmächtigter des Erzeugers."),
    )
    gegenstand_beschreibung = models.TextField(
        verbose_name=_("Beschreibung der Verpackung"),
        help_text=_("Anhang VIII, Nr. 4: Kennung der Verpackung zwecks Rückverfolgbarkeit."),
    )
    harmonisierung = models.TextField(
        verbose_name=_("Harmonisierung"),
        help_text=_("Anhang VIII, Nr. 5: Verweis auf die angewandten Rechtsakte der Union, z. B. PPWR (EU) 2025/..."),
    )
    normen_spezifikationen = models.TextField(
        verbose_name=_("Normen / Spezifikationen"),
        help_text=_("Anhang VIII, Nr. 6: Harmonisierte Normen oder gemeinsame Spezifikationen."),
    )
    notifizierte_stelle = models.TextField(
        blank=True,
        default="",
        verbose_name=_("Notifizierte Stelle"),
        help_text=_("Anhang VIII, Nr. 7: Name, Anschrift, Kennnummer der notifizierten Stelle (falls anwendbar)."),
    )
    zusaetzliche_angaben = models.TextField(
        blank=True,
        default="",
        verbose_name=_("Zusätzliche Angaben"),
        help_text=_("Anhang VIII, Nr. 8: Optionale weitere Angaben."),
    )
    ausstellungsort = models.CharField(
        max_length=255,
        verbose_name=_("Ausstellungsort"),
    )
    ausstellungsdatum = models.DateField(
        verbose_name=_("Ausstellungsdatum"),
    )
    unterzeichner_name = models.CharField(
        max_length=255,
        verbose_name=_("Name des Unterzeichners"),
    )
    unterzeichner_funktion = models.CharField(
        max_length=255,
        verbose_name=_("Funktion des Unterzeichners"),
    )
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
        verbose_name=_("PDF erstellt am"),
    )

    class Meta:
        verbose_name = _("EU-Konformitätserklärung")
        verbose_name_plural = _("EU-Konformitätserklärungen")
        ordering = ("-ausstellungsdatum",)

    def __str__(self) -> str:
        return self.declaration_number
