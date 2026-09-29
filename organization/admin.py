from django.contrib import admin
from django.contrib import messages
from django.contrib.admin.models import ADDITION, CHANGE, DELETION, LogEntry
from django.forms import PasswordInput
from django.http import HttpResponseRedirect
from django.urls import reverse
from django.utils.html import format_html
from django.utils.translation import gettext_lazy as _

from unfold.contrib.filters.admin import BooleanRadioFilter
from unfold.decorators import action
from unfold.enums import ActionVariant

from core.admin import BaseAdmin, BaseTabularInline
from organization.models import CompanyProfile, LegalDocument, OrganizationContact, OrganizationRole
from organization.services import OrganizationContactSmtpService


class SingletonAdmin(BaseAdmin):
    """Admin base for singleton models: the changelist redirects straight to the single edit form."""

    def changelist_view(self, request, extra_context=None):
        obj = self.model.load()
        url = reverse(
            f"admin:{self.model._meta.app_label}_{self.model._meta.model_name}_change",
            args=(obj.pk,),
        )
        return HttpResponseRedirect(url)

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


class OrganizationContactInline(BaseTabularInline):
    model = OrganizationContact
    fields = (
        "employee_profile",
        "role",
        "title",
        "public_email",
        "public_phone",
        "is_primary",
        "is_public",
        "sort_order",
        "created_at",
        "updated_at",
    )
    autocomplete_fields = ("employee_profile", "role")
    ordering = ("sort_order", "role__name")


class LegalDocumentInline(BaseTabularInline):
    model = LegalDocument
    fields = ("document_type", "title", "version", "valid_from", "is_active", "created_at", "updated_at")
    ordering = ("document_type", "-valid_from")


@admin.register(CompanyProfile)
class CompanyProfileAdmin(SingletonAdmin):
    search_fields = ("name", "legal_name", "city", "email")
    readonly_fields = BaseAdmin.readonly_fields + ("logo_preview",)
    inlines = (OrganizationContactInline, LegalDocumentInline)
    fieldsets = (
        (
            "Allgemein",
            {
                "fields": ("name", "legal_name", "tagline", "logo", "logo_preview", "logo_alt_text"),
            },
        ),
        (
            "Adresse",
            {
                "fields": ("street", "postal_code", "city", "region", "country"),
            },
        ),
        (
            "Kontakt",
            {
                "fields": ("phone", "email", "website"),
            },
        ),
        (
            "Rechtliches",
            {
                "fields": (
                    "vat_id",
                    "tax_number",
                    "commercial_register",
                    "register_court",
                    "managing_directors",
                ),
            },
        ),
        (
            "Intern",
            {
                "fields": ("bank_details", "notes"),
            },
        ),
    )

    @admin.display(description="Logo")
    def logo_preview(self, obj):
        if not obj or not obj.logo:
            return "-"
        return format_html('<img src="{}" style="max-height: 80px; width: auto;" alt="">', obj.logo.url)


@admin.register(OrganizationRole)
class OrganizationRoleAdmin(BaseAdmin):
    list_display = ("name", "code", "is_active", "sort_order", "updated_at")
    list_editable = ("is_active", "sort_order")
    search_fields = ("name", "code", "description")
    list_filter = [("is_active", BooleanRadioFilter)]
    ordering = ("sort_order", "name")


