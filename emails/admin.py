# emails/admin.py
from __future__ import annotations

import json
import logging
import re
from copy import deepcopy

from django import forms
from django.contrib import admin
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import Case, IntegerField, Max, Q, When
from django.http import HttpResponse, HttpResponseRedirect, JsonResponse
from django.urls import path, reverse
from django.utils.html import format_html, format_html_join
from django.utils.translation import gettext_lazy as _
from django_json_widget.widgets import JSONEditorWidget
from jinja2 import TemplateSyntaxError

logger = logging.getLogger(__name__)

from core.admin import BaseAdmin, BaseStackedInline
from emails.mjml import compile_mjml_to_html, html_to_plain_text, render_campaign_mjml
from emails.models import (
    EmailCampaign,
    EmailCampaignCategory,
    EmailCampaignComponent,
    EmailCampaignProduct,
    EmailCampaignQueueEntry,
    MjmlComponent,
)
from emails_v2.variable_parser import extract_variables

_MONOSPACE_STYLE = "font-family: monospace; width: 100%; min-height: 300px;"
_PRODUCT_FIELD_EXCLUDES = {
    "id",
    "created_at",
    "updated_at",
    "shopware_image_sync_hash",
}
_PRODUCT_EMAIL_FIELDS = (
    ("product.price", "Listenpreis aus dem passenden Verkaufskanal"),
    ("product.email_special_price", "aktiver Sonderpreis aus dem Produkt"),
    ("product.current_price", "Aktionspreis, sonst Listenpreis"),
    ("product.discount_pct", "Rabatt in Prozent"),
    ("product.shipping_cost_is_free", "kostenloser Versand true/false"),
    ("product.images", "sortierte Produktbilder"),
    ("product.first_image", "erstes Produktbild"),
)
_RECIPIENT_EMAIL_FIELDS = (
    ("recipient.email", "Newsletter-E-Mail-Adresse"),
    ("recipient.salutation_display_name", "Anrede, z. B. Herr/Frau"),
    ("recipient.salutation_letter_name", "Briefanrede aus Shopware"),
    ("recipient.first_name", "Vorname"),
    ("recipient.last_name", "Nachname"),
    ("recipient.full_name", "Titel, Vorname und Nachname"),
    ("recipient.street", "Strasse aus Newsletter-Anmeldung"),
    ("recipient.zip_code", "PLZ aus Newsletter-Anmeldung"),
    ("recipient.city", "Ort aus Newsletter-Anmeldung"),
    ("recipient.status", "Shopware Newsletter-Status"),
    ("recipient.is_customer", "true/false, ob ein Django-Kunde verknuepft wurde"),
    ("recipient.custom_fields", "Shopware Custom Fields"),
)
_CUSTOMER_EMAIL_FIELDS = (
    ("customer.erp_nr", "ERP-Kundennummer"),
    ("customer.name", "Kundenname"),
    ("customer.email", "Kunden-E-Mail"),
    ("customer.api_id", "Shopware Kunden-ID"),
    ("customer.vat_id", "USt-IdNr"),
    ("customer.is_gross", "Bruttopreise true/false"),
    ("is_customer", "true/false Alias fuer recipient.is_customer"),
)
_CHILDREN_SLOT_RE = re.compile(r"\{\{\s*children\s*\}\}")


def _children_slot_location(markup: str) -> tuple[int, str] | None:
    for line_number, line in enumerate((markup or "").splitlines(), start=1):
        if _CHILDREN_SLOT_RE.search(line):
            return line_number, line.strip()
    return None


def _recipient_customer_context_info_html():
    return format_html(
        "<section><h3 style='margin:0 0 8px;font-weight:600'>Empfaenger- & Kunden-Kontext</h3>"
        "<p>Beim personalisierten Rendern stehen <code>recipient</code>, "
        "<code>newsletter_recipient</code>, <code>customer</code> und <code>is_customer</code> "
        "im Template zur Verfuegung. Ohne konkreten Empfaenger bleiben diese Felder leer.</p>"
        "<h4 style='margin:12px 0 6px;font-weight:600'>Newsletter-Empfaenger</h4><ul>{}</ul>"
        "<h4 style='margin:12px 0 6px;font-weight:600'>Kunde</h4><ul>{}</ul>"
        "<p>Beispiel: <code>{{{{ recipient.salutation_display_name }}}} "
        "{{{{ recipient.last_name }}}}</code> oder "
        "<code>{{{{ customer.erp_nr }}}}</code>.</p>"
        "</section>",
        format_html_join(
            "",
            "<li><code>{{{{ {} }}}}</code> <span style='color:#666'>({})</span></li>",
            _RECIPIENT_EMAIL_FIELDS,
        ),
        format_html_join(
            "",
            "<li><code>{{{{ {} }}}}</code> <span style='color:#666'>({})</span></li>",
            _CUSTOMER_EMAIL_FIELDS,
        ),
    )


def _latest_active_preview_recipient():
    from newsletter.models import NewsletterRecipient

    return (
        NewsletterRecipient.objects.filter(
            status__in=(
                NewsletterRecipient.Status.DIRECT,
                NewsletterRecipient.Status.OPT_IN,
            )
        )
        .select_related("customer")
        .order_by("-last_synced_at", "-remote_updated_at", "-updated_at", "-created_at", "-pk")
        .first()
    )


def _component_identity(component: EmailCampaignComponent) -> int:
    return getattr(component, "pk", None) or getattr(component, "id", None) or id(component)


def _component_parent_id(component: EmailCampaignComponent) -> int | None:
    parent_id = getattr(component, "parent_id", None)
    if parent_id is not None:
        return parent_id
    parent = getattr(component, "parent", None)
    return _component_identity(parent) if parent is not None else None


