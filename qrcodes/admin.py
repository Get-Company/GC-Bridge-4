from django import forms
from django.contrib import admin
from django.urls import reverse
from django.utils.html import format_html
from unfold.widgets import UnfoldAdminColorInputWidget

from core.admin import BaseAdmin
from qrcodes.models import QrCode


class QrCodeAdminForm(forms.ModelForm):
    class Meta:
        model = QrCode
        fields = "__all__"
        widgets = {
            "foreground_color": UnfoldAdminColorInputWidget(),
            "background_color": UnfoldAdminColorInputWidget(),
        }


@admin.register(QrCode)
class QrCodeAdmin(BaseAdmin):
    form = QrCodeAdminForm
    list_display = ("title", "target_url", "center_mode", "is_active", "download_links", "updated_at")
    list_filter = ("center_mode", "is_active")
    search_fields = ("title", "target_url", "description", "center_text")
    list_editable = ("is_active",)
    readonly_fields = BaseAdmin.readonly_fields + ("download_links",)
    fieldsets = (
        (
            "QR-Code",
            {
                "fields": (
                    "title",
                    "target_url",
                    "description",
                    "is_active",
                ),
                "classes": ("tab",),
            },
        ),
        (
            "Mitte",
            {
                "fields": (
                    "center_mode",
                    "center_image",
                    "center_text",
                    "center_scale_percent",
                ),
                "classes": ("tab",),
            },
        ),
        (
            "Darstellung",
            {
                "fields": (
                    "foreground_color",
                    "background_color",
                    "download_links",
                ),
                "classes": ("tab",),
            },
        ),
        (
            "System",
            {
                "fields": BaseAdmin.readonly_fields,
                "classes": ("tab",),
            },
        ),
    )

    @admin.display(description="Downloads")
    def download_links(self, obj: QrCode | None = None):
        if not obj or not obj.pk:
            return "-"
        links = []
        for file_format in ("png", "jpg", "svg", "pdf"):
            url = reverse("qrcodes:download", args=(obj.pk, file_format, "medium"))
            links.append(f'<a href="{url}">{file_format.upper()}</a>')
        return format_html(" | ".join(links))
