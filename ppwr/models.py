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
