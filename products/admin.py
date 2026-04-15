from decimal import Decimal

from django import forms
from django.contrib import admin, messages
from django.contrib.contenttypes.models import ContentType
from django.core.management import call_command
from django.db.models import Case, IntegerField, Prefetch, Value, When
from django.http import HttpResponseRedirect
from django.urls import reverse
from django.utils import timezone
from django.utils.html import format_html
from modeltranslation.admin import TabbedTranslationAdmin

from unfold.contrib.filters.admin import (
    BooleanRadioFilter,
    RangeDateTimeFilter,
    RangeNumericFilter,
    RelatedDropdownFilter,
)
from unfold.decorators import action
from unfold.enums import ActionVariant
from unfold.forms import ActionForm as UnfoldActionForm

from core.admin import BaseAdmin, BaseStackedInline, BaseTabularInline
from core.admin_utils import log_admin_change
from shopware.models import ShopwareSettings
from .models import Category, Image, Price, Product, ProductImage, ProductProperty, PropertyGroup, PropertyValue, Storage, Tax


class StorageInline(BaseStackedInline):
    model = Storage
    fields = ("stock", "virtual_stock", "location")
    extra = 0


class ProductImageInline(BaseTabularInline):
    model = ProductImage
    fields = ("image_preview", "image", "order")
    readonly_fields = BaseTabularInline.readonly_fields + ("image_preview",)
    autocomplete_fields = ("image",)

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
    list_display = ("product", "sales_channel", "price", "special_percentage", "special_price", "special_active", "rebate_price", "created_at")
    search_fields = ("product__erp_nr", "product__name", "sales_channel__name")
    action_form = PriceActionForm
    actions = ("set_special_price_bulk", "clear_special_price_bulk")
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
class PropertyGroupAdmin(BaseAdmin):
    list_display = ("name", "external_key", "created_at")
    search_fields = ("name", "name_de", "name_en", "external_key")


@admin.register(PropertyValue)
class PropertyValueAdmin(BaseAdmin):
    list_display = ("name", "group", "external_key", "created_at")
    search_fields = ("name", "name_de", "name_en", "group__name", "group__name_de", "external_key")
    list_filter = [("group", RelatedDropdownFilter)]


@admin.register(Category)
class CategoryAdmin(BaseAdmin):
    list_display = ("name", "slug", "parent", "created_at")
    search_fields = ("name", "slug", "parent__name")
    list_filter = [
        ("parent", RelatedDropdownFilter),
        ("created_at", RangeDateTimeFilter),
    ]


@admin.register(Tax)
class TaxAdmin(BaseAdmin):
    list_display = ("name", "rate", "shopware_id", "created_at")
    search_fields = ("name", "shopware_id")
    list_filter = [
        ("rate", RangeNumericFilter),
        ("created_at", RangeDateTimeFilter),
    ]
