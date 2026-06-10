from django.contrib import admin
from django.http import HttpResponseRedirect
from django.urls import reverse
from django.utils.html import format_html

from unfold.contrib.filters.admin import BooleanRadioFilter

from core.admin import BaseAdmin, BaseTabularInline
from organization.models import CompanyProfile, LegalDocument, OrganizationContact, OrganizationRole


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
    list_display = (
        "employee_profile",
        "role",
        "title",
        "display_email",
        "display_phone",
        "is_primary",
        "is_public",
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
