from pathlib import Path

from django.core.validators import FileExtensionValidator, MaxValueValidator, MinValueValidator, RegexValidator
from django.db import models
from django.utils.text import slugify
from django.utils.translation import gettext_lazy as _

from core.models import BaseModel

hex_color_validator = RegexValidator(
    regex=r"^#[0-9a-fA-F]{6}$",
    message=_("Bitte eine gueltige Hex-Farbe im Format #RRGGBB eingeben."),
)


def qr_center_image_upload_to(instance: "QrCode", filename: str) -> str:
    extension = Path(filename).suffix.lower() or ".png"
    filename_slug = slugify(instance.title or "qr-code") or "qr-code"
    return f"qrcodes/center-images/{filename_slug}{extension}"


class QrCode(BaseModel):
    class CenterMode(models.TextChoices):
        NONE = "none", _("Ohne Inhalt")
        IMAGE = "image", _("Bild")
        TEXT = "text", _("Text")

    title = models.CharField(max_length=180, verbose_name=_("Titel"))
    target_url = models.URLField(max_length=2048, verbose_name=_("Ziel-URL"))
    description = models.TextField(blank=True, default="", verbose_name=_("Beschreibung"))
    center_mode = models.CharField(
        max_length=12,
        choices=CenterMode.choices,
        default=CenterMode.NONE,
        verbose_name=_("Mitte"),
    )
    center_image = models.ImageField(
        upload_to=qr_center_image_upload_to,
        blank=True,
        validators=[FileExtensionValidator(["jpg", "jpeg", "png", "webp"])],
        verbose_name=_("Bild in der Mitte"),
    )
    center_text = models.CharField(max_length=80, blank=True, default="", verbose_name=_("Text in der Mitte"))
    foreground_color = models.CharField(
        max_length=7,
        default="#111827",
        validators=[hex_color_validator],
        verbose_name=_("QR-Farbe"),
    )
    background_color = models.CharField(
        max_length=7,
        default="#ffffff",
        validators=[hex_color_validator],
        verbose_name=_("Hintergrundfarbe"),
    )
    center_scale_percent = models.PositiveSmallIntegerField(
        default=24,
        validators=[MinValueValidator(12), MaxValueValidator(32)],
        verbose_name=_("Groesse der Mitte in Prozent"),
        help_text=_("Empfohlen: 18 bis 26 Prozent. Groessere Werte koennen die Lesbarkeit reduzieren."),
    )
    is_active = models.BooleanField(default=True, db_index=True, verbose_name=_("Aktiv"))

    class Meta:
        verbose_name = _("QR-Code")
        verbose_name_plural = _("QR-Codes")
        ordering = ("title",)

    def __str__(self) -> str:
        return self.title