@admin.register(OrganizationContact)
class OrganizationContactAdmin(BaseAdmin):
    actions_detail = ("test_smtp_connection",)
    list_display = (
        "employee_profile",
        "role",
        "title",
        "display_email",
        "display_phone",
        "is_primary",
        "is_public",
        "smtp_status",
        "sort_order",
    )
    list_editable = ("is_primary", "is_public", "sort_order")
    search_fields = (
        "employee_profile__user__username",
        "employee_profile__user__first_name",
        "employee_profile__user__last_name",
        "employee_profile__employee_number",
        "role__name",
        "title",
        "public_email",
    )
    list_filter = [
        ("role", admin.RelatedOnlyFieldListFilter),
        ("is_primary", BooleanRadioFilter),
        ("is_public", BooleanRadioFilter),
    ]
    autocomplete_fields = ("company", "employee_profile", "role")
    ordering = ("sort_order", "role__name", "employee_profile__user__last_name")
    fieldsets = (
        (
            "Ansprechpartner",
            {
                "fields": (
                    "company",
                    "employee_profile",
                    "role",
                    "title",
                    "public_email",
                    "public_phone",
                    "is_primary",
                    "is_public",
                    "sort_order",
                    "notes",
                )
            },
        ),
        (
            "SMTP-Versand",
            {
                "fields": (
                    "smtp_host",
                    "smtp_port",
                    "smtp_security",
                    "smtp_username",
                    "smtp_password",
                    "smtp_sender_email",
                    "smtp_timeout",
                ),
                "description": (
                    "Diese Zugangsdaten werden verwendet, wenn der Ansprechpartner "
                    "als Absender eines automatischen Exports ausgewählt wird."
                ),
            },
        ),
        (
            "System",
            {
                "fields": BaseAdmin.readonly_fields,
                "classes": ("collapse",),
            },
        ),
    )

    @admin.display(boolean=True, description="SMTP eingerichtet")
    def smtp_status(self, obj: OrganizationContact) -> bool:
        return obj.smtp_is_configured

    def formfield_for_dbfield(self, db_field, request, **kwargs):
        if db_field.name == "smtp_password":
            kwargs["widget"] = PasswordInput(render_value=True)
        return super().formfield_for_dbfield(db_field, request, **kwargs)

    @action(
        description="SMTP-Verbindung testen",
        icon="wifi_tethering",
        variant=ActionVariant.PRIMARY,
    )
    def test_smtp_connection(self, request, object_id: str):
        contact = self.get_object(request, object_id)
        if contact is None:
            self.message_user(request, "Ansprechpartner nicht gefunden.", level=messages.ERROR)
            return self._redirect_to_changelist()
        try:
            OrganizationContactSmtpService().test_connection(contact)
        except Exception as exc:
            self.message_user(
                request,
                f"SMTP-Verbindung fehlgeschlagen: {exc}",
                level=messages.ERROR,
            )
        else:
            self.message_user(
                request,
                "SMTP-Verbindung und Anmeldung waren erfolgreich.",
                level=messages.SUCCESS,
            )
        return HttpResponseRedirect(request.path)


_ACTION_ICONS = {
    ADDITION: ("add_circle", "success"),
    CHANGE: ("edit", "warning"),
    DELETION: ("delete", "error"),
}
_ACTION_LABELS = {
    ADDITION: _("Erstellt"),
    CHANGE: _("Geändert"),
    DELETION: _("Gelöscht"),
}


@admin.register(LogEntry)
class AdminActivityAdmin(BaseAdmin):
    """Superuser-only history viewer for all admin backend activity."""

    list_display = (
        "action_time",
        "user",
        "content_type",
        "object_repr",
        "action_badge",
        "change_message",
    )
    list_filter = ("action_flag", "content_type", "user")
    search_fields = ("user__username", "user__first_name", "user__last_name", "object_repr", "change_message")
    date_hierarchy = "action_time"
    ordering = ("-action_time",)
    readonly_fields = ("action_time", "user", "content_type", "object_id", "object_repr", "action_flag", "change_message")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser

    def has_view_permission(self, request, obj=None):
        return request.user.is_superuser

    def has_module_perms(self, request):
        return request.user.is_superuser

    @admin.display(description=_("Aktion"))
    def action_badge(self, obj):
        icon, color = _ACTION_ICONS.get(obj.action_flag, ("help", "default"))
        label = _ACTION_LABELS.get(obj.action_flag, "?")
        return format_html(
            '<span style="display:inline-flex;align-items:center;gap:4px;">'
            '<span class="material-symbols-outlined" style="font-size:16px;">{}</span>{}'
            "</span>",
            icon,
            label,
        )

    class Meta:
        verbose_name = _("Backend-Aktivität")
        verbose_name_plural = _("Backend-Aktivitäten")


@admin.register(LegalDocument)
class LegalDocumentAdmin(BaseAdmin):
    list_display = ("document_type", "title", "version", "valid_from", "is_active", "updated_at")
    list_editable = ("is_active",)
    search_fields = ("title", "version", "content")
    list_filter = [
        "document_type",
        ("is_active", BooleanRadioFilter),
    ]
    autocomplete_fields = ("company",)
    ordering = ("document_type", "-valid_from", "-updated_at")
    fieldsets = (
        ("Allgemein", {"fields": ("company", "document_type", "title", "version", "valid_from", "is_active")}),
        ("Inhalt", {"fields": ("content",)}),
    )
