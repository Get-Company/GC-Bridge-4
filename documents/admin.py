from django import forms
from django.contrib import admin, messages
from django.core.files.uploadedfile import UploadedFile
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
        "live_preview_button",
        "template_variables",
        "template_syntax",
        "pdf_filename",
        "pdf_generated_at",
        "pdf_download_link",
        "cover_pdf_preview",
        "end_pdf_preview",
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
                    "use_jinja2",
                    "template_file",
                    "template_source_status",
                    "template_preview_link",
                    "live_preview_button",
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

    @admin.display(description="Live-Vorschau")
    def live_preview_button(self, obj=None):
        url = reverse("admin:documents_document_preview_template_live")
        return format_html(
            '<button type="button" class="document-editor-action" data-live-preview="{}">'
            "Live-Vorschau (ohne Speichern)"
            "</button>",
            url,
        )

    def preview_template_live_view(self, request):
        if request.method != "POST":
            return HttpResponse(status=405)
        html_content = request.POST.get("html_content", "")
        css_content = request.POST.get("css_content", "")
        use_jinja2 = request.POST.get("use_jinja2") == "true"
        doc = Document(
            title="Live-Vorschau",
            html_content=html_content,
            css_content=css_content,
            use_jinja2=use_jinja2,
        )
        try:
            context = DocumentTemplateContextService().build_preview_context(doc)
            html = DocumentPdfService().build_pdf_html(doc, context)
        except Exception as exc:
            return HttpResponse(
                format_html(
                    '<!doctype html><html lang="de"><head><meta charset="utf-8"><title>Fehler</title></head>'
                    '<body style="font-family:sans-serif;padding:24px;"><h1>Fehler</h1>'
                    "<p><strong>{}</strong></p>"
                    '<pre style="white-space:pre-wrap;background:#f3f4f6;padding:16px;">{}</pre></body></html>',
                    exc.__class__.__name__,
                    str(exc),
                ),
                status=400,
                content_type="text/html; charset=utf-8",
            )
        return HttpResponse(html, content_type="text/html; charset=utf-8")

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
            path(
                "preview-template-live/",
                self.admin_site.admin_view(self.preview_template_live_view),
                name="documents_document_preview_template_live",
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

                <h3>Engine</h3>
                <p>
                    Templates werden mit <strong>Jinja2</strong> gerendert (Schalter &bdquo;Jinja2-Engine&ldquo; im Template-Tab).
                    Jinja2 hat Zugriff auf die komplette Django-ORM-API &mdash; Daten koennen direkt im Template aus der
                    Datenbank geladen werden. Als Fallback steht die klassische Django-Template-Engine zur Verfuegung.
                </p>
                <p>
                    <strong>Immer verfuegbar:</strong> <code>document</code> (dieses Objekt),
                    <code>css</code> (CSS-Feld), <code>products</code> (alle Produkte als Queryset),
                    <code>rows</code>, <code>category_sections</code>, <code>row_count</code>,
                    <code>created_at_display</code>.
                </p>
                <p>
                    <strong>DB-Klassen im Template:</strong> <code>Product</code>, <code>Category</code>, <code>Tax</code>.
                    Weitere koennen in <code>documents/jinja2_env.py</code> eingetragen werden.
                </p>

                <hr/>

                <h3>Ausgabe</h3>
                <pre><code>{{ product.erp_nr }}
{{ product.name }}
{{ product.tax.name }}          {# Relation per Dot-Notation #}
{{ product.tax.rate }}
{{ product.category.name }}
{{ document.title }}</code></pre>
                <p>HTML-Sonderzeichen werden automatisch maskiert. Fuer rohen HTML-Inhalt <code>| safe</code> anhaengen:</p>
                <pre><code>{{ product.description | safe }}</code></pre>

                <hr/>

                <h3>Bedingungen</h3>
                <pre><code>{% if product.erp_nr == '204109' %}
  Sonderartikel
{% elif product.price > 100 %}
  Hochpreisig
{% else %}
  Standard
{% endif %}</code></pre>
                <p>Vergleichsoperatoren: <code>==</code> <code>!=</code> <code>&lt;</code> <code>&gt;</code> <code>&lt;=</code> <code>&gt;=</code> <code>in</code> <code>not in</code> <code>is none</code> <code>is not none</code></p>
                <pre><code>{% if product.rebate_price is not none %}
  Rabattpreis: {{ product.rebate_price }}
{% endif %}

{% if 'Glas' in product.category.name %}
  Glasartikel
{% endif %}</code></pre>

                <hr/>

                <h3>Schleifen</h3>
                <pre><code>{# Ueber vorbereitete Zeilen #}
{% for row in rows %}
  {{ row.erp_nr }} | {{ row.product_name }}
{% else %}
  Keine Produkte vorhanden.
{% endfor %}

{# Direkt aus der DB #}
{% for product in Product.objects.all().order_by('erp_nr') %}
  {{ product.erp_nr }} | {{ product.name }}
{% endfor %}

{# Mit Schleifenzaehler #}
{% for product in products %}
  {{ loop.index }}. {{ product.name }}   {# 1-basiert #}
  {{ loop.index0 }}                       {# 0-basiert #}
  {% if loop.first %}Erster Eintrag{% endif %}
  {% if loop.last %}Letzter Eintrag{% endif %}
{% endfor %}</code></pre>

                <hr/>

                <h3>Variablen setzen</h3>
                <pre><code>{# Einzelnes Objekt laden #}
{% set product = Product.objects.get(erp_nr='204109') %}
{{ product.name }}

{# Queryset einer Variable zuweisen #}
{% set glasartikel = Product.objects.filter(category__name='Glas').order_by('name') %}
{% for p in glasartikel %}
  {{ p.erp_nr }}
{% endfor %}

{# Berechneter Wert #}
{% set netto = product.price / 1.19 %}
Netto: {{ '%.2f'|format(netto) }} EUR</code></pre>

                <hr/>

                <h3>filter &mdash; Datensaetze einschraenken</h3>
                <pre><code>{# Einfacher Filter #}
{% for p in Product.objects.filter(category__name='Reinigung') %}
  {{ p.erp_nr }} | {{ p.name }}
{% endfor %}

{# Mehrere Kriterien (AND) #}
{% for p in Product.objects.filter(category__name='Glas', tax__rate=19) %}
  {{ p.erp_nr }}
{% endfor %}

{# Teilstring (icontains = Gross/Kleinschreibung egal) #}
{% for p in Product.objects.filter(name__icontains='flasche') %}
  {{ p.name }}
{% endfor %}

{# Numerischer Vergleich #}
{% for p in Product.objects.filter(price__gte=10, price__lte=50) %}
  {{ p.erp_nr }} | {{ p.price }}
{% endfor %}

{# Relation traversieren #}
{% for p in Product.objects.filter(tax__name='MwSt. 19%') %}
  {{ p.name }}
{% endfor %}

{# In-Liste #}
{% set nummern = ['204109', '204110', '204111'] %}
{% for p in Product.objects.filter(erp_nr__in=nummern) %}
  {{ p.erp_nr }}
{% endfor %}</code></pre>

                <hr/>

                <h3>exclude &mdash; Datensaetze ausschliessen</h3>
                <pre><code>{# Alles ausser einer Kategorie #}
{% for p in Product.objects.exclude(category__name='Intern') %}
  {{ p.erp_nr }}
{% endfor %}

{# Kombination filter + exclude #}
{% for p in Product.objects.filter(tax__rate=19).exclude(category__name='Aktionsware') %}
  {{ p.erp_nr }}
{% endfor %}</code></pre>

                <hr/>

                <h3>Sortieren und begrenzen</h3>
                <pre><code>{# Sortierung #}
Product.objects.order_by('name')           {# aufsteigend #}
Product.objects.order_by('-price')         {# absteigend #}
Product.objects.order_by('category__name', 'erp_nr')

{# Begrenzung (Slicing) #}
Product.objects.all()[:10]                 {# erste 10 #}
Product.objects.order_by('-price')[:5]    {# Top 5 teuerste #}

{# Anzahl #}
{% set anzahl = Product.objects.filter(category__name='Glas').count() %}
{{ anzahl }} Glasartikel</code></pre>

                <hr/>

                <h3>get &mdash; Einzelnes Objekt</h3>
                <pre><code>{# Wirft Fehler wenn nicht genau 1 Treffer #}
{% set p = Product.objects.get(erp_nr='204109') %}
{{ p.name }} | {{ p.tax.name }}

{# Sicherer: first() gibt None zurueck wenn nicht gefunden #}
{% set p = Product.objects.filter(erp_nr='204109').first() %}
{% if p %}
  {{ p.name }}
{% else %}
  Produkt nicht gefunden.
{% endif %}</code></pre>

                <hr/>

                <h3>Relationen</h3>
                <pre><code>{# ForeignKey vorwaerts #}
{{ product.tax.name }}
{{ product.tax.rate }}
{{ product.category.name }}
{{ product.category.parent.name }}    {# verschachtelt #}

{# Rueckwaerts (related_name) #}
{% for price in product.prices.all() %}
  {{ price.sales_channel }} | {{ price.price }}
{% endfor %}

{# Unterkategorien einer Kategorie #}
{% set kat = Category.objects.get(slug='getraenke') %}
{% for sub in kat.children.all() %}
  {{ sub.name }}
{% endfor %}</code></pre>

                <hr/>

                <h3>Filter (Ausgabeformatierung)</h3>
                <pre><code>{{ product.name | upper }}          Grossbuchstaben
{{ product.name | lower }}          Kleinbuchstaben
{{ product.name | truncate(40) }}   Abschneiden auf 40 Zeichen
{{ product.name | default('–') }}   Fallback wenn leer
{{ product.description | safe }}    Kein HTML-Escaping
{{ product.price | round(2) }}      Runden
{{ '%.2f'|format(product.price) }}  Dezimalformat (z.B. 12.50)</code></pre>

                <hr/>

                <h3>Kategoriestruktur (aus Vorschau-Kontext)</h3>
                <pre><code>{% for section in category_sections %}
  <h2>{{ section.category_name }}</h2>
  {% for group in section.groups %}
    <h3>{{ group.category_name }}</h3>
    {% for row in group.rows %}
      {{ row.erp_nr }} | {{ row.product_name }} | {{ row.price_display }}
    {% endfor %}
  {% endfor %}
{% endfor %}</code></pre>
                <p>Felder in <code>row</code>: <code>erp_nr</code>, <code>product_name</code>, <code>attributes</code>,
                <code>price</code>, <code>price_display</code>, <code>price_source</code>,
                <code>rebate_quantity</code>, <code>rebate_price</code>, <code>rebate_price_display</code>,
                <code>vpe_display</code>, <code>unit</code>, <code>factor</code>, <code>min_purchase</code>,
                <code>purchase_unit</code>, <code>category_level1_name</code>, <code>category_level2_name</code>.</p>

                <hr/>

                <h3>Unterschiede Django-Template vs. Jinja2</h3>
                <table>
                    <thead><tr><th>Django</th><th>Jinja2</th></tr></thead>
                    <tbody>
                        <tr><td><code>{% with x=y %}</code></td><td><code>{% set x = y %}</code></td></tr>
                        <tr><td><code>{{ val|default:"-" }}</code></td><td><code>{{ val|default('–') }}</code></td></tr>
                        <tr><td><code>{% empty %}</code> in for</td><td><code>{% else %}</code> in for</td></tr>
                        <tr><td>forloop.counter</td><td>loop.index</td></tr>
                        <tr><td>forloop.first/last</td><td>loop.first / loop.last</td></tr>
                        <tr><td>{% load ... %}</td><td>nicht noetig</td></tr>
                        <tr><td>kein DB-Zugriff</td><td>Product.objects.filter(...)</td></tr>
                    </tbody>
                </table>

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
