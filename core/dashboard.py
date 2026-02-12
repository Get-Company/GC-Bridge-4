from decimal import Decimal, ROUND_HALF_UP

from django.db.models import F
from django.utils import timezone

from products.models import Price


def _format_eur(value: Decimal) -> str:
    return f"{value.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)} EUR"


def _format_discount_percent(price: Decimal, special_price: Decimal) -> str:
    if price <= 0:
        return "0.00 %"
    reduction = ((price - special_price) / price) * Decimal("100")
    return f"{reduction.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)} %"


def dashboard_callback(request, context):
    now = timezone.now()

    discounted_prices = (
        Price.objects.select_related("product", "sales_channel")
        .filter(
            special_price__isnull=False,
            special_start_date__lte=now,
            special_end_date__gte=now,
            price__gt=0,
            special_price__lt=F("price"),
        )
        .order_by("special_end_date", "product__erp_nr")
    )

    rows = []
    for entry in discounted_prices:
        product_name = entry.product.name or "-"
        channel_name = entry.sales_channel.name if entry.sales_channel else "Default"
        end_date = timezone.localtime(entry.special_end_date).strftime("%d.%m.%Y %H:%M")

        rows.append(
            [
                f"{entry.product.erp_nr} - {product_name}",
                channel_name,
                _format_eur(entry.price),
                _format_eur(entry.special_price),
                _format_discount_percent(entry.price, entry.special_price),
                end_date,
            ]
        )

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

    return context
