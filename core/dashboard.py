import logging
import time
from decimal import Decimal, ROUND_HALF_UP

from django.contrib import messages
from django.db import DatabaseError, connection
from django.utils import timezone

from orders.models import Order
from products.models import PriceIncrease, Product
from shopware.models import ShopwareSettings

logger = logging.getLogger(__name__)

_HIDDEN_DASHBOARD_APPS = {
    "ai",
    "auth",
    "customer",
    "mappei",
    "microtech",
    "orders",
    "products",
    "shopware",
}

_REMOTE_METRICS_CACHE: dict = {"checked_at": 0.0, "value": None}
_REMOTE_METRICS_CACHE_SECONDS = 30.0
_PRICE_ANOMALY_ROW_LIMIT = 100


def _format_eur(value: Decimal) -> str:
    return f"{value.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)} EUR"


def _format_discount_percent(price: Decimal, special_price: Decimal) -> str:
    if price <= 0:
        return "0.00 %"
    reduction = ((price - special_price) / price) * Decimal("100")
    return f"{reduction.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)} %"


def _format_price_delta(actual: Decimal | None, expected: Decimal | None) -> str:
    if actual is None or expected is None:
        return "-"
    difference = actual - expected
    sign = "+" if difference > 0 else ""
    if expected <= 0:
        return f"{sign}{_format_eur(difference)}"
    percent = (difference / expected) * Decimal("100")
    return (
        f"{sign}{_format_eur(difference)} "
        f"({sign}{percent.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)} %)"
    )


def _price_label(product: Product) -> str:
    return f"{product.erp_nr} - {product.name or '-'}"


def _sales_channel_name(sales_channel) -> str:
    return sales_channel.name if sales_channel else "Standard"


