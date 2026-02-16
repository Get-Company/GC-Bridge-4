import logging
from decimal import Decimal, ROUND_HALF_UP

from django.contrib import messages
from django.db import DatabaseError, connection
from django.utils import timezone

logger = logging.getLogger(__name__)


def _format_eur(value: Decimal) -> str:
    return f"{value.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)} EUR"


def _format_discount_percent(price: Decimal, special_price: Decimal) -> str:
    if price <= 0:
        return "0.00 %"
    reduction = ((price - special_price) / price) * Decimal("100")
    return f"{reduction.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)} %"


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


def dashboard_callback(request, context):
    now = timezone.now()
    rows = []
    warning_message = None

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

    if warning_message and request is not None:
        messages.warning(request, warning_message)

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

    return context
