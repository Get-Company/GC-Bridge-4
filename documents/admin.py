from django import forms
from django.contrib import admin, messages
from django.http import FileResponse, Http404, HttpResponse, HttpResponseRedirect
from django.template import TemplateSyntaxError
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
        "template_preview_link",
        "template_variables",
        "template_syntax",
        "pdf_filename",
        "pdf_generated_at",
        "pdf_download_link",
    )
    actions = ("generate_pdf",)
    actions_detail = ("preview_template_detail", "generate_pdf_detail")

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
                    "template_file",
                    "template_source_status",
                    "template_preview_link",
                    "html_content",
                    "css_content",
                ),
                "classes": ("tab",),
                "description": "Die hochgeladene HTML-Datei ist die primaere Vorlage. Das HTML-Feld bleibt als Fallback fuer bestehende Dokumente erhalten.",
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
            "Variablen",
            {
                "fields": (
                    "template_variables",
                ),
                "classes": ("tab",),
                "description": "Verfuegbare Modellfelder, sortiert nach App und Datenbanktabelle. In echten Dokument-Kontexten sind nur Objekte verfuegbar, die der jeweilige Renderer uebergibt.",
            },
        ),
        (
            "Syntax",
            {
                "fields": (
                    "template_syntax",
                ),
                "classes": ("tab",),
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

    @admin.display(description="HTML-Vorschau")
    def template_preview_link(self, obj: Document | None = None):
        if not obj or not obj.pk:
            return "Nach dem Speichern verfuegbar"
        if not obj.template_file and not obj.html_content:
            return "Keine Vorlage hinterlegt"
        return format_html(
            '<a href="{}" target="_blank" rel="noopener" class="text-primary-600 dark:text-primary-500">Vorschau oeffnen</a>',
            reverse("admin:documents_document_preview_template", args=(obj.pk,)),
        )

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

    @admin.display(description="Syntax")
    def template_syntax(self, obj=None):
        return mark_safe(
            """
            <div class="prose prose-sm max-w-none dark:prose-invert">
                <p>
                    <strong>Parser:</strong> Die hochgeladene HTML-Datei wird bei jedem Rendern
                    mit der Django Template Engine (<code>django.template.Template</code>) geladen
                    und geparsed. Das CSS-Feld steht als Variable <code>{{ css }}</code> zur
                    Verfuegung.
                </p>
                <p>
                    <strong>PDF-Erzeugung:</strong> Die zentrale Dokument-Aktion rendert HTML/CSS
                    mit WeasyPrint und speichert das Ergebnis im Verzeichnis <code>Dokumente/</code>.
                    Preisliste und Bestellschein koennen weiterhin dynamische Variablen aus der
                    Preiserhoehung verwenden, wenn sie ueber die Preiserhoehungs-Actions erzeugt werden.
                </p>

                <h3>Allgemeine Syntax</h3>
                <ul>
                    <li><code>{{ document.title }}</code> gibt einen Wert aus.</li>
                    <li><code>{{ css }}</code> gibt den Inhalt des CSS-Feldes aus.</li>
                    <li><code>{% if document.is_active %}...{% elif rows %}...{% else %}...{% endif %}</code> verzweigt bedingt. Ein eigenes <code>then</code>-Keyword gibt es nicht; der Inhalt direkt nach <code>if</code> ist der Then-Zweig.</li>
                    <li><code>{% for row in rows %}...{% empty %}Keine Zeilen{% endfor %}</code> wiederholt Inhalte.</li>
                    <li>Eine <code>while</code>-Schleife gibt es in Django Templates nicht. Fuer Dokumente bitte <code>for</code>-Schleifen ueber vorbereitete Listen verwenden.</li>
                    <li><code>{{ value|default:"-" }}</code>, <code>{{ value|safe }}</code> und <code>{{ value|slice:"0:10" }}</code> nutzen Django-Filter.</li>
                </ul>

                <h3>Immer verfuegbar</h3>
                <div class="document-token-palette">
                    <button type="button" class="document-token-button js-document-token" data-token="{{ document.title }}">document.title</button>
                    <button type="button" class="document-token-button js-document-token" data-token="{{ document.slug }}">document.slug</button>
                    <button type="button" class="document-token-button js-document-token" data-token="{{ document.document_type }}">document.document_type</button>
                    <button type="button" class="document-token-button js-document-token" data-token="{{ css }}">css</button>
                </div>
                <ul>
                    <li><code>document</code> - dieses Dokument mit <code>.title</code>, <code>.slug</code>, <code>.document_type</code>, <code>.is_active</code>.</li>
                    <li><code>css</code> - Inhalt des CSS-Feldes.</li>
                </ul>

                <h3>Bei Preislisten und Bestellscheinen ueber Preiserhoehungs-Actions</h3>
                <div class="document-token-palette">
                    <button type="button" class="document-token-button js-document-token" data-token="{{ price_increase.title }}">price_increase.title</button>
                    <button type="button" class="document-token-button js-document-token" data-token="{{ created_at_display }}">created_at_display</button>
                    <button type="button" class="document-token-button js-document-token" data-token="{{ scope_label }}">scope_label</button>
                    <button type="button" class="document-token-button js-document-token" data-token="{{ row_count }}">row_count</button>
                    <button type="button" class="document-token-button js-document-token" data-token="{% for section in category_sections %}...{% endfor %}">for category_sections</button>
                    <button type="button" class="document-token-button js-document-token" data-token="{% for row in rows %}...{% endfor %}">for rows</button>
                </div>
                <ul>
                    <li><code>price_increase</code> - Preiserhoehungsobjekt mit <code>.title</code>, <code>.general_percentage</code>, <code>.sales_channel</code>, <code>.status</code>.</li>
                    <li><code>created_at</code> und <code>created_at_display</code> - Erstellzeitpunkt.</li>
                    <li><code>general_percentage_display</code>, <code>sales_channel</code>, <code>scope_label</code>, <code>root_category</code>, <code>row_count</code>.</li>
                    <li><code>category_sections</code> - Hauptkategorien mit <code>section.category_name</code>, <code>section.groups</code>, <code>group.category_name</code>, <code>group.rows</code>.</li>
                    <li><code>rows</code> - flache Produktliste.</li>
                </ul>

                <h3>Produktzeilen</h3>
                <div class="document-token-palette">
                    <button type="button" class="document-token-button js-document-token" data-token="{{ row.erp_nr }}">row.erp_nr</button>
                    <button type="button" class="document-token-button js-document-token" data-token="{{ row.product_name }}">row.product_name</button>
                    <button type="button" class="document-token-button js-document-token" data-token="{{ row.attributes|safe }}">row.attributes</button>
                    <button type="button" class="document-token-button js-document-token" data-token="{{ row.price_display }}">row.price_display</button>
                    <button type="button" class="document-token-button js-document-token" data-token="{{ row.rebate_price_display }}">row.rebate_price_display</button>
                    <button type="button" class="document-token-button js-document-token" data-token="{{ row.vpe_display|safe }}">row.vpe_display</button>
                </div>
                <ul>
                    <li><code>row.erp_nr</code>, <code>row.product_name</code>, <code>row.attributes</code></li>
                    <li><code>row.price</code>, <code>row.price_display</code>, <code>row.price_source</code></li>
                    <li><code>row.rebate_quantity</code>, <code>row.rebate_quantity_display</code></li>
                    <li><code>row.rebate_price</code>, <code>row.rebate_price_display</code></li>
                    <li><code>row.vpe_display</code>, <code>row.unit</code>, <code>row.factor</code>, <code>row.min_purchase</code>, <code>row.purchase_unit</code></li>
                    <li><code>row.category_level1_name</code>, <code>row.category_level1_id</code>, <code>row.category_level2_name</code>, <code>row.category_level2_id</code></li>
                </ul>
            </div>
            """
        )

    @admin.display(description="Variablen")
    def template_variables(self, obj=None):
        reference = DocumentTemplateContextService().get_model_variable_reference()
        html = [
            """
            <div class="prose prose-sm max-w-none dark:prose-invert document-reference">
                <p>
                    Die Liste zeigt Modellfelder als Orientierung fuer Template-Variablen. Direkter
                    Zugriff ist moeglich, wenn der jeweilige Renderer das Objekt in den Kontext legt,
                    z. B. <code>{{ document.title }}</code> oder in Produktzeilen <code>{{ row.product_name }}</code>.
                </p>
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
        except (TemplateSyntaxError, UnicodeDecodeError, OSError) as exc:
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
        description="HTML-Vorschau",
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
