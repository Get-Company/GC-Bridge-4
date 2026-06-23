import json

from django.contrib import admin, messages
from django.http import FileResponse, Http404, JsonResponse
from django.shortcuts import get_object_or_404
from django.template.response import TemplateResponse
from django.urls import path, reverse
from django.utils.html import format_html
from django.utils.translation import gettext_lazy as _
from django.views.decorators.http import require_POST
from unfold.decorators import action
from unfold.enums import ActionVariant

from core.admin import BaseAdmin
from ppwr.models import PackagingLabel
from ppwr.services import PackagingLabelPdfService

BLOCK_DEFINITIONS = [
    {
        "type": "producer_name",
        "label": "Hersteller",
        "icon": "business",
        "default_width_mm": 70,
        "default_height_mm": 8,
        "default_font_size": 9,
        "default_bold": True,
    },
    {
        "type": "address",
        "label": "Adresse",
        "icon": "location_on",
        "default_width_mm": 70,
        "default_height_mm": 16,
        "default_font_size": 8,
        "default_bold": False,
    },
    {
        "type": "email",
        "label": "E-Mail",
        "icon": "email",
        "default_width_mm": 70,
        "default_height_mm": 8,
        "default_font_size": 8,
        "default_bold": False,
    },
    {
        "type": "phone",
        "label": "Telefon",
        "icon": "phone",
        "default_width_mm": 50,
        "default_height_mm": 8,
        "default_font_size": 8,
        "default_bold": False,
    },
    {
        "type": "unique_packaging_id",
        "label": "Verpackungs-ID",
        "icon": "tag",
        "default_width_mm": 60,
        "default_height_mm": 8,
        "default_font_size": 8,
        "default_bold": False,
    },
    {
        "type": "qr_code",
        "label": "QR-Code",
        "icon": "qr_code_2",
        "default_width_mm": 25,
        "default_height_mm": 25,
        "default_font_size": 0,
        "default_bold": False,
    },
]


