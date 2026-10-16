"""Authoritative prices of a completed Shopware order, never catalogue prices."""
from __future__ import annotations

import json
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from core.services import BaseService

CENT = Decimal("0.01")
MAX_ROUNDING_OFFSET = CENT


class OrderPriceService(BaseService):
    @staticmethod
    def decimal(value) -> Decimal:
        try:
            result = Decimal(str(value).replace(",", "."))
        except (InvalidOperation, ValueError, TypeError) as exc:
            raise ValueError(f"Ungültiger Shopware-/Microtech-Preis: {value!r}.") from exc
        if not result.is_finite():
            raise ValueError("Preis ist keine endliche Zahl.")
        return result

    @classmethod
    def money(cls, value) -> Decimal:
        return cls.decimal(value).quantize(CENT, rounding=ROUND_HALF_UP)

    @classmethod
    def totals_match(cls, actual, expected) -> bool:
        """Allow one cent of rounding drift in persisted monetary totals."""
        return abs(cls.money(actual) - cls.money(expected)) <= MAX_ROUNDING_OFFSET

    @classmethod
    def unit_prices_match(cls, actual, expected, *, unit, quantity, total=None) -> bool:
        """Bound read-back unit-price rounding across the entire ordered quantity."""
        actual_total = cls.decimal(actual) / cls.unit_divisor(unit) * cls.decimal(quantity)
        expected_total = cls.decimal(expected) * cls.decimal(quantity)
        if cls.totals_match(actual_total, expected_total):
            return True
        # Converted Microtech invoices can report the generic label "Einheit"
        # for a price per 100. Require the returned line total to independently
        # confirm that basis; never infer it just from the expected shop price.
        if str(unit or "").strip().casefold() == "einheit" and total is not None:
            per_hundred_total = cls.decimal(actual) / Decimal(100) * cls.decimal(quantity)
            return (
                cls.totals_match(per_hundred_total, total)
                and cls.totals_match(per_hundred_total, expected_total)
            )
        return False

    @classmethod
    def snapshot_from_data(cls, data: dict) -> dict:
        price = data.get("price") or {}
        # Legacy imports without prices are left unverified and must reload
        # the completed order before an export can start.
        if "totalPrice" not in price:
            return {}
        snapshot = {
            "version": 1,
            "source_order_id": data.get("id"),
            "currency": (data.get("currency") or {}).get("isoCode") or "EUR",
            "price": price,
            "shipping": data.get("shippingCosts") or {},
            "lines": [
                {"id": line.get("id"), "quantity": line.get("quantity"),
                 "type": line.get("type"), "price": line.get("price") or {}}
                for line in data.get("lineItems") or []
            ],
        }
        return json.loads(json.dumps(snapshot, default=str))

    def ensure_snapshot(self, order) -> dict:
        if order.shopware_price_snapshot:
            self.validate_snapshot(order)
            return order.shopware_price_snapshot
        if not order.api_id:
            raise ValueError("Bestellung hat keine gesicherten Shopware-Originalpreise.")
        from shopware.services import OrderService
        from orders.services.order_sync import _normalize_entity

        response = OrderService().get_by_id(order.api_id)
        rows = _normalize_entity((response or {}).get("data") or [])
        data = rows[0] if isinstance(rows, list) and len(rows) == 1 else None
        if not data or data.get("id") != order.api_id:
            raise ValueError("Shopware-Originalbestellung konnte für die Preisprüfung nicht gelesen werden.")
        order.shopware_price_snapshot = self.snapshot_from_data(data)
        self.validate_snapshot(order)
        order.save(update_fields=("shopware_price_snapshot", "updated_at"))
        return order.shopware_price_snapshot

    def validate_snapshot(self, order) -> None:
        snapshot = order.shopware_price_snapshot
        if not snapshot or snapshot.get("version") != 1:
            raise ValueError("Shopware-Originalpreise fehlen oder haben eine unbekannte Version.")
        currency = str(snapshot.get("currency") or "")
        if len(currency) != 3 or not currency.isalpha() or currency != currency.upper():
            raise ValueError("Shopware-Währung fehlt oder ist kein ISO-Währungscode.")
        status = snapshot["price"].get("taxStatus")
        if status not in ("gross", "net", "tax-free"):
            raise ValueError("Shopware-Steuer-/Preisbasis fehlt.")
        details = list(order.details.all())
        lines = snapshot.get("lines") or []
        ids = [line.get("id") for line in lines]
        if any(not item for item in ids) or len(set(ids)) != len(ids):
            raise ValueError("Shopware-Preissicherung enthält keine eindeutigen Bestellpositionen.")
        if set(ids) != {detail.api_id for detail in details} or len(lines) != len(details):
            raise ValueError("Shopware-Originalpositionen stimmen nicht mit den Bridge-Bestellpositionen überein.")
        for detail in details:
            line = self.line(detail)
            if not detail.erp_nr or detail.quantity <= 0 or int(line["quantity"]) != detail.quantity:
                raise ValueError(f"Artikel/Menge der Shopware-Position {detail.api_id} stimmt nicht überein.")
            if self.money(self.unit_price(detail) * detail.quantity) != self.money(line["price"]["totalPrice"]):
                raise ValueError(f"Einzelpreis/Menge passt nicht zur Shopware-Positionssumme {detail.api_id}.")
        shipping = self.shipping_price(order)
        total = sum((self.decimal(line["price"]["totalPrice"]) for line in lines), Decimal(0)) + shipping
        key = "totalPrice" if self.is_gross(order) or status == "tax-free" else "netPrice"
        expected = snapshot["price"].get(key)
        if expected is None or self.money(total) != self.money(expected):
            raise ValueError("Shopware-Positions- und Versandpreise stimmen nicht mit der Bestellsumme überein.")
        if self.money(order.total_price) != self.money(snapshot["price"]["totalPrice"]):
            raise ValueError("Bridge-Gesamtsumme stimmt nicht mit der gesicherten Shopware-Bestellung überein.")

    @staticmethod
    def is_gross(order) -> bool:
        return (order.shopware_price_snapshot.get("price") or {}).get("taxStatus") == "gross"

    def line(self, detail) -> dict:
        lines = detail.order.shopware_price_snapshot.get("lines") or []
        matches = [line for line in lines if line.get("id") == detail.api_id]
        if len(matches) != 1:
            raise ValueError(f"Shopware-Originalpreis der Position {detail.api_id} fehlt.")
        return matches[0]

    def unit_price(self, detail) -> Decimal:
        if not getattr(detail.order, "shopware_price_snapshot", None):
            return detail.unit_price
        return self.decimal(self.line(detail)["price"]["unitPrice"])

    def shipping_price(self, order) -> Decimal:
        if not getattr(order, "shopware_price_snapshot", None):
            return order.shipping_costs or Decimal(0)
        shipping = order.shopware_price_snapshot.get("shipping") or {}
        return self.decimal(shipping.get("totalPrice", "0"))

    @staticmethod
    def unit_divisor(unit) -> Decimal:
        return Decimal(100) if str(unit or "").strip().startswith("%") else Decimal(1)

    def validate_position(self, detail, position) -> None:
        divisor = self.unit_divisor(position.get("unit"))
        effective = self.decimal(position.get("price")) / divisor
        if (position.get("erpNumber") != detail.erp_nr
                or self.decimal(position.get("quantity")) != detail.quantity
                or effective != self.unit_price(detail)):
            raise ValueError(
                f"Regel-Mapping verändert den Shopware-Bestellpreis, Artikel oder Menge von {detail.erp_nr}; "
                "Preis und Einheit müssen zusammen exakt dem Original entsprechen."
            )

    def expected_export(self, order, positions) -> dict:
        self.validate_snapshot(order)
        expected = []
        for detail in sorted(order.details.all(), key=lambda detail: detail.id):
            expected.append({"erpNumber": detail.erp_nr, "quantity": str(detail.quantity),
                             "unitPrice": str(self.unit_price(detail)),
                             "totalPrice": str(self.money(self.line(detail)["price"]["totalPrice"]))})
        # Match by article + quantity + price, independently of export sorting.
        shipping = self.shipping_price(order)
        if shipping > 0:
            article_positions = [p for p in positions if p.get("erpNumber")]
            shipping_position = article_positions[len(expected)]
            expected.append({"erpNumber": shipping_position["erpNumber"], "quantity": "1",
                             "unitPrice": str(shipping), "totalPrice": str(self.money(shipping))})
        price = order.shopware_price_snapshot["price"]
        return {"gross": self.is_gross(order), "currency": order.shopware_price_snapshot["currency"], "positions": expected,
                "netto": str(price.get("netPrice", price["totalPrice"])),
                "brutto": str(price["totalPrice"])}

    def verify_export(self, expected: dict, result: dict) -> dict:
        vorgang = (result or {}).get("vorgang") or {}
        if not vorgang or not vorgang.get("belegNr"):
            raise ValueError("Microtech-Vorgang konnte zur Preisprüfung nicht gelesen werden.")
        if vorgang.get("currency") != expected["currency"]:
            raise ValueError("Microtech-Währung stimmt nicht mit Shopware überein.")
        remaining = [p for p in vorgang.get("positions") or [] if p.get("erpNumber")]
        for source in expected["positions"]:
            candidates = [p for p in remaining if p.get("erpNumber") == source["erpNumber"]
                          and self.decimal(p.get("quantity")) == self.decimal(source["quantity"])]
            unit_key = "grossUnitPrice" if expected["gross"] else "unitPrice"
            total_key = "grossTotalPrice" if expected["gross"] else "totalPrice"
            matching = [p for p in candidates if p.get(unit_key) is not None and p.get(total_key) is not None
                        and self.unit_prices_match(p[unit_key], source["unitPrice"],
                                                   unit=p.get("unit"), quantity=source["quantity"],
                                                   total=p[total_key])
                        and self.totals_match(p[total_key], source["totalPrice"])]
            if not matching:
                raise ValueError(f"Microtech-Preisabweichung für {source['erpNumber']}: "
                                 f"Shopware {source['quantity']} × {source['unitPrice']} = {source['totalPrice']}; "
                                 f"Microtech: {[(p.get(unit_key), p.get(total_key), p.get('unit')) for p in candidates]}.")
            remaining.remove(matching[0])
        if any(p.get("totalPrice") is None or self.money(p["totalPrice"]) != 0 for p in remaining):
            raise ValueError("Microtech enthält zusätzliche preiswirksame Artikelpositionen.")
        for field in ("netto", "brutto"):
            if vorgang.get(field) is None or not self.totals_match(vorgang[field], expected[field]):
                raise ValueError(f"Microtech-{field} {vorgang.get(field)} weicht von Shopware {expected[field]} ab.")
        return {"belegNr": vorgang["belegNr"], "positions_checked": len(expected["positions"]),
                "netto": str(self.money(vorgang["netto"])), "brutto": str(self.money(vorgang["brutto"]))}
