from __future__ import annotations

import csv
from decimal import Decimal, ROUND_FLOOR, ROUND_HALF_UP
from io import StringIO
from typing import Iterable, Iterator

from django.db.models import Prefetch

from core.services.base import BaseService
from shopware.models import ShopwareSettings
from products.models import Category, Image, Package, Price, Product, ProductImage


class MaboxExportError(RuntimeError):
    pass


class MaboxExportService(BaseService):
    """Build the Mabox CSV using the legacy resource_2.py column contract."""

    model = Product
    MANUFACTURER = "Classei | Egon Heimann GmbH"
    PURCHASE_FACTOR = Decimal("0.70")
    DELIVERY_DAYS = "2"
    HEADERS = (
        "Artikelnummer",
        "GTIN",
        "HAN",
        "Vaterartikel",
        "Artikelname",
        "Kurzbeschreibung",
        "Beschreibung",
        "Verkaufskanal-Suchbegriffe",
        "Titel-Tag (SEO)",
        "Meta-Keywords (SEO)",
        "Meta-Description (SEO)",
        "Brutto-VK",
        "Netto-VK",
        "Durchschnittlicher Einkaufspreis (netto)",
        "UVP",
        "Steuersatz in %",
        "Auf Lager",
        "Artikelgewicht",
        "Versandgewicht",
        "Breite",
        "Höhe",
        "Länge",
        "Verkaufseinheit",
        "Inhalt/Menge",
        "Maßeinheit",
        "Hersteller",
        "Warengruppe",
        "Ist Vaterartikel",
        "Mindestabnahme [Händler]",
        "Abnahmeintervall [Händler]",
        "Mindestabnahme [Endkunden]",
        "Abnahmeintervall [Endkunden]",
        "Mindestabnahme [B2B]",
        "Abnahmeintervall [B2B]",
        "Lieferant",
        "Artikelnummer (Lieferant)",
        "Artikelname (Lieferant)",
        "Brutto-EK",
        "Netto-EK",
        "Lieferzeit in Tagen (Lieferant)",
        "Mindestabnahme (Lieferant)",
        "Abnahmeintervall (Lieferant)",
        "Lieferantenbestand",
        "Dropshipping möglich",
        "Bild 1",
        "Bild 2",
        "Bild 3",
        "Bild 4",
        "Bild 5",
        "Kategoriepfad",
    )

    def __init__(
        self,
        *,
        sales_channel: ShopwareSettings | None = None,
    ) -> None:
        self._sales_channel = sales_channel
        self._category_paths: dict[int, tuple[str, ...]] | None = None

    @property
    def sales_channel(self) -> ShopwareSettings:
        if self._sales_channel is not None:
            return self._sales_channel

        self._sales_channel = ShopwareSettings.objects.filter(is_active=True, is_default=True).first()
        if self._sales_channel is None:
            raise MaboxExportError("Es ist kein aktiver Standard-Verkaufskanal als Preisquelle vorhanden.")
        return self._sales_channel

    def get_queryset(self):
        price_queryset = Price.objects.filter(sales_channel=self.sales_channel).select_related("sales_channel")
        package_queryset = Package.objects.filter(is_active=True, mabox_enabled=True).order_by(
            "quantity", "package_nr"
        )
        image_queryset = ProductImage.objects.select_related("image").order_by("order", "id")
        legacy_image_queryset = Image.objects.order_by("id")
        return (
            Product.objects.filter(is_active=True, is_archived=False)
            .select_related("tax", "storage")
            .prefetch_related(
                Prefetch("prices", queryset=price_queryset, to_attr="mabox_prices"),
                Prefetch("packages", queryset=package_queryset, to_attr="mabox_packages"),
                Prefetch("product_images", queryset=image_queryset, to_attr="ordered_product_images"),
                Prefetch("images", queryset=legacy_image_queryset, to_attr="mabox_legacy_images"),
                "categories",
            )
            .order_by("erp_nr")
        )

    def render_csv(self, products: Iterable[Product] | None = None) -> str:
        output = StringIO(newline="")
        writer = csv.writer(output, dialect="excel", lineterminator="\r\n")
        writer.writerow(self.HEADERS)
        writer.writerows(self.iter_rows(products))
        return output.getvalue()

    def iter_rows(self, products: Iterable[Product] | None = None) -> Iterator[list[object]]:
        source = products if products is not None else self.get_queryset()
        for product in source:
            packages = list(getattr(product, "mabox_packages", ()))
            price = self._get_price(product)
            yield self._build_row(product=product, price=price, packages=packages)
            for package in packages:
                yield self._build_row(product=product, price=price, packages=packages, package=package)

    def _build_row(
        self,
        *,
        product: Product,
        price: Price,
        packages: list[Package],
        package: Package | None = None,
    ) -> list[object]:
        is_parent = package is None and bool(packages)
        net_price = None if is_parent else self._net_price(product=product, price=price, package=package)
        gross_price = None if net_price is None else net_price * self._tax_factor(product)
        net_purchase_price = None if net_price is None else net_price * self.PURCHASE_FACTOR
        gross_purchase_price = None if gross_price is None else gross_price * self.PURCHASE_FACTOR
        unit = self._unit(product.unit)
        stock = self._stock(product=product, package=package)
        name = self._localized_value(product, "name")
        description = self._clean_text(self._localized_value(product, "description"))
        description_short = self._clean_text(
            self._localized_value(product, "description_short") or description
        )
        images = self._image_urls(product)
        min_purchase = 1 if package else self._value_or_blank(product.min_purchase)
        purchase_unit = 1 if package else self._value_or_blank(product.purchase_unit)
        article_number = package.package_nr if package else product.erp_nr
        gtin = (package.gtin or product.gtin) if package else product.gtin

        return [
            article_number,
            gtin or "",
            "",
            product.erp_nr if package else "",
            name,
            description_short,
            description,
            "",
            name,
            "",
            description,
            self._format_price(gross_price),
            self._format_price(net_price),
            self._format_price(net_purchase_price),
            "",
            self._format_price(product.tax.rate if product.tax else None),
            stock,
            self._format_measure(product.weight_net),
            self._format_measure(product.weight_gross),
            "",
            "",
            "",
            unit,
            package.quantity if package else 1,
            unit,
            self.MANUFACTURER,
            "",
            1 if is_parent else 0,
            min_purchase,
            purchase_unit,
            min_purchase,
            purchase_unit,
            min_purchase,
            purchase_unit,
            self.MANUFACTURER,
            article_number,
            name,
            self._format_price(gross_purchase_price),
            self._format_price(net_purchase_price),
            self.DELIVERY_DAYS,
            self._value_or_blank(product.min_purchase),
            self._value_or_blank(product.purchase_unit),
            stock,
            0,
            *images,
            self._category_path(product),
        ]

    def _get_price(self, product: Product) -> Price:
        prices = list(getattr(product, "mabox_prices", ()))
        if not prices:
            prices = list(product.prices.filter(sales_channel=self.sales_channel)[:1])
        if not prices:
            raise MaboxExportError(
                f"Produkt {product.erp_nr}: Kein Preis für Verkaufskanal '{self.sales_channel.name}'."
            )
        if product.tax is None:
            raise MaboxExportError(f"Produkt {product.erp_nr}: Kein Steuersatz hinterlegt.")
        return prices[0]

    @staticmethod
    def _net_price(*, product: Product, price: Price, package: Package | None) -> Decimal:
        unit_price = Decimal(price.price)
        if (
            package is not None
            and price.rebate_quantity
            and price.rebate_price is not None
            and package.quantity >= price.rebate_quantity
        ):
            unit_price = Decimal(price.rebate_price)
        if package is None:
            return unit_price
        factor = Decimal(product.factor or 1)
        return unit_price / factor * Decimal(package.quantity)

    @staticmethod
    def _tax_factor(product: Product) -> Decimal:
        return Decimal("1") + Decimal(product.tax.rate) / Decimal("100")

    @staticmethod
    def _stock(*, product: Product, package: Package | None) -> int:
        storage = getattr(product, "storage", None)
        stock = Decimal(storage.get_stock if storage is not None else 0)
        if package is not None:
            stock /= Decimal(package.quantity)
        return max(0, int(stock.to_integral_value(rounding=ROUND_FLOOR)))

    @staticmethod
    def _format_price(value: Decimal | None) -> str:
        if value is None:
            return ""
        rounded = Decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        return f"{rounded:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

    @staticmethod
    def _format_measure(value: Decimal | None) -> str:
        if value is None:
            return ""
        normalized = Decimal(value).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
        return format(normalized, "f").rstrip("0").rstrip(".").replace(".", ",")

    @staticmethod
    def _unit(value: str | None) -> str:
        return "Stück" if not value or value == "Stck" else value

    @staticmethod
    def _value_or_blank(value):
        return "" if value is None else value

    @staticmethod
    def _clean_text(value: str | None) -> str:
        return str(value or "").replace("\r", "").replace("\n", "")

    @staticmethod
    def _localized_value(product: Product, field_name: str) -> str:
        return str(getattr(product, f"{field_name}_de", None) or getattr(product, field_name, None) or "")

    @staticmethod
    def _image_urls(product: Product) -> list[str]:
        if hasattr(product, "ordered_product_images") and hasattr(product, "mabox_legacy_images"):
            ordered_images = [
                product_image.image
                for product_image in product.ordered_product_images
                if product_image.image_id and product_image.image
            ]
            known_ids = {image.pk for image in ordered_images}
            ordered_images.extend(
                image for image in product.mabox_legacy_images if image.pk not in known_ids
            )
        else:
            ordered_images = product.get_images()
        urls = [image.url for image in ordered_images if image.url][:5]
        return urls + [""] * (5 - len(urls))

    def _category_path(self, product: Product) -> str:
        categories = list(product.categories.all())
        if not categories:
            return ""
        if all(isinstance(category, Category) for category in categories):
            paths = self._get_category_paths()
            candidates = [(category, paths.get(category.pk, (category.name,))) for category in categories]
            _category, path = max(
                candidates,
                key=lambda item: (item[0].level, -item[0].sort_order, -item[0].pk),
            )
            return " > ".join(path)
        category = max(categories, key=lambda item: (item.level, -item.sort_order, -item.pk))
        return category.get_category_path()

    def _get_category_paths(self) -> dict[int, tuple[str, ...]]:
        if self._category_paths is None:
            paths: dict[int, tuple[str, ...]] = {}
            categories = Category.objects.only("id", "parent_id", "name", "tree_id", "lft").order_by(
                "tree_id", "lft"
            )
            for category in categories:
                paths[category.pk] = (*paths.get(category.parent_id, ()), category.name)
            self._category_paths = paths
        return self._category_paths