def _tree_sorted_component_ids(components: list[EmailCampaignComponent]) -> list[int]:
    component_ids = {_component_identity(component) for component in components}
    children_by_parent: dict[int | None, list[EmailCampaignComponent]] = {}

    for component in components:
        parent_id = _component_parent_id(component)
        if parent_id not in component_ids:
            parent_id = None
        children_by_parent.setdefault(parent_id, []).append(component)

    for siblings in children_by_parent.values():
        siblings.sort(key=lambda component: (getattr(component, "order", 0), _component_identity(component)))

    sorted_ids: list[int] = []
    seen_ids: set[int] = set()

    def visit(component: EmailCampaignComponent) -> None:
        component_id = _component_identity(component)
        if component_id in seen_ids:
            return
        seen_ids.add(component_id)
        sorted_ids.append(component_id)
        for child in children_by_parent.get(component_id, []):
            visit(child)

    for root in children_by_parent.get(None, []):
        visit(root)

    for component in sorted(components, key=lambda item: (getattr(item, "order", 0), _component_identity(item))):
        visit(component)

    return sorted_ids


def _component_tree_depth(component: EmailCampaignComponent) -> int:
    depth = 0
    seen_ids = {_component_identity(component)}
    parent = getattr(component, "parent", None)

    while parent is not None:
        parent_id = _component_identity(parent)
        if parent_id in seen_ids:
            break
        seen_ids.add(parent_id)
        depth += 1
        parent = getattr(parent, "parent", None)

    return depth


def _copy_campaign_products(
    source_campaign: EmailCampaign,
    target_campaign: EmailCampaign,
) -> dict[int, EmailCampaignProduct]:
    copied_products: dict[int, EmailCampaignProduct] = {}

    for source_product in source_campaign.campaign_products.order_by("order", "id"):
        copied_product = EmailCampaignProduct.objects.create(
            campaign=target_campaign,
            product_id=source_product.product_id,
            special_price_override=source_product.special_price_override,
            discount_pct=source_product.discount_pct,
            prices_synced_at=None,
            order=source_product.order,
        )
        copied_products[source_product.pk] = copied_product

    return copied_products


def _copy_campaign_components(
    source_campaign: EmailCampaign,
    target_campaign: EmailCampaign,
) -> None:
    if target_campaign.components.exists():
        return

    campaign_products_by_source_id = _copy_campaign_products(source_campaign, target_campaign)
    source_components = list(
        source_campaign.components.select_related(
            "library_component",
            "campaign_product",
            "product",
            "parent",
        ).order_by("order", "id")
    )
    copied_components: dict[int, EmailCampaignComponent] = {}

    for source_component in source_components:
        copied_component = EmailCampaignComponent.objects.create(
            campaign=target_campaign,
            library_component_id=source_component.library_component_id,
            parent=None,
            campaign_product=campaign_products_by_source_id.get(source_component.campaign_product_id),
            product_id=source_component.product_id,
            title=source_component.title,
            variables=deepcopy(source_component.variables),
            order=source_component.order,
            enabled=source_component.enabled,
        )
        copied_components[source_component.pk] = copied_component

    parent_updates = []
    for source_component in source_components:
        if not source_component.parent_id:
            continue
        copied_component = copied_components[source_component.pk]
        copied_parent = copied_components.get(source_component.parent_id)
        if copied_parent is None:
            continue
        copied_component.parent = copied_parent
        parent_updates.append(copied_component)

    if parent_updates:
        EmailCampaignComponent.objects.bulk_update(parent_updates, ["parent"])


class LenientJSONField(forms.JSONField):
    def to_python(self, value):
        try:
            return super().to_python(value)
        except forms.ValidationError:
            if not isinstance(value, str):
                raise
            return super().to_python(_normalize_json_string_control_chars(value))


def _normalize_json_string_control_chars(value: str) -> str:
    chars: list[str] = []
    in_string = False
    escaped = False
    last_was_space = False

    for char in value:
        if escaped:
            chars.append(char)
            escaped = False
            last_was_space = False
            continue

        if char == "\\":
            chars.append(char)
            escaped = True
            last_was_space = False
            continue

        if char == '"':
            chars.append(char)
            in_string = not in_string
            last_was_space = False
            continue

        if in_string and char in "\r\n\t":
            if not last_was_space:
                chars.append(" ")
                last_was_space = True
            continue

        chars.append(char)
        last_was_space = char == " "

    return "".join(chars)


def _json_variables_field(*, label: str, help_text: str = "") -> LenientJSONField:
    return LenientJSONField(
        label=label,
        required=False,
        help_text=help_text,
        widget=JSONEditorWidget(
            width="100%",
            height="320px",
            options={"modes": ["code", "tree"]},
        ),
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
        help_text=_("JSON-Objekt mit Standardwerten fuer Django/Jinja-Platzhalter."),
    )

    class Meta:
        model = MjmlComponent
        fields = "__all__"

    def clean_default_variables(self):
        return _clean_json_object(
            self.cleaned_data.get("default_variables"),
            field_name=_("Standard-Variablen"),
        )

    def clean(self):
        cleaned_data = super().clean()
        markup = cleaned_data.get("mjml_markup", "")
        rendering_mode = cleaned_data.get(
            "rendering_mode", MjmlComponent.RenderingMode.DJANGO_JINJA
        )

        if rendering_mode == MjmlComponent.RenderingMode.SHOPWARE:
            return cleaned_data

        try:
            extract_variables(markup)
        except TemplateSyntaxError as error:
            self.add_error(
                "mjml_markup",
                forms.ValidationError(
                    _("Ungültige Jinja-Template-Syntax in Zeile %(line)s: %(message)s"),
                    params={"line": error.lineno, "message": error.message},
                ),
            )

        return cleaned_data


