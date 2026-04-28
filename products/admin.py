import json
import re
import subprocess
from html import unescape
from bs4 import Comment
from datetime import datetime
from decimal import Decimal
from io import BytesIO
from pathlib import Path
from shutil import which

from bs4 import BeautifulSoup
from django.conf import settings
from django import forms
from django.contrib import admin, messages
from django.contrib.admin.models import LogEntry
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.db import transaction
from django.db.models import Case, Count, F, IntegerField, Prefetch, Q, Value, When, Window
from django.db.models.functions import RowNumber
from django.http import Http404, HttpResponse, HttpResponseRedirect, HttpResponseNotAllowed, JsonResponse
from django.template.loader import render_to_string
from django.template.response import TemplateResponse
from django.urls import path, reverse
from django.utils.text import slugify
from django.utils import timezone
from django.utils.html import format_html, format_html_join
from django.utils.safestring import mark_safe
from modeltranslation.admin import TabbedTranslationAdmin
from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas as pdf_canvas
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.platypus import (
    CondPageBreak,
    Flowable,
    KeepTogether,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)
from django.views.generic import TemplateView
from pypdf import PdfReader, PdfWriter

from ai.models import AIRewriteJob, AIRewritePrompt
from ai.rewrite_fields import get_rewriteable_product_field_names
from ai.services import AIRewriteService
from unfold.contrib.filters.admin import (
    BooleanRadioFilter,
    RangeDateTimeFilter,
    RangeNumericFilter,
    RelatedDropdownFilter,
)
from unfold.decorators import action
from unfold.enums import ActionVariant
from unfold.forms import ActionForm as UnfoldActionForm
from unfold.views import UnfoldModelAdminViewMixin

from core.admin import BaseAdmin, BaseStackedInline, BaseTabularInline
from core.admin_utils import log_admin_change
from mappei.models import MappeiPriceSnapshot, MappeiProductMapping
from shopware.models import ShopwareSettings
from .services import PriceIncreaseService
from .models import (
    Category,
    Image,
    Price,
    PriceHistory,
    PriceIncrease,
    PriceIncreaseItem,
    Product,
    ProductImage,
    ProductProperty,
    PropertyGroup,
    PropertyValue,
    Storage,
    Tax,
)


class FullWidthHeadingBar(Flowable):
    def __init__(
        self,
        html: str,
        style: ParagraphStyle,
        *,
        page_width: float,
        left_margin: float,
        background_color=colors.HexColor("#e9ecef"),
        padding_top: float = 7,
        padding_bottom: float = 7,
    ):
        super().__init__()
        self.paragraph = Paragraph(html, style)
        self.page_width = page_width
        self.left_margin = left_margin
        self.background_color = background_color
        self.padding_top = padding_top
        self.padding_bottom = padding_bottom
        self.height = 0
        self.paragraph_width = 0

    def wrap(self, avail_width, avail_height):
        paragraph_width, paragraph_height = self.paragraph.wrap(avail_width, avail_height)
        self.paragraph_width = paragraph_width
        self.height = paragraph_height + self.padding_top + self.padding_bottom
        return avail_width, self.height

    def draw(self):
        canvas = self.canv
        canvas.saveState()
        canvas.setFillColor(self.background_color)
        canvas.rect(-self.left_margin, 0, self.page_width, self.height, stroke=0, fill=1)
        canvas.restoreState()
        self.paragraph.drawOn(canvas, 0, self.padding_bottom)


class StorageInline(BaseStackedInline):
    model = Storage
    fields = ("stock", "virtual_stock", "location")
    extra = 0


class ProductImageInline(BaseTabularInline):
    model = ProductImage
    fields = ("image_preview", "image", "order")
    readonly_fields = BaseTabularInline.readonly_fields + ("image_preview",)
    autocomplete_fields = ("image",)
    ordering_field = "order"
    hide_ordering_field = True

    def get_queryset(self, request):
        queryset = super().get_queryset(request)
        return queryset.select_related("image").order_by("order", "id")

    @admin.display(description="Vorschau")
    def image_preview(self, obj: ProductImage):
        image = getattr(obj, "image", None)
        if not image or not image.url:
            return ""
        return format_html(
            '<img src="{}" loading="lazy" style="width:60px;height:60px;object-fit:cover;border-radius:4px;" />',
            image.url,
        )


class PriceInline(BaseTabularInline):
    model = Price
    fields = (
        "sales_channel",
        "price",
        "special_percentage",
        "special_start_date",
        "special_end_date",
        "special_price",
        "special_active",
        "rebate_quantity",
        "rebate_price",
    )
    readonly_fields = BaseTabularInline.readonly_fields + ("special_price", "special_active")

    def get_queryset(self, request):
        queryset = super().get_queryset(request)
        return (
            queryset.exclude(sales_channel__isnull=True)
            .select_related("sales_channel")
            .order_by(
                Case(
                    When(sales_channel__is_default=True, then=Value(0)),
                    default=Value(1),
                    output_field=IntegerField(),
                ),
                "sales_channel__name",
                "pk",
            )
        )

    @admin.display(boolean=True, description="Sonderpreis aktiv")
    def special_active(self, obj: Price) -> bool:
        return obj.is_special_active

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "sales_channel":
            kwargs["queryset"] = ShopwareSettings.objects.filter(is_active=True).order_by(
                Case(
                    When(is_default=True, then=Value(0)),
                    default=Value(1),
                    output_field=IntegerField(),
                ),
                "name",
                "pk",
            )
        return super().formfield_for_foreignkey(db_field, request, **kwargs)


class PriceHistoryInline(BaseTabularInline):
    model = PriceHistory
    fields = (
        "created_at",
        "change_type",
        "changed_fields",
        "price",
        "rebate_quantity",
        "rebate_price",
        "special_percentage",
        "special_price",
        "special_start_date",
        "special_end_date",
    )
    readonly_fields = fields
    can_delete = False
    extra = 0
    max_num = 0
    ordering = ("-created_at", "-id")

    def has_add_permission(self, request, obj=None):
        return False


class ProductPropertyInline(BaseTabularInline):
    model = ProductProperty
    fields = ("group_name", "value")
    readonly_fields = BaseTabularInline.readonly_fields + ("group_name",)
    autocomplete_fields = ("value",)

    def get_queryset(self, request):
        queryset = super().get_queryset(request)
        return queryset.select_related("value__group").order_by("value__group__name", "value__name", "id")

    @admin.display(description="Gruppe")
    def group_name(self, obj: ProductProperty):
        if not obj.value_id:
            return ""
        return obj.value.group.name


class ProductSpecialPriceActionForm(UnfoldActionForm):
    sales_channel = forms.ModelChoiceField(
        label="Sales-Channel",
        required=False,
        queryset=ShopwareSettings.objects.none(),
    )
    special_percentage = forms.DecimalField(
        label="Sonderpreis Prozent",
        required=False,
        min_value=Decimal("0.01"),
        max_value=Decimal("99.99"),
        decimal_places=2,
    )
    special_start_date = forms.DateTimeField(
        label="Sonderpreis ab",
        required=False,
        input_formats=["%Y-%m-%dT%H:%M", "%Y-%m-%dT%H:%M:%S"],
        widget=forms.DateTimeInput(
            format="%Y-%m-%dT%H:%M",
            attrs={"type": "datetime-local"},
        ),
    )
    special_end_date = forms.DateTimeField(
        label="Sonderpreis bis",
        required=False,
        input_formats=["%Y-%m-%dT%H:%M", "%Y-%m-%dT%H:%M:%S"],
        widget=forms.DateTimeInput(
            format="%Y-%m-%dT%H:%M",
            attrs={"type": "datetime-local"},
        ),
    )
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["sales_channel"].queryset = ShopwareSettings.objects.filter(is_active=True).order_by(
            Case(
                When(is_default=True, then=Value(0)),
                default=Value(1),
                output_field=IntegerField(),
            ),
            "name",
            "pk",
        )


class PriceActionForm(UnfoldActionForm):
    special_percentage = forms.DecimalField(
        label="Sonderpreis (%)",
        required=False,
        min_value=Decimal("0.01"),
        max_value=Decimal("99.99"),
        decimal_places=2,
    )
    special_start_date = forms.DateTimeField(
        label="Sonderpreis ab",
        required=False,
        input_formats=["%Y-%m-%dT%H:%M", "%Y-%m-%dT%H:%M:%S"],
        widget=forms.DateTimeInput(
            format="%Y-%m-%dT%H:%M",
            attrs={"type": "datetime-local"},
        ),
    )
    special_end_date = forms.DateTimeField(
        label="Sonderpreis bis",
        required=False,
        input_formats=["%Y-%m-%dT%H:%M", "%Y-%m-%dT%H:%M:%S"],
        widget=forms.DateTimeInput(
            format="%Y-%m-%dT%H:%M",
            attrs={"type": "datetime-local"},
        ),
    )


