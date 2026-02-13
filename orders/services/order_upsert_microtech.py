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

            is_new = self._open_or_create_vorgang(
                order=order,
                vorgang_service=vorgang_service,
                so_vorgang=so_vorgang,
            )

            self._set_header_fields(order=order, vorgang_service=vorgang_service)
            self._add_positions(order=order, vorgang_service=vorgang_service)
            self._add_shipping_position(order=order, vorgang_service=vorgang_service)

            vorgang_service.post()

            erp_order_id = str(vorgang_service.get_field("BelegNr") or "")
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
    ) -> bool:
        existing_id = (order.erp_order_id or "").strip()

        if existing_id and vorgang_service.find(existing_id):
            vorgang_service.edit()
            self._delete_all_positions(so_vorgang)
            return False

        so_vorgang.Append(DEFAULT_ORDER_TYPE_NUMBER, order.customer.erp_nr)
        return True

    @staticmethod
    def _delete_all_positions(so_vorgang) -> None:
        positionen = so_vorgang.Positionen
        while positionen.DataSet.RecordCount > 0:
            positionen.DataSet.First()
            positionen.Delete()

    def _set_header_fields(self, *, order: Order, vorgang_service: MicrotechVorgangService) -> None:
        vorgang_service.set_field("AuftrNr", order.api_id)
        description = order.description or f"Shopware Bestellung {order.order_number}"
        vorgang_service.set_field("Bez", description)

    def _add_positions(self, *, order: Order, vorgang_service: MicrotechVorgangService) -> None:
        so_vorgang = vorgang_service.get_special_object("soVorgang")
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

    def _add_shipping_position(self, *, order: Order, vorgang_service: MicrotechVorgangService) -> None:
        if not order.shipping_costs or order.shipping_costs <= Decimal("0"):
            return

        so_vorgang = vorgang_service.get_special_object("soVorgang")
        so_vorgang.Positionen.Add(1, DEFAULT_UNIT, DEFAULT_SHIPPING_ERP_NR)
        self._set_position_price(
            so_vorgang=so_vorgang,
            price=order.shipping_costs,
            is_gross=order.customer.is_gross,
        )

    @staticmethod
    def _set_position_price(*, so_vorgang, price: Decimal, is_gross: bool) -> None:
        epr = so_vorgang.Positionen.EPr.GetEditObject(2)
        if is_gross:
            epr.GesBrutto = float(price)
        else:
            epr.GesNetto = float(price)
        epr.Save()


__all__ = ["OrderUpsertMicrotechService", "OrderUpsertResult"]
