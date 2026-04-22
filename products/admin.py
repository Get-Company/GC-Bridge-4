import json
from datetime import datetime
from decimal import Decimal

from django import forms
from django.contrib import admin, messages
from django.contrib.admin.models import LogEntry
from django.contrib.contenttypes.models import ContentType
from django.core.management import call_command
from django.core.serializers.json import DjangoJSONEncoder
from django.db.models import Case, Count, F, IntegerField, Prefetch, Q, Value, When, Window
from django.db.models.functions import RowNumber
from django.http import Http404, HttpResponseRedirect, HttpResponseNotAllowed, JsonResponse
from django.template.loader import render_to_string
from django.template.response import TemplateResponse
from django.urls import path, reverse
from django.utils import timezone
from django.utils.html import format_html
from js_asset import JS
from mptt.admin import DraggableMPTTAdmin
from modeltranslation.admin import TabbedTranslationAdmin
from django.views.generic import TemplateView

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
    actions_detail = ("open_positions_detail", "sync_positions_detail", "apply_price_increase_detail")
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
        item.display_current_rebate_quantity = self._format_integer(item.current_rebate_quantity)
        item.display_current_rebate_price = self._format_decimal(item.current_rebate_price)
        item.display_unit = item.unit or ""
        item.display_new_price = self._format_decimal(item.effective_new_price)
        item.display_new_rebate_price = self._format_decimal(item.effective_new_rebate_price)
        item.placeholder_new_price = self._format_decimal(item.suggested_price)
        item.placeholder_new_rebate_price = self._format_decimal(item.suggested_rebate_price)
        logged_status_message = getattr(item, "logged_status_message", "")
        item.row_status_message = getattr(item, "row_status_message", item.last_status_message or logged_status_message)
        item.row_status_detail = self._build_row_status_detail(item)
        item.row_status_meta = self._build_row_status_meta(item)
        item.save_url = self._positions_save_url(price_increase.pk, item.pk)
        return item

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

        mappings = (
            MappeiProductMapping.objects.filter(product_id__in=product_ids)
            .select_related("mappei_product")
        )
        mapping_by_product_id = {mapping.product_id: mapping for mapping in mappings}
        mappei_product_ids = [mapping.mappei_product_id for mapping in mapping_by_product_id.values()]
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
            mapping = mapping_by_product_id.get(item.product_id)
            if not mapping:
                continue
            snapshot = snapshot_by_product_id.get(mapping.mappei_product_id)
            if not snapshot:
                continue
            item.mappei_data = cls._build_mappei_price_data(item, mapping, snapshot)

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

    def _build_price_history_chart(self, item: PriceIncreaseItem, history_entries: list[PriceHistory]) -> dict:
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

        return {
            "data": json.dumps(
                {
                    "labels": [str(year) for year in sorted_years],
                    "datasets": [
                        {
                            "label": "Preis",
                            "data": prices,
                            "borderColor": "var(--color-primary-600)",
                            "backgroundColor": "var(--color-primary-100)",
                            "pointRadius": 4,
                            "pointHoverRadius": 6,
                            "tension": 0.25,
                            "displayYAxis": True,
                            "suffixYAxis": "EUR",
                            "maxTicksXLimit": 12,
                        }
                    ],
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

    @action(
        description="Positionsliste",
        icon="table_rows",
        variant=ActionVariant.PRIMARY,
    )
    def open_positions_detail(self, request, object_id: str):
        obj = self.get_object(request, object_id)
        if not obj:
            self.message_user(request, "Preiserhoehung nicht gefunden.", level=messages.ERROR)
            return HttpResponseRedirect(reverse("admin:products_priceincrease_changelist"))
        return HttpResponseRedirect(self._positions_page_url(obj.pk))

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
        chart = self._build_price_history_chart(item, history_entries)
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

    @action(
        description="Positionen aktualisieren",
        icon="sync",
        variant=ActionVariant.PRIMARY,
    )
    def sync_positions_detail(self, request, object_id: str):
        obj = self.get_object(request, object_id)
        if not obj:
            self.message_user(request, "Preiserhoehung nicht gefunden.", level=messages.ERROR)
            return HttpResponseRedirect(reverse("admin:products_priceincrease_changelist"))
        if obj.status == PriceIncrease.Status.APPLIED:
            self.message_user(request, "Uebernommene Preiserhoehungen koennen nicht mehr aktualisiert werden.", level=messages.WARNING)
            return HttpResponseRedirect(reverse("admin:products_priceincrease_change", args=(object_id,)))
        try:
            count = PriceIncreaseService().sync_items(obj)
        except ValueError as exc:
            self.message_user(request, str(exc), level=messages.ERROR)
        else:
            self.message_user(request, f"{count} Preisposition(en) aktualisiert.")
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
    list_display = ("name", "external_key", "created_at")
    search_fields = ("name", "name_de", "name_en", "external_key")
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
class CategoryAdmin(DraggableMPTTAdmin, BaseAdmin):
    list_display = (
        "tree_actions",
        "indented_title",
        "slug",
        "legacy_erp_nr",
        "parent",
        "created_at",
    )
    list_display_links = ("indented_title",)
    search_fields = ("name", "slug", "legacy_erp_nr", "legacy_api_id", "parent__name")
    list_filter = [
        ("parent", RelatedDropdownFilter),
        ("created_at", RangeDateTimeFilter),
    ]
    readonly_fields = BaseAdmin.readonly_fields + ("legacy_erp_nr", "legacy_api_id", "legacy_parent_erp_nr")
    mptt_indent_field = "name"

    def changelist_view(self, request, *args, **kwargs):
        response = super().changelist_view(request, *args, **kwargs)
        try:
            response.context_data["media"] = response.context_data["media"] + forms.Media(
                css={"all": ["products/admin/category_mptt_unfold.css"]},
                js=[
                    "admin/js/vendor/jquery/jquery.js",
                    "admin/js/jquery.init.js",
                    JS(
                        "mptt/draggable-admin.js",
                        {
                            "id": "draggable-admin-context",
                            "data-context": json.dumps(
                                self._tree_context(request),
                                cls=DjangoJSONEncoder,
                            ),
                        },
                    ),
                    JS(
                        "products/admin/category_mptt_unfold.js",
                        {
                            "id": "category-mptt-unfold-context",
                            "data-context": json.dumps(
                                self._tree_context(request),
                                cls=DjangoJSONEncoder,
                            ),
                        },
                    ),
                ],
            )
        except (AttributeError, KeyError):
            pass
        return response


@admin.register(Tax)
class TaxAdmin(BaseAdmin):
    list_display = ("name", "rate", "shopware_id", "created_at")
    search_fields = ("name", "shopware_id")
    list_filter = [
        ("rate", RangeNumericFilter),
        ("created_at", RangeDateTimeFilter),
    ]
