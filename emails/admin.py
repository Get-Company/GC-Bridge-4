# emails/admin.py
from __future__ import annotations

import json
import logging

from django import forms
from django.contrib import admin
from django.http import HttpResponse, JsonResponse
from django.urls import path
from django.utils.html import format_html, format_html_join
from django.utils.translation import gettext_lazy as _

logger = logging.getLogger(__name__)

from core.admin import BaseAdmin, BaseStackedInline, BaseTabularInline
from emails.mjml import compile_mjml_to_html, render_campaign_mjml
from emails.models import (
    EmailCampaign,
    EmailCampaignComponent,
    EmailCampaignProduct,
    MjmlComponent,
)
from emails.tasks import apply_campaign_prices_async

_MONOSPACE_STYLE = "font-family: monospace; width: 100%; min-height: 300px;"
_JSON_STYLE = "font-family: monospace; width: 100%; min-height: 180px;"
_PRODUCT_FIELD_EXCLUDES = {
    "id",
    "created_at",
    "updated_at",
    "shopware_image_sync_hash",
}
_PRODUCT_EMAIL_FIELDS = (
    ("product.price", "Listenpreis aus dem passenden Verkaufskanal"),
    ("product.email_special_price", "Kampagnen-Aktionspreis"),
    ("product.current_price", "Aktionspreis, sonst Listenpreis"),
    ("product.discount_pct", "Rabatt in Prozent"),
    ("product.shipping_cost_is_free", "kostenloser Versand true/false"),
    ("product.images", "sortierte Produktbilder"),
    ("product.first_image", "erstes Produktbild"),
)


class PrettyJSONWidget(forms.Textarea):
    def format_value(self, value):
        if value in (None, ""):
            return ""
        if isinstance(value, str):
            return value
        return json.dumps(value, ensure_ascii=False, indent=2)


def _json_variables_field(*, label: str, help_text: str = "") -> forms.JSONField:
    return forms.JSONField(
        label=label,
        required=False,
        help_text=help_text,
        widget=PrettyJSONWidget(attrs={"style": _JSON_STYLE}),
    )


def _clean_json_object(value, *, field_name: str):
    if value in (None, ""):
        return {}
    if not isinstance(value, dict):
        raise forms.ValidationError(
            _("%(field_name)s muss ein JSON-Objekt sein, z.B. {\"titel\": \"Hallo\"}."),
            params={"field_name": field_name},
        )
    return value


class MjmlComponentAdminForm(forms.ModelForm):
    default_variables = _json_variables_field(
        label=_("Standard-Variablen"),
        help_text=_("JSON-Objekt mit Standardwerten fuer Platzhalter."),
    )

    class Meta:
        model = MjmlComponent
        fields = "__all__"

    def clean_default_variables(self):
        return _clean_json_object(
            self.cleaned_data.get("default_variables"),
            field_name=_("Standard-Variablen"),
        )


class EmailCampaignComponentInlineForm(forms.ModelForm):
    variables = _json_variables_field(
        label=_("Variablen"),
        help_text=_("Nur abweichende Keys setzen. Nicht gesetzte Keys kommen aus der Komponente."),
    )

    class Meta:
        model = EmailCampaignComponent
        fields = "__all__"

    def clean_variables(self):
        return _clean_json_object(
            self.cleaned_data.get("variables"),
            field_name=_("Variablen"),
        )


@admin.register(MjmlComponent)
class MjmlComponentAdmin(BaseAdmin):
    form = MjmlComponentAdminForm
    list_display = ("name", "placement", "is_default", "order")
    list_filter = ("placement", "is_default")
    list_editable = ("is_default", "order")
    search_fields = ("name",)
    readonly_fields = BaseAdmin.readonly_fields + ("product_template_variables",)

    def formfield_for_dbfield(self, db_field, request, **kwargs):
        field = super().formfield_for_dbfield(db_field, request, **kwargs)
        if db_field.name == "mjml_markup" and field is not None:
            field.widget = forms.Textarea(attrs={"style": _MONOSPACE_STYLE})
        return field

    fieldsets = (
        (
            _("Komponente"),
            {
                "fields": ("name", "placement", "is_default", "order"),
            },
        ),
        (
            _("MJML-Markup"),
            {
                "fields": ("mjml_markup", "default_variables"),
            },
        ),
        (
            _("Produkt-Variablen"),
            {
                "fields": ("product_template_variables",),
                "classes": ("collapse",),
            },
        ),
        (
            _("System"),
            {
                "fields": BaseAdmin.readonly_fields,
                "classes": ("collapse",),
            },
        ),
    )

    @admin.display(description=_("Produkt-Variablen"))
    def product_template_variables(self, obj: MjmlComponent):
        from products.models import Product

        product_fields = [
            (f"product.{field.name}", field.verbose_name)
            for field in Product._meta.fields
            if field.name not in _PRODUCT_FIELD_EXCLUDES
        ]
        return format_html(
            "<p><strong>Direkte Product-Felder</strong></p><ul>{}</ul>"
            "<p><strong>E-Mail-spezifische Felder</strong></p><ul>{}</ul>"
            "<p>Preisformatierung: <code>{{{{ product.price|format_price }}}}</code></p>",
            format_html_join(
                "",
                "<li><code>{{{{ {} }}}}</code> <span style='color:#666'>({})</span></li>",
                product_fields,
            ),
            format_html_join(
                "",
                "<li><code>{{{{ {} }}}}</code> <span style='color:#666'>({})</span></li>",
                _PRODUCT_EMAIL_FIELDS,
            ),
        )