@admin.register(PackagingLabel)
class PackagingLabelAdmin(BaseAdmin):
    list_display = ("name", "unique_packaging_id", "canvas_dimensions", "pdf_generated_at", "editor_link", "updated_at")
    search_fields = ("name", "slug", "unique_packaging_id")
    readonly_fields = BaseAdmin.readonly_fields + (
        "pdf_filename",
        "pdf_generated_at",
        "pdf_download_link",
        "editor_button",
    )
    actions_detail = (
        {
            "title": _("Etikett"),
            "icon": "more_vert",
            "items": [
                "open_editor_detail",
                "generate_pdf_detail",
            ],
        },
    )

    fieldsets = (
        (
            "Etikett",
            {
                "fields": (
                    "name",
                    "slug",
                    "unique_packaging_id",
                    "canvas_width_mm",
                    "canvas_height_mm",
                    "company",
                    "qr_code",
                    "editor_button",
                ),
                "classes": ("tab",),
            },
        ),
        (
            "PDF",
            {
                "fields": (
                    "pdf_generated_at",
                    "pdf_filename",
                    "pdf_download_link",
                ),
                "classes": ("tab",),
            },
        ),
        (
            "Notizen",
            {
                "fields": ("notes",),
                "classes": ("tab",),
            },
        ),
        (
            "System",
            {
                "fields": ("created_at", "updated_at"),
                "classes": ("tab",),
            },
        ),
    )

    def get_urls(self):
        return [
            path(
                "<path:object_id>/editor/",
                self.admin_site.admin_view(self.editor_view),
                name="ppwr_packaginglabel_editor",
            ),
            path(
                "<path:object_id>/save-layout/",
                self.admin_site.admin_view(self.save_layout_view),
                name="ppwr_packaginglabel_save_layout",
            ),
            path(
                "<path:object_id>/generate-pdf/",
                self.admin_site.admin_view(self.generate_pdf_view),
                name="ppwr_packaginglabel_generate_pdf",
            ),
            path(
                "<path:object_id>/download-pdf/",
                self.admin_site.admin_view(self.download_pdf_view),
                name="ppwr_packaginglabel_download_pdf",
            ),
        ] + super().get_urls()

    @admin.display(description=_("Maße"))
    def canvas_dimensions(self, obj: PackagingLabel) -> str:
        return f"{obj.canvas_width_mm} × {obj.canvas_height_mm} mm"

    @admin.display(description=_("Editor"))
    def editor_link(self, obj: PackagingLabel) -> str:
        if not obj.pk:
            return "-"
        url = reverse("admin:ppwr_packaginglabel_editor", args=(obj.pk,))
        return format_html(
            '<a href="{}" class="text-primary-600 dark:text-primary-500 flex items-center gap-1">'
            '<span class="material-symbols-outlined" style="font-size:16px">edit</span> Editor</a>',
            url,
        )

    @admin.display(description=_("Editor öffnen"))
    def editor_button(self, obj: PackagingLabel | None = None) -> str:
        if not obj or not obj.pk:
            return "Nach dem Speichern verfügbar."
        url = reverse("admin:ppwr_packaginglabel_editor", args=(obj.pk,))
        return format_html(
            '<a href="{}" class="button" style="display:inline-flex;align-items:center;gap:6px;'
            'background:#ff9933;color:#fff;padding:6px 14px;border-radius:6px;text-decoration:none;font-weight:600;">'
            '<span class="material-symbols-outlined" style="font-size:18px">edit</span> Grafik-Editor öffnen</a>',
            url,
        )

    @admin.display(description=_("PDF"))
    def pdf_download_link(self, obj: PackagingLabel | None = None) -> str:
        if not obj or not obj.pk or not obj.pdf_filename:
            return "-"
        pdf_path = PackagingLabelPdfService().get_pdf_path(obj)
        if not pdf_path or not pdf_path.exists():
            return format_html("{} (Datei fehlt)", obj.pdf_filename)
        return format_html(
            '<a href="{}" class="text-primary-600 dark:text-primary-500">PDF herunterladen</a>',
            reverse("admin:ppwr_packaginglabel_download_pdf", args=(obj.pk,)),
        )

    @action(description=_("Editor"), icon="edit", variant=ActionVariant.PRIMARY)
    def open_editor_detail(self, request, object_id: str):
        from django.http import HttpResponseRedirect
        return HttpResponseRedirect(reverse("admin:ppwr_packaginglabel_editor", args=(object_id,)))

    @action(description=_("PDF generieren"), icon="picture_as_pdf", variant=ActionVariant.INFO)
    def generate_pdf_detail(self, request, object_id: str):
        from django.http import HttpResponseRedirect
        label = self.get_object(request, object_id)
        if not label:
            self.message_user(request, "Etikett nicht gefunden.", level=messages.ERROR)
            return HttpResponseRedirect(reverse("admin:ppwr_packaginglabel_changelist"))
        PackagingLabelPdfService().generate_pdf(label)
        self.message_user(request, "PDF erfolgreich generiert.")
        return HttpResponseRedirect(reverse("admin:ppwr_packaginglabel_change", args=(object_id,)))

    def editor_view(self, request, object_id: str):
        label = get_object_or_404(PackagingLabel, pk=object_id)
        company = label.company

        preview_data = {
            "producer_name": company.legal_name or company.name or "(Hersteller nicht hinterlegt)",
            "address": "\n".join(
                p for p in [company.street, f"{company.postal_code} {company.city}".strip(), company.country] if p.strip()
            ) or "(Adresse nicht hinterlegt)",
            "email": company.email or "(E-Mail nicht hinterlegt)",
            "phone": company.phone or "(Telefon nicht hinterlegt)",
            "unique_packaging_id": label.unique_packaging_id or "(Verpackungs-ID nicht vergeben)",
            "qr_code": label.qr_code.title if label.qr_code else "(Kein QR-Code)",
        }

        qr_preview_url = (
            reverse("qrcodes:preview", args=(label.qr_code.pk,))
            if label.qr_code_id
            else ""
        )

        context = {
            **self.admin_site.each_context(request),
            "title": f"Editor — {label.name}",
            "label": label,
            "block_definitions": BLOCK_DEFINITIONS,
            "layout_data_json": json.dumps(label.layout_data),
            "preview_data_json": json.dumps(preview_data),
            "qr_preview_url": qr_preview_url,
            "save_url": reverse("admin:ppwr_packaginglabel_save_layout", args=(label.pk,)),
            "generate_pdf_url": reverse("admin:ppwr_packaginglabel_generate_pdf", args=(label.pk,)),
            "change_url": reverse("admin:ppwr_packaginglabel_change", args=(label.pk,)),
        }
        return TemplateResponse(request, "admin/ppwr/label_editor.html", context)

    def save_layout_view(self, request, object_id: str):
        if request.method != "POST":
            return JsonResponse({"error": "POST required"}, status=405)
        label = get_object_or_404(PackagingLabel, pk=object_id)
        try:
            data = json.loads(request.body)
            layout = data.get("layout", [])
        except (json.JSONDecodeError, AttributeError):
            return JsonResponse({"error": "Ungültiges JSON"}, status=400)
        label.layout_data = layout
        label.save(update_fields=["layout_data", "updated_at"])
        return JsonResponse({"ok": True})

    def generate_pdf_view(self, request, object_id: str):
        label = get_object_or_404(PackagingLabel, pk=object_id)
        try:
            pdf_path = PackagingLabelPdfService().generate_pdf(label)
        except Exception as exc:
            return JsonResponse({"error": str(exc)}, status=500)
        return FileResponse(
            pdf_path.open("rb"),
            as_attachment=True,
            filename=pdf_path.name,
            content_type="application/pdf",
        )

    def download_pdf_view(self, request, object_id: str):
        label = get_object_or_404(PackagingLabel, pk=object_id)
        pdf_path = PackagingLabelPdfService().get_pdf_path(label)
        if not pdf_path or not pdf_path.exists():
            raise Http404("PDF nicht gefunden.")
        return FileResponse(pdf_path.open("rb"), as_attachment=True, filename=pdf_path.name)