class EmailCampaignComponentInlineForm(forms.ModelForm):
    variables = _json_variables_field(
        label=_("Variablen"),
        help_text=_("Nur abweichende Keys setzen. Nicht gesetzte Keys kommen aus der Komponente."),
    )

    class Meta:
        model = EmailCampaignComponent
        fields = "__all__"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        legacy_campaign_product = getattr(self.instance, "campaign_product", None)
        if legacy_campaign_product is None:
            return
        if not getattr(self.instance, "product_id", None):
            self.initial["product"] = legacy_campaign_product.product_id

    def clean_variables(self):
        return _clean_json_object(
            self.cleaned_data.get("variables"),
            field_name=_("Variablen"),
        )


@admin.register(MjmlComponent)
class MjmlComponentAdmin(BaseAdmin):
    form = MjmlComponentAdminForm
    list_display = ("name", "rendering_mode", "placement", "is_default", "order")
    list_filter = ("rendering_mode", "placement", "is_default")
    list_editable = ("is_default", "order")
    search_fields = ("name",)
    readonly_fields = BaseAdmin.readonly_fields + ("component_info",)

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
                "fields": ("rendering_mode", "mjml_markup", "default_variables"),
            },
        ),
        (
            _("Info"),
            {
                "fields": ("component_info",),
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

    @admin.display(description=_("Komponenten-Info"))
    def component_info(self, obj: MjmlComponent):
        from products.models import Product

        product_fields = [
            (f"product.{field.name}", field.verbose_name)
            for field in Product._meta.fields
            if field.name not in _PRODUCT_FIELD_EXCLUDES
        ]
        children_slot = _children_slot_location(getattr(obj, "mjml_markup", ""))
        if children_slot:
            line_number, line = children_slot
            children_info = format_html(
                "<p>Untergeordnete Kampagnen-Komponenten werden exakt an "
                "<code>{{{{ children }}}}</code> eingefuegt.</p>"
                "<p><strong>Fundstelle:</strong> Zeile {}</p>"
                "<pre style='margin:0;white-space:pre-wrap;font-family:monospace'>{}</pre>",
                line_number,
                line,
            )
        else:
            children_info = format_html(
                "<p>Diese Komponente enthaelt keinen <code>{}</code>-Slot.</p>"
                "<p>Wenn im Kampagnen-Inline Children unter diese Komponente gehaengt werden, "
                "werden sie erst ausgegeben, sobald das MJML-Markup den Slot enthaelt.</p>",
                "{{ children }}",
            )

        return format_html(
            "<div style='display:grid;gap:16px'>"
            "<section><h3 style='margin:0 0 8px;font-weight:600'>Verschachtelung</h3>{}</section>"
            "<section><h3 style='margin:0 0 8px;font-weight:600'>Standard-Variablen</h3>"
            "<p>Werte aus <code>default_variables</code> stehen direkt per "
            "<code>{{{{ variablenname }}}}</code> zur Verfuegung und koennen in der Kampagne "
            "ueberschrieben werden.</p></section>"
            "<section><h3 style='margin:0 0 8px;font-weight:600'>Produkt-Kontext</h3>"
            "<p>Wenn eine Kampagnen-Komponente mit einem Produkt verknuepft ist, steht "
            "<code>product</code> im Template zur Verfuegung.</p>"
            "<h4 style='margin:12px 0 6px;font-weight:600'>Direkte Product-Felder</h4><ul>{}</ul>"
            "<h4 style='margin:12px 0 6px;font-weight:600'>E-Mail-spezifische Felder</h4><ul>{}</ul>"
            "<p>Preisformatierung: <code>{{{{ product.price|format_price }}}}</code></p>"
            "</section>"
            "{}"
            "</div>",
            children_info,
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
            _recipient_customer_context_info_html(),
        )

    product_template_variables = component_info


class EmailCampaignComponentInline(BaseStackedInline):
    model = EmailCampaignComponent
    form = EmailCampaignComponentInlineForm
    tab = False
    fieldsets = (
        (
            None,
            {
                "fields": ("tree_position", "order", "title", "library_component", "variables"),
            },
        ),
        (
            _("Einstellungen"),
            {
                "fields": ("parent", "enabled"),
                "classes": ("collapse",),
            },
        ),
        (
            _("Produkt"),
            {
                "fields": ("product", "current_price_display"),
                "classes": ("collapse",),
            },
        ),
        (
            _("Komponenten-Info"),
            {
                "fields": ("component_default_variables",),
                "classes": ("collapse",),
            },
        ),
    )
    readonly_fields = BaseStackedInline.readonly_fields + (
        "tree_position",
        "current_price_display",
        "component_default_variables",
    )
    autocomplete_fields = ("library_component", "product")
    collapsible = True
    extra = 0

    def get_queryset(self, request):
        queryset = super().get_queryset(request).select_related(
            "library_component",
            "product",
            "campaign_product__product",
            "parent",
            "parent__parent",
            "parent__parent__parent",
        )
        components = list(queryset)
        sorted_ids = _tree_sorted_component_ids(components)
        if not sorted_ids:
            return queryset
        preserved_order = Case(
            *[When(pk=component_id, then=position) for position, component_id in enumerate(sorted_ids)],
            output_field=IntegerField(),
        )
        return queryset.order_by(preserved_order)

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        campaign_id = request.resolver_match.kwargs.get("object_id") if request.resolver_match else None
        if db_field.name == "parent":
            if campaign_id:
                kwargs["queryset"] = (
                    EmailCampaignComponent.objects.filter(campaign_id=campaign_id)
                    .select_related("library_component")
                    .order_by("order", "id")
                )
            else:
                kwargs["queryset"] = EmailCampaignComponent.objects.none()
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    @admin.display(description=_("Baum"))
    def tree_position(self, obj: EmailCampaignComponent):
        if not getattr(obj, "pk", None):
            return format_html(
                "<h3 style='margin:0;font-size:14px;font-weight:600;color:#6b7280'>{}</h3>",
                _("Neue Komponente"),
            )

        depth = _component_tree_depth(obj)
        prefix = "-" * depth
        component_title = obj.title or getattr(getattr(obj, "library_component", None), "name", str(obj))
        return format_html(
            "<h3 style='margin:0 0 4px {}px;display:flex;align-items:center;gap:8px;"
            "font-size:14px;line-height:20px;font-weight:600;color:#111827'>"
            "<span class='material-symbols-outlined' style='font-size:18px;color:#9ca3af'>drag_indicator</span>"
            "<span style='font-family:monospace;color:#6b7280'>{}</span>"
            "<span style='font-family:monospace;color:#9ca3af'>{}</span>"
            "<span>{}</span>"
            "</h3>",
            depth * 24,
            obj.order,
            prefix,
            component_title,
        )

    @admin.display(description=_("Aktueller Preis"))
    def current_price_display(self, obj: EmailCampaignComponent):
        product = getattr(obj, "product", None)
        if product is None and getattr(obj, "campaign_product", None):
            product = obj.campaign_product.product
        if product is None:
            return "—"
        try:
            from shopware.models import ShopwareSettings
            default_channel = ShopwareSettings.objects.filter(is_default=True, is_active=True).first()
            price_entry = None
            if default_channel:
                price_entry = product.prices.filter(sales_channel=default_channel).first()
            if price_entry is None:
                price_entry = product.prices.order_by("pk").first()
            if price_entry is None:
                return "—"
            price = price_entry.get_current_price(as_float=False)
            return f"{price:,.2f} €".replace(",", "X").replace(".", ",").replace("X", ".")
        except Exception:
            return "—"

    @admin.display(description=_("Komponenten-Info"))
    def component_default_variables(self, obj: EmailCampaignComponent):
        library_component = getattr(obj, "library_component", None)
        default_variables = getattr(library_component, "default_variables", None) or {}
        markup = getattr(library_component, "mjml_markup", "") if library_component else ""
        children_slot = _children_slot_location(markup)

        if children_slot:
            line_number, line = children_slot
            children_info = format_html(
                "<p style='margin:0 0 8px;color:#1f2937'>"
                "Children dieser Komponente werden an <code>{{{{ children }}}}</code> eingefuegt."
                "</p>"
                "<p style='margin:0 0 8px;color:#374151'><strong>Fundstelle:</strong> Zeile {}</p>"
                "<pre style='margin:0;white-space:pre-wrap;font-family:monospace'>{}</pre>",
                line_number,
                line,
            )
        else:
            children_info = format_html(
                "<p style='margin:0;color:#6b7280'>"
                "Diese Komponente enthaelt keinen <code>{}</code>-Slot. "
                "Untergeordnete Komponenten werden deshalb nicht ausgegeben."
                "</p>",
                "{{ children }}",
            )

        if default_variables:
            variables_info = format_html(
                "<p style='margin:0 0 8px;color:#1f2937'>"
                "Diese Werte kommen aus der Komponente. Im Feld Variablen darunter "
                "muessen nur abweichende Keys gesetzt werden."
                "</p>"
                "<pre style='margin:0;white-space:pre-wrap;font-family:monospace'>{}</pre>",
                json.dumps(default_variables, ensure_ascii=False, indent=2),
            )
        else:
            variables_info = format_html(
                "<p style='margin:0;color:#6b7280'>{}</p>",
                _("Diese Komponente setzt keine Standard-Variablen."),
            )

        return format_html(
            "<div style='padding:10px 12px;border:1px solid #bfdbfe;"
            "background:#eff6ff;border-radius:6px;display:grid;gap:12px'>"
            "<section><h4 style='margin:0 0 6px;font-weight:600'>Verschachtelung</h4>{}</section>"
            "<section><h4 style='margin:0 0 6px;font-weight:600'>Standard-Variablen</h4>{}</section>"
            "</div>",
            children_info,
            variables_info,
        )


@admin.register(EmailCampaign)
class EmailCampaignAdmin(BaseAdmin):
    list_display = (
        "internal_title",
        "editor_link",
        "category_list",
        "send_at",
        "product_count",
        "status",
        "created_at",
    )
    list_filter = ("categories", "status", "send_at", "created_at")
    search_fields = ("internal_title",)
    list_editable = ("status",)
    inlines = (EmailCampaignComponentInline,)
    autocomplete_fields = ("categories",)

    fieldsets = (
        (
            _("Kampagne"),
            {
                "fields": ("internal_title", "layout_mode", "categories", "status", "send_at", "simple_editor_link", "visual_editor_link"),
            },
        ),
        (
            _("Info"),
            {
                "fields": ("campaign_context_info",),
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
    readonly_fields = BaseAdmin.readonly_fields + ("campaign_context_info", "simple_editor_link", "visual_editor_link")

    def get_readonly_fields(self, request, obj=None):
        fields = tuple(super().get_readonly_fields(request, obj))
        return fields + (("layout_mode",) if obj else ())

    def get_changeform_initial_data(self, request):
        data = super().get_changeform_initial_data(request)
        data.setdefault("layout_mode", EmailCampaign.LayoutMode.SIMPLE)
        return data

    def get_inlines(self, request, obj=None):
        return [] if obj is None or obj.layout_mode in {EmailCampaign.LayoutMode.SIMPLE, EmailCampaign.LayoutMode.VISUAL} else super().get_inlines(request, obj)

    @admin.display(description=_("Editor"))
    def editor_link(self, obj):
        if obj.layout_mode not in {EmailCampaign.LayoutMode.SIMPLE, EmailCampaign.LayoutMode.VISUAL}:
            return "—"
        name = "admin:emails_emailcampaign_visual_editor" if obj.layout_mode == EmailCampaign.LayoutMode.VISUAL else "admin:emails_emailcampaign_simple_editor"
        url = reverse(name, args=[obj.pk])
        return format_html('<a href="{}">Öffnen</a>', url)

    @admin.display(description=_("E-Mail gestalten"))
    def simple_editor_link(self, obj):
        if not obj or not obj.pk:
            return "Nach dem Speichern öffnet sich der einfache Editor."
        if obj.layout_mode != EmailCampaign.LayoutMode.SIMPLE:
            return "Diese Kampagne verwendet einen anderen Editor."
        url = reverse("admin:emails_emailcampaign_simple_editor", args=[obj.pk])
        return format_html('<a class="button" href="{}">Einfachen Editor öffnen →</a>', url)

    @admin.display(description=_("Visueller Editor"))
    def visual_editor_link(self, obj):
        if not obj or not obj.pk:
            return "Nach dem Speichern kann der visuelle Editor geöffnet werden."
        url = reverse("admin:emails_emailcampaign_visual_editor", args=[obj.pk])
        label = "Visuellen Editor öffnen →" if obj.layout_mode == EmailCampaign.LayoutMode.VISUAL else "Zum visuellen MJML-Editor wechseln →"
        return format_html('<a class="button" href="{}">{}</a>', url, label)

    def get_queryset(self, request):
        return super().get_queryset(request).prefetch_related("categories")

    @admin.display(description=_("Kategorien"))
    def category_list(self, obj: EmailCampaign) -> str:
        return ", ".join(category.name for category in obj.categories.all()) or "—"

    @admin.display(description=_("Produkte"))
    def product_count(self, obj: EmailCampaign) -> int:
        if obj.layout_mode in {EmailCampaign.LayoutMode.SIMPLE, EmailCampaign.LayoutMode.VISUAL}:
            return obj.campaign_products.count()
        return obj.components.filter(
            Q(product__isnull=False) | Q(campaign_product__isnull=False)
        ).distinct().count()

    @admin.display(description=_("Komponenten"))
    def component_count(self, obj: EmailCampaign) -> int:
        return obj.components.count()

    @admin.display(description=_("Kampagnen-Info"))
    def campaign_context_info(self, obj: EmailCampaign):
        return format_html(
            "<div style='display:grid;gap:16px'>{}</div>",
            _recipient_customer_context_info_html(),
        )

    def save_formset(self, request, form, formset, change):
        instances = formset.save(commit=False)
        campaign = form.instance
        new_instances = [i for i in instances if not i.pk and isinstance(i, EmailCampaignComponent)]
        if new_instances:
            existing_max = (
                EmailCampaignComponent.objects.filter(campaign=campaign)
                .aggregate(max_order=Max("order"))["max_order"]
                or 0
            )
            next_order = existing_max + 10
            for instance in new_instances:
                instance.order = next_order
                next_order += 10
        for instance in instances:
            instance.save()
        formset.save_m2m()
        for obj in formset.deleted_objects:
            obj.delete()

    def save_model(self, request, obj, form, change):
        if not change:
            source_id = request.GET.get(self.copy_source_param)
            if source_id:
                source_campaign = self.get_object(request, source_id)
                if source_campaign:
                    obj.layout_mode = source_campaign.layout_mode
                    if source_campaign.layout_mode in {EmailCampaign.LayoutMode.SIMPLE, EmailCampaign.LayoutMode.VISUAL}:
                        obj.editor_content = deepcopy(source_campaign.editor_content)
        super().save_model(request, obj, form, change)
        if change:
            return

        source_id = request.GET.get(self.copy_source_param)
        if source_id:
            source_campaign = self.get_object(request, source_id)
            if source_campaign is None:
                return
            if not self.has_view_or_change_permission(request, source_campaign):
                raise PermissionDenied
            if source_campaign.layout_mode in {EmailCampaign.LayoutMode.SIMPLE, EmailCampaign.LayoutMode.VISUAL}:
                copied_products = _copy_campaign_products(source_campaign, obj)
                id_map = {old_id: item.pk for old_id, item in copied_products.items()}
                content = dict(obj.editor_content or {})
                if source_campaign.layout_mode == EmailCampaign.LayoutMode.SIMPLE:
                    for heading in content.get("headings") or []:
                        old_id = heading.get("after_product_id")
                        if old_id:
                            heading["after_product_id"] = str(id_map.get(int(old_id), ""))
                elif content.get("visual_document"):
                    from emails.visual_editor import remap_product_ids

                    content["visual_document"] = remap_product_ids(content["visual_document"], id_map)
                obj.editor_content = content
                obj.save(update_fields=["editor_content"])
            elif source_campaign.layout_mode == EmailCampaign.LayoutMode.COMPONENTS:
                _copy_campaign_components(source_campaign, obj)
            return

        if obj.layout_mode == EmailCampaign.LayoutMode.COMPONENTS:
            self._ensure_default_components(obj)

    def response_add(self, request, obj, post_url_continue=None):
        if obj.layout_mode == EmailCampaign.LayoutMode.VISUAL and "_addanother" not in request.POST:
            return HttpResponseRedirect(reverse("admin:emails_emailcampaign_visual_editor", args=[obj.pk]))
        if obj.layout_mode == EmailCampaign.LayoutMode.SIMPLE and "_addanother" not in request.POST:
            url = reverse("admin:emails_emailcampaign_simple_editor", args=[obj.pk])
            return HttpResponseRedirect(url)
        return super().response_add(request, obj, post_url_continue)

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
                    title=lib_component.name,
                    variables={},
                    order=index * 10,
                    enabled=True,
                )
            )
        EmailCampaignComponent.objects.bulk_create(components)

    def get_urls(self):
        urls = super().get_urls()
        custom = [
            path("<int:campaign_id>/visual-editor/", self.admin_site.admin_view(self.visual_editor_view), name="emails_emailcampaign_visual_editor"),
            path("<int:campaign_id>/visual-editor/save/", self.admin_site.admin_view(self.visual_editor_save_view), name="emails_emailcampaign_visual_save"),
            path("<int:campaign_id>/visual-editor/preview/", self.admin_site.admin_view(self.visual_editor_preview_view), name="emails_emailcampaign_visual_preview"),
            path("<int:campaign_id>/editor/", self.admin_site.admin_view(self.simple_editor_view), name="emails_emailcampaign_simple_editor"),
            path("<int:campaign_id>/editor/save/", self.admin_site.admin_view(self.simple_editor_save_view), name="emails_emailcampaign_simple_save"),
            path("<int:campaign_id>/editor/preview/", self.admin_site.admin_view(self.simple_editor_preview_view), name="emails_emailcampaign_simple_preview"),
            path("<int:campaign_id>/editor/search/", self.admin_site.admin_view(self.simple_editor_search_view), name="emails_emailcampaign_simple_search"),
            path("<int:campaign_id>/editor/product/add/", self.admin_site.admin_view(self.simple_editor_product_add_view), name="emails_emailcampaign_simple_product_add"),
            path("<int:campaign_id>/editor/product/<int:product_id>/", self.admin_site.admin_view(self.simple_editor_product_view), name="emails_emailcampaign_simple_product"),
            path(
                "<int:campaign_id>/export-html/",
                self.admin_site.admin_view(self.export_html_view),
                name="emails_emailcampaign_export_html",
            ),
        ]
        return custom + urls

    def _editor_campaign(self, request, campaign_id):
        from django.shortcuts import get_object_or_404

        campaign = get_object_or_404(EmailCampaign, pk=campaign_id)
        if not self.has_change_permission(request, campaign):
            raise PermissionDenied
        if campaign.layout_mode != EmailCampaign.LayoutMode.SIMPLE:
            raise PermissionDenied
        return campaign

    def _product_editor_campaign(self, request, campaign_id):
        campaign = self._visual_campaign(request, campaign_id)
        if campaign.layout_mode not in {EmailCampaign.LayoutMode.SIMPLE, EmailCampaign.LayoutMode.VISUAL}:
            raise PermissionDenied
        return campaign

    def _visual_campaign(self, request, campaign_id):
        from django.shortcuts import get_object_or_404

        campaign = get_object_or_404(EmailCampaign, pk=campaign_id)
        if not self.has_change_permission(request, campaign):
            raise PermissionDenied
        return campaign

    def visual_editor_view(self, request, campaign_id):
        from django.shortcuts import render
        from emails.visual_editor import ATTRS, CHILDREN, default_document

        campaign = self._visual_campaign(request, campaign_id)
        campaign_products = list(campaign.campaign_products.select_related("product").order_by("order", "id"))
        document = (campaign.editor_content or {}).get("visual_document") or default_document(
            campaign.editor_content, [item.pk for item in campaign_products]
        )
        return render(request, "emails/visual_editor.html", {
            "campaign": campaign,
            "document": document,
            "schema": {"children": CHILDREN, "attrs": ATTRS},
            "products": {
                str(item.pk): {
                    "label": f"{item.product.erp_nr} · {item.product.name or ''}",
                    "mode": "price" if item.special_price_override else "percent" if item.discount_pct else "none",
                    "value": str(item.special_price_override or item.discount_pct or ""),
                }
                for item in campaign_products
            },
        })

    def visual_editor_save_view(self, request, campaign_id):
        from emails.visual_editor import product_ids, render_visual_mjml, validate_document

        campaign = self._visual_campaign(request, campaign_id)
        if request.method != "POST":
            return JsonResponse({"error": "POST erforderlich."}, status=405)
        try:
            document = validate_document(json.loads(request.body))
            allowed_ids = set(campaign.campaign_products.values_list("id", flat=True))
            if not product_ids(document) <= allowed_ids:
                raise ValueError("Ein Produkt gehört nicht zu dieser Kampagne.")
            compile_mjml_to_html(render_visual_mjml(document, campaign=campaign))
            campaign.editor_content = {**(campaign.editor_content or {}), "visual_document": document}
            campaign.layout_mode = EmailCampaign.LayoutMode.VISUAL
            campaign.save(update_fields=["editor_content", "layout_mode"])
            return JsonResponse({"saved": True})
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            return JsonResponse({"error": str(exc)}, status=400)
        except Exception:
            logger.exception("Visual MJML save validation failed for campaign %s", campaign_id)
            return JsonResponse({"error": "MJML konnte nicht kompiliert werden."}, status=400)

    def visual_editor_preview_view(self, request, campaign_id):
        from emails.visual_editor import render_visual_mjml

        campaign = self._visual_campaign(request, campaign_id)
        if request.method != "POST":
            return JsonResponse({"error": "POST erforderlich."}, status=405)
        try:
            document = json.loads(request.body)
            mjml = render_visual_mjml(document, campaign=campaign)
            preview_mjml = render_visual_mjml(document, campaign=campaign, editor_classes=True)
            return JsonResponse({"html": compile_mjml_to_html(preview_mjml), "mjml": mjml})
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            return JsonResponse({"error": str(exc)}, status=400)
        except Exception:
            logger.exception("Visual MJML preview failed for campaign %s", campaign_id)
            return JsonResponse({"error": "Vorschau konnte nicht erstellt werden."}, status=500)

    def simple_editor_view(self, request, campaign_id):
        from django.shortcuts import render
        from emails.simple_editor import content_for

        campaign = self._editor_campaign(request, campaign_id)
        return render(request, "emails/simple_editor.html", {
            "campaign": campaign,
            "content": content_for(campaign),
            "campaign_products": campaign.campaign_products.select_related("product").order_by("order", "id"),
        })

    def simple_editor_save_view(self, request, campaign_id):
        from emails.simple_editor import DEFAULT_CONTENT, normalize_headings, valid_media_url

        campaign = self._editor_campaign(request, campaign_id)
        if request.method != "POST":
            return JsonResponse({"error": "POST erforderlich."}, status=405)
        try:
            payload = json.loads(request.body)
            if not isinstance(payload, dict):
                raise ValueError("Ungültige Daten.")
            content = {**(campaign.editor_content or {})}
            for key in DEFAULT_CONTENT:
                if key in {"product_texts", "headings"}:
                    continue
                if key in payload:
                    content[key] = str(payload[key])[:10000]
            if not valid_media_url(content.get("logo_url", DEFAULT_CONTENT["logo_url"])):
                raise ValueError("Die Logo-URL muss mit http oder https beginnen.")
            if "headings" in payload:
                raw_headings = payload["headings"]
                if not isinstance(raw_headings, list) or len(raw_headings) > 30:
                    raise ValueError("Maximal 30 Zwischenüberschriften sind möglich.")
                headings = normalize_headings(raw_headings)
                if len(headings) != len(raw_headings):
                    raise ValueError("Eine Zwischenüberschrift hat eine ungültige Kennung.")
                product_ids = {
                    str(pk) for pk in campaign.campaign_products.values_list("id", flat=True)
                }
                if any(
                    heading["after_product_id"] not in product_ids | {""}
                    for heading in headings
                ):
                    raise ValueError("Die Position einer Zwischenüberschrift ist ungültig.")
                content["headings"] = headings
            product_texts = payload.get("product_texts")
            if isinstance(product_texts, dict):
                allowed_ids = {str(pk) for pk in campaign.campaign_products.values_list("product_id", flat=True)}
                for item in product_texts.values():
                    if not isinstance(item, dict):
                        continue
                    for url in str(item.get("media_urls", "")).splitlines():
                        if url.strip() and not valid_media_url(url):
                            raise ValueError("Produktbilder benötigen eine gültige http- oder https-URL.")
                content["product_texts"] = {
                    key: {
                        field: str(value)[:10000]
                        for field, value in item.items() if field in {"section_heading", "title", "description", "media_urls"}
                    }
                    for key, item in product_texts.items()
                    if key in allowed_ids and isinstance(item, dict)
                }
            campaign.editor_content = content
            campaign.save(update_fields=["editor_content"])
            return JsonResponse({"saved": True})
        except (ValueError, TypeError) as exc:
            return JsonResponse({"error": str(exc)}, status=400)

    def simple_editor_preview_view(self, request, campaign_id):
        from emails.simple_editor import build_simple_mjml

        campaign = self._editor_campaign(request, campaign_id)
        if request.method != "POST":
            return JsonResponse({"error": "POST erforderlich."}, status=405)
        try:
            content = json.loads(request.body)
            mjml = build_simple_mjml(campaign, override=content)
            return JsonResponse({"html": compile_mjml_to_html(mjml)})
        except Exception:
            logger.exception("Simple email preview failed for campaign %s", campaign_id)
            return JsonResponse({"error": "Vorschau konnte nicht erstellt werden."}, status=500)

    def simple_editor_search_view(self, request, campaign_id):
        from products.models import Product

        self._product_editor_campaign(request, campaign_id)
        query = request.GET.get("q", "").strip()[:100]
        if len(query) < 2:
            return JsonResponse({"products": []})
        products = Product.objects.filter(is_archived=False).filter(
            Q(erp_nr__icontains=query) | Q(sku__icontains=query) | Q(name__icontains=query)
        ).order_by("erp_nr")[:12]
        return JsonResponse({"products": [
            {"id": product.pk, "label": f"{product.erp_nr} · {product.name or ''}"}
            for product in products
        ]})

    def simple_editor_product_add_view(self, request, campaign_id):
        from products.models import Product

        campaign = self._product_editor_campaign(request, campaign_id)
        if request.method != "POST":
            return JsonResponse({"error": "POST erforderlich."}, status=405)
        try:
            payload = json.loads(request.body)
            product = Product.objects.get(pk=payload.get("product_id"), is_archived=False)
            campaign_product, _ = EmailCampaignProduct.objects.get_or_create(
                campaign=campaign, product=product,
                defaults={"order": campaign.campaign_products.count()},
            )
            return JsonResponse({"id": campaign_product.pk})
        except (Product.DoesNotExist, ValueError, TypeError):
            return JsonResponse({"error": "Produkt nicht gefunden."}, status=400)

    def simple_editor_product_view(self, request, campaign_id, product_id):
        from decimal import Decimal, InvalidOperation

        campaign = self._product_editor_campaign(request, campaign_id)
        if request.method != "POST":
            return JsonResponse({"error": "POST erforderlich."}, status=405)
        try:
            item = campaign.campaign_products.get(pk=product_id)
            payload = json.loads(request.body)
            action = payload.get("action")
            if campaign.layout_mode == EmailCampaign.LayoutMode.VISUAL and action != "price":
                raise ValueError("Im visuellen Editor wird die Reihenfolge über die Bausteine geändert.")
            if action == "remove":
                ordered_items = list(campaign.campaign_products.order_by("order", "id"))
                item_index = next(i for i, row in enumerate(ordered_items) if row.pk == item.pk)
                previous_id = str(ordered_items[item_index - 1].pk) if item_index else ""
                item.delete()
                content = dict(campaign.editor_content or {})
                product_texts = dict(content.get("product_texts") or {})
                product_texts.pop(str(item.product_id), None)
                content["product_texts"] = product_texts
                headings = list(content.get("headings") or [])
                for heading in headings:
                    if heading.get("after_product_id") == str(item.pk):
                        heading["after_product_id"] = previous_id
                content["headings"] = headings
                campaign.editor_content = content
                campaign.save(update_fields=["editor_content"])
            elif action == "price":
                mode = payload.get("mode")
                value = str(payload.get("value", "")).replace(",", ".").strip()
                amount = Decimal(value) if value else None
                if amount is not None and (not amount.is_finite() or amount <= 0):
                    raise ValueError("Der Wert muss größer als 0 sein.")
                if mode == "price":
                    if amount is not None:
                        from emails.mjml import ProductEmailProxy, _campaign_sales_channel_ids

                        list_price = ProductEmailProxy(
                            item.product,
                            sales_channel_ids=_campaign_sales_channel_ids(campaign),
                        ).price
                        if list_price is not None and amount >= list_price:
                            raise ValueError("Der Sonderpreis muss unter dem Listenpreis liegen.")
                    item.special_price_override, item.discount_pct = amount, None
                elif mode == "percent":
                    if amount is not None and amount >= 100:
                        raise ValueError("Rabatt muss unter 100 % liegen.")
                    item.special_price_override, item.discount_pct = None, amount
                elif mode == "none":
                    item.special_price_override = item.discount_pct = None
                else:
                    raise ValueError("Unbekannter Preismodus.")
                item.full_clean()
                item.save(update_fields=["special_price_override", "discount_pct"])
            elif action in {"up", "down"}:
                items = list(campaign.campaign_products.order_by("order", "id"))
                index = next(i for i, row in enumerate(items) if row.pk == item.pk)
                other = index + (-1 if action == "up" else 1)
                if 0 <= other < len(items):
                    items[index], items[other] = items[other], items[index]
                    for position, row in enumerate(items):
                        row.order = position
                    EmailCampaignProduct.objects.bulk_update(items, ["order"])
            else:
                raise ValueError("Unbekannte Aktion.")
            return JsonResponse({"saved": True})
        except (EmailCampaignProduct.DoesNotExist, ValueError, InvalidOperation, StopIteration, ValidationError) as exc:
            return JsonResponse({"error": str(exc)}, status=400)

    def export_html_view(self, request, campaign_id: int):
        try:
            campaign = EmailCampaign.objects.get(pk=campaign_id)
        except EmailCampaign.DoesNotExist:
            return JsonResponse({"error": "Kampagne nicht gefunden."}, status=404)

        try:
            preview_recipient = _latest_active_preview_recipient()
            mjml = render_campaign_mjml(campaign, recipient=preview_recipient)
            html = compile_mjml_to_html(mjml)
            text = html_to_plain_text(html)
        except Exception:
            logger.exception("MJML export failed for campaign %s", campaign_id)
            return JsonResponse({"error": "Fehler beim Rendern der Kampagne."}, status=500)

        if request.GET.get("download"):
            response = HttpResponse(html, content_type="text/html; charset=utf-8")
            safe_title = campaign.internal_title[:40].replace(" ", "_")
            filename = f"email_{campaign.pk}_{safe_title}.html"
            response["Content-Disposition"] = f'attachment; filename="{filename}"'
            return response

        return JsonResponse({"html": html, "mjml": mjml, "text": text})


@admin.register(EmailCampaignCategory)
class EmailCampaignCategoryAdmin(BaseAdmin):
    list_display = ("name", "created_at", "updated_at")
    search_fields = ("name",)
    ordering = ("name",)


@admin.register(EmailCampaignQueueEntry)
class EmailCampaignQueueEntryAdmin(BaseAdmin):
    list_display = ("email", "campaign", "recipient", "customer", "status", "queued_at", "sent_at")
    list_filter = ("status", "campaign", "queued_at", "sent_at")
    search_fields = (
        "email",
        "subject",
        "campaign__internal_title",
        "recipient__email",
        "recipient__first_name",
        "recipient__last_name",
        "customer__erp_nr",
        "customer__name",
        "customer__email",
    )
    autocomplete_fields = ("campaign", "recipient", "customer")
    readonly_fields = BaseAdmin.readonly_fields + (
        "campaign",
        "recipient",
        "customer",
        "email",
        "subject",
        "rendered_html_preview",
        "queued_at",
    )
    fieldsets = (
        (
            _("Warteschlange"),
            {
                "fields": ("campaign", "recipient", "customer", "email", "subject", "status"),
            },
        ),
        (
            _("Versand"),
            {
                "fields": ("queued_at", "sent_at", "error_message"),
            },
        ),
        (
            _("E-Mail Vorschau"),
            {
                "fields": ("rendered_html_preview",),
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

    @admin.display(description=_("Gerenderte HTML E-Mail"))
    def rendered_html_preview(self, obj: EmailCampaignQueueEntry):
        if not obj.rendered_html:
            return "—"
        return format_html(
            '<iframe sandbox="" srcdoc="{}" '
            'style="width:100%;min-height:720px;border:1px solid #d1d5db;'
            'border-radius:6px;background:#fff;"></iframe>',
            obj.rendered_html,
        )
