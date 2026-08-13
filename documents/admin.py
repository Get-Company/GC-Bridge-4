from django import forms
from django.contrib import admin, messages
from django.core.files.uploadedfile import UploadedFile
from django.http import FileResponse, Http404, HttpResponse, HttpResponseRedirect
from django.urls import path, reverse
from django.utils.html import escape, format_html
from django.utils.safestring import mark_safe
from unfold.contrib.filters.admin import BooleanRadioFilter
from unfold.contrib.forms.widgets import WysiwygWidget
from unfold.decorators import action
from unfold.enums import ActionVariant

from core.admin import BaseAdmin, BaseTabularInline
from documents.document_version_service import DocumentVersionService
from documents.models import (
    Document,
    DocumentVersion,
)
from documents.services import DocumentPdfService, DocumentTemplateContextService


class DocumentAdminForm(forms.ModelForm):
    shopware_layout_choices: list[tuple[str, str]] | None = None
    shopware_pdf_choices: list[tuple[str, str]] | None = None
    shopware_media_folder_choices: list[tuple[str, str]] | None = None
    shopware_choices_error = ""

    class Meta:
        model = Document
        fields = "__all__"
        widgets = {
            "html_content": WysiwygWidget(
                attrs={
                    "data-document-editor": "html",
                    "aria-label": "HTML-Inhalt",
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

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._configure_shopware_select(
            "shopware_cms_page_id",
            self.shopware_layout_choices,
            "Shopware Erlebniswelt (optional)",
            "Optional: Diese Seite nimmt das Dokument auf. Enthält sie genau ein Text-Element, wird nur "
            "dessen Inhalt ersetzt - sonst wird ihr Aufbau durch ein einzelnes Text-Element "
            "mit dem Dokument ersetzt. Nur für Seiten verwenden, die allein dem Dokument dienen.",
            empty_label="Keine Erlebniswelt aktualisieren (nur PDF hochladen)",
        )
        self._configure_shopware_select(
            "shopware_media_id",
            self.shopware_pdf_choices,
            "Shopware PDF-Datei",
            "Diese vorhandene Shopware-Mediendatei wird beim Veröffentlichen ersetzt.",
        )
        self._configure_shopware_select(
            "shopware_media_folder_id",
            self.shopware_media_folder_choices,
            "Shopware Medienordner",
            "Optional: Beim Veröffentlichen wird die PDF in diesen Ordner verschoben. Ohne Auswahl bleibt ihr "
            "aktueller Shopware-Ordner unverändert.",
            empty_label="Ordner der ausgewählten Datei beibehalten",
        )

    def _configure_shopware_select(
        self,
        field_name: str,
        choices: list[tuple[str, str]] | None,
        label: str,
        help_text: str,
        *,
        empty_label: str = "---------",
    ) -> None:
        if choices is None:
            if self.shopware_choices_error:
                self.fields[field_name].help_text = (
                    f"{help_text} Auswahl konnte nicht geladen werden: {self.shopware_choices_error}"
                )
            return

        current_value = str(
            self.initial.get(field_name) or getattr(self.instance, field_name, "") or ""
        ).strip()
        choice_map = dict(choices)
        if current_value and current_value not in choice_map:
            choices = [(current_value, f"Gespeicherte ID: {current_value}"), *choices]

        self.fields[field_name] = forms.ChoiceField(
            required=False,
            choices=[("", empty_label), *choices],
            label=label,
            help_text=help_text,
            widget=forms.Select(attrs={"class": "vSelect2"}),
        )


class DocumentVersionInline(BaseTabularInline):
    model = DocumentVersion
    extra = 0
    can_delete = False
    show_change_link = True
    fields = ("version_number", "label", "is_active", "activated_at", "created_at")
    readonly_fields = BaseTabularInline.readonly_fields + ("version_number", "label", "is_active", "activated_at")


@admin.register(Document)
class DocumentAdmin(BaseAdmin):
    form = DocumentAdminForm
    autocomplete_fields = ("price_list_duplicate_categories",)
    inlines = (DocumentVersionInline,)
    conditional_fields = {
        "price_list_duplicate_categories": "document_type == 'price_list'",
    }
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
        "shopware_link_ids",
        "active_version_display",
    )
    actions = ("generate_pdf",)
    actions_detail = (
        {
            "title": "Dokument",
            "icon": "more_vert",
            "items": [
                "create_version_detail",
                "generate_pdf_detail",
                "publish_to_shopware_detail",
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
                    "price_list_duplicate_categories",
                    "active_version_display",
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
                    "source_docx",
                    "html_content",
                    "css_content",
                ),
                "classes": ("tab",),
                "description": (
                    "DOCX- und RTF-Quelldateien lassen sich nach dem Speichern direkt im passenden Programm oeffnen. "
                    "HTML wird im WYSIWYG-Editor gepflegt; das gespeicherte CSS wird dort geladen."
                ),
            },
        ),
        (
            "Shopware-Verknüpfung",
            {
                "fields": (
                    "shopware_cms_page_id",
                    "shopware_media_id",
                    "shopware_media_folder_id",
                    "shopware_link_ids",
                ),
                "classes": ("tab",),
                "description": (
                    "Die vorhandene PDF-Datei auswählen und speichern. Optional kann eine Erlebniswelt "
                    "ausgewählt werden. „In Shopware veröffentlichen“ erzeugt bei jedem Klick ein aktuelles PDF "
                    "und überschreibt genau die ausgewählte Mediendatei. Ist eine Erlebniswelt ausgewählt, wird "
                    "auch deren HTML-Inhalt aktualisiert. Optional kann ein Zielordner für die PDF ausgewählt werden; ohne "
                    "Auswahl bleibt ihr Ordner in Shopware erhalten. Bringt die Erlebniswelt nicht genau ein Text-Element mit, "
                    "wird ihr gesamter Aufbau durch ein einzelnes Text-Element ersetzt - vorhandene "
                    "Bilder, Videos und weitere Blöcke gehen dabei verloren."
                ),
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

    def get_form(self, request, obj=None, change=False, **kwargs):
        form_class = super().get_form(request, obj, change=change, **kwargs)
        from documents.shopware_publication_service import DocumentShopwarePublicationService

        try:
            service = DocumentShopwarePublicationService()
            layout_choices = service.list_layout_choices()
            pdf_choices = service.list_pdf_media_choices()
            media_folder_choices = service.list_media_folder_choices()
            choices_error = ""
        except Exception as exc:
            layout_choices = None
            pdf_choices = None
            media_folder_choices = None
            choices_error = str(exc)

        return type(
            "ShopwareLinkedDocumentAdminForm",
            (form_class,),
            {
                "shopware_layout_choices": layout_choices,
                "shopware_pdf_choices": pdf_choices,
                "shopware_media_folder_choices": media_folder_choices,
                "shopware_choices_error": choices_error,
            },
        )

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
            return "WYSIWYG-HTML-Feld"
        return "Keine Vorlage"

    @admin.display(description="Aktive Version")
    def active_version_display(self, obj: Document | None = None):
        if not obj or not obj.active_version_id:
            return "Noch keine Version aktiviert"
        return obj.active_version

    @admin.display(description="Shopware IDs")
    def shopware_link_ids(self, obj: Document | None = None):
        if not obj:
            return "Nach dem Speichern verfügbar"
        missing_links = []
        if not obj.shopware_media_id:
            missing_links.append("PDF-Datei")
        notice = ""
        if missing_links:
            notice = format_html(
                '<span class="text-red-600 dark:text-red-400">Nicht veröffentlichbar: {} auswählen und speichern.</span><br>',
                ", ".join(missing_links),
            )
        elif not obj.shopware_cms_page_id:
            notice = mark_safe(
                '<span class="text-amber-600 dark:text-amber-400">'
                "Nur die PDF wird veröffentlicht; es ist keine Erlebniswelt verknüpft.</span><br>"
            )
        layout_id = obj.shopware_cms_page_id or "nicht ausgewählt"
        media_id = obj.shopware_media_id or "nicht ausgewählt"
        folder_id = obj.shopware_media_folder_id or "Ordner der ausgewählten Datei beibehalten"
        return format_html(
            "{}<code>Erlebniswelt: {}</code><br><code>PDF: {}</code><br><code>Medienordner: {}</code>",
            notice,
            layout_id,
            media_id,
            folder_id,
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
                <p>
                    Varianten werden pro gleicher Preis-, Staffelpreis-, Staffelmengen- und
                    VPE-Kombination zu einer Preislisten-Zeile zusammengefasst. Die
                    Standardvariante ist der Repräsentant ihrer Preiszeile; weitere Preiszeilen
                    verwenden jeweils den ersten passenden Artikel. <code>attributes</code>
                    enthält die möglichen Werte je Variantenattribut, nicht alle Kombinationen.
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
        description="Neue Version anlegen",
        icon="add",
        variant=ActionVariant.PRIMARY,
    )
    def create_version_detail(self, request, object_id: str):
        document = self.get_object(request, object_id)
        if not document:
            self.message_user(request, "Dokument nicht gefunden.", level=messages.ERROR)
            return HttpResponseRedirect(reverse("admin:documents_document_changelist"))
        try:
            version = DocumentVersionService().create_from_document(document)
        except Exception as exc:
            self.message_user(request, f"Dokumentversion konnte nicht angelegt werden: {exc}", level=messages.ERROR)
            return HttpResponseRedirect(reverse("admin:documents_document_change", args=(object_id,)))
        self.message_user(request, f"Version {version.version_number} wurde als Entwurf angelegt.")
        return HttpResponseRedirect(reverse("admin:documents_documentversion_change", args=(version.pk,)))

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
        description="In Shopware veröffentlichen",
        icon="cloud_upload",
        variant=ActionVariant.PRIMARY,
    )
    def publish_to_shopware_detail(self, request, object_id: str):
        from documents.shopware_publication_service import DocumentShopwarePublicationService

        document = self.get_object(request, object_id)
        if not document:
            self.message_user(request, "Dokument nicht gefunden.", level=messages.ERROR)
            return HttpResponseRedirect(reverse("admin:documents_document_changelist"))
        try:
            result = DocumentShopwarePublicationService().publish(document)
            if result["cms_page_id"]:
                message = (
                    "Erlebniswelt (Slot-ID: {cms_slot_id}) aktualisiert und die aktuelle PDF unter "
                    "Media-ID {media_id} überschrieben."
                ).format(**result)
            else:
                message = "Aktuelle PDF unter Media-ID {media_id} überschrieben.".format(**result)
            self.message_user(request, message)
        except Exception as exc:
            self.message_user(request, f"Shopware-Veröffentlichung fehlgeschlagen: {exc}", level=messages.ERROR)
        return HttpResponseRedirect(reverse("admin:documents_document_change", args=(object_id,)))


class DocumentVersionAdminForm(forms.ModelForm):
    class Meta:
        model = DocumentVersion
        fields = "__all__"
        widgets = {
            "template_source": WysiwygWidget(
                attrs={
                    "data-document-editor": "html",
                    "aria-label": "HTML-Inhalt",
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


@admin.register(DocumentVersion)
class DocumentVersionAdmin(BaseAdmin):
    form = DocumentVersionAdminForm
    list_display = ("document", "version_number", "label", "is_active", "activated_at", "updated_at")
    list_filter = (("is_active", BooleanRadioFilter),)
    search_fields = ("document__title", "document__slug", "label", "template_source", "css_content")
    readonly_fields = BaseAdmin.readonly_fields + ("document", "version_number", "is_active", "activated_at")
    actions_detail = (
        {
            "title": "Veroeffentlichen",
            "icon": "cloud_upload",
            "items": ["activate_and_publish_detail"],
        },
    )
    fieldsets = (
        (
            "Version",
            {
                "fields": ("document", "version_number", "label", "is_active", "activated_at"),
                "description": (
                    "Die aktive Version aktualisiert die verknüpfte PDF-Datei und zusätzlich die Erlebniswelt, "
                    "wenn diese am Dokument ausgewählt ist."
                ),
            },
        ),
        (
            "Template",
            {
                "fields": ("use_jinja2", "template_source", "css_content"),
            },
        ),
        (
            "System",
            {
                "fields": ("created_at", "updated_at"),
            },
        ),
    )

    class Media:
        css = {
            "all": ("documents/admin/document_editor.css",),
        }
        js = ("documents/admin/document_editor.js",)

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        if obj and obj.is_active:
            return False
        return super().has_delete_permission(request, obj)

    @action(
        description="Aktivieren und zu Shopware veroeffentlichen",
        icon="cloud_upload",
        variant=ActionVariant.PRIMARY,
        permissions=("change",),
    )
    def activate_and_publish_detail(self, request, object_id: str):
        version = self.get_object(request, object_id)
        if version is None:
            self.message_user(request, "Dokumentversion nicht gefunden.", level=messages.ERROR)
            return HttpResponseRedirect(reverse("admin:documents_documentversion_changelist"))
        try:
            result = DocumentVersionService().activate_and_publish(version)
        except Exception as exc:
            self.message_user(
                request,
                f"Aktivierung oder Shopware-Veröffentlichung fehlgeschlagen: {exc}",
                level=messages.ERROR,
            )
        else:
            publication_message = (
                f"Version {version.version_number} aktiviert, Erlebniswelt aktualisiert und PDF unter "
                if result["cms_page_id"]
                else f"Version {version.version_number} aktiviert und die PDF unter "
            )
            self.message_user(
                request,
                f"{publication_message}Media-ID {result['media_id']} überschrieben.",
            )
        return HttpResponseRedirect(reverse("admin:documents_documentversion_change", args=(object_id,)))
