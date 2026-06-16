# emails/admin.py
from __future__ import annotations

import logging

from django.contrib import admin
from django.http import HttpResponse, JsonResponse
from django.urls import path
from django.utils.html import format_html
from django.utils.translation import gettext_lazy as _

logger = logging.getLogger(__name__)

from core.admin import BaseAdmin, BaseStackedInline, BaseTabularInline
from emails.mjml import compile_mjml_to_html, render_campaign_mjml
from emails.models import (
    EmailCampaign,
    EmailCampaignComponent,
    EmailCampaignProduct,
    EmailCampaignSalesChannel,
)


class EmailCampaignComponentInline(BaseStackedInline):
    model = EmailCampaignComponent
    fields = ("order", "enabled", "component_key", "title", "body_html")
    extra = 0
    ordering = ("order", "id")


class EmailCampaignProductInline(BaseTabularInline):
    model = EmailCampaignProduct
    fields = ("order", "product", "special_price_override", "current_price_display")
    readonly_fields = BaseTabularInline.readonly_fields + ("current_price_display",)
    autocomplete_fields = ("product",)
    extra = 0

    @admin.display(description=_("Aktueller Preis"))
    def current_price_display(self, obj: EmailCampaignProduct):
        if obj.product_id is None:
            return "—"
        try:
            price = obj.product.price
            return f"{price:,.2f} €".replace(",", "X").replace(".", ",").replace("X", ".")
        except Exception:
            return "—"


class EmailCampaignSalesChannelInline(BaseTabularInline):
    model = EmailCampaignSalesChannel
    fields = ("sales_channel", "enabled", "is_default_display")
    readonly_fields = BaseTabularInline.readonly_fields + ("is_default_display",)
    extra = 0

    @admin.display(description=_("Standard"))
    def is_default_display(self, obj: EmailCampaignSalesChannel):
        if obj.sales_channel_id and obj.sales_channel.is_default:
            return format_html(
                '<span style="color:#16a34a;font-weight:bold">{} {}</span>',
                "✓",
                _("Standard"),
            )
        return "—"


@admin.register(EmailCampaign)
class EmailCampaignAdmin(BaseAdmin):
    list_display = ("internal_title", "h1", "product_count", "status", "product_template", "created_at")
    list_filter = ("status", "product_template", "created_at")
    search_fields = ("internal_title", "h1")
    list_editable = ("status",)
    inlines = (EmailCampaignComponentInline, EmailCampaignProductInline, EmailCampaignSalesChannelInline)

    fieldsets = (
        (
            _("E-Mail Inhalte"),
            {
                "fields": ("internal_title", "h1", "h1_small", "intro_text"),
            },
        ),
        (
            _("Einstellungen"),
            {
                "fields": ("product_template", "status"),
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

    def change_view(self, request, object_id, form_url="", extra_context=None):
        extra_context = extra_context or {}
        campaign = self.get_object(request, object_id)
        extra_context.update(self._component_context(campaign))
        return super().change_view(request, object_id, form_url, extra_context)

    def add_view(self, request, form_url="", extra_context=None):
        extra_context = extra_context or {}
        extra_context.update(self._component_context())
        return super().add_view(request, form_url, extra_context)

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        self._ensure_default_components(obj)
        if not change:
            # Late import avoids circular import between emails and shopware apps at module load time.
            from shopware.models import ShopwareSettings
            default_channel = ShopwareSettings.objects.filter(is_default=True, is_active=True).first()
            if default_channel:
                EmailCampaignSalesChannel.objects.get_or_create(
                    campaign=obj,
                    sales_channel=default_channel,
                    defaults={"enabled": True},
                )

    def _component_context(self, campaign: EmailCampaign | None = None) -> dict:
        component_library = [
            {"key": key, "label": label}
            for key, label in EmailCampaignComponent.ComponentKey.choices
        ]
        active_components = []
        if campaign:
            active_components = list(campaign.components.order_by("order", "id"))

        return {
            "component_library": component_library,
            "active_components": active_components,
        }

    def _ensure_default_components(self, campaign: EmailCampaign) -> None:
        if campaign.components.exists():
            return

        components = []
        for index, component_key in enumerate(EmailCampaignComponent.DEFAULT_COMPONENTS, start=1):
            label = EmailCampaignComponent.ComponentKey(component_key).label
            body_html = campaign.intro_text if component_key == EmailCampaignComponent.ComponentKey.TITLE_INTRO else ""
            components.append(
                EmailCampaignComponent(
                    campaign=campaign,
                    component_key=component_key,
                    title=str(label),
                    body_html=body_html,
                    order=index * 10,
                    enabled=True,
                )
            )
        EmailCampaignComponent.objects.bulk_create(components)

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
