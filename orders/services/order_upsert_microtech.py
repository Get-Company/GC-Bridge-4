from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from loguru import logger

from core.services import BaseService
from customer.services import CustomerUpsertMicrotechService
from microtech.models import MicrotechSettings
from microtech.services import (
    MicrotechArtikelService,
    MicrotechVorgangService,
    microtech_connection,
)
from orders.models import Order, OrderDetail
from orders.services.constants import (
    DEFAULT_ORDER_TYPE_NUMBER,
    DEFAULT_PAYMENT_TYPE_NUMBER,
    DEFAULT_SHIPPING_ERP_NR,
    DEFAULT_SHIPPING_TYPE_NUMBER,
    DEFAULT_UNIT,
)
from products.models import Product


@dataclass(slots=True)
class OrderUpsertResult:
    order: Order
    erp_order_id: str
    is_new: bool


@dataclass(frozen=True, slots=True)
class MicrotechOrderDefaults:
    order_type_number: int
    payment_type_number: int
    shipping_type_number: int


class OrderUpsertMicrotechService(BaseService):
    model = Order

    def upsert_order(self, order: Order) -> OrderUpsertResult:
        if not isinstance(order, Order):
            raise TypeError("order must be an instance of Order.")

        self._ensure_customer_synced(order)
        order_defaults = self._load_order_defaults()

        with microtech_connection() as erp:
            vorgang_service = MicrotechVorgangService(erp=erp)
            so_vorgang = vorgang_service.get_special_object("soVorgang")
            if so_vorgang is None:
                raise ValueError("SpecialObject 'soVorgang' konnte nicht geladen werden.")

            is_new, known_beleg_nr = self._open_or_create_vorgang(
                order=order,
                vorgang_service=vorgang_service,
                so_vorgang=so_vorgang,
                order_type_number=order_defaults.order_type_number,
            )

            self._set_header_fields(
                order=order,
                so_vorgang=so_vorgang,
                payment_type_number=order_defaults.payment_type_number,
                shipping_type_number=order_defaults.shipping_type_number,
            )
            self._add_positions(order=order, so_vorgang=so_vorgang, erp=erp)
            self._add_shipping_position(order=order, so_vorgang=so_vorgang)

            so_vorgang.Post()

            erp_order_id = (known_beleg_nr or "").strip()
            if is_new and not erp_order_id:
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

        self._persist_erp_order_id(order=order, erp_order_id=erp_order_id)

        return OrderUpsertResult(order=order, erp_order_id=erp_order_id, is_new=is_new)

    def _ensure_customer_synced(self, order: Order) -> None:
        customer = order.customer
        if not customer:
            raise ValueError("Order has no customer assigned.")

        logger.info("Syncing customer {} to Microtech before order upsert.", customer.pk)
        CustomerUpsertMicrotechService().upsert_customer(
            customer,
            shipping_address=order.shipping_address,
            billing_address=order.billing_address,
        )
        customer.refresh_from_db()

        if not customer.erp_nr:
            raise ValueError("Customer ERP number could not be determined after upsert.")

    def _open_or_create_vorgang(
        self,
        *,
        order: Order,
        vorgang_service: MicrotechVorgangService,
        so_vorgang,
        order_type_number: int,
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

        so_vorgang.Append(order_type_number, order.customer.erp_nr)
        new_beleg_nr = self._get_vorgang_field(so_vorgang=so_vorgang, field_name="BelegNr")
        if new_beleg_nr:
            self._persist_erp_order_id(order=order, erp_order_id=new_beleg_nr)
            logger.info(
                "Captured Microtech BelegNr {} directly after Append for order {}.",
                new_beleg_nr,
                order.order_number,
            )
        return True, new_beleg_nr

    def _find_existing_beleg_nr(
        self,
        *,
        order: Order,
        vorgang_service: MicrotechVorgangService,
    ) -> str:
        existing_id = (order.erp_order_id or "").strip()
        if existing_id:
            if vorgang_service.find(existing_id):
                return existing_id
            logger.warning(
                "Stored erp_order_id {} for order {} not found in Microtech. "
                "Creating a new Vorgang and replacing obsolete id.",
                existing_id,
                order.order_number,
            )
            self._clear_erp_order_id(order=order)
            return ""

        # Primary business key for fallback search should be order_number.
        # Keep api_id only as backward-compatible fallback for records created before this change.
        auftr_nr_candidates: list[str] = []
        order_number = (order.order_number or "").strip()
        api_id = (order.api_id or "").strip()
        if order_number:
            auftr_nr_candidates.append(order_number)
        if api_id and api_id not in auftr_nr_candidates:
            auftr_nr_candidates.append(api_id)

        customer_erp_nr = (order.customer.erp_nr or "").strip() if order.customer else ""

        for auftr_nr in auftr_nr_candidates:
            beleg_nr = self._find_beleg_nr_by_auftr_nr(
                vorgang_service=vorgang_service,
                auftr_nr=auftr_nr,
                customer_erp_nr=customer_erp_nr,
            )
            if beleg_nr:
                logger.info(
                    "Found existing Vorgang by AuftrNr for order {} (AuftrNr={}, BelegNr={}).",
                    order.order_number,
                    auftr_nr,
                    beleg_nr,
                )
                return beleg_nr

        return ""

    @staticmethod
    def _find_beleg_nr_by_auftr_nr(
        *,
        vorgang_service: MicrotechVorgangService,
        auftr_nr: str,
        customer_erp_nr: str,
    ) -> str:
        if not auftr_nr:
            return ""
        if not vorgang_service.set_filter({"AuftrNr": auftr_nr}):
            return ""

        try:
            dataset = vorgang_service.dataset
            if dataset.RecordCount < 1:
                return ""

            dataset.First()
            first_beleg_nr = ""
            while not dataset.Eof:
                beleg_nr = str(vorgang_service.get_field("BelegNr") or "").strip()
                adr_nr = str(vorgang_service.get_field("AdrNr") or "").strip()
                if beleg_nr and not first_beleg_nr:
                    first_beleg_nr = beleg_nr
                if beleg_nr and customer_erp_nr and adr_nr == customer_erp_nr:
                    return beleg_nr
                dataset.Next()
            return first_beleg_nr
        finally:
            vorgang_service.clear_filter()

    @staticmethod
    def _delete_all_positions(so_vorgang) -> None:
        positionen = so_vorgang.Positionen
        while positionen.DataSet.RecordCount > 0:
            positionen.DataSet.First()
            positionen.DataSet.Delete()

    def _set_header_fields(
        self,
        *,
        order: Order,
        so_vorgang,
        payment_type_number: int,
        shipping_type_number: int,
    ) -> None:
        auftr_nr = (order.order_number or "").strip() or (order.api_id or "").strip()
        self._set_vorgang_field(so_vorgang=so_vorgang, field_name="AuftrNr", value=auftr_nr)
        description = order.description or f"Shopware Bestellung {order.order_number}"
        self._set_vorgang_field(so_vorgang=so_vorgang, field_name="Bez", value=description)
        self._set_optional_vorgang_field(
            so_vorgang=so_vorgang,
            field_name="ZahlArt",
            value=payment_type_number,
        )
        self._set_optional_vorgang_field(
            so_vorgang=so_vorgang,
            field_name="VsdArt",
            value=shipping_type_number,
        )

    def _add_positions(self, *, order: Order, so_vorgang, erp) -> None:
        details: list[OrderDetail] = list(order.details.all())
        artikel_service = MicrotechArtikelService(erp=erp)
        article_name_cache: dict[str, str] = {}
        article_raw_unit_cache: dict[str, str] = {}
        product_unit_map = self._build_product_unit_map(details)

        for detail in details:
            erp_nr = (detail.erp_nr or "").strip()
            if not erp_nr:
                logger.warning(
                    "OrderDetail {} has no erp_nr, skipping position.",
                    detail.pk,
                )
                continue

            unit = self._resolve_position_unit(
                detail=detail,
                erp_nr=erp_nr,
                artikel_service=artikel_service,
                product_unit_map=product_unit_map,
                article_name_cache=article_name_cache,
                article_raw_unit_cache=article_raw_unit_cache,
            )
            quantity = detail.quantity or 1
            position_name = self._resolve_position_name(
                detail=detail,
                erp_nr=erp_nr,
                artikel_service=artikel_service,
                article_name_cache=article_name_cache,
            )

            so_vorgang.Positionen.Add(quantity, unit, erp_nr)
            if self._requires_microtech_base_price(unit):
                self._set_position_name(
                    so_vorgang=so_vorgang,
                    position_name=position_name,
                )
            else:
                self._set_position_price(
                    so_vorgang=so_vorgang,
                    price=detail.unit_price,
                    is_gross=order.customer.is_gross,
                    position_name=position_name,
                )

    @staticmethod
    def _build_product_unit_map(details: list[OrderDetail]) -> dict[str, str]:
        erp_nrs = {(detail.erp_nr or "").strip() for detail in details if (detail.erp_nr or "").strip()}
        if not erp_nrs:
            return {}
        rows = (
            Product.objects
            .filter(erp_nr__in=erp_nrs)
            .exclude(unit__isnull=True)
            .exclude(unit="")
            .values_list("erp_nr", "unit")
        )
        return {str(erp_nr).strip(): str(unit).strip() for erp_nr, unit in rows if erp_nr and unit}

    @staticmethod
    def _resolve_position_unit(
        *,
        detail: OrderDetail,
        erp_nr: str,
        artikel_service: MicrotechArtikelService,
        product_unit_map: dict[str, str],
        article_name_cache: dict[str, str],
        article_raw_unit_cache: dict[str, str],
    ) -> str:
        raw_unit = article_raw_unit_cache.get(erp_nr)
        if raw_unit is None:
            raw_unit = ""
            try:
                found = artikel_service.find(erp_nr, index_field="ArtNr") or artikel_service.find(erp_nr)
                if found:
                    raw_unit = str(artikel_service.get_unit(raw=True) or "").strip()
                    article_name_cache.setdefault(erp_nr, str(artikel_service.get_name() or "").strip())
            except Exception:
                logger.exception(
                    "Failed to load raw article unit (Einh) for erp_nr {} while building order positions.",
                    erp_nr,
                )
            article_raw_unit_cache[erp_nr] = raw_unit

        return raw_unit or product_unit_map.get(erp_nr) or (detail.unit or "").strip() or DEFAULT_UNIT

    @staticmethod
    def _requires_microtech_base_price(unit: str) -> bool:
        normalized = (unit or "").strip().replace(" ", "")
        return normalized.startswith("%")

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
    def _set_position_price(
        *,
        so_vorgang,
        price: Decimal,
        is_gross: bool,
        position_name: str = "",
    ) -> None:
        position_dataset = so_vorgang.Positionen.DataSet
        position_dataset.Edit()
        OrderUpsertMicrotechService._write_position_name(
            dataset=position_dataset,
            position_name=position_name,
        )

        epr = position_dataset.Fields("EPr").GetEditObject(2)
        if is_gross:
            epr.GesBrutto = float(price)
        else:
            epr.GesNetto = float(price)
        epr.Save()
        position_dataset.Post()

    @staticmethod
    def _set_position_name(
        *,
        so_vorgang,
        position_name: str,
    ) -> None:
        if not position_name:
            return
        position_dataset = so_vorgang.Positionen.DataSet
        position_dataset.Edit()
        OrderUpsertMicrotechService._write_position_name(
            dataset=position_dataset,
            position_name=position_name,
        )
        position_dataset.Post()

    @staticmethod
    def _write_position_name(*, dataset, position_name: str) -> None:
        if not position_name:
            return
        name_written = (
            OrderUpsertMicrotechService._set_position_field(
                dataset=dataset,
                field_name="Bez",
                value=position_name,
            )
            or OrderUpsertMicrotechService._set_position_field(
                dataset=dataset,
                field_name="KuBez",
                value=position_name,
            )
        )
        if not name_written:
            logger.debug("Position name could not be written (fields Bez/KuBez unavailable).")

    @staticmethod
    def _set_position_field(*, dataset, field_name: str, value: str) -> bool:
        try:
            field = dataset.Fields.Item(field_name)
        except Exception:
            return False

        for attr in ("AsString", "Text"):
            try:
                setattr(field, attr, str(value))
                return True
            except Exception:
                continue
        return False

    @staticmethod
    def _resolve_position_name(
        *,
        detail: OrderDetail,
        erp_nr: str,
        artikel_service: MicrotechArtikelService,
        article_name_cache: dict[str, str],
    ) -> str:
        detail_name = (detail.name or "").strip()
        if detail_name:
            return detail_name

        cached_name = article_name_cache.get(erp_nr)
        if cached_name is not None:
            return cached_name

        article_name = ""
        try:
            found = artikel_service.find(erp_nr, index_field="ArtNr") or artikel_service.find(erp_nr)
            if found:
                article_name = str(artikel_service.get_name() or "").strip()
        except Exception:
            logger.exception(
                "Failed to load article name (KuBez5) for erp_nr {} while building order positions.",
                erp_nr,
            )

        article_name_cache[erp_nr] = article_name
        return article_name

    @staticmethod
    def _set_vorgang_field(*, so_vorgang, field_name: str, value: str | int) -> None:
        if value is None:
            return
        field = so_vorgang.DataSet.Fields.Item(field_name)
        field_type = getattr(field, "FieldType", "")
        if field_type in {"Integer", "Byte", "AutoInc", "Boolean"}:
            field.AsInteger = int(value)
            return
        if field_type in {"Float", "Double"}:
            field.AsFloat = float(value)
            return
        if field_type in {"Blob", "Info"}:
            field.Text = str(value)
            return
        field.AsString = str(value)

    @staticmethod
    def _set_optional_vorgang_field(*, so_vorgang, field_name: str, value: str | int) -> None:
        try:
            OrderUpsertMicrotechService._set_vorgang_field(
                so_vorgang=so_vorgang,
                field_name=field_name,
                value=value,
            )
        except Exception:
            logger.warning(
                "Konnte optionales Feld '{}' nicht setzen (Wert='{}').",
                field_name,
                value,
            )

    @staticmethod
    def _get_vorgang_field(*, so_vorgang, field_name: str) -> str:
        try:
            field = so_vorgang.DataSet.Fields.Item(field_name)
            return str(field.AsString or "")
        except Exception:
            logger.exception("Konnte Feld '{}' aus soVorgang nicht lesen.", field_name)
            return ""

    @staticmethod
    def _persist_erp_order_id(*, order: Order, erp_order_id: str) -> None:
        erp_order_id = (erp_order_id or "").strip()
        if not erp_order_id or order.erp_order_id == erp_order_id:
            return
        order.erp_order_id = erp_order_id
        order.save(update_fields=["erp_order_id", "updated_at"])

    @staticmethod
    def _clear_erp_order_id(*, order: Order) -> None:
        if not order.erp_order_id:
            return
        order.erp_order_id = ""
        order.save(update_fields=["erp_order_id", "updated_at"])

    @staticmethod
    def _load_order_defaults() -> MicrotechOrderDefaults:
        fallback = MicrotechOrderDefaults(
            order_type_number=DEFAULT_ORDER_TYPE_NUMBER,
            payment_type_number=DEFAULT_PAYMENT_TYPE_NUMBER,
            shipping_type_number=DEFAULT_SHIPPING_TYPE_NUMBER,
        )
        try:
            cfg = MicrotechSettings.load()
        except Exception:
            logger.exception("Konnte MicrotechSettings nicht laden. Nutze Fallback-Standardwerte.")
            return fallback

        return MicrotechOrderDefaults(
            order_type_number=OrderUpsertMicrotechService._coerce_positive_int(
                getattr(cfg, "default_vorgangsart_id", None),
                fallback.order_type_number,
            ),
            payment_type_number=OrderUpsertMicrotechService._coerce_positive_int(
                getattr(cfg, "default_zahlungsart_id", None),
                fallback.payment_type_number,
            ),
            shipping_type_number=OrderUpsertMicrotechService._coerce_positive_int(
                getattr(cfg, "default_versandart_id", None),
                fallback.shipping_type_number,
            ),
        )

    @staticmethod
    def _coerce_positive_int(value: object, default: int) -> int:
        try:
            parsed = int(str(value).strip())
        except (TypeError, ValueError):
            return default
        if parsed <= 0:
            return default
        return parsed


__all__ = ["OrderUpsertMicrotechService", "OrderUpsertResult"]
