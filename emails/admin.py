# emails/admin.py
from __future__ import annotations

import json
import logging
import re

from django import forms
from django.contrib import admin
from django.db.models import Case, IntegerField, Max, Q, When
from django.http import HttpResponse, JsonResponse
from django.urls import path
from django.utils.html import format_html, format_html_join
from django.utils.translation import gettext_lazy as _

logger = logging.getLogger(__name__)

from core.admin import BaseAdmin, BaseStackedInline
from emails.mjml import compile_mjml_to_html, render_campaign_mjml
from emails.models import (
    EmailCampaign,
    EmailCampaignComponent,
    MjmlComponent,
)

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
    ("product.email_special_price", "aktiver Sonderpreis aus dem Produkt"),
    ("product.current_price", "Aktionspreis, sonst Listenpreis"),
    ("product.discount_pct", "Rabatt in Prozent"),
    ("product.shipping_cost_is_free", "kostenloser Versand true/false"),
    ("product.images", "sortierte Produktbilder"),
    ("product.first_image", "erstes Produktbild"),
)
_CHILDREN_SLOT_RE = re.compile(r"\{\{\s*children\s*\}\}")


def _children_slot_location(markup: str) -> tuple[int, str] | None:
    for line_number, line in enumerate((markup or "").splitlines(), start=1):
        if _CHILDREN_SLOT_RE.search(line):
            return line_number, line.strip()
    return None


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


class PrettyJSONWidget(forms.Textarea):
    def format_value(self, value):
        if value in (None, ""):
            return ""
        if isinstance(value, str):
            return value
        return json.dumps(value, ensure_ascii=False, indent=2)


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
    list_display = ("name", "placement", "is_default", "order")
    list_filter = ("placement", "is_default")
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
                "fields": ("mjml_markup", "default_variables"),
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
        )

    product_template_variables = component_info


class EmailCampaignComponentInline(BaseStackedInline):
    model = EmailCampaignComponent
    form = EmailCampaignComponentInlineForm
    tab = False
    ordering_field = "order"
    hide_ordering_field = True
    fieldsets = (
        (
            None,
            {
                "fields": ("tree_position", "order", "library_component", "variables"),
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
            return format_html("<span style='color:#6b7280'>{}</span>", _("Neue Komponente"))

        depth = _component_tree_depth(obj)
        prefix = "-" * depth
        component_name = getattr(getattr(obj, "library_component", None), "name", str(obj))
        return format_html(
            "<div style='margin-left:{}px;font-family:monospace'>"
            "<span style='color:#6b7280'>{}</span> {}</div>",
            depth * 24,
            prefix,
            component_name,
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
    list_display = ("internal_title", "component_count", "product_count", "status", "created_at")
    list_filter = ("status", "created_at")
    search_fields = ("internal_title",)
    list_editable = ("status",)
    inlines = (EmailCampaignComponentInline,)

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
        return obj.components.filter(
            Q(product__isnull=False) | Q(campaign_product__isnull=False)
        ).distinct().count()

    @admin.display(description=_("Komponenten"))
    def component_count(self, obj: EmailCampaign) -> int:
        return obj.components.count()

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
        super().save_model(request, obj, form, change)
        if not change:
            self._ensure_default_components(obj)

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
