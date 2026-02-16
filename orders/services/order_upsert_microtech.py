from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from loguru import logger

from core.services import BaseService
from customer.services import CustomerUpsertMicrotechService
from microtech.services import MicrotechVorgangService, microtech_connection
from orders.models import Order, OrderDetail
from orders.services.constants import (
    DEFAULT_ORDER_TYPE_NUMBER,
    DEFAULT_SHIPPING_ERP_NR,
    DEFAULT_UNIT,
)


@dataclass(slots=True)
class OrderUpsertResult:
    order: Order
    erp_order_id: str
    is_new: bool


class OrderUpsertMicrotechService(BaseService):
    model = Order

    def upsert_order(self, order: Order) -> OrderUpsertResult:
        if not isinstance(order, Order):
            raise TypeError("order must be an instance of Order.")

        self._ensure_customer_synced(order)

        with microtech_connection() as erp:
            vorgang_service = MicrotechVorgangService(erp=erp)
            so_vorgang = vorgang_service.get_special_object("soVorgang")
            if so_vorgang is None:
                raise ValueError("SpecialObject 'soVorgang' konnte nicht geladen werden.")

            is_new, known_beleg_nr = self._open_or_create_vorgang(
                order=order,
                vorgang_service=vorgang_service,
                so_vorgang=so_vorgang,
            )

            self._set_header_fields(order=order, so_vorgang=so_vorgang)
            self._add_positions(order=order, so_vorgang=so_vorgang)
            self._add_shipping_position(order=order, so_vorgang=so_vorgang)

            so_vorgang.Post()

            erp_order_id = self._get_vorgang_field(so_vorgang=so_vorgang, field_name="BelegNr")
            if not erp_order_id:
                erp_order_id = known_beleg_nr or self._find_existing_beleg_nr(
                    order=order,
                    vorgang_service=vorgang_service,
                )
            logger.info(
                "Order {} posted as Vorgang BelegNr={} (new={}).",
                order.order_number,
                erp_order_id,
                is_new,
            )

        if order.erp_order_id != erp_order_id:
            order.erp_order_id = erp_order_id
            order.save(update_fields=["erp_order_id", "updated_at"])

        return OrderUpsertResult(order=order, erp_order_id=erp_order_id, is_new=is_new)

    def _ensure_customer_synced(self, order: Order) -> None:
        customer = order.customer
        if not customer:
            raise ValueError("Order has no customer assigned.")

        logger.info("Syncing customer {} to Microtech before order upsert.", customer.pk)
        CustomerUpsertMicrotechService().upsert_customer(customer)
        customer.refresh_from_db()

        if not customer.erp_nr:
            raise ValueError("Customer ERP number could not be determined after upsert.")

    def _open_or_create_vorgang(
        self,
        *,
        order: Order,
        vorgang_service: MicrotechVorgangService,
        so_vorgang,
    ) -> tuple[bool, str]:
        existing_beleg_nr = self._find_existing_beleg_nr(order=order, vorgang_service=vorgang_service)
        if existing_beleg_nr:
            so_vorgang.Edit(existing_beleg_nr)
            self._delete_all_positions(so_vorgang)
            logger.info(
                "Reusing existing Vorgang for order {} (BelegNr={}).",
                order.order_number,
                existing_beleg_nr,
            )
            return False, existing_beleg_nr

        so_vorgang.Append(DEFAULT_ORDER_TYPE_NUMBER, order.customer.erp_nr)
        return True, ""

    def _find_existing_beleg_nr(
        self,
        *,
        order: Order,
        vorgang_service: MicrotechVorgangService,
    ) -> str:
        existing_id = (order.erp_order_id or "").strip()
        if existing_id and vorgang_service.find(existing_id):
            return existing_id

        auftr_nr = (order.api_id or "").strip()
        if not auftr_nr:
            return ""

        if not vorgang_service.set_filter({"AuftrNr": auftr_nr}):
            return ""

        try:
            if vorgang_service.dataset.RecordCount < 1:
                return ""
            vorgang_service.dataset.First()
            beleg_nr = str(vorgang_service.get_field("BelegNr") or "").strip()
            if beleg_nr:
                logger.info(
                    "Found existing Vorgang by AuftrNr for order {} (AuftrNr={}, BelegNr={}).",
                    order.order_number,
                    auftr_nr,
                    beleg_nr,
                )
            return beleg_nr
        finally:
            vorgang_service.clear_filter()

    @staticmethod
    def _delete_all_positions(so_vorgang) -> None:
        positionen = so_vorgang.Positionen
        while positionen.DataSet.RecordCount > 0:
            positionen.DataSet.First()
            positionen.DataSet.Delete()

    def _set_header_fields(self, *, order: Order, so_vorgang) -> None:
        self._set_vorgang_field(so_vorgang=so_vorgang, field_name="AuftrNr", value=order.api_id)
        description = order.description or f"Shopware Bestellung {order.order_number}"
        self._set_vorgang_field(so_vorgang=so_vorgang, field_name="Bez", value=description)

    def _add_positions(self, *, order: Order, so_vorgang) -> None:
        details: list[OrderDetail] = list(order.details.all())

        for detail in details:
            erp_nr = (detail.erp_nr or "").strip()
            if not erp_nr:
                logger.warning(
                    "OrderDetail {} has no erp_nr, skipping position.",
                    detail.pk,
                )
                continue

            unit = detail.unit or DEFAULT_UNIT
            quantity = detail.quantity or 1

            so_vorgang.Positionen.Add(quantity, unit, erp_nr)
            self._set_position_price(
                so_vorgang=so_vorgang,
                price=detail.unit_price,
                is_gross=order.customer.is_gross,
            )

    def _add_shipping_position(self, *, order: Order, so_vorgang) -> None:
        if not order.shipping_costs or order.shipping_costs <= Decimal("0"):
            return

        so_vorgang.Positionen.Add(1, DEFAULT_UNIT, DEFAULT_SHIPPING_ERP_NR)
        self._set_position_price(
            so_vorgang=so_vorgang,
            price=order.shipping_costs,
            is_gross=order.customer.is_gross,
        )

    @staticmethod
    def _set_position_price(*, so_vorgang, price: Decimal, is_gross: bool) -> None:
        so_vorgang.Positionen.DataSet.Edit()
        epr = so_vorgang.Positionen.DataSet.Fields("EPr").GetEditObject(2)
        if is_gross:
            epr.GesBrutto = float(price)
        else:
            epr.GesNetto = float(price)
        epr.Save()
        so_vorgang.Positionen.DataSet.Post()

    @staticmethod
    def _set_vorgang_field(*, so_vorgang, field_name: str, value: str) -> None:
        if value is None:
            return
        field = so_vorgang.DataSet.Fields.Item(field_name)
        field.AsString = str(value)

    @staticmethod
    def _get_vorgang_field(*, so_vorgang, field_name: str) -> str:
        try:
            field = so_vorgang.DataSet.Fields.Item(field_name)
            return str(field.AsString or "")
        except Exception:
            logger.exception("Konnte Feld '{}' aus soVorgang nicht lesen.", field_name)
            return ""


__all__ = ["OrderUpsertMicrotechService", "OrderUpsertResult"]