class PriceIncreaseItemEditForm(forms.ModelForm):
    class Meta:
        model = PriceIncreaseItem
        fields = ("new_price", "new_rebate_price")
        widgets = {
            "new_price": forms.TextInput(attrs={"inputmode": "decimal"}),
            "new_rebate_price": forms.TextInput(attrs={"inputmode": "decimal"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["new_price"].required = False
        self.fields["new_rebate_price"].required = False
        self.fields["new_price"].label = "Neuer Preis"
        self.fields["new_rebate_price"].label = "neuer Rab.Preis"
        self.fields["new_price"].localize = True
        self.fields["new_rebate_price"].localize = True
        self._apply_dynamic_widget_state()

    def _apply_dynamic_widget_state(self):
        base_input_classes = (
            "w-full rounded border border-gray-300 bg-white px-3 py-2 text-sm "
            "focus:border-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-500/20"
        )
        self.fields["new_price"].widget.attrs["class"] = base_input_classes
        self.fields["new_rebate_price"].widget.attrs["class"] = base_input_classes
        if self.instance.price_increase_id and self.instance.current_price is not None:
            self.fields["new_price"].widget.attrs["placeholder"] = self._format_decimal(self.instance.suggested_price)
            if self.instance.suggested_rebate_price is not None:
                self.fields["new_rebate_price"].widget.attrs["placeholder"] = self._format_decimal(
                    self.instance.suggested_rebate_price
                )
        if self.instance.price_increase_id and self.instance.price_increase.status == PriceIncrease.Status.APPLIED:
            self.fields["new_price"].disabled = True
            self.fields["new_rebate_price"].disabled = True

    @staticmethod
    def _format_decimal(value: Decimal | None) -> str:
        if value is None:
            return ""
        return format(value.quantize(Decimal("0.01")), "f")


class PriceIncreaseItemValueForm(forms.Form):
    value = forms.DecimalField(required=False, localize=True)


class PriceIncreasePositionsPageView(UnfoldModelAdminViewMixin, TemplateView):
    title = "Preiserhoehungs-Positionen"
    permission_required = ("products.view_priceincrease",)
    template_name = "admin/products/price_increase_positions.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        price_increase = self.model_admin._get_price_increase_or_404(self.kwargs["object_id"])
        context.update(
            self.model_admin._build_positions_context(
                request=self.request,
                price_increase=price_increase,
                search_term=self.request.GET.get("q", ""),
            )
        )
        return context


class CategoryManagerPageView(UnfoldModelAdminViewMixin, TemplateView):
    title = "Kategorien verwalten"
    permission_required = ("products.view_category",)
    template_name = "admin/products/category_manager.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(self.model_admin._build_manager_context(self.request))
        return context


@admin.register(Product)
class ProductAdmin(TabbedTranslationAdmin, BaseAdmin):
    formfield_overrides = {
        **getattr(TabbedTranslationAdmin, "formfield_overrides", {}),
        **BaseAdmin.formfield_overrides,
    }
    compressed_fields = BaseAdmin.compressed_fields
    warn_unsaved_form = BaseAdmin.warn_unsaved_form
    change_form_show_cancel_button = BaseAdmin.change_form_show_cancel_button
    list_filter_sheet = BaseAdmin.list_filter_sheet
    list_horizontal_scrollbar_top = BaseAdmin.list_horizontal_scrollbar_top
    list_display = ("image_preview", "erp_nr", "name", "customs_tariff_number", "is_active", "created_at")
    list_display_links = list_display
    ordering = ("-is_active", "erp_nr")
    search_fields = ("erp_nr", "sku", "name")
    list_filter = [
        ("is_active", BooleanRadioFilter),
        ("tax", RelatedDropdownFilter),
        ("categories", RelatedDropdownFilter),
        ("created_at", RangeDateTimeFilter),
    ]
    inlines = (ProductImageInline, ProductPropertyInline, StorageInline, PriceInline)
    exclude = ("images",)
    filter_horizontal = ("categories",)
    action_form = ProductSpecialPriceActionForm
    actions = (
        "sync_from_microtech",
        "sync_to_shopware",
        "set_special_price_for_channel",
        "clear_special_price_for_channel",
    )
    actions_detail = (
        "sync_from_microtech_detail",
        "sync_to_shopware_detail",
    )
    change_form_after_template = "admin/products/includes/ai_rewrite_field_buttons.html"

    def get_queryset(self, request):
        queryset = super().get_queryset(request)
        return queryset.prefetch_related(
            Prefetch(
                "product_images",
                queryset=ProductImage.objects.select_related("image").order_by("order", "id"),
                to_attr="ordered_product_images",
            )
        )

    def _redirect_to_change_page(self, object_id: str) -> HttpResponseRedirect:
        change_url = reverse("admin:products_product_change", args=(object_id,))
        return HttpResponseRedirect(change_url)

    def get_urls(self):
        return [
            path(
                "<path:object_id>/request-ai-rewrite/",
                self.admin_site.admin_view(self.request_ai_rewrite_for_field),
                name="products_product_request_ai_rewrite",
            ),
        ] + super().get_urls()

    def _log_admin_error(self, request, message: str, *, obj: Product | None = None) -> None:
        log_admin_change(
            user_id=request.user.id,
            content_type_id=ContentType.objects.get_for_model(Product).id,
            object_id=str(obj.pk) if obj else None,
            object_repr=str(obj) if obj else "Shopware Sync",
            message=message,
        )

    def _build_action_form(self, request):
        form = self.action_form(request.POST)
        form.fields["action"].choices = self.get_action_choices(request)
        return form

    @staticmethod
    def _to_aware_datetime(value):
        if value and timezone.is_naive(value):
            return timezone.make_aware(value, timezone.get_current_timezone())
        return value

    @admin.display(description="Bild")
    def image_preview(self, obj: Product):
        image = obj.first_image
        if not image or not image.url:
            return ""
        return format_html(
            '<img src="{}" loading="lazy" style="width:50px;height:50px;object-fit:cover;border-radius:4px;" />',
            image.url,
        )

    def render_change_form(self, request, context, add=False, change=False, form_url="", obj=None):
        context = {
            **context,
            "ai_rewrite_field_targets_json": self._build_ai_rewrite_field_targets_json(context),
            "ai_rewrite_create_url": (
                reverse("admin:products_product_request_ai_rewrite", args=(obj.pk,))
                if obj and obj.pk
                else ""
            ),
        }
        return super().render_change_form(
            request,
            context,
            add=add,
            change=change,
            form_url=form_url,
            obj=obj,
        )

    def _build_ai_rewrite_field_targets_json(self, context) -> list[dict[str, object]]:
        adminform = context.get("adminform")
        if adminform is None:
            return []
        rewriteable_field_names = get_rewriteable_product_field_names()
        form_field_names = set(adminform.form.fields.keys()) & rewriteable_field_names
        product_content_type = ContentType.objects.get_for_model(Product)
        prompt_counts: dict[str, int] = {}
        for target_field in (
            AIRewritePrompt.objects.filter(
                is_active=True,
                content_type=product_content_type,
                target_field__in=form_field_names,
            )
            .order_by("target_field")
            .values_list("target_field", flat=True)
        ):
            prompt_counts[target_field] = prompt_counts.get(target_field, 0) + 1
        payload = [
            {
                "field": field_name,
                "label": "AI",
                "title": (
                    "Rewrite mit Standard-Prompt erzeugen"
                    if prompt_counts.get(field_name, 0) == 1
                    else "Rewrite fuer dieses Feld anlegen"
                ),
                "hasMultiplePrompts": prompt_counts.get(field_name, 0) > 1,
            }
            for field_name in sorted(form_field_names)
        ]
        return payload

    def request_ai_rewrite_for_field(self, request, object_id: str):
        if request.method != "POST":
            return HttpResponseNotAllowed(["POST"])
        if not request.user.has_perm("ai.add_airewritejob"):
            self.message_user(request, "Keine Berechtigung fuer AI Rewrite Jobs.", level=messages.ERROR)
            return self._redirect_to_change_page(object_id)

        product = self.get_object(request, object_id)
        if not product:
            self.message_user(request, "Produkt nicht gefunden.", level=messages.ERROR)
            return self._redirect_to_change_page(object_id)

        target_field = str(request.POST.get("target_field") or "").strip()
        if not target_field:
            self.message_user(request, "Kein Zielfeld uebergeben.", level=messages.ERROR)
            return self._redirect_to_change_page(object_id)

        product_content_type = ContentType.objects.get_for_model(Product)
        prompt_queryset = (
            AIRewritePrompt.objects.filter(
                is_active=True,
                content_type=product_content_type,
                target_field=target_field,
            )
            .select_related("provider")
            .order_by("name", "pk")
        )
        prompt_count = prompt_queryset.count()

        if prompt_count != 1:
            if prompt_count == 0:
                self.message_user(
                    request,
                    f"Kein aktiver AI-Prompt fuer das Feld '{target_field}' vorhanden. Bitte im Request-Formular einen Prompt auswaehlen oder anlegen.",
                    level=messages.WARNING,
                )
            request_url = reverse("admin:ai_airewritejob_request")
            return HttpResponseRedirect(
                f"{request_url}?product={product.pk}&target_field={target_field}"
            )

        prompt = prompt_queryset.first()
        if prompt is None:
            self.message_user(request, "Kein passender Prompt gefunden.", level=messages.ERROR)
            return self._redirect_to_change_page(object_id)

        job = AIRewriteService().request_rewrite(
            content_object=product,
            prompt=prompt,
            requested_by=request.user,
        )
        if job.status == AIRewriteJob.Status.FAILED:
            self.message_user(
                request,
                f"Rewrite fehlgeschlagen: {job.error_message}",
                level=messages.ERROR,
            )
        else:
            self.message_user(
                request,
                f"Rewrite-Job fuer {product.erp_nr} / {target_field} erzeugt.",
            )
        return HttpResponseRedirect(reverse("admin:ai_airewritejob_change", args=(job.pk,)))

    def _sync_products_bulk(self, products, request=None) -> tuple[int, int, list[str]]:
        erp_nrs = [erp_nr for erp_nr in products.values_list("erp_nr", flat=True)] if hasattr(products, "values_list") else [
            product.erp_nr for product in products
        ]
        erp_nrs = [erp_nr for erp_nr in erp_nrs if erp_nr]
        if not erp_nrs:
            return 0, 0, []

        try:
            call_command("shopware_sync_products", *erp_nrs)
        except Exception as exc:
            if request:
                for erp_nr in erp_nrs:
                    product = Product.objects.filter(erp_nr=erp_nr).first()
                    self._log_admin_error(
                        request,
                        f"Shopware sync fehlgeschlagen fuer {erp_nr}: {exc}",
                        obj=product,
                    )
            return 0, len(erp_nrs), [str(exc)]

        return len(erp_nrs), 0, []

    @action(
        description="Von Microtech synchronisieren",
        icon="sync",
        variant=ActionVariant.PRIMARY,
    )
    def sync_from_microtech(self, request, queryset):
        erp_nrs = list(queryset.values_list("erp_nr", flat=True))
        if not erp_nrs:
            self.message_user(request, "Keine Produkte ausgewaehlt.", level=messages.WARNING)
            return
        try:
            call_command("microtech_sync_products", *erp_nrs)
            self.message_user(request, f"{len(erp_nrs)} Produkt(e) von Microtech synchronisiert.")
        except Exception as exc:
            self._log_admin_error(
                request,
                f"Microtech sync failed: {exc}",
            )
            self.message_user(request, f"Microtech Sync fehlgeschlagen: {exc}", level=messages.ERROR)

    @action(
        description="Von Microtech synchronisieren",
        icon="sync",
        variant=ActionVariant.PRIMARY,
    )
    def sync_from_microtech_detail(self, request, object_id: str):
        product = self.get_object(request, object_id)
        if not product:
            self.message_user(request, "Produkt nicht gefunden.", level=messages.ERROR)
            return self._redirect_to_change_page(object_id)
        try:
            call_command("microtech_sync_products", product.erp_nr)
            self.message_user(request, f"Produkt {product.erp_nr} von Microtech synchronisiert.")
        except Exception as exc:
            self._log_admin_error(
                request,
                f"Microtech sync failed for {product.erp_nr}: {exc}",
                obj=product,
            )
            self.message_user(request, f"Microtech Sync fehlgeschlagen: {exc}", level=messages.ERROR)
        return self._redirect_to_change_page(object_id)

    @action(
        description="Nach Shopware synchronisieren",
        icon="sync",
        variant=ActionVariant.PRIMARY,
    )
    def sync_to_shopware(self, request, queryset):
        try:
            success_count, error_count, error_messages = self._sync_products_bulk(queryset, request=request)
        except Exception as exc:
            self._log_admin_error(
                request,
                f"Shopware sync fehlgeschlagen: {exc}",
            )
            self.message_user(
                request,
                f"Sync fehlgeschlagen: {exc} — Details im Produkt-Verlauf (History).",
                level=messages.ERROR,
            )
            return
        if success_count:
            self.message_user(request, f"{success_count} Produkt(e) synchronisiert.")
        if error_count:
            detail = f": {error_messages[0]}" if error_messages else ""
            self.message_user(
                request,
                f"{error_count} Produkt(e) mit Fehlern{detail} — Details im Produkt-Verlauf (History).",
                level=messages.ERROR,
            )

    @action(
        description="Nach Shopware synchronisieren",
        icon="sync",
        variant=ActionVariant.PRIMARY,
    )
    def sync_to_shopware_detail(self, request, object_id: str):
        product = self.get_object(request, object_id)
        if not product:
            self.message_user(request, "Produkt nicht gefunden.", level=messages.ERROR)
            return self._redirect_to_change_page(object_id)
        try:
            success_count, error_count, error_messages = self._sync_products_bulk([product], request=request)
            if success_count:
                self.message_user(request, f"Produkt {product.erp_nr} synchronisiert.")
            if error_count:
                detail = error_messages[0] if error_messages else "Unbekannter Fehler"
                self.message_user(
                    request,
                    f"Sync fehlgeschlagen: {detail} — Details im Produkt-Verlauf (History).",
                    level=messages.ERROR,
                )
        except Exception as exc:
            self._log_admin_error(
                request,
                f"Shopware sync fehlgeschlagen fuer {product.erp_nr}: {exc}",
                obj=product,
            )
            self.message_user(
                request,
                f"Sync fehlgeschlagen: {exc} — Details im Produkt-Verlauf (History).",
                level=messages.ERROR,
            )
        return self._redirect_to_change_page(object_id)

    @admin.action(description="Sonderpreis fuer Sales-Channel setzen")
    def set_special_price_for_channel(self, request, queryset):
        form = self._build_action_form(request)
        if not form.is_valid():
            self.message_user(
                request,
                "Bitte gueltige Werte fuer Sales-Channel, Prozent, Start und Ende eingeben.",
                level=messages.ERROR,
            )
            return

        sales_channel = form.cleaned_data.get("sales_channel")
        special_percentage = form.cleaned_data.get("special_percentage")
        special_start_date = self._to_aware_datetime(form.cleaned_data.get("special_start_date"))
        special_end_date = self._to_aware_datetime(form.cleaned_data.get("special_end_date"))

        if sales_channel is None:
            self.message_user(request, "Bitte einen Sales-Channel auswaehlen.", level=messages.ERROR)
            return
        if special_percentage is None:
            self.message_user(request, "Bitte einen Prozentwert eingeben.", level=messages.ERROR)
            return
        if special_start_date and special_end_date and special_end_date < special_start_date:
            self.message_user(request, "Sonderpreis bis muss nach Sonderpreis ab liegen.", level=messages.ERROR)
            return

        prices = Price.objects.filter(product__in=queryset, sales_channel=sales_channel).select_related("product")
        updated = 0
        for price in prices:
            price.special_percentage = special_percentage
            price.special_start_date = special_start_date
            price.special_end_date = special_end_date
            price.save()
            updated += 1

        total_products = queryset.count()
        missing = total_products - updated
        self.message_user(
            request,
            f"Sonderpreis fuer {updated} Preis(e) in {sales_channel.name} gesetzt.",
        )
        if missing > 0:
            self.message_user(
                request,
                (
                    f"{missing} Produkt(e) ohne Preis in {sales_channel.name} uebersprungen. "
                    "Preis bitte im Produkt-Inline anlegen."
                ),
                level=messages.WARNING,
            )

    @admin.action(description="Sonderpreis fuer Sales-Channel aufheben")
    def clear_special_price_for_channel(self, request, queryset):
        form = self._build_action_form(request)
        if not form.is_valid():
            self.message_user(
                request,
                "Bitte gueltige Werte fuer den Sales-Channel eingeben.",
                level=messages.ERROR,
            )
            return

        sales_channel = form.cleaned_data.get("sales_channel")
        if sales_channel is None:
            self.message_user(request, "Bitte einen Sales-Channel auswaehlen.", level=messages.ERROR)
            return

        updated = Price.objects.filter(product__in=queryset, sales_channel=sales_channel).update(
            special_percentage=None,
            special_price=None,
            special_start_date=None,
            special_end_date=None,
        )
        self.message_user(
            request,
            f"Sonderpreis fuer {updated} Preis(e) in {sales_channel.name} aufgehoben.",
        )


@admin.register(Price)
class PriceAdmin(BaseAdmin):
    list_display = (
        "product",
        "sales_channel",
        "price",
        "special_percentage",
        "special_price",
        "special_active",
        "rebate_price",
        "created_at",
    )
    search_fields = ("product__erp_nr", "product__name", "sales_channel__name")
    action_form = PriceActionForm
    actions = ("set_special_price_bulk", "clear_special_price_bulk")
    inlines = (PriceHistoryInline,)
    list_filter = [
        ("sales_channel", RelatedDropdownFilter),
        ("price", RangeNumericFilter),
        ("created_at", RangeDateTimeFilter),
    ]

    @staticmethod
    def _to_aware_datetime(value):
        if value and timezone.is_naive(value):
            return timezone.make_aware(value, timezone.get_current_timezone())
        return value

    def _build_action_form(self, request):
        form = self.action_form(request.POST)
        form.fields["action"].choices = self.get_action_choices(request)
        return form

    @admin.action(description="Sonderpreis setzen (%%)")
    def set_special_price_bulk(self, request, queryset):
        form = self._build_action_form(request)
        if not form.is_valid():
            self.message_user(request, "Bitte gueltige Werte fuer Prozent, Start und Ende eingeben.", level=messages.ERROR)
            return

        special_percentage = form.cleaned_data.get("special_percentage")
        special_start_date = self._to_aware_datetime(form.cleaned_data.get("special_start_date"))
        special_end_date = self._to_aware_datetime(form.cleaned_data.get("special_end_date"))

        if special_percentage is None:
            self.message_user(request, "Bitte fuer diese Aktion einen Prozentwert eingeben.", level=messages.ERROR)
            return

        if special_start_date and special_end_date and special_end_date < special_start_date:
            self.message_user(request, "Sonderpreis bis muss nach Sonderpreis ab liegen.", level=messages.ERROR)
            return

        updated = 0
        for price in queryset:
            price.special_percentage = special_percentage
            price.special_start_date = special_start_date
            price.special_end_date = special_end_date
            price.save()
            updated += 1

        self.message_user(request, f"Sonderpreis fuer {updated} Preis(e) gesetzt.")

    @admin.action(description="Sonderpreis aufheben")
    def clear_special_price_bulk(self, request, queryset):
        updated = 0
        for price in queryset:
            price.special_percentage = None
            price.special_start_date = None
            price.special_end_date = None
            price.save()
            updated += 1

        self.message_user(request, f"Sonderpreis fuer {updated} Preis(e) aufgehoben.")

    @admin.display(boolean=True, description="Sonderpreis aktiv")
    def special_active(self, obj: Price) -> bool:
        return obj.is_special_active


@admin.register(PriceHistory)
class PriceHistoryAdmin(BaseAdmin):
    list_display = (
        "price_entry",
        "change_type",
        "changed_fields",
        "price",
        "special_price",
        "rebate_quantity",
        "rebate_price",
        "created_at",
    )
    search_fields = (
        "price_entry__product__erp_nr",
        "price_entry__product__name",
        "price_entry__sales_channel__name",
        "changed_fields",
    )
    list_filter = [
        "change_type",
        ("created_at", RangeDateTimeFilter),
    ]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(PriceIncrease)
class PriceIncreaseAdmin(BaseAdmin):
    PRICE_INCREASE_TITLE_MONTH_MAP = {
        "jan": 1,
        "januar": 1,
        "feb": 2,
        "februar": 2,
        "mar": 3,
        "maerz": 3,
        "märz": 3,
        "mrz": 3,
        "april": 4,
        "apr": 4,
        "mai": 5,
        "jun": 6,
        "juni": 6,
        "jul": 7,
        "juli": 7,
        "aug": 8,
        "august": 8,
        "sep": 9,
        "sept": 9,
        "september": 9,
        "okt": 10,
        "oktober": 10,
        "nov": 11,
        "november": 11,
        "dez": 12,
        "dezember": 12,
    }
    price_list_pdf_template_name = "admin/products/price_list_pdf.html"
    price_list_cover_pdf_path = Path("templates/admin/products/includes/cover_pricelist.pdf")
    price_list_closing_pdf_path = Path("products/static/products/pdf/price_list_back.pdf")
    price_list_cover_date_page_index = 0
    price_list_cover_date_x = 16 * mm
    price_list_cover_date_y_from_top = 9.4 * mm
    price_list_cover_date_font_size = 5 * mm
    price_list_cover_date_font_name = "Arial"
    price_list_cover_date_font_bold_name = "Arial-Bold"
    price_list_page_number_font_name = "Helvetica"
    price_list_page_number_font_size = 9
    price_list_page_number_y = 8 * mm
    change_form_outer_after_template = "admin/products/includes/price_increase_positions_inline.html"
    list_display = (
        "title",
        "status",
        "sales_channel",
        "general_percentage",
        "position_count",
        "positions_synced_at",
        "applied_at",
        "created_at",
    )
    search_fields = ("title", "sales_channel__name")
    list_filter = [
        "status",
        ("created_at", RangeDateTimeFilter),
        ("applied_at", RangeDateTimeFilter),
    ]
    actions = ("export_price_list_pdf",)
    actions_detail = ("export_price_list_pdf_detail", "apply_price_increase_detail")
    readonly_fields = BaseAdmin.readonly_fields + (
        "status",
        "sales_channel",
        "position_count",
        "positions_synced_at",
        "applied_at",
    )
    fieldsets = (
        (
            "Allgemein",
            {
                "fields": (
                    "title",
                    "status",
                    "sales_channel",
                    "general_percentage",
                )
            },
        ),
        (
            "Ausfuehrung",
            {
                "fields": (
                    "position_count",
                    "positions_synced_at",
                    "applied_at",
                    "created_at",
                    "updated_at",
                )
            },
        ),
    )

    @admin.display(description="Positionen")
    def position_count(self, obj: PriceIncrease):
        annotated_count = getattr(obj, "_position_count", None)
        if annotated_count is not None:
            return annotated_count
        return obj.position_count

    def get_queryset(self, request):
        queryset = super().get_queryset(request)
        return queryset.select_related("sales_channel").annotate(_position_count=Count("items"))

    def get_urls(self):
        positions_view = self.admin_site.admin_view(
            PriceIncreasePositionsPageView.as_view(model_admin=self)
        )
        return [
            path(
                "<path:object_id>/positions/",
                positions_view,
                name="products_priceincrease_positions",
            ),
            path(
                "<path:object_id>/positions/table/",
                self.admin_site.admin_view(self.positions_table_view),
                name="products_priceincrease_positions_table",
            ),
            path(
                "<path:object_id>/positions/<path:item_id>/save/",
                self.admin_site.admin_view(self.save_position_value_view),
                name="products_priceincrease_position_save",
            ),
            path(
                "<path:object_id>/positions/<path:item_id>/chart/",
                self.admin_site.admin_view(self.position_chart_view),
                name="products_priceincrease_position_chart",
            ),
        ] + super().get_urls()

    def _build_action_form(self, request):
        form = self.action_form(request.POST)
        form.fields["action"].choices = self.get_action_choices(request)
        return form

    @staticmethod
    def _positions_page_url(object_id: int | str) -> str:
        return reverse("admin:products_priceincrease_positions", args=(object_id,))

    @staticmethod
    def _positions_table_url(object_id: int | str) -> str:
        return reverse("admin:products_priceincrease_positions_table", args=(object_id,))

    @staticmethod
    def _positions_save_url(object_id: int | str, item_id: int | str) -> str:
        return reverse("admin:products_priceincrease_position_save", args=(object_id, item_id))

    @staticmethod
    def _position_chart_url(object_id: int | str, item_id: int | str) -> str:
        return reverse("admin:products_priceincrease_position_chart", args=(object_id, item_id))

    @staticmethod
    def _format_decimal(value: Decimal | None) -> str:
        if value is None:
            return ""
        return format(value.quantize(Decimal("0.01")), "f").replace(".", ",")

    @staticmethod
    def _format_integer(value) -> str:
        return "" if value in (None, "") else str(value)

    @classmethod
    def _build_price_list_vpe_display(cls, row: dict) -> str:
        primary_value = row["factor"] or row["purchase_unit"]
        primary_display = cls._format_integer(primary_value) or "-"
        min_purchase_display = cls._format_integer(row["min_purchase"]) or "-"
        purchase_unit_display = cls._format_integer(row["purchase_unit"]) or "-"
        unit = (row.get("unit") or "").strip() or "St."
        if row["factor"]:
            price_unit_label = f"Preis pro {row['factor']} {unit}"
        else:
            price_unit_label = f"Preis pro {unit}"
        return format_html(
            "{}<br/><font size=\"7\">Min: {} | Schritt: {}</font><br/><font size=\"7\">{}</font>",
            primary_display,
            min_purchase_display,
            purchase_unit_display,
            price_unit_label,
        )

    @staticmethod
    def _format_pdf_decimal(value: Decimal | None) -> str:
        if value is None:
            return "-"
        return format(value.quantize(Decimal("0.01")), "f").replace(".", ",")

    @classmethod
    def _format_pdf_currency(cls, value: Decimal | None) -> str:
        formatted_value = cls._format_pdf_decimal(value)
        if formatted_value == "-":
            return formatted_value
        return f"{formatted_value} €"

    @staticmethod
    def _pdf_price_source(item: PriceIncreaseItem) -> str:
        has_new_price = item.new_price is not None
        has_new_rebate_price = item.new_rebate_price is not None
        if has_new_price and has_new_rebate_price:
            return "neu"
        if not has_new_price and not has_new_rebate_price:
            return "aktuell"
        return "gemischt"

    @staticmethod
    def _category_in_root(category: Category, root_category: Category) -> bool:
        return (
            category.tree_id == root_category.tree_id
            and category.lft >= root_category.lft
            and category.rght <= root_category.rght
        )

    @staticmethod
    def _category_path_in_subtree(category: Category, subtree_categories: list[Category]) -> list[Category]:
        return [
            candidate
            for candidate in subtree_categories
            if (
                candidate.tree_id == category.tree_id
                and candidate.lft <= category.lft
                and candidate.rght >= category.rght
            )
        ]

    @staticmethod
    def _product_attribute_summary(product: Product) -> str:
        attributes = []
        for product_property in product.product_properties.all():
            value = product_property.value
            group_name = value.group.name if value.group_id else ""
            if group_name:
                attributes.append((group_name, value.name))
            else:
                attributes.append(("", value.name))
        if not attributes:
            description_short = (product.description_short or "").strip()
            if not description_short:
                return "-"
            cleaned_description = PriceIncreaseAdmin._clean_pdf_html(description_short)
            return mark_safe(cleaned_description) if cleaned_description else "-"
        return format_html_join(
            mark_safe("<br/>"),
            "{}",
            (
                (
                    format_html("<b>{}</b>: {}", group_name, value_name)
                    if group_name
                    else format_html("{}", value_name),
                )
                for group_name, value_name in attributes
            ),
        )

    def _build_price_list_items(
        self,
        *,
        price_increase: PriceIncrease,
        root_category: Category,
    ) -> list[dict]:
        subtree_categories = list(
            Category.objects.filter(
                tree_id=root_category.tree_id,
                lft__gte=root_category.lft,
                rght__lte=root_category.rght,
            ).order_by("lft", "id")
        )
        items = list(
            price_increase.items.select_related("product")
            .prefetch_related(
                Prefetch(
                    "product__categories",
                    queryset=Category.objects.order_by("tree_id", "lft", "id"),
                ),
                Prefetch(
                    "product__product_properties",
                    queryset=ProductProperty.objects.select_related("value__group").order_by(
                        "value__group__name",
                        "value__name",
                    ),
                )
            )
            .filter(
                product__is_active=True,
                product__categories__tree_id=root_category.tree_id,
                product__categories__lft__gte=root_category.lft,
                product__categories__rght__lte=root_category.rght,
            )
            .distinct()
        )

        entries: list[dict] = []
        for item in items:
            matching_categories = [
                category
                for category in item.product.categories.all()
                if self._category_in_root(category, root_category)
            ]
            if not matching_categories:
                continue
            lead_category = min(matching_categories, key=lambda category: (-category.level, category.lft, category.id))
            category_path = self._category_path_in_subtree(lead_category, subtree_categories)
            level1_category = category_path[1] if len(category_path) > 1 else root_category
            level2_category = category_path[2] if len(category_path) > 2 else level1_category
            effective_price = item.new_price if item.new_price is not None else item.current_price
            effective_rebate_price = item.new_rebate_price if item.new_rebate_price is not None else item.current_rebate_price
            entries.append(
                {
                    "sort_key": (
                        root_category.tree_id,
                        level1_category.lft,
                        level1_category.sort_order,
                        level1_category.name.lower(),
                        level2_category.tree_id,
                        level2_category.lft,
                        level2_category.sort_order,
                        level2_category.name.lower(),
                        item.product.sort_order,
                        item.product.erp_nr,
                        item.pk,
                    ),
                    "category_name": level2_category.name,
                    "category_level1_id": level1_category.pk,
                    "category_level1_name": level1_category.name,
                    "category_level1_sort_key": (
                        level1_category.tree_id,
                        level1_category.lft,
                        level1_category.sort_order,
                        level1_category.name.lower(),
                        level1_category.pk,
                    ),
                    "category_level2_id": level2_category.pk,
                    "category_level2_name": level2_category.name,
                    "category_level2_sort_key": (
                        level2_category.tree_id,
                        level2_category.lft,
                        level2_category.sort_order,
                        level2_category.name.lower(),
                        level2_category.pk,
                    ),
                    "erp_nr": item.product.erp_nr,
                    "attributes": self._product_attribute_summary(item.product),
                    "product_name": item.product.name or "",
                    "factor": item.product.factor,
                    "min_purchase": item.product.min_purchase,
                    "purchase_unit": item.product.purchase_unit,
                    "unit": item.unit or item.product.unit or "",
                    "price": effective_price,
                    "rebate_quantity": item.current_rebate_quantity,
                    "rebate_price": effective_rebate_price,
                    "price_source": self._pdf_price_source(item),
                }
            )

        return sorted(entries, key=lambda entry: entry["sort_key"])

    @staticmethod
    def _build_price_list_scope_label(root_categories: list[Category]) -> str:
        if not root_categories:
            return "Standard-Verkaufskanal"
        if len(root_categories) == 1:
            return root_categories[0].name
        return "Alle Oberkategorien"

    def _get_price_list_root_categories(self, price_increase: PriceIncrease) -> list[Category]:
        tree_ids = list(
            price_increase.items.filter(
                product__is_active=True,
                product__categories__isnull=False,
            )
            .values_list("product__categories__tree_id", flat=True)
            .distinct()
        )
        if not tree_ids:
            return []
        return list(
            Category.objects.filter(parent__isnull=True, tree_id__in=tree_ids).order_by(
                "tree_id",
                "sort_order",
                "name",
                "id",
            )
        )

    @staticmethod
    def _clean_pdf_html(html: str) -> str:
        fragment = BeautifulSoup(unescape(html or ""), "html.parser")
        for comment in fragment.find_all(string=lambda text: isinstance(text, Comment)):
            comment.extract()

        block_tags = {
            "address",
            "article",
            "blockquote",
            "dd",
            "div",
            "dl",
            "dt",
            "h1",
            "h2",
            "h3",
            "h4",
            "h5",
            "h6",
            "header",
            "footer",
            "li",
            "p",
            "pre",
            "section",
        }

        for tag in fragment.find_all(True):
            if tag.name == "strong":
                tag.name = "b"
            elif tag.name == "em":
                tag.name = "i"
            elif tag.name in block_tags:
                if tag.previous_sibling is not None:
                    tag.insert_before(fragment.new_tag("br"))
                if tag.get_text(strip=True) or tag.find(True):
                    tag.insert_after(fragment.new_tag("br"))
                tag.unwrap()
            elif tag.name not in {"b", "br", "font", "i", "sub", "sup", "u"}:
                tag.unwrap()

        cleaned_html = fragment.decode_contents(formatter="html")
        cleaned_html = re.sub(r"</br\s*>", "", cleaned_html, flags=re.IGNORECASE)
        cleaned_html = re.sub(r"<br\s*/?>", "<br/>", cleaned_html, flags=re.IGNORECASE)
        cleaned_html = re.sub(r"(?:\s*<br/>\s*){3,}", "<br/><br/>", cleaned_html)
        cleaned_html = re.sub(r"^\s*(?:<br/>\s*)+", "", cleaned_html)
        cleaned_html = re.sub(r"(?:\s*<br/>\s*)+\s*$", "", cleaned_html)
        cleaned_html = re.sub(r"[ \t\r\n]+", " ", cleaned_html)
        cleaned_html = re.sub(r"\s*<br/>\s*", "<br/>", cleaned_html)
        return cleaned_html.strip()

    def _paragraph_from_tag(self, tag, style: ParagraphStyle, *, prefix: str = "") -> Paragraph | None:
        html = self._clean_pdf_html(tag.decode_contents(formatter="html"))
        if not html:
            return None
        return Paragraph(f"{prefix}{html}", style)

    def _full_width_heading_from_tag(
        self,
        tag,
        style: ParagraphStyle,
        *,
        page_width: float,
        left_margin: float,
    ) -> FullWidthHeadingBar | None:
        html = self._clean_pdf_html(tag.decode_contents(formatter="html"))
        if not html:
            return None
        return FullWidthHeadingBar(
            html,
            style,
            page_width=page_width,
            left_margin=left_margin,
        )

    def _price_list_pdf_styles(self) -> dict[str, ParagraphStyle]:
        sample_styles = getSampleStyleSheet()
        body = ParagraphStyle(
            name="PriceListPdfBody",
            parent=sample_styles["Normal"],
            fontName="Helvetica",
            fontSize=10,
            leading=14,
            spaceAfter=6,
        )
        return {
            "h1": ParagraphStyle(
                name="PriceListPdfHeading1",
                parent=sample_styles["Heading1"],
                fontName="Helvetica-Bold",
                fontSize=26,
                leading=31,
                spaceAfter=14,
            ),
            "h2": ParagraphStyle(
                name="PriceListPdfHeading2",
                parent=sample_styles["Heading2"],
                fontName="Helvetica-Bold",
                fontSize=16,
                leading=20,
                spaceAfter=8,
            ),
            "h3": ParagraphStyle(
                name="PriceListPdfHeading3",
                parent=sample_styles["Heading3"],
                fontName="Helvetica-Bold",
                fontSize=12,
                leading=16,
                spaceAfter=6,
            ),
            "category_heading": ParagraphStyle(
                name="PriceListPdfCategoryHeading",
                parent=sample_styles["Heading1"],
                fontName="Helvetica-Bold",
                fontSize=15,
                leading=18,
                spaceAfter=0,
            ),
            "body": body,
            "bullet": ParagraphStyle(
                name="PriceListPdfBullet",
                parent=body,
                leftIndent=14,
                firstLineIndent=-8,
            ),
            "table_header": ParagraphStyle(
                name="PriceListPdfTableHeader",
                parent=sample_styles["Normal"],
                fontName="Helvetica-Bold",
                fontSize=9,
                leading=11,
            ),
            "table_header_right": ParagraphStyle(
                name="PriceListPdfTableHeaderRight",
                parent=sample_styles["Normal"],
                fontName="Helvetica-Bold",
                fontSize=9,
                leading=11,
                alignment=TA_RIGHT,
            ),
            "table_cell": ParagraphStyle(
                name="PriceListPdfTableCell",
                parent=sample_styles["Normal"],
                fontName="Helvetica",
                fontSize=8,
                leading=9,
            ),
            "table_cell_right": ParagraphStyle(
                name="PriceListPdfTableCellRight",
                parent=sample_styles["Normal"],
                fontName="Helvetica",
                fontSize=8,
                leading=9,
                alignment=TA_RIGHT,
            ),
        }

    @staticmethod
    def _bytes_to_pdf_reader(pdf_content: bytes) -> PdfReader:
        return PdfReader(BytesIO(pdf_content))

    @staticmethod
    def _resolve_pdf_asset_path(relative_path: Path | str) -> Path:
        return Path(settings.BASE_DIR) / Path(relative_path)

    def _load_optional_pdf_asset(self, relative_path: Path | str) -> bytes | None:
        absolute_path = self._resolve_pdf_asset_path(relative_path)
        if not absolute_path.exists() or not absolute_path.is_file():
            return None
        return absolute_path.read_bytes()

    def _build_pdf_from_sections(
        self,
        *,
        sections,
        title: str,
        empty_message: str | None = None,
    ) -> bytes | None:
        buffer = BytesIO()
        document = SimpleDocTemplate(
            buffer,
            pagesize=A4,
            leftMargin=24,
            rightMargin=24,
            topMargin=24,
            bottomMargin=24,
            title=title,
            author="GC-Bridge",
        )
        styles = self._price_list_pdf_styles()
        story = []

        for section in sections:
            section_elements = self._build_price_list_pdf_elements(
                section,
                styles,
                page_width=A4[0],
                left_margin=document.leftMargin,
            )
            if not section_elements:
                continue
            if story:
                story.append(PageBreak())
            story.extend(section_elements)

        if not story:
            if not empty_message:
                return None
            story.append(Paragraph(empty_message, styles["body"]))

        document.build(story)
        return buffer.getvalue()

    @classmethod
    def _find_font_file(cls, pattern: str) -> str | None:
        if not which("fc-match"):
            return None
        try:
            font_file = subprocess.check_output(
                ["fc-match", "-f", "%{file}\n", pattern],
                text=True,
            ).strip()
        except (OSError, subprocess.CalledProcessError):
            return None
        return font_file or None

    @classmethod
    def _ensure_cover_date_fonts_registered(cls) -> tuple[str, str]:
        regular_font_name = cls.price_list_cover_date_font_name
        bold_font_name = cls.price_list_cover_date_font_bold_name
        try:
            pdfmetrics.getFont(regular_font_name)
            pdfmetrics.getFont(bold_font_name)
            return regular_font_name, bold_font_name
        except KeyError:
            pass

        regular_font_file = cls._find_font_file("Arial")
        bold_font_file = cls._find_font_file("Arial:style=Bold") or cls._find_font_file("Arial Bold")
        if not regular_font_file:
            regular_font_file = cls._find_font_file("Arimo")
        if not bold_font_file:
            bold_font_file = cls._find_font_file("Arimo:style=Bold") or cls._find_font_file("Arimo Bold")

        if regular_font_file:
            pdfmetrics.registerFont(TTFont(regular_font_name, regular_font_file))
            pdfmetrics.registerFont(TTFont(bold_font_name, bold_font_file or regular_font_file))
            return regular_font_name, bold_font_name

        return "Helvetica", "Helvetica-Bold"

    @classmethod
    def _extract_cover_date_from_title(cls, title: str) -> str | None:
        normalized_title = (title or "").strip()
        if not normalized_title:
            return None

        month_year_match = re.search(r"\b(?P<month>\d{1,2})[./-](?P<year>\d{4})\b", normalized_title)
        if month_year_match:
            month = int(month_year_match.group("month"))
            year = int(month_year_match.group("year"))
            if 1 <= month <= 12:
                return f"{month:02d}/{year}"

        year_month_match = re.search(r"\b(?P<year>\d{4})[./-](?P<month>\d{1,2})\b", normalized_title)
        if year_month_match:
            month = int(year_month_match.group("month"))
            year = int(year_month_match.group("year"))
            if 1 <= month <= 12:
                return f"{month:02d}/{year}"

        month_name_match = re.search(
            r"\b(?P<month_name>januar|jan|februar|feb|märz|maerz|mar|mrz|april|apr|mai|juni|jun|juli|jul|august|aug|"
            r"september|sept|sep|oktober|okt|november|nov|dezember|dez)\b[\s/-]*(?P<year>\d{4})\b",
            normalized_title,
            flags=re.IGNORECASE,
        )
        if not month_name_match:
            return None

        month_name = month_name_match.group("month_name").lower()
        month = cls.PRICE_INCREASE_TITLE_MONTH_MAP.get(month_name)
        year = int(month_name_match.group("year"))
        if not month:
            return None
        return f"{month:02d}/{year}"

    @classmethod
    def _build_cover_effective_date_text(cls, price_increase: PriceIncrease) -> tuple[str, str]:
        formatted_month = cls._extract_cover_date_from_title(price_increase.title)
        if not formatted_month:
            reference_datetime = price_increase.applied_at or price_increase.positions_synced_at or price_increase.created_at
            localized_reference = timezone.localtime(reference_datetime) if reference_datetime else timezone.localtime()
            formatted_month = localized_reference.strftime("%m/%Y")
        return "ab ", formatted_month

    def _overlay_date_on_cover_pdf(self, pdf_content: bytes, *, price_increase: PriceIncrease) -> bytes:
        reader = self._bytes_to_pdf_reader(pdf_content)
        writer = PdfWriter()
        prefix_text, date_text = self._build_cover_effective_date_text(price_increase)
        regular_font_name, bold_font_name = self._ensure_cover_date_fonts_registered()

        for page_index, page in enumerate(reader.pages):
            if page_index == self.price_list_cover_date_page_index:
                overlay_buffer = BytesIO()
                page_width = float(page.mediabox.width)
                page_height = float(page.mediabox.height)
                overlay = pdf_canvas.Canvas(overlay_buffer, pagesize=(page_width, page_height))
                font_size = float(self.price_list_cover_date_font_size)
                x_position = float(self.price_list_cover_date_x)
                # The requested coordinates are measured from the top edge of the cover.
                y_position = page_height - float(self.price_list_cover_date_y_from_top) - font_size
                overlay.setFont(regular_font_name, font_size)
                overlay.drawString(x_position, y_position, prefix_text)
                prefix_width = pdfmetrics.stringWidth(prefix_text, regular_font_name, font_size)
                overlay.setFont(bold_font_name, font_size)
                overlay.drawString(x_position + prefix_width, y_position, date_text)
                overlay.save()

                overlay_reader = PdfReader(BytesIO(overlay_buffer.getvalue()))
                page.merge_page(overlay_reader.pages[0])
            writer.add_page(page)

        output = BytesIO()
        writer.write(output)
        return output.getvalue()

    def _overlay_page_numbers_on_pdf(self, pdf_content: bytes) -> bytes:
        reader = self._bytes_to_pdf_reader(pdf_content)
        writer = PdfWriter()
        total_pages = len(reader.pages)

        for page_index, page in enumerate(reader.pages, start=1):
            overlay_buffer = BytesIO()
            page_width = float(page.mediabox.width)
            page_height = float(page.mediabox.height)
            overlay = pdf_canvas.Canvas(overlay_buffer, pagesize=(page_width, page_height))
            overlay.setFont(self.price_list_page_number_font_name, self.price_list_page_number_font_size)
            overlay.drawCentredString(
                page_width / 2,
                float(self.price_list_page_number_y),
                f"{page_index}/{total_pages}",
            )
            overlay.save()

            overlay_reader = PdfReader(BytesIO(overlay_buffer.getvalue()))
            page.merge_page(overlay_reader.pages[0])
            writer.add_page(page)

        output = BytesIO()
        writer.write(output)
        return output.getvalue()

    def _merge_price_list_pdf_parts(
        self,
        *,
        cover_pdf: bytes | None,
        content_pdf: bytes | None,
        closing_pdf: bytes | None,
    ) -> bytes:
        writer = PdfWriter()
        total_pages = 0

        def append_pdf(pdf_content: bytes | None) -> int:
            nonlocal total_pages
            if not pdf_content:
                return 0
            reader = self._bytes_to_pdf_reader(pdf_content)
            for page in reader.pages:
                writer.add_page(page)
                total_pages += 1
            return len(reader.pages)

        append_pdf(cover_pdf)
        append_pdf(content_pdf)

        if closing_pdf:
            closing_reader = self._bytes_to_pdf_reader(closing_pdf)
            closing_page_count = len(closing_reader.pages)
            if (total_pages + closing_page_count) % 2 != 0:
                writer.add_blank_page(width=A4[0], height=A4[1])
                total_pages += 1
            for page in closing_reader.pages:
                writer.add_page(page)
                total_pages += 1
        elif total_pages % 2 != 0:
            writer.add_blank_page(width=A4[0], height=A4[1])

        output = BytesIO()
        writer.write(output)
        return self._overlay_page_numbers_on_pdf(output.getvalue())

    @staticmethod
    def _build_price_list_category_sections(rows: list[dict], root_category: Category | None) -> list[dict]:
        if not rows:
            scope_label = root_category.name if root_category else "Standard-Verkaufskanal"
            return [
                {
                    "category_name": scope_label,
                    "sort_key": (0, 0, scope_label.lower(), 0),
                    "groups": [
                        {
                            "category_name": scope_label,
                            "sort_key": (
                                0,
                                0,
                                scope_label.lower(),
                                0,
                            ),
                            "rows": [],
                        }
                    ],
                }
            ]

        sections_by_key: dict[tuple, dict] = {}
        for row in rows:
            section_key = tuple(row["category_level1_sort_key"])
            group_key = tuple(row["category_level2_sort_key"])
            section = sections_by_key.setdefault(
                section_key,
                {
                    "category_name": row["category_level1_name"],
                    "sort_key": section_key,
                    "groups_by_key": {},
                },
            )
            group = section["groups_by_key"].setdefault(
                group_key,
                {
                    "category_name": row["category_level2_name"],
                    "sort_key": group_key,
                    "rows": [],
                },
            )
            group["rows"].append(row)

        sections = sorted(sections_by_key.values(), key=lambda section: section["sort_key"])
        for section in sections:
            groups = sorted(section["groups_by_key"].values(), key=lambda group: group["sort_key"])
            for group in groups:
                group["rows"] = sorted(group["rows"], key=lambda row: row["sort_key"])
            section["groups"] = groups
            del section["groups_by_key"]
        return sections

    def _build_price_list_template_context(
        self,
        *,
        price_increase: PriceIncrease,
        root_category: Category | None,
        rows: list[dict],
        scope_label: str | None = None,
    ) -> dict:
        template_rows = []
        for row in rows:
            template_row = dict(row)
            rebate_quantity = row["rebate_quantity"]
            rebate_price = row["rebate_price"]
            has_rebate_data = not (
                rebate_quantity in (None, "", 0)
                and (rebate_price is None or rebate_price == Decimal("0.00"))
            )
            template_row["price_display"] = self._format_pdf_currency(row["price"])
            template_row["vpe_display"] = self._build_price_list_vpe_display(row)
            template_row["rebate_quantity_display"] = self._format_integer(rebate_quantity) if has_rebate_data else "-"
            template_row["rebate_price_display"] = self._format_pdf_currency(rebate_price) if has_rebate_data else "-"
            template_rows.append(template_row)

        created_at = timezone.localtime()
        sales_channel = price_increase.sales_channel.name if price_increase.sales_channel_id else "-"
        scope_label = scope_label or (root_category.name if root_category else "Standard-Verkaufskanal")
        return {
            "created_at": created_at,
            "created_at_display": created_at.strftime("%d.%m.%Y %H:%M"),
            "general_percentage_display": self._format_pdf_decimal(price_increase.general_percentage),
            "price_increase": price_increase,
            "category_sections": self._build_price_list_category_sections(template_rows, root_category),
            "root_category": root_category,
            "scope_label": scope_label,
            "row_count": len(template_rows),
            "rows": template_rows,
            "sales_channel": sales_channel,
        }

    def _parse_price_list_pdf_table(
        self,
        table_node,
        styles: dict[str, ParagraphStyle],
    ) -> tuple[list[list], list[float | None], list[str]]:
        table_rows = []
        column_widths: list[float | None] = []
        column_alignments: list[str] = []

        for row_index, tr in enumerate(table_node.select("tr")):
            cells = tr.find_all(["td", "th"], recursive=False)
            if not cells:
                continue

            if not column_widths:
                for cell in cells:
                    width = cell.get("data-width")
                    try:
                        column_widths.append(float(width) if width else None)
                    except (TypeError, ValueError):
                        column_widths.append(None)
                    column_alignments.append((cell.get("data-align") or "left").lower())

            rendered_cells = []
            for column_index, cell in enumerate(cells):
                while column_index >= len(column_alignments):
                    column_alignments.append("left")
                align = (cell.get("data-align") or column_alignments[column_index]).lower()
                is_header = cell.name == "th" or row_index == 0
                style_key = "table_header" if is_header else "table_cell"
                if align == "right":
                    style_key = f"{style_key}_right"
                rendered_cells.append(self._paragraph_from_tag(cell, styles[style_key]) or "")
            table_rows.append(rendered_cells)
        return table_rows, column_widths, column_alignments

    @staticmethod
    def _create_price_list_pdf_table(
        table_rows: list[list],
        column_widths: list[float | None],
        column_alignments: list[str],
    ) -> Table | Spacer:
        if not table_rows:
            return Spacer(1, 1)

        style_commands = [
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f1f3f5")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.black),
            ("LINEBELOW", (0, 0), (-1, 0), 0.8, colors.HexColor("#adb5bd")),
            ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#dee2e6")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 5),
            ("RIGHTPADDING", (0, 0), (-1, -1), 5),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]
        for column_index, align in enumerate(column_alignments):
            if align in {"center", "left", "right"}:
                style_commands.append(("ALIGN", (column_index, 0), (column_index, -1), align.upper()))

        table = Table(
            table_rows,
            repeatRows=1,
            colWidths=column_widths if any(width is not None for width in column_widths) else None,
        )
        table.setStyle(TableStyle(style_commands))
        return table

    def _build_price_list_pdf_table(self, table_node, styles: dict[str, ParagraphStyle]) -> Table | Spacer:
        table_rows, column_widths, column_alignments = self._parse_price_list_pdf_table(table_node, styles)
        return self._create_price_list_pdf_table(table_rows, column_widths, column_alignments)

    def _build_price_list_heading_table_block(
        self,
        *,
        heading: Paragraph | None,
        table_node,
        styles: dict[str, ParagraphStyle],
        leading_elements: list | None = None,
        first_body_rows: int = 1,
    ) -> list:
        block_elements = list(leading_elements or [])
        if heading is not None:
            block_elements.append(heading)
        first_table, remaining_table = self._build_price_list_pdf_table_parts(
            table_node,
            styles,
            first_body_rows=first_body_rows,
        )
        block_elements.append(first_table)

        elements = [KeepTogether(block_elements)]
        if remaining_table is not None:
            elements.append(remaining_table)
        return elements

    def _build_price_list_pdf_table_parts(
        self,
        table_node,
        styles: dict[str, ParagraphStyle],
        *,
        first_body_rows: int = 1,
    ) -> tuple[Table | Spacer, Table | Spacer | None]:
        table_rows, column_widths, column_alignments = self._parse_price_list_pdf_table(table_node, styles)
        if len(table_rows) <= 1:
            table = self._create_price_list_pdf_table(table_rows, column_widths, column_alignments)
            return table, None

        split_index = min(len(table_rows), 1 + max(1, first_body_rows))
        first_table = self._create_price_list_pdf_table(
            table_rows[:split_index],
            column_widths,
            column_alignments,
        )
        remaining_rows = table_rows[split_index:]
        if not remaining_rows:
            return first_table, None
        remaining_table = self._create_price_list_pdf_table(
            [table_rows[0], *remaining_rows],
            column_widths,
            column_alignments,
        )
        return first_table, remaining_table

    def _build_price_list_pdf_elements(
        self,
        node,
        styles: dict[str, ParagraphStyle],
        *,
        page_width: float,
        left_margin: float,
    ) -> list:
        elements = []
        children = [child for child in node.children if getattr(child, "name", None)]
        child_index = 0
        while child_index < len(children):
            child = children[child_index]
            if not getattr(child, "name", None):
                child_index += 1
                continue

            name = child.name.lower()
            if name in {"script", "style"}:
                child_index += 1
                continue
            next_child = children[child_index + 1] if child_index + 1 < len(children) else None
            next_next_child = children[child_index + 2] if child_index + 2 < len(children) else None
            if name in {"h1", "h2", "h3", "p"}:
                if child.get("data-pdf-full-width-bar"):
                    if (
                        next_child is not None
                        and next_next_child is not None
                        and next_child.name.lower() == "h2"
                        and next_next_child.name.lower() == "table"
                    ):
                        full_width_heading = self._full_width_heading_from_tag(
                            child,
                            styles["category_heading"],
                            page_width=page_width,
                            left_margin=left_margin,
                        )
                        subsection_heading = self._paragraph_from_tag(next_child, styles["h2"])
                        leading_elements = []
                        if full_width_heading is not None:
                            leading_elements.extend([full_width_heading, Spacer(1, 10)])
                        elements.extend(
                            self._build_price_list_heading_table_block(
                                heading=subsection_heading,
                                table_node=next_next_child,
                                styles=styles,
                                leading_elements=leading_elements,
                            )
                        )
                        child_index += 3
                        continue
                    if next_child is not None and next_child.name.lower() in {"h2", "h3", "table"}:
                        elements.append(CondPageBreak(130))
                    paragraph = self._full_width_heading_from_tag(
                        child,
                        styles["category_heading"],
                        page_width=page_width,
                        left_margin=left_margin,
                    )
                    if paragraph is not None:
                        elements.append(paragraph)
                        elements.append(Spacer(1, 10))
                    child_index += 1
                    continue
                paragraph = self._paragraph_from_tag(child, styles.get(name, styles["body"]))
                if paragraph is not None:
                    if name == "h2" and next_child is not None and next_child.name.lower() == "table":
                        elements.extend(
                            self._build_price_list_heading_table_block(
                                heading=paragraph,
                                table_node=next_child,
                                styles=styles,
                            )
                        )
                        child_index += 2
                        continue
                    elements.append(paragraph)
                child_index += 1
                continue
            if name in {"div", "article", "header", "footer", "section"}:
                elements.extend(
                    self._build_price_list_pdf_elements(
                        child,
                        styles,
                        page_width=page_width,
                        left_margin=left_margin,
                    )
                )
                child_index += 1
                continue
            if name in {"ul", "ol"}:
                for index, item in enumerate(child.find_all("li", recursive=False), start=1):
                    prefix = "&bull; " if name == "ul" else f"{index}. "
                    paragraph = self._paragraph_from_tag(item, styles["bullet"], prefix=prefix)
                    if paragraph is not None:
                        elements.append(paragraph)
                child_index += 1
                continue
            if name == "table":
                elements.append(self._build_price_list_pdf_table(child, styles))
                child_index += 1
                continue

            paragraph = self._paragraph_from_tag(child, styles["body"])
            if paragraph is not None:
                elements.append(paragraph)
            child_index += 1
        return elements

    def _build_price_list_pdf(
        self,
        *,
        price_increase: PriceIncrease,
        root_category: Category | None,
        rows: list[dict],
        scope_label: str | None = None,
    ) -> bytes:
        context = self._build_price_list_template_context(
            price_increase=price_increase,
            root_category=root_category,
            rows=rows,
            scope_label=scope_label,
        )
        html = render_to_string(self.price_list_pdf_template_name, context)
        soup = BeautifulSoup(html, "html.parser")

        cover_pdf = self._load_optional_pdf_asset(self.price_list_cover_pdf_path)
        if cover_pdf:
            cover_pdf = self._overlay_date_on_cover_pdf(cover_pdf, price_increase=price_increase)
        else:
            cover_pdf = self._build_pdf_from_sections(
                sections=soup.select('[data-pdf-section="cover"]'),
                title=f"{price_increase.title} Cover",
            )

        content_pdf = self._build_pdf_from_sections(
            sections=soup.select('[data-pdf-section="category"]'),
            title=price_increase.title,
            empty_message="Keine Inhalte fuer die Preisliste vorhanden.",
        )

        closing_pdf = self._load_optional_pdf_asset(self.price_list_closing_pdf_path)
        if not closing_pdf:
            closing_pdf = self._build_pdf_from_sections(
                sections=soup.select('[data-pdf-section="closing"]'),
                title=f"{price_increase.title} Rueckseite",
            )

        return self._merge_price_list_pdf_parts(
            cover_pdf=cover_pdf,
            content_pdf=content_pdf,
            closing_pdf=closing_pdf,
        )

    def _get_price_increase_or_404(self, object_id: int | str) -> PriceIncrease:
        price_increase = PriceIncrease.objects.select_related("sales_channel").filter(pk=object_id).first()
        if not price_increase:
            raise Http404("Preiserhoehung nicht gefunden.")
        return price_increase

    def _get_positions_queryset(self, price_increase: PriceIncrease, search_term: str = ""):
        queryset = (
            price_increase.items.select_related("price_increase", "product", "source_price", "last_changed_by")
            .filter(product__is_active=True)
            .order_by("product__erp_nr", "id")
        )
        search_term = (search_term or "").strip()
        if search_term:
            if len(search_term) < 3:
                return queryset.none()
            queryset = queryset.filter(
                Q(product__erp_nr__icontains=search_term) | Q(product__name__icontains=search_term)
            )
        return queryset

    def _prepare_position_item(self, price_increase: PriceIncrease, item: PriceIncreaseItem) -> PriceIncreaseItem:
        item.display_current_price = self._format_decimal(item.current_price)
        item.display_current_rebate_quantity = self._format_integer(item.normalized_current_rebate_quantity)
        item.display_current_rebate_price = self._format_decimal(item.normalized_current_rebate_price)
        item.display_unit = item.unit or ""
        item.display_new_price = self._format_decimal(item.effective_new_price)
        item.display_new_rebate_price = self._format_decimal(item.effective_new_rebate_price)
        item.placeholder_new_price = self._format_decimal(item.suggested_price)
        item.placeholder_new_rebate_price = self._format_decimal(item.suggested_rebate_price)
        logged_status_message = getattr(item, "logged_status_message", "")
        item.row_status_message = getattr(item, "row_status_message", item.last_status_message or logged_status_message)
        item.row_status_detail = self._build_row_status_detail(item)
        item.row_status_meta = self._build_row_status_meta(item)
        item.validation_issues = item.get_pricing_check_issues()
        item.validation_errors = [
            issue for issue in item.validation_issues if issue["severity"] == PriceIncreaseItem.CHECK_SEVERITY_ERROR
        ]
        item.validation_warnings = [
            issue for issue in item.validation_issues if issue["severity"] == PriceIncreaseItem.CHECK_SEVERITY_WARNING
        ]
        item.save_url = self._positions_save_url(price_increase.pk, item.pk)
        return item

    @staticmethod
    def _format_validation_error(exc: ValidationError) -> str:
        if hasattr(exc, "message_dict"):
            messages_list = []
            for field_errors in exc.message_dict.values():
                messages_list.extend(str(error) for error in field_errors)
            if messages_list:
                return " ".join(messages_list)
        return " ".join(str(message) for message in exc.messages) or "Ungueltige Eingabe."

    @staticmethod
    def _build_mappei_price_data(
        item: PriceIncreaseItem,
        mapping: MappeiProductMapping,
        snapshot: MappeiPriceSnapshot,
    ) -> dict | None:
        """Return Mappei comparison price data normalized to our price unit."""
        mappei_product = mapping.mappei_product
        product = item.product
        internal_factor = Decimal(str(product.factor or 1))
        if internal_factor <= 0:
            internal_factor = Decimal("1")
        comparison_unit = product.factor or product.purchase_unit or item.current_rebate_quantity or 1
        comparison_qty = Decimal(str(comparison_unit))
        if comparison_qty <= 0:
            comparison_qty = internal_factor
        internal_basis_price = (item.current_price / internal_factor) * comparison_qty
        mappei_vpe_qty = Decimal(str(mappei_product.vpe_menge or 1))
        if mappei_vpe_qty <= 0:
            mappei_vpe_qty = Decimal("1")

        has_staffel = (
            snapshot.staffelpreis_min is not None
            and snapshot.staffelpreis_max is not None
            and snapshot.staffelpreismenge_max is not None
        )
        tier_qty = snapshot.staffelpreismenge_max if has_staffel else None
        tier_price = None
        if has_staffel:
            # The snapshot stores min/max prices, not quantity-price pairs. The base row is
            # stored separately in ``preis``, so the other endpoint belongs to the higher tier.
            tier_price = snapshot.staffelpreis_min
            if snapshot.preis == snapshot.staffelpreis_min:
                tier_price = snapshot.staffelpreis_max

        if tier_qty and tier_price is not None and comparison_qty >= Decimal(str(tier_qty)):
            applicable_price = tier_price
            applicable_qty = tier_qty
            tier_applies = True
        else:
            applicable_price = snapshot.preis
            applicable_qty = mappei_product.vpe_menge or snapshot.staffelpreismenge_min or 1
            tier_applies = False

        price_per_piece = applicable_price / mappei_vpe_qty
        normalized_total = applicable_price * (comparison_qty / mappei_vpe_qty)

        return {
            "artikelnr": mappei_product.artikelnr,
            "url": mappei_product.url,
            "scraped_at": snapshot.scraped_at,
            "base_price": snapshot.preis,
            "base_qty": mappei_product.vpe_menge or snapshot.staffelpreismenge_min or 1,
            "staffel_price_min": snapshot.staffelpreis_min,
            "staffel_price_max": snapshot.staffelpreis_max,
            "staffel_menge_min": snapshot.staffelpreismenge_min,
            "staffel_menge_max": snapshot.staffelpreismenge_max,
            "tier_price": tier_price,
            "tier_qty": tier_qty,
            "vpe_menge": mappei_product.vpe_menge,
            "vpe_einheit": mappei_product.vpe_einheit,
            "partial_success": snapshot.partial_success,
            "has_staffel": has_staffel,
            "tier_applies": tier_applies,
            "applicable_price": applicable_price,
            "applicable_qty": applicable_qty,
            "price_per_piece": price_per_piece,
            "normalized_total": normalized_total,
            "internal_basis_price": internal_basis_price,
            "internal_factor": internal_factor,
            "purchase_unit": product.purchase_unit or item.current_rebate_quantity or 1,
            "comparison_unit": comparison_unit,
            "mappei_vpe_qty": mappei_vpe_qty,
        }

    @classmethod
    def _attach_mappei_price_data(cls, items: list[PriceIncreaseItem]) -> None:
        for item in items:
            item.mappei_data = None

        product_ids = [item.product_id for item in items if item.product_id]
        if not product_ids:
            return

        mappings = list(
            MappeiProductMapping.objects.filter(product_id__in=product_ids)
            .select_related("mappei_product")
            .order_by("product_id", "mappei_product__artikelnr", "id")
        )
        mappings_by_product_id: dict[int, list[MappeiProductMapping]] = {}
        for mapping in mappings:
            mappings_by_product_id.setdefault(mapping.product_id, []).append(mapping)

        mappei_product_ids = [mapping.mappei_product_id for mapping in mappings]
        if not mappei_product_ids:
            return

        latest_snapshots = (
            MappeiPriceSnapshot.objects.filter(product_id__in=mappei_product_ids)
            .annotate(
                row_number=Window(
                    expression=RowNumber(),
                    partition_by=[F("product_id")],
                    order_by=[F("scraped_at").desc(), F("id").desc()],
                )
            )
            .filter(row_number=1)
        )
        snapshot_by_product_id = {snapshot.product_id: snapshot for snapshot in latest_snapshots}

        for item in items:
            item_mappings = mappings_by_product_id.get(item.product_id, [])
            if not item_mappings:
                continue
            mappei_data_options = [
                cls._build_mappei_price_data(item, mapping, snapshot)
                for mapping in item_mappings
                if (snapshot := snapshot_by_product_id.get(mapping.mappei_product_id))
            ]
            mappei_data_options = [mappei_data for mappei_data in mappei_data_options if mappei_data]
            if mappei_data_options:
                item.mappei_data = min(
                    mappei_data_options,
                    key=lambda mappei_data: (
                        mappei_data["normalized_total"],
                        mappei_data["artikelnr"],
                    ),
                )

    @staticmethod
    def _get_row_status_user_and_time(item: PriceIncreaseItem):
        if item.last_changed_by_id:
            user_label = item.last_changed_by.get_username() or str(item.last_changed_by)
        elif getattr(item, "logged_status_user", None):
            user_label = item.logged_status_user.get_username() or str(item.logged_status_user)
        else:
            user_label = "unbekannter Nutzer"
        changed_at_value = item.last_changed_at or getattr(item, "logged_status_at", None)
        return user_label, changed_at_value

    @classmethod
    def _build_row_status_meta(cls, item: PriceIncreaseItem) -> str:
        message = item.last_status_message or getattr(item, "logged_status_message", "")
        if not message:
            return ""
        user_label, changed_at_value = cls._get_row_status_user_and_time(item)
        if changed_at_value:
            changed_at = timezone.localtime(changed_at_value).strftime("%d.%m.%Y %H:%M")
            return f"von {user_label} am {changed_at}"
        return f"von {user_label}"

    @classmethod
    def _build_row_status_detail(cls, item: PriceIncreaseItem) -> str:
        message = item.last_status_message or getattr(item, "logged_status_message", "")
        if not message:
            return ""
        user_label, changed_at_value = cls._get_row_status_user_and_time(item)
        if changed_at_value:
            changed_at = timezone.localtime(changed_at_value).strftime("%d.%m.%Y %H:%M")
            return f"{message} von {user_label} am {changed_at}"
        return f"{message} von {user_label}"

    @staticmethod
    def _price_timeline_years() -> tuple[int, int]:
        new_price_year = timezone.localdate().year
        current_price_year = new_price_year - 1
        return current_price_year, new_price_year

    @classmethod
    def _price_summary_date_range(cls):
        current_price_year, _new_price_year = cls._price_timeline_years()
        current_timezone = timezone.get_current_timezone()
        start_at = timezone.make_aware(datetime(current_price_year - 3, 1, 1), current_timezone)
        end_at = timezone.make_aware(datetime(current_price_year, 1, 1), current_timezone)
        return start_at, end_at

    @staticmethod
    def _get_latest_history_price_by_year(history_entries: list[PriceHistory]) -> dict[int, Decimal]:
        yearly_prices: dict[int, Decimal] = {}
        for entry in sorted(history_entries, key=lambda entry: (entry.created_at, entry.pk or 0)):
            yearly_prices[timezone.localtime(entry.created_at).year] = entry.price
        return yearly_prices

    def _build_yearly_price_summary(self, item: PriceIncreaseItem, history_entries: list[PriceHistory]) -> list[dict[str, str]]:
        current_price_year, _new_price_year = self._price_timeline_years()
        yearly_prices = self._get_latest_history_price_by_year(history_entries)
        display_years = range(current_price_year - 3, current_price_year)

        summary = []
        for year in display_years:
            price = yearly_prices.get(year)
            summary.append(
                {
                    "year": str(year),
                    "price": self._format_decimal(price) if price is not None else "-",
                    "has_price": price is not None,
                }
            )
        return summary

    def _build_price_history_chart(
        self,
        item: PriceIncreaseItem,
        history_entries: list[PriceHistory],
        mappei_yearly_prices: dict[int, Decimal] | None = None,
    ) -> dict:
        current_price_year, new_price_year = self._price_timeline_years()
        yearly_prices = {
            year: price
            for year, price in self._get_latest_history_price_by_year(history_entries).items()
            if year < current_price_year
        }
        yearly_prices[current_price_year] = item.current_price
        yearly_prices[new_price_year] = item.effective_new_price
        sorted_years = sorted(yearly_prices)
        prices = [float(yearly_prices[year]) for year in sorted_years]
        formatted_points = [
            {
                "year": str(year),
                "price": self._format_decimal(yearly_prices[year]),
                "is_current_price": year == current_price_year,
                "is_new_price": year == new_price_year,
            }
            for year in sorted_years
        ]

        datasets = [
            {
                "label": "Preis",
                "data": prices,
                "borderColor": "#ff9933",
                "backgroundColor": "rgba(255, 153, 51, 0.1)",
                "pointRadius": 4,
                "pointHoverRadius": 6,
                "tension": 0.25,
                "displayYAxis": True,
                "suffixYAxis": "EUR",
                "maxTicksXLimit": 12,
            }
        ]
        if mappei_yearly_prices:
            mappei_prices = [
                float(mappei_yearly_prices[year]) if year in mappei_yearly_prices else None
                for year in sorted_years
            ]
            if any(p is not None for p in mappei_prices):
                datasets.append(
                    {
                        "label": "Mappei (höchster Preis)",
                        "data": mappei_prices,
                        "borderColor": "#c20e1a",
                        "backgroundColor": "rgba(194, 14, 26, 0.1)",
                        "pointRadius": 4,
                        "pointHoverRadius": 6,
                        "tension": 0.25,
                        "spanGaps": True,
                    }
                )

        return {
            "data": json.dumps(
                {
                    "labels": [str(year) for year in sorted_years],
                    "datasets": datasets,
                }
            ),
            "height": 240,
            "points": formatted_points,
            "current_price_year": str(current_price_year),
            "new_price_year": str(new_price_year),
        }

    def _build_price_history_chart_meta(self, price_increase: PriceIncrease, item: PriceIncreaseItem) -> dict:
        current_price_year, new_price_year = self._price_timeline_years()
        return {
            "chart_url": self._position_chart_url(price_increase.pk, item.pk),
            "height": 240,
            "current_price_year": str(current_price_year),
            "new_price_year": str(new_price_year),
        }

    def _build_yearly_price_history(
        self,
        item: PriceIncreaseItem,
        history_entries: list[PriceHistory],
    ) -> tuple[list[dict[str, str]], dict]:
        return (
            self._build_yearly_price_summary(item, history_entries),
            self._build_price_history_chart(item, history_entries),
        )

    def _get_save_field_label(self, field_name: str) -> str:
        if field_name == "new_price":
            return "Neuer Preis"
        if field_name == "new_rebate_price":
            return "neuer Rab.Preis"
        return field_name

    @staticmethod
    def _attach_logged_position_statuses(items: list[PriceIncreaseItem]) -> None:
        item_ids = [str(item.pk) for item in items if item.pk and not item.last_status_message]
        if not item_ids:
            return
        content_type_id = ContentType.objects.get_for_model(PriceIncreaseItem).id
        latest_log_entries = (
            LogEntry.objects.filter(
                content_type_id=content_type_id,
                object_id__in=item_ids,
                change_message__contains=" gespeichert: ",
            )
            .select_related("user")
            .order_by("object_id", "-action_time", "-id")
        )
        latest_entry_by_object_id = {}
        for log_entry in latest_log_entries:
            latest_entry_by_object_id.setdefault(log_entry.object_id, log_entry)

        for item in items:
            log_entry = latest_entry_by_object_id.get(str(item.pk))
            if not log_entry:
                continue
            item.logged_status_message = log_entry.change_message
            item.logged_status_user = log_entry.user
            item.logged_status_at = log_entry.action_time

    def _build_positions_context(self, request, price_increase: PriceIncrease, search_term: str = "") -> dict:
        search_term = (search_term or "").strip()
        items = list(self._get_positions_queryset(price_increase, search_term))
        self._attach_logged_position_statuses(items)
        self._attach_mappei_price_data(items)
        source_price_ids = [item.source_price_id for item in items if item.source_price_id]
        history_start_at, history_end_at = self._price_summary_date_range()
        history_entries = (
            PriceHistory.objects.filter(price_entry_id__in=source_price_ids)
            .filter(created_at__gte=history_start_at, created_at__lt=history_end_at)
            .only("price_entry_id", "created_at", "price")
            .order_by("price_entry_id", "created_at", "id")
        )
        history_by_price_id: dict[int, list[PriceHistory]] = {}
        for history_entry in history_entries:
            history_by_price_id.setdefault(history_entry.price_entry_id, []).append(history_entry)

        prepared_items = []
        for item in items:
            item = self._prepare_position_item(price_increase, item)
            item.yearly_prices = self._build_yearly_price_summary(
                item,
                history_by_price_id.get(item.source_price_id, []),
            )
            item.price_history_chart = self._build_price_history_chart_meta(price_increase, item)
            prepared_items.append(item)

        return {
            **self.admin_site.each_context(request),
            "title": f"Preiserhoehungs-Positionen: {price_increase.title}",
            "subtitle": "Asynchrone Listenansicht",
            "price_increase": price_increase,
            "items": prepared_items,
            "search_term": search_term,
            "search_min_length": 3,
            "price_increase_change_url": reverse("admin:products_priceincrease_change", args=(price_increase.pk,)),
            "price_increase_changelist_url": reverse("admin:products_priceincrease_changelist"),
            "positions_table_url": self._positions_table_url(price_increase.pk),
            "is_applied": price_increase.status == PriceIncrease.Status.APPLIED,
            "shopware_shop_url": getattr(settings, "SHOPWARE6_SHOP_URL", ""),
        }

    def render_change_form(self, request, context, add=False, change=False, form_url="", obj=None):
        context = {**context}
        if obj and obj.pk:
            context.update(
                {
                    "price_increase_positions_inline_context": {
                        **self.admin_site.each_context(request),
                        "price_increase": obj,
                        "items": [],
                        "search_term": "",
                        "search_min_length": 3,
                        "positions_table_url": self._positions_table_url(obj.pk),
                        "is_applied": obj.status == PriceIncrease.Status.APPLIED,
                        "defer_initial_load": True,
                    },
                    "price_increase_positions_inline_enabled": True,
                }
            )
        else:
            context.update(
                {
                    "price_increase_positions_inline_context": {},
                    "price_increase_positions_inline_enabled": False,
                }
            )
        return super().render_change_form(
            request,
            context,
            add=add,
            change=change,
            form_url=form_url,
            obj=obj,
        )

    def positions_table_view(self, request, object_id: str):
        price_increase = self._get_price_increase_or_404(object_id)
        context = self._build_positions_context(
            request=request,
            price_increase=price_increase,
            search_term=request.GET.get("q", ""),
        )
        return TemplateResponse(
            request,
            "admin/products/includes/price_increase_positions_table.html",
            context,
        )

    def position_chart_view(self, request, object_id: str, item_id: str):
        if request.method != "GET":
            return HttpResponseNotAllowed(["GET"])

        price_increase = self._get_price_increase_or_404(object_id)
        item = (
            price_increase.items.select_related("price_increase", "product", "source_price")
            .filter(pk=item_id, product__is_active=True)
            .first()
        )
        if not item:
            return JsonResponse({"error": "Position nicht gefunden."}, status=404)

        history_entries = list(
            PriceHistory.objects.filter(price_entry_id=item.source_price_id)
            .only("price_entry_id", "created_at", "price")
            .order_by("created_at", "id")
        )
        mappei_product_ids = list(
            MappeiProductMapping.objects.filter(product_id=item.product_id)
            .values_list("mappei_product_id", flat=True)
        )
        mappei_yearly_prices: dict[int, Decimal] = {}
        if mappei_product_ids:
            for snapshot in (
                MappeiPriceSnapshot.objects.filter(
                    product_id__in=mappei_product_ids,
                    preis__isnull=False,
                )
                .only("product_id", "scraped_at", "preis")
                .order_by("scraped_at")
            ):
                year = timezone.localtime(snapshot.scraped_at).year
                if year not in mappei_yearly_prices or snapshot.preis > mappei_yearly_prices[year]:
                    mappei_yearly_prices[year] = snapshot.preis
        chart = self._build_price_history_chart(item, history_entries, mappei_yearly_prices or None)
        return JsonResponse(
            {
                "data": json.loads(chart["data"]),
                "height": chart["height"],
                "current_price_year": chart["current_price_year"],
                "new_price_year": chart["new_price_year"],
            }
        )

    def save_position_value_view(self, request, object_id: str, item_id: str):
        if request.method != "POST":
            return HttpResponseNotAllowed(["POST"])
        if not self.has_change_permission(request):
            return JsonResponse({"error": "Keine Berechtigung zum Speichern."}, status=403)

        price_increase = self._get_price_increase_or_404(object_id)
        if price_increase.status == PriceIncrease.Status.APPLIED:
            return JsonResponse({"error": "Diese Preiserhoehung wurde bereits uebernommen."}, status=400)

        item = (
            price_increase.items.select_related("price_increase", "product", "source_price", "last_changed_by")
            .filter(pk=item_id, product__is_active=True)
            .first()
        )
        if not item:
            return JsonResponse({"error": "Position nicht gefunden."}, status=404)

        field_name = str(request.POST.get("field") or "").strip()
        if field_name not in {"new_price", "new_rebate_price"}:
            return JsonResponse({"error": "Ungueltiges Feld."}, status=400)

        value_form = PriceIncreaseItemValueForm(request.POST)
        if not value_form.is_valid():
            return JsonResponse({"error": "Ungueltiger Preiswert."}, status=400)

        previous_value = getattr(item, field_name)
        setattr(item, field_name, value_form.cleaned_data["value"])
        try:
            item.full_clean()
        except ValidationError as exc:
            return JsonResponse({"error": self._format_validation_error(exc)}, status=400)
        item.save()
        item.refresh_from_db()
        old_value = self._format_decimal(previous_value)
        new_value = self._format_decimal(getattr(item, field_name))
        field_label = self._get_save_field_label(field_name)
        status_message = f"{field_label} gespeichert: {old_value or 'leer'} -> {new_value or 'leer'}"
        item.last_status_message = status_message
        item.last_changed_by = request.user
        item.last_changed_at = timezone.now()
        item.save(update_fields=["last_status_message", "last_changed_by", "last_changed_at", "updated_at"])
        item.row_status_message = status_message
        self._attach_mappei_price_data([item])
        self._prepare_position_item(price_increase, item)
        history_start_at, history_end_at = self._price_summary_date_range()
        item.yearly_prices = self._build_yearly_price_summary(
            item,
            list(
                PriceHistory.objects.filter(price_entry_id=item.source_price_id)
                .filter(created_at__gte=history_start_at, created_at__lt=history_end_at)
                .only("price_entry_id", "created_at", "price")
                .order_by("created_at", "id")
            ),
        )
        item.price_history_chart = self._build_price_history_chart_meta(price_increase, item)

        log_admin_change(
            user_id=request.user.id,
            content_type_id=ContentType.objects.get_for_model(PriceIncreaseItem).id,
            object_id=str(item.pk),
            object_repr=str(item),
            message=item.row_status_message,
        )

        row_html = render_to_string(
            "admin/products/includes/price_increase_position_row.html",
            {
                "item": item,
                "price_increase": price_increase,
                "is_applied": False,
            },
            request=request,
        )
        return JsonResponse(
            {
                "message": item.row_status_message,
                "row_html": row_html,
            }
        )

    def save_model(self, request, obj, form, change):
        is_create = obj.pk is None
        super().save_model(request, obj, form, change)
        if is_create:
            try:
                count = PriceIncreaseService().sync_items(obj)
            except ValueError as exc:
                self.message_user(request, str(exc), level=messages.ERROR)
            else:
                self.message_user(request, f"{count} Preisposition(en) fuer die Preiserhoehung eingelesen.")

    def _build_default_price_list_response(self, price_increase: PriceIncrease) -> HttpResponse:
        if price_increase.status != PriceIncrease.Status.APPLIED:
            PriceIncreaseService().sync_items(price_increase)

        root_categories = self._get_price_list_root_categories(price_increase)
        rows: list[dict] = []
        for root_category in root_categories:
            rows.extend(
                self._build_price_list_items(
                    price_increase=price_increase,
                    root_category=root_category,
                )
            )

        scope_label = self._build_price_list_scope_label(root_categories)
        pdf_content = self._build_price_list_pdf(
            price_increase=price_increase,
            root_category=root_categories[0] if len(root_categories) == 1 else None,
            rows=rows,
            scope_label=scope_label,
        )

        filename_title = slugify(price_increase.title) or f"preiserhoehung-{price_increase.pk}"
        filename_scope = slugify(scope_label) or "standard-verkaufskanal"
        response = HttpResponse(pdf_content, content_type="application/pdf")
        response["Content-Disposition"] = (
            f'attachment; filename="{filename_title}-{filename_scope}-preisliste.pdf"'
        )
        return response

    @admin.action(description="PDF Preisliste")
    def export_price_list_pdf(self, request, queryset):
        selected_ids = list(queryset.values_list("pk", flat=True))
        if len(selected_ids) != 1:
            self.message_user(
                request,
                "Bitte genau eine Preiserhoehung markieren, damit eine eindeutige PDF erzeugt werden kann.",
                level=messages.ERROR,
            )
            return

        price_increase = (
            PriceIncrease.objects.filter(pk=selected_ids[0])
            .select_related("sales_channel")
            .first()
        )
        if not price_increase:
            self.message_user(request, "Preiserhoehung nicht gefunden.", level=messages.ERROR)
            return

        try:
            return self._build_default_price_list_response(price_increase)
        except ValueError as exc:
            self.message_user(request, str(exc), level=messages.ERROR)
            return

    @action(
        description="PDF Preisliste",
        icon="picture_as_pdf",
        variant=ActionVariant.PRIMARY,
    )
    def export_price_list_pdf_detail(self, request, object_id: str):
        obj = self.get_object(request, object_id)
        if not obj:
            self.message_user(request, "Preiserhoehung nicht gefunden.", level=messages.ERROR)
            return HttpResponseRedirect(reverse("admin:products_priceincrease_changelist"))
        try:
            return self._build_default_price_list_response(obj)
        except ValueError as exc:
            self.message_user(request, str(exc), level=messages.ERROR)
        return HttpResponseRedirect(reverse("admin:products_priceincrease_change", args=(object_id,)))

    @action(
        description="Preiserhoehung uebernehmen",
        icon="done",
        variant=ActionVariant.PRIMARY,
    )
    def apply_price_increase_detail(self, request, object_id: str):
        obj = self.get_object(request, object_id)
        if not obj:
            self.message_user(request, "Preiserhoehung nicht gefunden.", level=messages.ERROR)
            return HttpResponseRedirect(reverse("admin:products_priceincrease_changelist"))
        try:
            updated = PriceIncreaseService().apply(obj)
        except ValueError as exc:
            self.message_user(request, str(exc), level=messages.ERROR)
        else:
            self.message_user(request, f"Preiserhoehung uebernommen. {updated} Standardpreis(e) aktualisiert.")
        return HttpResponseRedirect(reverse("admin:products_priceincrease_change", args=(object_id,)))


@admin.register(PriceIncreaseItem)
class PriceIncreaseItemAdmin(BaseAdmin):
    form = PriceIncreaseItemEditForm
    list_display = (
        "erp_nr_display",
        "price_display",
        "rebate_quantity_display",
        "rebate_price_display",
        "unit_display",
        "new_price",
        "new_rebate_price",
    )
    list_display_links = list_display
    ordering = ("product__erp_nr", "id")
    list_filter = [("price_increase", RelatedDropdownFilter)]
    search_fields = (
        "price_increase__title",
        "product__erp_nr",
        "product__name",
    )
    list_per_page = 200
    readonly_fields = (
        "price_increase",
        "product",
        "source_price",
        "unit",
        "current_price",
        "current_rebate_quantity",
        "current_rebate_price",
    )
    fieldsets = (
        (
            "Preiserhoehungs-Position",
            {
                "fields": (
                    "price_increase",
                    "product",
                    "source_price",
                    "unit",
                    "current_price",
                    "current_rebate_quantity",
                    "current_rebate_price",
                    "new_price",
                    "new_rebate_price",
                    "created_at",
                    "updated_at",
                )
            },
        ),
    )

    def get_queryset(self, request):
        queryset = super().get_queryset(request)
        return queryset.select_related("price_increase", "product", "source_price").order_by(
            "product__erp_nr", "id"
        ).filter(product__is_active=True)

    @admin.display(description="ErpNr", ordering="product__erp_nr")
    def erp_nr_display(self, obj: PriceIncreaseItem):
        return obj.product.erp_nr

    @admin.display(description="Preis", ordering="current_price")
    def price_display(self, obj: PriceIncreaseItem):
        return obj.current_price

    @admin.display(description="VPE", ordering="current_rebate_quantity")
    def rebate_quantity_display(self, obj: PriceIncreaseItem):
        return obj.current_rebate_quantity

    @admin.display(description="Rab.Preis", ordering="current_rebate_price")
    def rebate_price_display(self, obj: PriceIncreaseItem):
        return obj.current_rebate_price

    @admin.display(description="Einht.", ordering="unit")
    def unit_display(self, obj: PriceIncreaseItem):
        return obj.unit

    def has_add_permission(self, request):
        return False


@admin.register(Storage)
class StorageAdmin(BaseAdmin):
    list_display = ("product", "stock", "virtual_stock", "location", "created_at")
    search_fields = ("product__erp_nr", "product__name", "location")
    list_filter = [
        ("stock", RangeNumericFilter),
        ("created_at", RangeDateTimeFilter),
    ]


@admin.register(Image)
class ImageAdmin(BaseAdmin):
    list_display = ("image_preview", "path", "alt_text", "created_at")
    search_fields = ("path", "alt_text")

    @admin.display(description="Bild")
    def image_preview(self, obj: Image):
        if not obj.url:
            return ""
        return format_html(
            '<img src="{}" loading="lazy" style="width:60px;height:60px;object-fit:cover;border-radius:4px;" />',
            obj.url,
        )


@admin.register(PropertyGroup)
class PropertyGroupAdmin(TabbedTranslationAdmin, BaseAdmin):
    formfield_overrides = {
        **getattr(TabbedTranslationAdmin, "formfield_overrides", {}),
        **BaseAdmin.formfield_overrides,
    }
    list_display = ("name", "created_at")
    search_fields = ("name", "name_de", "name_en")
    ordering = ("name",)


@admin.register(PropertyValue)
class PropertyValueAdmin(TabbedTranslationAdmin, BaseAdmin):
    formfield_overrides = {
        **getattr(TabbedTranslationAdmin, "formfield_overrides", {}),
        **BaseAdmin.formfield_overrides,
    }
    list_display = ("name", "group", "external_key", "created_at")
    search_fields = ("name", "name_de", "name_en", "group__name", "group__name_de", "external_key")
    list_filter = [("group", RelatedDropdownFilter), ("created_at", RangeDateTimeFilter)]
    autocomplete_fields = ("group",)
    ordering = ("group__name", "name")


@admin.register(Category)
class CategoryAdmin(BaseAdmin):
    list_display = (
        "name",
        "slug",
        "legacy_erp_nr",
        "parent",
        "sort_order",
        "created_at",
    )
    list_display_links = ("name",)
    search_fields = ("name", "slug", "legacy_erp_nr", "legacy_api_id", "parent__name")
    list_filter = [
        ("parent", RelatedDropdownFilter),
        ("created_at", RangeDateTimeFilter),
    ]
    readonly_fields = BaseAdmin.readonly_fields + (
        "legacy_erp_nr",
        "legacy_api_id",
        "legacy_parent_erp_nr",
    )
    ordering = ("tree_id", "lft")

    def get_urls(self):
        manager_view = self.admin_site.admin_view(CategoryManagerPageView.as_view(model_admin=self))
        return [
            path("manager/", manager_view, name="products_category_manager"),
            path("manager/tree/", self.admin_site.admin_view(self.tree_api_view), name="products_category_tree_api"),
            path("manager/move/", self.admin_site.admin_view(self.move_api_view), name="products_category_move_api"),
            path(
                "manager/<path:object_id>/products/",
                self.admin_site.admin_view(self.products_api_view),
                name="products_category_products_api",
            ),
            path(
                "manager/<path:object_id>/products/update/",
                self.admin_site.admin_view(self.product_assignment_api_view),
                name="products_category_product_assignment_api",
            ),
        ] + super().get_urls()

    def changelist_view(self, request, extra_context=None):
        return HttpResponseRedirect(reverse("admin:products_category_manager"))

    def _build_manager_context(self, request):
        return {
            **self.admin_site.each_context(request),
            "title": "Kategorien verwalten",
            "subtitle": "Baumstruktur und Produktzuordnung",
            "category_tree": self._category_tree_payload(),
            "category_count": Category.objects.count(),
            "product_count": Product.objects.count(),
            "urls": {
                "tree": reverse("admin:products_category_tree_api"),
                "move": reverse("admin:products_category_move_api"),
                "products": reverse(
                    "admin:products_category_products_api",
                    args=(0,),
                ).replace("/0/", "/{id}/"),
                "assignment": reverse(
                    "admin:products_category_product_assignment_api",
                    args=(0,),
                ).replace("/0/", "/{id}/"),
                "add": reverse("admin:products_category_add"),
            },
            "can_change_categories": self.has_change_permission(request),
        }

    def tree_api_view(self, request):
        if not self.has_view_permission(request):
            return JsonResponse({"error": "Keine Berechtigung."}, status=403)
        return JsonResponse({"categories": self._category_tree_payload()})

    def move_api_view(self, request):
        if request.method != "POST":
            return HttpResponseNotAllowed(["POST"])
        if not self.has_change_permission(request):
            return JsonResponse({"error": "Keine Berechtigung zum Speichern."}, status=403)

        try:
            category_id = int(request.POST.get("category_id") or 0)
            target_id = int(request.POST.get("target_id") or 0)
        except (TypeError, ValueError):
            return JsonResponse({"error": "Ungueltige Kategorie."}, status=400)

        position = str(request.POST.get("position") or "").strip()
        if position not in {"before", "after", "inside"}:
            return JsonResponse({"error": "Ungueltige Zielposition."}, status=400)

        category = Category.objects.filter(pk=category_id).first()
        target = Category.objects.filter(pk=target_id).first()
        if not category or not target:
            return JsonResponse({"error": "Kategorie nicht gefunden."}, status=404)
        if category.pk == target.pk or target.is_descendant_of(category):
            return JsonResponse({"error": "Diese Verschiebung wuerde einen Zyklus erzeugen."}, status=400)

        self._move_category(category=category, target=target, position=position)
        return JsonResponse({"categories": self._category_tree_payload()})

    def products_api_view(self, request, object_id: str):
        if not self.has_view_permission(request):
            return JsonResponse({"error": "Keine Berechtigung."}, status=403)
        category = self._get_category_or_404(object_id)
        return JsonResponse(self._category_products_payload(category, request.GET.get("q", "")))

    def product_assignment_api_view(self, request, object_id: str):
        if request.method != "POST":
            return HttpResponseNotAllowed(["POST"])
        if not self.has_change_permission(request):
            return JsonResponse({"error": "Keine Berechtigung zum Speichern."}, status=403)

        category = self._get_category_or_404(object_id)
        action_name = str(request.POST.get("action") or "").strip()
        try:
            product_id = int(request.POST.get("product_id") or 0)
        except (TypeError, ValueError):
            return JsonResponse({"error": "Ungueltiges Produkt."}, status=400)

        product = Product.objects.filter(pk=product_id).first()
        if not product:
            return JsonResponse({"error": "Produkt nicht gefunden."}, status=404)

        if action_name == "add":
            product.categories.add(category)
        elif action_name == "remove":
            product.categories.remove(category)
        else:
            return JsonResponse({"error": "Ungueltige Aktion."}, status=400)

        return JsonResponse(self._category_products_payload(category, request.POST.get("q", "")))

    def _category_tree_payload(self) -> list[dict]:
        product_counts = {
            row["category_id"]: row["count"]
            for row in Product.categories.through.objects.values("category_id").annotate(
                count=Count("product_id"),
            )
        }
        child_parent_ids = set(
            Category.objects.exclude(parent_id__isnull=True).values_list("parent_id", flat=True).distinct()
        )
        categories = Category.objects.order_by("tree_id", "lft").values(
            "id",
            "name",
            "slug",
            "parent_id",
            "legacy_erp_nr",
            "sort_order",
            "level",
            "lft",
            "rght",
        )
        return [
            {
                "id": row["id"],
                "name": row["name"],
                "slug": row["slug"],
                "parent_id": row["parent_id"],
                "legacy_erp_nr": row["legacy_erp_nr"],
                "sort_order": row["sort_order"],
                "level": row["level"],
                "has_children": row["id"] in child_parent_ids,
                "product_count": product_counts.get(row["id"], 0),
                "edit_url": reverse("admin:products_category_change", args=(row["id"],)),
            }
            for row in categories
        ]

    def _move_category(self, *, category: Category, target: Category, position: str) -> None:
        if position == "inside":
            new_parent = target
            siblings = list(
                target.get_children()
                .exclude(pk=category.pk)
                .order_by("sort_order", "name", "pk")
            )
            siblings.append(category)
        else:
            new_parent = target.parent
            if new_parent:
                siblings = list(
                    new_parent.get_children()
                    .exclude(pk=category.pk)
                    .order_by("sort_order", "name", "pk")
                )
            else:
                siblings = list(
                    Category.objects.root_nodes()
                    .exclude(pk=category.pk)
                    .order_by("sort_order", "name", "pk")
                )
            target_index = next((index for index, sibling in enumerate(siblings) if sibling.pk == target.pk), None)
            if target_index is None:
                target_index = len(siblings)
            insert_index = target_index + 1 if position == "after" else target_index
            siblings.insert(insert_index, category)

        new_parent_id = new_parent.pk if new_parent else None
        with transaction.atomic(), Category.objects.disable_mptt_updates():
            for index, sibling in enumerate(siblings, start=1):
                Category.objects.filter(pk=sibling.pk).update(
                    parent_id=new_parent_id,
                    sort_order=index * 10,
                )
        with transaction.atomic():
            Category.objects.rebuild()

    def _get_category_or_404(self, object_id: str) -> Category:
        category = Category.objects.filter(pk=object_id).first()
        if not category:
            raise Http404("Kategorie nicht gefunden.")
        return category

    def _category_products_payload(self, category: Category, search_term: str = "") -> dict:
        search_term = (search_term or "").strip()
        assigned_queryset = Product.objects.filter(categories=category).order_by("erp_nr", "name", "pk")
        assigned_total = assigned_queryset.count()
        assigned_products = [self._product_payload(product) for product in assigned_queryset[:200]]

        available_products = []
        if len(search_term) >= 2:
            available_queryset = (
                Product.objects.exclude(categories=category)
                .filter(Q(erp_nr__icontains=search_term) | Q(name__icontains=search_term))
                .order_by("-is_active", "erp_nr", "name", "pk")
                .distinct()
            )
            available_products = [self._product_payload(product) for product in available_queryset[:30]]

        return {
            "category": {
                "id": category.pk,
                "name": category.name,
                "legacy_erp_nr": category.legacy_erp_nr,
                "edit_url": reverse("admin:products_category_change", args=(category.pk,)),
            },
            "assigned_total": assigned_total,
            "assigned_products": assigned_products,
            "available_products": available_products,
            "search_term": search_term,
            "search_min_length": 2,
        }

    @staticmethod
    def _product_payload(product: Product) -> dict:
        return {
            "id": product.pk,
            "erp_nr": product.erp_nr,
            "name": product.name or "",
            "is_active": product.is_active,
            "edit_url": reverse("admin:products_product_change", args=(product.pk,)),
        }


@admin.register(Tax)
class TaxAdmin(BaseAdmin):
    list_display = ("name", "rate", "shopware_id", "created_at")
    search_fields = ("name", "shopware_id")
    list_filter = [
        ("rate", RangeNumericFilter),
        ("created_at", RangeDateTimeFilter),
    ]
