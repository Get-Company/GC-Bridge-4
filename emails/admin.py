import requests
from django.conf import settings
from django.contrib import admin, messages
from django.template.loader import render_to_string
from django.urls import path, reverse
from django.utils.html import format_html
from django.http import HttpResponseRedirect
import nested_admin
from unfold.admin import ModelAdmin as UnfoldModelAdmin
from unfold.admin import TabularInline as UnfoldTabularInline
from unfold.admin import StackedInline as UnfoldStackedInline

from .models import Email, EmailSection, EmailSectionProduct


class EmailSectionProductInline(nested_admin.NestedTabularInline, UnfoldTabularInline):
    model = EmailSectionProduct
    extra = 1
    fields = ("product", "special_percentage", "position")
    sortable_field_name = "position"
    tab = True


class EmailSectionInline(nested_admin.NestedStackedInline, UnfoldStackedInline):
    model = EmailSection
    extra = 1
    fields = ("header", "position")
    sortable_field_name = "position"
    tab = True
    inlines = [EmailSectionProductInline]


@admin.register(Email)
class EmailAdmin(nested_admin.NestedModelAdmin, UnfoldModelAdmin):
    compressed_fields = True
    warn_unsaved_form = True
    change_form_show_cancel_button = True
    list_display = ("name", "subject")
    search_fields = ("name", "subject")
    fields = ("name", "subject", "introduction", "render_mjml_button", "html_display")
    readonly_fields = ("created_at", "updated_at", "render_mjml_button", "html_display")
    inlines = [EmailSectionInline]

    def get_urls(self):
        urls = super().get_urls()
        custom = [
            path(
                "<int:pk>/render-mjml/",
                self.admin_site.admin_view(self._render_mjml_view),
                name="emails_email_render_mjml",
            ),
        ]
        return custom + urls

    def render_mjml_button(self, obj):
        if not obj.pk:
            return "Erst speichern, dann rendern."
        url = reverse("admin:emails_email_render_mjml", args=[obj.pk])
        return format_html(
            '<a class="button" href="{}" style="padding:6px 14px;background:#417690;'
            'color:#fff;border-radius:4px;text-decoration:none;font-weight:bold;">'
            "MJML rendern &amp; HTML speichern</a>",
            url,
        )

    render_mjml_button.short_description = "Aktion"

    def html_display(self, obj):
        if not obj.html:
            return "Noch kein HTML — bitte zuerst MJML rendern."
        return format_html(
            '<textarea rows="20" style="width:100%;font-family:monospace;font-size:11px;'
            'white-space:pre;">{}</textarea>',
            obj.html,
        )

    html_display.short_description = "HTML (zum Kopieren)"

    def _render_mjml_view(self, request, pk):
        obj = Email.objects.get(pk=pk)
        redirect_url = reverse("admin:emails_email_change", args=[pk])

        sections = obj.sections.prefetch_related(
            "section_products__product__product_images__image"
        ).order_by("position")

        mjml_content = render_to_string(
            "emails/email.mjml",
            {"email": obj, "sections": sections},
        )
        obj.full_mjml = mjml_content
        obj.save(update_fields=["full_mjml"])

        app_id = getattr(settings, "MJML_APP_ID", "")
        secret = getattr(settings, "MJML_SECRET", "")
        base_url = getattr(settings, "MJML_BASE_URL", "https://api.mjml.io/v1/render")

        if not app_id or not secret:
            messages.error(request, "MJML_APP_ID oder MJML_SECRET fehlen in den Einstellungen.")
            return HttpResponseRedirect(redirect_url)

        try:
            response = requests.post(
                base_url,
                auth=(app_id, secret),
                json={"mjml": mjml_content},
                timeout=30,
            )
            response.raise_for_status()
            data = response.json()

            if data.get("errors"):
                for error in data["errors"]:
                    messages.error(
                        request,
                        f"MJML-Fehler: {error.get('message')} (Zeile {error.get('line')})",
                    )
            else:
                obj.html = data.get("html", "")
                obj.save(update_fields=["html"])
                messages.success(request, "MJML erfolgreich gerendert. HTML wurde gespeichert.")

        except requests.exceptions.RequestException as e:
            messages.error(request, f"Fehler beim MJML-API-Aufruf: {e}")

        return HttpResponseRedirect(redirect_url)