class EmailCampaignComponentInline(BaseStackedInline):
    model = EmailCampaignComponent
    form = EmailCampaignComponentInlineForm
    tab = False
    sortable = True
    sortable_field_name = "order"
    fields = (
        "order",
        "enabled",
        "library_component",
        "campaign_product",
        "component_default_variables",
        "variables",
    )
    readonly_fields = BaseStackedInline.readonly_fields + ("component_default_variables",)
    autocomplete_fields = ("library_component",)
    collapsible = True
    extra = 0

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("library_component")

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "campaign_product":
            campaign_id = request.resolver_match.kwargs.get("object_id") if request.resolver_match else None
            if campaign_id:
                kwargs["queryset"] = EmailCampaignProduct.objects.filter(campaign_id=campaign_id).select_related(
                    "product"
                ).order_by("order", "id")
            else:
                kwargs["queryset"] = EmailCampaignProduct.objects.none()
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    @admin.display(description=_("Standard-Variablen der Komponente"))
    def component_default_variables(self, obj: EmailCampaignComponent):
        library_component = getattr(obj, "library_component", None)
        default_variables = getattr(library_component, "default_variables", None) or {}
        if not default_variables:
            return format_html(
                "<div style='padding:10px 12px;border:1px solid #d1d5db;"
                "background:#f9fafb;border-radius:6px;color:#6b7280'>"
                "{}</div>",
                _("Diese Komponente setzt keine Standard-Variablen."),
            )

        json_text = json.dumps(default_variables, ensure_ascii=False, indent=2)
        return format_html(
            "<div style='padding:10px 12px;border:1px solid #bfdbfe;"
            "background:#eff6ff;border-radius:6px'>"
            "<p style='margin:0 0 8px;color:#1f2937'>"
            "Diese Werte kommen aus der Komponente. Im Feld Variablen darunter "
            "muessen nur abweichende Keys gesetzt werden."
            "</p>"
            "<pre style='margin:0;white-space:pre-wrap;font-family:monospace'>{}</pre>"
            "</div>",
            json_text,
        )


class EmailCampaignProductInline(BaseTabularInline):
    model = EmailCampaignProduct
    tab = False
    sortable = True
    sortable_field_name = "order"
    fields = ("order", "product", "special_price_override", "discount_pct", "current_price_display", "prices_synced_at")
    readonly_fields = BaseTabularInline.readonly_fields + ("current_price_display", "prices_synced_at")
    autocomplete_fields = ("product",)
    extra = 0

    @admin.display(description=_("Aktueller Preis"))
    def current_price_display(self, obj: EmailCampaignProduct):
        if obj.product_id is None:
            return "—"
        try:
            from shopware.models import ShopwareSettings
            default_channel = ShopwareSettings.objects.filter(is_default=True, is_active=True).first()
            price_entry = None
            if default_channel:
                price_entry = obj.product.prices.filter(sales_channel=default_channel).first()
            if price_entry is None:
                price_entry = obj.product.prices.order_by("pk").first()
            if price_entry is None:
                return "—"
            price = price_entry.price
            return f"{price:,.2f} €".replace(",", "X").replace(".", ",").replace("X", ".")
        except Exception:
            return "—"


@admin.register(EmailCampaign)
class EmailCampaignAdmin(BaseAdmin):
    list_display = ("internal_title", "component_count", "product_count", "status", "created_at")
    list_filter = ("status", "created_at")
    search_fields = ("internal_title",)
    list_editable = ("status",)
    inlines = (EmailCampaignComponentInline, EmailCampaignProductInline)

    fieldsets = (
        (
            _("Kampagne"),
            {
                "fields": ("internal_title", "status"),
            },
        ),
        (
            _("System"),
            {
                "fields": BaseAdmin.readonly_fields,
                "classes": ("collapse",),
            },
        ),
    )

    @admin.display(description=_("Produkte"))
    def product_count(self, obj: EmailCampaign) -> int:
        return obj.campaign_products.count()

    @admin.display(description=_("Komponenten"))
    def component_count(self, obj: EmailCampaign) -> int:
        return obj.components.count()

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        if not change:
            self._ensure_default_components(obj)

    def save_related(self, request, form, formsets, change):
        super().save_related(request, form, formsets, change)
        apply_campaign_prices_async.delay(form.instance.pk)

    def _ensure_default_components(self, campaign: EmailCampaign) -> None:
        if campaign.components.exists():
            return

        components = []
        for index, lib_component in enumerate(
            MjmlComponent.objects.filter(is_default=True).order_by("order", "name"), start=1
        ):
            components.append(
                EmailCampaignComponent(
                    campaign=campaign,
                    library_component=lib_component,
                    variables={},
                    order=index * 10,
                    enabled=True,
                )
            )
        EmailCampaignComponent.objects.bulk_create(components)

    def get_urls(self):
        urls = super().get_urls()
        custom = [
            path(
                "<int:campaign_id>/export-html/",
                self.admin_site.admin_view(self.export_html_view),
                name="emails_emailcampaign_export_html",
            ),
        ]
        return custom + urls

    def export_html_view(self, request, campaign_id: int):
        try:
            campaign = EmailCampaign.objects.get(pk=campaign_id)
        except EmailCampaign.DoesNotExist:
            return JsonResponse({"error": "Kampagne nicht gefunden."}, status=404)

        try:
            mjml = render_campaign_mjml(campaign)
            html = compile_mjml_to_html(mjml)
        except Exception:
            logger.exception("MJML export failed for campaign %s", campaign_id)
            return JsonResponse({"error": "Fehler beim Rendern der Kampagne."}, status=500)

        if request.GET.get("download"):
            response = HttpResponse(html, content_type="text/html; charset=utf-8")
            safe_title = campaign.internal_title[:40].replace(" ", "_")
            filename = f"email_{campaign.pk}_{safe_title}.html"
            response["Content-Disposition"] = f'attachment; filename="{filename}"'
            return response

        return JsonResponse({"html": html, "mjml": mjml})