def _detect_price_column() -> tuple[str | None, str | None]:
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT column_name, data_type
                FROM information_schema.columns
                WHERE table_name = 'products_price'
                ORDER BY ordinal_position
                """
            )
            column_rows = cursor.fetchall()
    except DatabaseError:
        return (
            None,
            "Tabelle 'products_price' nicht erreichbar. "
            "Bitte Datenbankverbindung und Berechtigungen prüfen.",
        )

    if not column_rows:
        return None, "Tabelle 'products_price' wurde nicht gefunden."

    columns = {name for name, _ in column_rows}
    numeric_types = {"smallint", "integer", "bigint", "numeric", "real", "double precision"}
    numeric_columns = {name for name, data_type in column_rows if data_type in numeric_types}

    required_discount_columns = {"special_price", "special_start_date", "special_end_date"}
    missing_discount_columns = sorted(required_discount_columns - columns)
    if missing_discount_columns:
        return (
            None,
            "Inkompatibles Legacy-Schema in products_price. "
            f"Fehlende Spalten fuer Dashboard-Rabatte: {', '.join(missing_discount_columns)}",
        )

    if "price" in columns:
        return "price", None

    known_legacy_candidates = (
        "gross_price",
        "normal_price",
        "base_price",
        "net_price",
        "amount",
    )
    for candidate in known_legacy_candidates:
        if candidate in numeric_columns:
            return (
                candidate,
                f"Legacy-Preisspalte '{candidate}' erkannt. "
                "Bitte Datenbankschema auf 'price' aktualisieren.",
            )

    derived_candidates = sorted(
        column_name
        for column_name in numeric_columns
        if ("price" in column_name.lower() or "amount" in column_name.lower())
        and column_name not in {"special_price", "rebate_price"}
        and not column_name.startswith("special_")
        and not column_name.startswith("rebate_")
    )
    if derived_candidates:
        selected_column = derived_candidates[0]
        return (
            selected_column,
            f"Nicht-standard Preisspalte '{selected_column}' erkannt. "
            "Bitte Datenbankschema auf 'price' aktualisieren.",
        )

    visible_columns = ", ".join(sorted(columns))
    return (
        None,
        "Preisfeld in products_price nicht gefunden. "
        f"Gefundene Spalten: {visible_columns or '(keine)'}",
    )


def _fetch_discounted_rows(now, price_column: str) -> list[list[str]]:
    qn = connection.ops.quote_name
    price_table = qn("products_price")
    product_table = qn("products_product")
    channel_table = qn("shopware_shopwaresettings")
    price_field = qn(price_column)
    query = f"""
        SELECT
            p.erp_nr,
            p.name,
            COALESCE(sc.name, 'Default') AS channel_name,
            pr.{price_field} AS base_price,
            pr.special_price,
            pr.special_end_date
        FROM {price_table} pr
        JOIN {product_table} p ON p.id = pr.product_id
        LEFT JOIN {channel_table} sc ON sc.id = pr.sales_channel_id
        WHERE pr.special_price IS NOT NULL
          AND pr.special_start_date <= %s
          AND pr.special_end_date >= %s
          AND pr.{price_field} > 0
          AND pr.special_price < pr.{price_field}
        ORDER BY pr.special_end_date, p.erp_nr
    """

    rows = []
    with connection.cursor() as cursor:
        cursor.execute(query, [now, now])
        for erp_nr, product_name, channel_name, price, special_price, special_end_date in cursor.fetchall():
            if timezone.is_naive(special_end_date):
                special_end_date = timezone.make_aware(special_end_date, timezone.get_current_timezone())
            local_end_date = timezone.localtime(special_end_date).strftime("%d.%m.%Y %H:%M")
            rows.append(
                [
                    f"{erp_nr} - {product_name or '-'}",
                    channel_name or "Default",
                    _format_eur(price),
                    _format_eur(special_price),
                    _format_discount_percent(price, special_price),
                    local_end_date,
                ]
            )
    return rows


def _format_datetime(value) -> str:
    if not value:
        return "-"
    if timezone.is_naive(value):
        value = timezone.make_aware(value, timezone.get_current_timezone())
    return timezone.localtime(value).strftime("%d.%m.%Y %H:%M")


def _filter_dashboard_apps(context: dict) -> None:
    app_list = context.get("app_list") or []
    available_apps = context.get("available_apps") or []

    def is_visible(app: dict) -> bool:
        return str(app.get("app_label") or "").strip().lower() not in _HIDDEN_DASHBOARD_APPS

    context["app_list"] = [app for app in app_list if is_visible(app)]
    context["available_apps"] = [app for app in available_apps if is_visible(app)]


def _fetch_open_order_rows(limit: int = 10) -> tuple[int, list[list[str]]]:
    queryset = (
        Order.objects.select_related("customer")
        .filter(order_state="open")
        .order_by("-purchase_date", "-created_at")
    )
    count = queryset.count()
    rows = [
        [
            order.order_number or order.api_id,
            str(order.customer) if order.customer_id else "-",
            _format_eur(order.total_price),
            order.payment_method or "-",
            _format_datetime(order.purchase_date),
        ]
        for order in queryset[:limit]
    ]
    return count, rows


def _get_remote_shopware_metrics() -> dict:
    """Load cached, read-only counts from the Shopware Admin API."""
    now = time.monotonic()
    cached = _REMOTE_METRICS_CACHE.get("value")
    checked_at = float(_REMOTE_METRICS_CACHE.get("checked_at") or 0.0)
    if cached is not None and now - checked_at < _REMOTE_METRICS_CACHE_SECONDS:
        return dict(cached)

    metrics: dict = {
        "customer_count": None,
        "customer_error": None,
        "product_rows": [],
        "product_error": None,
    }
    try:
        from shopware.services import CustomerService, ProductService
    except Exception as exc:
        metrics["customer_error"] = str(exc)
        metrics["product_error"] = str(exc)
    else:
        try:
            metrics["customer_count"] = CustomerService().count_active_accounts()
        except Exception as exc:
            metrics["customer_error"] = str(exc)

        try:
            active_channels = list(
                ShopwareSettings.objects.filter(is_active=True)
                .exclude(sales_channel_id="")
                .order_by("name", "pk")
            )
            if not active_channels:
                metrics["product_error"] = "Keine aktiven Verkaufskanäle mit Shopware-ID konfiguriert."
            else:
                product_service = ProductService()
                rows = []
                for sales_channel in active_channels:
                    bridge_count = Product.objects.filter(
                        is_active=True,
                        prices__sales_channel=sales_channel,
                    ).distinct().count()
                    try:
                        shopware_count = product_service.count_active_by_sales_channel(
                            sales_channel.sales_channel_id
                        )
                    except Exception as exc:  # The remaining channels are still useful.
                        rows.append(
                            {
                                "sales_channel": sales_channel.name,
                                "bridge_count": bridge_count,
                                "shopware_count": None,
                                "difference": None,
                                "ok": None,
                                "detail": str(exc),
                            }
                        )
                        continue

                    difference = shopware_count - bridge_count
                    rows.append(
                        {
                            "sales_channel": sales_channel.name,
                            "bridge_count": bridge_count,
                            "shopware_count": shopware_count,
                            "difference": difference,
                            "ok": difference == 0,
                            "detail": "",
                        }
                    )
                metrics["product_rows"] = rows
        except Exception as exc:
            metrics["product_error"] = str(exc)

    _REMOTE_METRICS_CACHE.update({"checked_at": now, "value": metrics})
    return dict(metrics)


def _fetch_price_anomaly_rows() -> tuple[int, list[list[str]], str | None, str | None]:
    """Compare the current prices with the targets of the latest applied increase."""
    price_increase = (
        PriceIncrease.objects.select_related("sales_channel")
        .filter(status=PriceIncrease.Status.APPLIED)
        .order_by("-applied_at", "-pk")
        .first()
    )
    if price_increase is None:
        return 0, [], "Keine übernommene Preiserhöhung vorhanden.", None

    rows: list[list[str]] = []
    items = price_increase.items.select_related(
        "product",
        "price_increase",
        "source_price__sales_channel",
    ).order_by("product__erp_nr", "pk")
    for item in items:
        source_price = item.source_price
        sales_channel = _sales_channel_name(source_price.sales_channel)
        product_label = _price_label(item.product)
        expected_price = item.effective_new_price
        actual_price = Decimal(source_price.price)

        if actual_price != expected_price:
            direction = "zu hoch" if actual_price > expected_price else "zu niedrig"
            rows.append(
                [
                    product_label,
                    sales_channel,
                    f"Normalpreis seit der letzten Preiserhöhung {direction}",
                    _format_eur(actual_price),
                    _format_eur(expected_price),
                    _format_price_delta(actual_price, expected_price),
                ]
            )

        expected_rebate_price = item.effective_new_rebate_price
        actual_rebate_price = source_price.rebate_price
        rebate_label = f"Staffelpreis (Menge {source_price.rebate_quantity or '-'})"
        if expected_rebate_price is None and actual_rebate_price is not None:
            rows.append(
                [
                    product_label,
                    sales_channel,
                    f"{rebate_label} unerwartet gesetzt",
                    _format_eur(actual_rebate_price),
                    "-",
                    "-",
                ]
            )
        elif expected_rebate_price is not None and actual_rebate_price is None:
            rows.append(
                [
                    product_label,
                    sales_channel,
                    f"{rebate_label} fehlt",
                    "-",
                    _format_eur(expected_rebate_price),
                    "-",
                ]
            )
        elif expected_rebate_price is not None and actual_rebate_price != expected_rebate_price:
            direction = "zu hoch" if actual_rebate_price > expected_rebate_price else "zu niedrig"
            rows.append(
                [
                    product_label,
                    sales_channel,
                    f"{rebate_label} seit der letzten Preiserhöhung {direction}",
                    _format_eur(actual_rebate_price),
                    _format_eur(expected_rebate_price),
                    _format_price_delta(actual_rebate_price, expected_rebate_price),
                ]
            )

        for issue in item.get_pricing_check_issues():
            field_name = str(issue.get("field") or "")
            actual_value: Decimal | None = None
            expected_value: Decimal | None = None
            if field_name == "new_price":
                actual_value = item.effective_new_price
                expected_value = item.suggested_price
            elif field_name == "new_rebate_price":
                actual_value = item.effective_new_rebate_price
                expected_value = item.suggested_rebate_price
            elif field_name == "current_rebate_price":
                actual_value = item.current_rebate_price
                expected_value = item.current_price

            rows.append(
                [
                    product_label,
                    sales_channel,
                    str(issue["message"]),
                    _format_eur(actual_value) if actual_value is not None else "-",
                    _format_eur(expected_value) if expected_value is not None else "-",
                    _format_price_delta(actual_value, expected_value),
                ]
            )

    applied_at = _format_datetime(price_increase.applied_at)
    return len(rows), rows[:_PRICE_ANOMALY_ROW_LIMIT], None, f"{price_increase.title} ({applied_at})"


def dashboard_callback(request, context):
    now = timezone.now()
    rows = []
    warning_message = None
    open_orders_rows = []
    open_orders_count = 0
    open_orders_warning = None
    price_anomaly_rows = []
    price_anomaly_count = 0
    price_anomaly_warning = None
    latest_price_increase = None

    try:
        price_column, warning_message = _detect_price_column()
        if price_column:
            rows = _fetch_discounted_rows(now, price_column)
    except DatabaseError:
        logger.exception("Dashboard discounted prices could not be loaded.")
        warning_message = (
            "Rabattdaten konnten nicht geladen werden. "
            "Bitte Datenbankverbindung und Migrationen prüfen."
        )

    try:
        open_orders_count, open_orders_rows = _fetch_open_order_rows()
    except DatabaseError:
        logger.exception("Dashboard open orders could not be loaded.")
        open_orders_warning = (
            "Offene Bestellungen konnten nicht geladen werden. "
            "Bitte Datenbankverbindung und Migrationen prüfen."
        )

    try:
        (
            price_anomaly_count,
            price_anomaly_rows,
            price_anomaly_warning,
            latest_price_increase,
        ) = _fetch_price_anomaly_rows()
    except DatabaseError:
        logger.exception("Dashboard price anomalies could not be loaded.")
        price_anomaly_warning = (
            "Preisprüfungen konnten nicht geladen werden. "
            "Bitte Datenbankverbindung und Migrationen prüfen."
        )

    try:
        from core.admin_status import shopware_health_check

        shopware_health = shopware_health_check()
    except Exception as exc:
        logger.exception("Dashboard Shopware health check failed.")
        shopware_health = {
            "ok": False,
            "detail": str(exc),
            "latency_ms": None,
        }

    shopware_customer_count = None
    shopware_customer_warning = None
    product_balance_rows: list[dict] = []
    product_balance_warning = None
    if shopware_health.get("ok") is True:
        remote_metrics = _get_remote_shopware_metrics()
        shopware_customer_count = remote_metrics["customer_count"]
        shopware_customer_warning = remote_metrics["customer_error"]
        product_balance_rows = remote_metrics["product_rows"]
        product_balance_warning = remote_metrics["product_error"]
    else:
        detail = shopware_health.get("detail") or "Shopware ist nicht erreichbar."
        shopware_customer_warning = detail
        product_balance_warning = detail

    product_balance_count = sum(row["ok"] is False for row in product_balance_rows)

    if warning_message and request is not None:
        messages.warning(request, warning_message)
    if open_orders_warning and request is not None:
        messages.warning(request, open_orders_warning)

    _filter_dashboard_apps(context)

    context["discounted_articles_table"] = {
        "headers": [
            "Artikel",
            "Verkaufskanal",
            "Normalpreis",
            "Sonderpreis",
            "Reduziert um",
            "Endet am",
        ],
        "rows": rows,
    }
    context["discounted_articles_count"] = len(rows)
    context["discounted_articles_warning"] = warning_message
    context["open_orders_table"] = {
        "headers": [
            "Bestellung",
            "Kunde",
            "Gesamtpreis",
            "Zahlart",
            "Bestelldatum",
        ],
        "rows": open_orders_rows,
    }
    context["open_orders_count"] = open_orders_count
    context["open_orders_warning"] = open_orders_warning
    context["shopware_health"] = shopware_health
    context["shopware_customer_count"] = shopware_customer_count
    context["shopware_customer_warning"] = shopware_customer_warning
    context["product_balance_rows"] = product_balance_rows
    context["product_balance_count"] = product_balance_count
    context["product_balance_warning"] = product_balance_warning
    context["price_anomalies_table"] = {
        "headers": [
            "Artikel",
            "Verkaufskanal",
            "Problem",
            "Ist",
            "Erwartet",
            "Abweichung",
        ],
        "rows": price_anomaly_rows,
    }
    context["price_anomaly_count"] = price_anomaly_count
    context["price_anomaly_warning"] = price_anomaly_warning
    context["latest_price_increase"] = latest_price_increase
    context["price_anomaly_row_limit"] = _PRICE_ANOMALY_ROW_LIMIT

    return context
