from django.db import models
from django.db.models import Q
from django.utils.translation import gettext_lazy as _

from core.models import BaseModel


class CompanyProfile(BaseModel):
    name = models.CharField(max_length=255, blank=True, default="", verbose_name=_("Firmenname"))
    legal_name = models.CharField(max_length=255, blank=True, default="", verbose_name=_("Rechtlicher Name"))
    tagline = models.CharField(max_length=255, blank=True, default="", verbose_name=_("Kurzbeschreibung"))
    logo = models.ImageField(upload_to="organization/logos/", blank=True, verbose_name=_("Logo"))
    logo_alt_text = models.CharField(max_length=255, blank=True, default="", verbose_name=_("Logo Alternativtext"))
    street = models.CharField(max_length=255, blank=True, default="", verbose_name=_("Strasse und Hausnummer"))
    postal_code = models.CharField(max_length=20, blank=True, default="", verbose_name=_("PLZ"))
    city = models.CharField(max_length=120, blank=True, default="", verbose_name=_("Ort"))
    region = models.CharField(max_length=120, blank=True, default="", verbose_name=_("Region/Kanton"))
    country = models.CharField(max_length=120, blank=True, default="", verbose_name=_("Land"))
    phone = models.CharField(max_length=80, blank=True, default="", verbose_name=_("Telefon"))
    email = models.EmailField(blank=True, default="", verbose_name=_("E-Mail"))
    website = models.URLField(blank=True, default="", verbose_name=_("Webseite"))
    vat_id = models.CharField(max_length=80, blank=True, default="", verbose_name=_("USt-IdNr."))
    tax_number = models.CharField(max_length=80, blank=True, default="", verbose_name=_("Steuernummer"))
    commercial_register = models.CharField(max_length=255, blank=True, default="", verbose_name=_("Handelsregister"))
    register_court = models.CharField(max_length=255, blank=True, default="", verbose_name=_("Registergericht"))
    managing_directors = models.TextField(blank=True, default="", verbose_name=_("Geschaeftsfuehrung"))
    bank_details = models.TextField(blank=True, default="", verbose_name=_("Bankverbindung"))
    notes = models.TextField(blank=True, default="", verbose_name=_("Interne Notizen"))

    class Meta:
        verbose_name = _("Firmendaten")
        verbose_name_plural = _("Firmendaten")

    def __str__(self) -> str:
        return self.name or self.legal_name or "Firmendaten"

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)

    @classmethod
    def load(cls) -> "CompanyProfile":
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj


class OrganizationRole(BaseModel):
    name = models.CharField(max_length=120, unique=True, verbose_name=_("Rolle"))
    code = models.SlugField(max_length=80, unique=True, verbose_name=_("Code"))
    description = models.TextField(blank=True, default="", verbose_name=_("Beschreibung"))
    is_active = models.BooleanField(default=True, verbose_name=_("Aktiv"))
    sort_order = models.PositiveIntegerField(default=1000, db_index=True, verbose_name=_("Sortierung"))

    class Meta:
        verbose_name = _("Ansprechpartner-Rolle")
        verbose_name_plural = _("Ansprechpartner-Rollen")
        ordering = ("sort_order", "name")

    def __str__(self) -> str:
        return self.name


class OrganizationContact(BaseModel):
    company = models.ForeignKey(
        CompanyProfile,
        on_delete=models.CASCADE,
        related_name="contacts",
        default=1,
        verbose_name=_("Firma"),
    )
    employee_profile = models.ForeignKey(
        "hr.EmployeeProfile",
        on_delete=models.CASCADE,
        related_name="organization_contacts",
        verbose_name=_("Mitarbeiterprofil"),
    )
    role = models.ForeignKey(
        OrganizationRole,
        on_delete=models.PROTECT,
        related_name="contacts",
        verbose_name=_("Rolle"),
    )
    title = models.CharField(max_length=120, blank=True, default="", verbose_name=_("Titel/Funktion"))
    public_email = models.EmailField(blank=True, default="", verbose_name=_("Oeffentliche E-Mail"))
    public_phone = models.CharField(max_length=80, blank=True, default="", verbose_name=_("Oeffentliches Telefon"))
    is_primary = models.BooleanField(default=False, verbose_name=_("Primaerer Ansprechpartner"))
    is_public = models.BooleanField(default=True, verbose_name=_("Oeffentlich sichtbar"))
    sort_order = models.PositiveIntegerField(default=1000, db_index=True, verbose_name=_("Sortierung"))
    notes = models.TextField(blank=True, default="", verbose_name=_("Interne Notizen"))

    class Meta:
        verbose_name = _("Ansprechpartner")
        verbose_name_plural = _("Ansprechpartner")
        ordering = ("sort_order", "role__name", "employee_profile__user__last_name")
        constraints = [
            models.UniqueConstraint(
                fields=("company", "employee_profile", "role"),
                name="unique_organization_contact_role",
            ),
            models.UniqueConstraint(
                fields=("company", "role"),
                condition=Q(is_primary=True),
                name="unique_primary_organization_contact_per_role",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.employee_profile} - {self.role}"

    @property
    def display_email(self) -> str:
        return self.public_email or self.employee_profile.user.email

    @property
    def display_phone(self) -> str:
        return self.public_phone or self.employee_profile.phone


class LegalDocument(BaseModel):
    class DocumentType(models.TextChoices):
        TERMS = "terms", _("AGB")
        IMPRINT = "imprint", _("Impressum")
        PRIVACY = "privacy", _("Datenschutz")
        OTHER = "other", _("Sonstiges")

    company = models.ForeignKey(
        CompanyProfile,
        on_delete=models.CASCADE,
        related_name="legal_documents",
        default=1,
        verbose_name=_("Firma"),
    )
    document_type = models.CharField(max_length=30, choices=DocumentType.choices, verbose_name=_("Dokumenttyp"))
    title = models.CharField(max_length=255, verbose_name=_("Titel"))
    version = models.CharField(max_length=50, blank=True, default="", verbose_name=_("Version"))
    valid_from = models.DateField(null=True, blank=True, verbose_name=_("Gueltig ab"))
    content = models.TextField(blank=True, default="", verbose_name=_("Inhalt"))
    is_active = models.BooleanField(default=True, verbose_name=_("Aktiv"))

    class Meta:
        verbose_name = _("Rechtstext")
        verbose_name_plural = _("Rechtstexte")
        ordering = ("document_type", "-valid_from", "-updated_at")
        constraints = [
            models.UniqueConstraint(
                fields=("company", "document_type"),
                condition=Q(is_active=True),
                name="unique_active_legal_document_per_type",
            ),
        ]

    def __str__(self) -> str:
        suffix = f" ({self.version})" if self.version else ""
        return f"{self.get_document_type_display()}: {self.title}{suffix}"
