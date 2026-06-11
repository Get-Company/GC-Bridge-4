from django import forms
from django.contrib import admin, messages
from django.core.files.uploadedfile import UploadedFile
from django.http import FileResponse, Http404, HttpResponse, HttpResponseRedirect
from django.urls import path, reverse
from django.utils.html import escape, format_html
from django.utils.safestring import mark_safe
from unfold.contrib.filters.admin import BooleanRadioFilter
from unfold.decorators import action
from unfold.enums import ActionVariant

from core.admin import BaseAdmin
from documents.models import Document
from documents.services import DocumentPdfService, DocumentTemplateContextService


class DocumentAdminForm(forms.ModelForm):
    class Meta:
        model = Document
        fields = "__all__"
        widgets = {
            "html_content": forms.Textarea(
                attrs={
                    "class": "vLargeTextField font-mono",
                    "data-document-editor": "html",
                    "rows": 36,
                    "spellcheck": "false",
                }
            ),
            "css_content": forms.Textarea(
                attrs={
                    "class": "vLargeTextField font-mono",
                    "data-document-editor": "css",
                    "rows": 24,
                    "spellcheck": "false",
                }
            ),
        }


@admin.register(Document)
class DocumentAdmin(BaseAdmin):
    form = DocumentAdminForm
    list_display = (
        "title",
        "document_type",
        "slug",
        "template_source_status",
        "is_active",
        "pdf_generated_at",
        "pdf_download_link",
        "updated_at",
    )
    list_editable = ("is_active",)
    list_filter = [
        "document_type",
        ("is_active", BooleanRadioFilter),
    ]
    search_fields = ("title", "slug", "html_content", "css_content", "template_file", "pdf_filename")
    readonly_fields = BaseAdmin.readonly_fields + (
        "template_source_status",
        "template_help",
        "pdf_filename",
        "pdf_generated_at",
        "pdf_download_link",
        "cover_pdf_preview",
        "end_pdf_preview",
        "shopware_media_id",
    )
    actions = ("generate_pdf",)
    actions_detail = (
        {
            "title": "Dokument",
            "icon": "more_vert",
            "items": [
                "generate_pdf_detail",
                "upload_to_shopware_detail",
                "preview_template_detail",
            ],
        },
    )

    class Media:
        css = {
            "all": ("documents/admin/document_editor.css",),
        }
        js = ("documents/admin/document_editor.js",)

    fieldsets = (
        (
            "Dokument",
            {
                "fields": (
                    "document_type",
                    "slug",
                    "title",
                    "is_active",
                ),
                "classes": ("tab",),
            },
        ),
        (
            "Template",
            {
                "fields": (
                    "use_jinja2",
                    "template_file",
                    "template_source_status",
                    "html_content",
                    "css_content",
                ),
                "classes": ("tab",),
                "description": "HTML-Datei hochladen: Inhalt wird automatisch ins HTML-Feld uebernommen. Jinja2 aktiviert DB-Zugriff im Template.",
            },
        ),
        (
            "PDF",
            {
                "fields": (
                    "pdf_generated_at",
                    "pdf_filename",
                    "pdf_download_link",
                    "cover_pdf",
                    "cover_pdf_preview",
                    "end_pdf",
                    "end_pdf_preview",
                    "shopware_media_id",
                ),
                "classes": ("tab",),
            },
        ),
        (
            "Template-Hilfe",
            {
                "fields": (
                    "template_help",
                ),
                "classes": ("tab",),
                "description": "Kompakte Referenz fuer Jinja2-Syntax, Kontextvariablen und verfuegbare Modellfelder.",
            },
        ),
        (
            "System",
            {
                "fields": (
                    "created_at",
                    "updated_at",
                ),
                "classes": ("tab",),
            },
        ),
    )

    def response_change(self, request, obj):
        if "_continue" in request.POST:
            return HttpResponseRedirect(
                reverse("admin:documents_document_change", args=(obj.pk,))
            )
        return super().response_change(request, obj)

    def save_model(self, request, obj, form, change):
        uploaded = form.cleaned_data.get("template_file")
        if isinstance(uploaded, UploadedFile):
            uploaded.seek(0)
            obj.html_content = uploaded.read().decode("utf-8")
            uploaded.seek(0)
        super().save_model(request, obj, form, change)

    @admin.display(description="Cover-PDF Vorschau")
    def cover_pdf_preview(self, obj: Document | None = None):
        if not obj or not obj.cover_pdf:
            return "-"
        return format_html('<span class="text-xs text-gray-500">{}</span>', obj.cover_pdf.name)

    @admin.display(description="End-PDF Vorschau")
    def end_pdf_preview(self, obj: Document | None = None):
        if not obj or not obj.end_pdf:
            return "-"
        return format_html('<span class="text-xs text-gray-500">{}</span>', obj.end_pdf.name)

    def get_urls(self):
        return [
            path(
                "<path:object_id>/download-pdf/",
                self.admin_site.admin_view(self.download_pdf_view),
                name="documents_document_download_pdf",
            ),
            path(
                "<path:object_id>/preview-template/",
                self.admin_site.admin_view(self.preview_template_view),
                name="documents_document_preview_template",
            ),
        ] + super().get_urls()

    @admin.display(description="Template")
    def template_source_status(self, obj: Document | None = None):
        if not obj or not obj.pk:
            return "Nach dem Speichern verfuegbar"
        if obj.template_file:
            return format_html("<code>{}</code>", obj.template_file.name)
        if obj.html_content:
            return "Legacy-HTML-Feld"
        return "Keine Vorlage"

    @admin.display(description="PDF")
    def pdf_download_link(self, obj: Document | None = None):
        if not obj or not obj.pk or not obj.pdf_filename:
            return "-"
        pdf_path = DocumentPdfService().get_pdf_path(obj)
        if not pdf_path or not pdf_path.exists():
            return format_html("{} (Datei fehlt)", obj.pdf_filename)
        return format_html(
            '<a href="{}" class="text-primary-600 dark:text-primary-500">PDF herunterladen</a>',
            reverse("admin:documents_document_download_pdf", args=(obj.pk,)),
        )

    @admin.display(description="Variablen und Syntax")
    def template_help(self, obj=None):
        reference = DocumentTemplateContextService().get_model_variable_reference()
        html = [
            """
            <div class="prose prose-sm max-w-none dark:prose-invert document-reference">
                <h3>Kontext</h3>
                <p>
                    Standard ist <strong>Jinja2</strong>. Immer verfuegbar sind
                    <code>document</code>, <code>css</code>, <code>created_at_display</code>,
                    <code>rows</code>, <code>category_sections</code> und <code>row_count</code>.
                    Fuer direkte Abfragen stehen <code>Product</code>, <code>Category</code>,
                    <code>Tax</code> und <code>price_list_catalog_sections()</code> bereit.
                </p>
                <h3>Syntax kurz</h3>
                <pre><code>{{ document.title }}
{{ row.price_display|default("-") }}

{% set sections = price_list_catalog_sections() %}
{% for section in sections %}
  {{ section.name }}
{% else %}
  Keine Daten vorhanden.
{% endfor %}

{% if row.rebate_price_display != "-" %}
  Staffelpreis: {{ row.rebate_price_display }}
{% endif %}

{% for product in Product.objects.filter(is_active=True).order_by("erp_nr")[:20] %}
  {{ product.erp_nr }} | {{ product.name }}
{% endfor %}</code></pre>
                <h3>Wichtige Zeilenfelder</h3>
                <p>
                    <code>erp_nr</code>, <code>product_name</code>, <code>attributes</code>,
                    <code>vpe_display</code>, <code>price_display</code>,
                    <code>rebate_quantity_display</code>, <code>rebate_price_display</code>,
                    <code>category_level1_name</code>, <code>category_level2_name</code>.
                </p>
                <h3>Modellfelder</h3>
            """
        ]
        for app in reference:
            html.append(
                f'<details class="document-reference-app"><summary>{escape(app["name"])} <code>{escape(app["label"])}</code></summary>'
            )
            for model in app["models"]:
                html.append(
                    f'<details class="document-reference-model"><summary>{escape(model["object_name"])} <code>{escape(model["table"])}</code></summary>'
                )
                html.append('<div class="document-reference-fields">')
                for field in model["fields"]:
                    relation = f' -> {escape(field["relation"])}' if field["relation"] else ""
                    reverse = " Rueckbezug" if field["reverse"] else ""
                    html.append(
                        '<div class="document-reference-field">'
                        f'<code>{escape(field["name"])}</code>'
                        f'<span>{escape(str(field["label"]))} - {escape(field["type"])}{relation}{reverse}</span>'
                        "</div>"
                    )
                html.append("</div></details>")
            html.append("</details>")
        html.append("</div>")
        return mark_safe("".join(html))

    def download_pdf_view(self, request, object_id: str):
        document = self.get_object(request, object_id)
        if not document:
            raise Http404("Dokument nicht gefunden.")
        pdf_path = DocumentPdfService().get_pdf_path(document)
        if not pdf_path or not pdf_path.exists():
            raise Http404("PDF nicht gefunden.")
        return FileResponse(pdf_path.open("rb"), as_attachment=True, filename=pdf_path.name)

    def preview_template_view(self, request, object_id: str):
        document = self.get_object(request, object_id)
        if not document:
            raise Http404("Dokument nicht gefunden.")
        try:
            context = DocumentTemplateContextService().build_preview_context(document)
            html = DocumentPdfService().build_pdf_html(document, context)
        except Exception as exc:
            return HttpResponse(
                format_html(
                    "<!doctype html><html lang=\"de\"><head><meta charset=\"utf-8\"><title>Template-Fehler</title></head>"
                    "<body style=\"font-family:sans-serif;padding:24px;\"><h1>Template konnte nicht gerendert werden</h1>"
                    "<p><strong>{}</strong></p><pre style=\"white-space:pre-wrap;background:#f3f4f6;padding:16px;\">{}</pre></body></html>",
                    exc.__class__.__name__,
                    str(exc),
                ),
                status=400,
                content_type="text/html; charset=utf-8",
            )
        return HttpResponse(html, content_type="text/html; charset=utf-8")

    @admin.action(description="PDF speichern")
    def generate_pdf(self, request, queryset):
        service = DocumentPdfService()
        created_count = 0
        for document in queryset:
            service.generate_pdf(document)
            created_count += 1
        self.message_user(request, f"{created_count} PDF-Datei(en) im Verzeichnis Dokumente gespeichert.")

    @action(
        description="Vorschau",
        icon="visibility",
        variant=ActionVariant.INFO,
    )
    def preview_template_detail(self, request, object_id: str):
        return HttpResponseRedirect(reverse("admin:documents_document_preview_template", args=(object_id,)))

    @action(
        description="PDF speichern",
        icon="picture_as_pdf",
        variant=ActionVariant.PRIMARY,
    )
    def generate_pdf_detail(self, request, object_id: str):
        document = self.get_object(request, object_id)
        if not document:
            self.message_user(request, "Dokument nicht gefunden.", level=messages.ERROR)
            return HttpResponseRedirect(reverse("admin:documents_document_changelist"))
        DocumentPdfService().generate_pdf(document)
        self.message_user(request, "PDF-Datei im Verzeichnis Dokumente gespeichert.")
        return HttpResponseRedirect(reverse("admin:documents_document_change", args=(object_id,)))

    @action(
        description="Hochladen",
        icon="cloud_upload",
        variant=ActionVariant.WARNING,
    )
    def upload_to_shopware_detail(self, request, object_id: str):
        from documents.shopware_upload_service import DocumentShopwareUploadService
        document = self.get_object(request, object_id)
        if not document:
            self.message_user(request, "Dokument nicht gefunden.", level=messages.ERROR)
            return HttpResponseRedirect(reverse("admin:documents_document_changelist"))
        try:
            media_id = DocumentShopwareUploadService().upload_pdf(document)
            self.message_user(request, f"PDF erfolgreich zu Shopware hochgeladen (Media-ID: {media_id}).")
        except Exception as exc:
            self.message_user(request, f"Shopware-Upload fehlgeschlagen: {exc}", level=messages.ERROR)
        return HttpResponseRedirect(reverse("admin:documents_document_change", args=(object_id,)))
