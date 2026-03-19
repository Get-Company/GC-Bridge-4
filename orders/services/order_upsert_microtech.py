from __future__ import annotations

from dataclasses import dataclass, replace
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from loguru import logger

from core.services import BaseService
from customer.services import CustomerUpsertMicrotechService
from microtech.models import MicrotechOrderRuleAction, MicrotechSettings
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
from orders.services.order_rule_resolver import (
    OrderRuleResolverService,
    ResolvedDatasetAction,
    ResolvedOrderRule,
)
from products.models import Product


@dataclass(slots=True)
class OrderUpsertResult:
    order: Order
    erp_order_id: str
    is_new: bool
    rule_debug: "OrderRuleDebugInfo"


@dataclass(frozen=True, slots=True)
class OrderRuleDebugInfo:
    rule_id: int | None
    rule_name: str
    payment_position_requested: bool
    payment_position_added: bool
    payment_position_reason: str
    payment_position_erp_nr: str
    payment_position_amount: Decimal | None = None
    dataset_actions_total: int = 0
    dataset_actions_applied: int = 0
    dataset_set_field_requested: int = 0
    dataset_set_field_applied: int = 0
    dataset_create_position_requested: int = 0
    dataset_create_position_applied: int = 0
    dataset_created_position_erp_nrs: tuple[str, ...] = ()
    dataset_actions_note: str = ""


@dataclass(frozen=True, slots=True)
class DatasetActionDebugInfo:
    total: int = 0
    applied: int = 0
    set_field_requested: int = 0
    set_field_applied: int = 0
    create_position_requested: int = 0
    create_position_applied: int = 0
    created_position_erp_nrs: tuple[str, ...] = ()
    note: str = ""


@dataclass(frozen=True, slots=True)
class MicrotechOrderDefaults:
    order_type_number: int
    payment_type_number: int
    shipping_type_number: int


class OrderUpsertMicrotechService(BaseService):
    model = Order

    _SWISS_COUNTRY_CODES = {"CH", "CHE", "SCHWEIZ", "SWITZERLAND", "SUISSE", "SVIZZERA"}
    _INTEGER_FIELD_TYPES = frozenset({"Integer", "Byte", "AutoInc", "Boolean", "SmallInt"})
    _FLOAT_FIELD_TYPES = frozenset({"Float", "Double", "Currency"})
    _TEXT_FIELD_TYPES = frozenset({"Blob", "Info", "Memo"})
    _STRING_FIELD_TYPES = frozenset({"WideString", "String", "UnicodeString", "Date", "DateTime"})

    def refresh_erp_order_id(self, order: Order, *, erp: Any | None = None) -> str:
        if not isinstance(order, Order):
            raise TypeError("order must be an instance of Order.")

        if erp is None:
            with microtech_connection() as erp_connection:
                return self.refresh_erp_order_id(order, erp=erp_connection)

        vorgang_service = MicrotechVorgangService(erp=erp)
        beleg_nr = self._find_existing_beleg_nr(order=order, vorgang_service=vorgang_service)
        if beleg_nr:
            self._persist_erp_order_id(order=order, erp_order_id=beleg_nr)
            return beleg_nr

        self._clear_erp_order_id(order=order)
        return ""

    def upsert_order(self, order: Order, *, erp: Any | None = None) -> OrderUpsertResult:
        if not isinstance(order, Order):
            raise TypeError("order must be an instance of Order.")

        if erp is None:
            with microtech_connection() as erp_connection:
                return self.upsert_order(order, erp=erp_connection)

        resolved_rule = OrderRuleResolverService().resolve_for_order(order=order)
        self._ensure_customer_synced(
            order,
            na1_mode=resolved_rule.na1_mode,
            na1_static_value=resolved_rule.na1_static_value,
            erp=erp,
        )
        order_defaults = self._load_order_defaults()
        order_type_number = self._coerce_positive_int(
            resolved_rule.vorgangsart_id,
            order_defaults.order_type_number,
        )
        payment_type_number = self._coerce_positive_int(
            resolved_rule.zahlungsart_id,
            order_defaults.payment_type_number,
        )
        shipping_type_number = self._coerce_positive_int(
            resolved_rule.versandart_id,
            order_defaults.shipping_type_number,
        )

        vorgang_service = MicrotechVorgangService(erp=erp)
        so_vorgang = vorgang_service.get_special_object("soVorgang")
        if so_vorgang is None:
            raise ValueError("SpecialObject 'soVorgang' konnte nicht geladen werden.")

        is_new, known_beleg_nr = self._open_or_create_vorgang(
            order=order,
            vorgang_service=vorgang_service,
            so_vorgang=so_vorgang,
            order_type_number=order_type_number,
        )

        self._set_header_fields(
            order=order,
            so_vorgang=so_vorgang,
            payment_type_number=payment_type_number,
            shipping_type_number=shipping_type_number,
            payment_terms_text=resolved_rule.zahlungsbedingung,
        )
        self._add_positions(order=order, so_vorgang=so_vorgang, erp=erp)
        self._add_shipping_position(order=order, so_vorgang=so_vorgang)
        dataset_debug = self._apply_rule_dataset_actions(
            order=order,
            so_vorgang=so_vorgang,
            resolved_rule=resolved_rule,
        )
        payment_debug = self._add_payment_position(
            order=order,
            so_vorgang=so_vorgang,
            resolved_rule=resolved_rule,
        )
        rule_debug = replace(
            payment_debug,
            dataset_actions_total=dataset_debug.total,
            dataset_actions_applied=dataset_debug.applied,
            dataset_set_field_requested=dataset_debug.set_field_requested,
            dataset_set_field_applied=dataset_debug.set_field_applied,
            dataset_create_position_requested=dataset_debug.create_position_requested,
            dataset_create_position_applied=dataset_debug.create_position_applied,
            dataset_created_position_erp_nrs=dataset_debug.created_position_erp_nrs,
            dataset_actions_note=dataset_debug.note,
        )
        logger.info(
            "Order {} rule debug: rule_id={}, rule_name='{}', dataset_actions_total={}, "
            "dataset_actions_applied={}, create_position_requested={}, create_position_applied={}, "
            "created_position_erp_nrs='{}', payment_position_requested={}, payment_position_added={}, "
            "payment_position_erp_nr='{}', payment_position_amount='{}', reason='{}'.",
            order.order_number,
            rule_debug.rule_id,
            rule_debug.rule_name,
            rule_debug.dataset_actions_total,
            rule_debug.dataset_actions_applied,
            rule_debug.dataset_create_position_requested,
            rule_debug.dataset_create_position_applied,
            ",".join(rule_debug.dataset_created_position_erp_nrs),
            rule_debug.payment_position_requested,
            rule_debug.payment_position_added,
            rule_debug.payment_position_erp_nr,
            rule_debug.payment_position_amount,
            rule_debug.payment_position_reason,
        )

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

        return OrderUpsertResult(
            order=order,
            erp_order_id=erp_order_id,
            is_new=is_new,
            rule_debug=rule_debug,
        )

    def _ensure_customer_synced(
        self,
        order: Order,
        *,
        na1_mode: str = "auto",
        na1_static_value: str = "",
        erp: Any | None = None,
    ) -> None:
        customer = order.customer
        if not customer:
            raise ValueError("Order has no customer assigned.")

        logger.info("Syncing customer {} to Microtech before order upsert.", customer.pk)
        upsert_result = CustomerUpsertMicrotechService().upsert_customer(
            customer,
            shipping_address=order.shipping_address,
            billing_address=order.billing_address,
            na1_mode=na1_mode,
            na1_static_value=na1_static_value,
            erp=erp,
        )
        logger.info(
            "Customer {} sync finished before order {}: erp_nr={}, shipping_ans_nr={}, billing_ans_nr={}, "
            "is_new_customer={}, shopware_updated={}.",
            customer.pk,
            order.order_number,
            upsert_result.erp_nr,
            upsert_result.shipping_ans_nr,
            upsert_result.billing_ans_nr,
            upsert_result.is_new_customer,
            upsert_result.shopware_updated,
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
        payment_terms_text: str = "",
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
        if (payment_terms_text or "").strip():
            self._set_optional_vorgang_field(
                so_vorgang=so_vorgang,
                field_name="ZahlBed",
                value=payment_terms_text,
            )

    def _add_positions(self, *, order: Order, so_vorgang, erp) -> None:
        details: list[OrderDetail] = list(order.details.all())
        artikel_service = MicrotechArtikelService(erp=erp)
        article_name_cache: dict[str, str] = {}
        article_raw_unit_cache: dict[str, str] = {}
        product_unit_map = self._build_product_unit_map(details)
        product_export_text_map = self._build_product_export_text_map(details)
        append_customs_metadata = self._has_swiss_billing_address(order)

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
                product_export_text_map=product_export_text_map,
                append_customs_metadata=append_customs_metadata,
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

    @classmethod
    def _build_product_export_text_map(cls, details: list[OrderDetail]) -> dict[str, str]:
        erp_nrs = {(detail.erp_nr or "").strip() for detail in details if (detail.erp_nr or "").strip()}
        if not erp_nrs:
            return {}

        rows = (
            Product.objects
            .filter(erp_nr__in=erp_nrs)
            .values_list("erp_nr", "customs_tariff_number", "weight_gross", "weight_net")
        )
        result: dict[str, str] = {}
        for erp_nr, customs_tariff_number, weight_gross, weight_net in rows:
            if not erp_nr:
                continue
            export_text = cls._build_export_metadata_text(
                customs_tariff_number=customs_tariff_number,
                weight_gross=weight_gross,
                weight_net=weight_net,
            )
            if export_text:
                result[str(erp_nr).strip()] = export_text
        return result

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

    @classmethod
    def _has_swiss_billing_address(cls, order: Order) -> bool:
        billing_address = getattr(order, "billing_address", None)
        country_code = str(getattr(billing_address, "country_code", "") or "").strip().upper()
        return country_code in cls._SWISS_COUNTRY_CODES

    def _add_shipping_position(self, *, order: Order, so_vorgang) -> None:
        if not order.shipping_costs or order.shipping_costs <= Decimal("0"):
            return

        so_vorgang.Positionen.Add(1, DEFAULT_UNIT, DEFAULT_SHIPPING_ERP_NR)
        self._set_position_price(
            so_vorgang=so_vorgang,
            price=order.shipping_costs,
            is_gross=order.customer.is_gross,
        )

    def _apply_rule_dataset_actions(
        self,
        *,
        order: Order,
        so_vorgang,
        resolved_rule: ResolvedOrderRule,
    ) -> DatasetActionDebugInfo:
        if not resolved_rule.dataset_actions:
            return DatasetActionDebugInfo(note="Keine Dataset-Aktionen in der Regel vorhanden.")

        created_extra_position = False
        total = 0
        applied = 0
        set_field_requested = 0
        set_field_applied = 0
        create_position_requested = 0
        create_position_applied = 0
        created_erp_nrs: list[str] = []
        seen_created_erp_nrs: set[str] = set()
        notes: list[str] = []

        for action in resolved_rule.dataset_actions:
            total += 1
            if action.action_type == MicrotechOrderRuleAction.ActionType.CREATE_EXTRA_POSITION:
                create_position_requested += 1
                erp_nr = (action.target_value or "").strip()
                if not erp_nr:
                    notes.append("create_extra_position skipped: empty ERP-Nr")
                    continue
                if erp_nr in seen_created_erp_nrs:
                    notes.append(f"duplicate create_extra_position skipped: {erp_nr}")
                    continue
                seen_created_erp_nrs.add(erp_nr)
                so_vorgang.Positionen.Add(1, DEFAULT_UNIT, erp_nr)
                created_extra_position = True
                create_position_applied += 1
                applied += 1
                created_erp_nrs.append(erp_nr)
                logger.info(
                    "Order {}: created extra position with ERP-Nr '{}'.",
                    order.order_number,
                    erp_nr,
                )
                continue

            if action.action_type != MicrotechOrderRuleAction.ActionType.SET_FIELD:
                notes.append(f"unknown action_type={action.action_type}")
                logger.warning(
                    "Order {}: unknown dataset action_type '{}', skipping.",
                    order.order_number,
                    action.action_type,
                )
                continue

            set_field_requested += 1
            if self._is_vorgang_dataset_action(action):
                written = self._set_dataset_field(
                    dataset=so_vorgang.DataSet,
                    field_name=action.dataset_field_name,
                    value=action.target_value,
                    field_type_hint=action.dataset_field_type,
                )
                if not written:
                    notes.append(f"set_field failed: Vorgang.{action.dataset_field_name}")
                    logger.warning(
                        "Order {}: failed to set Vorgang field '{}' to '{}'.",
                        order.order_number,
                        action.dataset_field_name,
                        action.target_value,
                    )
                else:
                    set_field_applied += 1
                    applied += 1
                continue

            if self._is_vorgang_position_dataset_action(action):
                if not created_extra_position:
                    notes.append("VorgangPosition set_field skipped: no extra position created")
                    logger.warning(
                        "Order {}: action on VorgangPosition skipped because no extra position was created.",
                        order.order_number,
                    )
                    continue
                position_dataset = so_vorgang.Positionen.DataSet
                position_dataset.Edit()
                written = self._set_dataset_field(
                    dataset=position_dataset,
                    field_name=action.dataset_field_name,
                    value=action.target_value,
                    field_type_hint=action.dataset_field_type,
                )
                if written:
                    position_dataset.Post()
                    set_field_applied += 1
                    applied += 1
                else:
                    notes.append(f"set_field failed: VorgangPosition.{action.dataset_field_name}")
                    logger.warning(
                        "Order {}: failed to set VorgangPosition field '{}' to '{}'.",
                        order.order_number,
                        action.dataset_field_name,
                        action.target_value,
                    )
                continue

            notes.append(
                f"unsupported dataset: {action.dataset_source_identifier or action.dataset_name}"
            )
            logger.warning(
                "Order {}: dataset action for unsupported dataset '{}' ignored.",
                order.order_number,
                action.dataset_source_identifier or action.dataset_name,
            )

        note = "; ".join(notes[:3]).strip()
        return DatasetActionDebugInfo(
            total=total,
            applied=applied,
            set_field_requested=set_field_requested,
            set_field_applied=set_field_applied,
            create_position_requested=create_position_requested,
            create_position_applied=create_position_applied,
            created_position_erp_nrs=tuple(created_erp_nrs),
            note=note,
        )

    @staticmethod
    def _is_vorgang_dataset_action(action: ResolvedDatasetAction) -> bool:
        source = (action.dataset_source_identifier or "").strip().lower()
        name = (action.dataset_name or "").strip().lower()
        return source == "vorgang - vorgange" or name == "vorgang"

    @staticmethod
    def _is_vorgang_position_dataset_action(action: ResolvedDatasetAction) -> bool:
        source = (action.dataset_source_identifier or "").strip().lower()
        name = (action.dataset_name or "").strip().lower()
        return source == "vorgangposition - vorgangspositionen" or name == "vorgangposition"

    def _add_payment_position(
        self,
        *,
        order: Order,
        so_vorgang,
        resolved_rule: ResolvedOrderRule,
    ) -> OrderRuleDebugInfo:
        rule_id = resolved_rule.rule_id
        rule_name = (resolved_rule.rule_name or "").strip()

        if not resolved_rule.add_payment_position:
            reason = "Regel fordert keine Zahlungs-Zusatzposition an."
            logger.info("Order {}: {}", order.order_number, reason)
            return OrderRuleDebugInfo(
                rule_id=rule_id,
                rule_name=rule_name,
                payment_position_requested=False,
                payment_position_added=False,
                payment_position_reason=reason,
                payment_position_erp_nr=(resolved_rule.payment_position_erp_nr or "").strip(),
            )

        erp_nr = (resolved_rule.payment_position_erp_nr or "").strip()
        if not erp_nr:
            reason = "Zahlungs-Zusatzposition aktiviert, aber ERP-Nr ist leer."
            logger.warning(
                "Rule {} requests payment surcharge position, but payment_position_erp_nr is empty. "
                "Order {} will not receive this position.",
                resolved_rule.rule_name or resolved_rule.rule_id,
                order.order_number,
            )
            return OrderRuleDebugInfo(
                rule_id=rule_id,
                rule_name=rule_name,
                payment_position_requested=True,
                payment_position_added=False,
                payment_position_reason=reason,
                payment_position_erp_nr="",
            )

        amount = self._resolve_payment_position_amount(order=order, resolved_rule=resolved_rule)
        if amount is None:
            so_vorgang.Positionen.Add(1, DEFAULT_UNIT, erp_nr)
            reason = (
                f"Zahlungs-Zusatzposition '{erp_nr}' wurde angelegt "
                "ohne Preisanpassung (Microtech-Standardpreis)."
            )
            logger.info("Order {}: {}", order.order_number, reason)
            return OrderRuleDebugInfo(
                rule_id=rule_id,
                rule_name=rule_name,
                payment_position_requested=True,
                payment_position_added=True,
                payment_position_reason=reason,
                payment_position_erp_nr=erp_nr,
                payment_position_amount=None,
            )

        so_vorgang.Positionen.Add(1, DEFAULT_UNIT, erp_nr)
        self._set_position_price(
            so_vorgang=so_vorgang,
            price=amount,
            is_gross=order.customer.is_gross,
            position_name=(resolved_rule.payment_position_name or "").strip(),
        )
        reason = f"Zahlungs-Zusatzposition '{erp_nr}' wurde mit Betrag {amount} angelegt."
        logger.info("Order {}: {}", order.order_number, reason)
        return OrderRuleDebugInfo(
            rule_id=rule_id,
            rule_name=rule_name,
            payment_position_requested=True,
            payment_position_added=True,
            payment_position_reason=reason,
            payment_position_erp_nr=erp_nr,
            payment_position_amount=amount,
        )

    @staticmethod
    def _resolve_payment_position_amount(
        *,
        order: Order,
        resolved_rule: ResolvedOrderRule,
    ) -> Decimal | None:
        value = resolved_rule.payment_position_value
        if value is None:
            return None

        if resolved_rule.payment_position_mode == "percent_total":
            base_total = order.total_price or Decimal("0.00")
            amount = (base_total * value) / Decimal("100")
        else:
            amount = value

        return amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

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
    def _resolve_dataset_write_kind(*, live_field_type: object, field_type_hint: str = "") -> str:
        for raw_type in (live_field_type, field_type_hint):
            field_type = str(raw_type or "").strip()
            if not field_type:
                continue
            if field_type in OrderUpsertMicrotechService._INTEGER_FIELD_TYPES:
                return "integer"
            if field_type in OrderUpsertMicrotechService._FLOAT_FIELD_TYPES:
                return "float"
            if field_type in OrderUpsertMicrotechService._TEXT_FIELD_TYPES:
                return "text"
            if field_type in OrderUpsertMicrotechService._STRING_FIELD_TYPES:
                return "string"
        return "string"

    @staticmethod
    def _set_dataset_field(*, dataset, field_name: str, value: object, field_type_hint: str = "") -> bool:
        try:
            field = dataset.Fields.Item(field_name)
        except Exception:
            return False

        write_kind = OrderUpsertMicrotechService._resolve_dataset_write_kind(
            live_field_type=getattr(field, "FieldType", ""),
            field_type_hint=field_type_hint,
        )
        text_value = str(value)

        try:
            if write_kind == "integer":
                normalized = text_value.strip().lower()
                if normalized in {"1", "true", "yes", "on", "ja"}:
                    field.AsInteger = 1
                    return True
                if normalized in {"0", "false", "no", "off", "nein"}:
                    field.AsInteger = 0
                    return True
                field.AsInteger = int(text_value)
                return True

            if write_kind == "float":
                field.AsFloat = float(text_value.replace(",", "."))
                return True

            if write_kind == "text":
                field.Text = text_value
                return True

            field.AsString = text_value
            return True
        except Exception:
            return False

    @staticmethod
    def _resolve_position_name(
        *,
        detail: OrderDetail,
        erp_nr: str,
        artikel_service: MicrotechArtikelService,
        article_name_cache: dict[str, str],
        product_export_text_map: dict[str, str],
        append_customs_metadata: bool,
    ) -> str:
        detail_name = (detail.name or "").strip()
        if detail_name:
            return OrderUpsertMicrotechService._append_export_metadata_to_position_name(
                detail_name,
                product_export_text_map.get(erp_nr, ""),
                append_customs_metadata=append_customs_metadata,
            )

        cached_name = article_name_cache.get(erp_nr)
        if cached_name is not None:
            return OrderUpsertMicrotechService._append_export_metadata_to_position_name(
                cached_name,
                product_export_text_map.get(erp_nr, ""),
                append_customs_metadata=append_customs_metadata,
            )

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
        return OrderUpsertMicrotechService._append_export_metadata_to_position_name(
            article_name,
            product_export_text_map.get(erp_nr, ""),
            append_customs_metadata=append_customs_metadata,
        )

    @staticmethod
    def _append_export_metadata_to_position_name(
        position_name: str,
        export_metadata_text: str,
        *,
        append_customs_metadata: bool,
    ) -> str:
        base_name = (position_name or "").strip()
        metadata = (export_metadata_text or "").strip()
        if not append_customs_metadata or not metadata:
            return base_name
        if not base_name:
            return metadata
        return f"{base_name}\n{metadata}"

    @classmethod
    def _build_export_metadata_text(
        cls,
        *,
        customs_tariff_number: str | None,
        weight_gross: Decimal | None,
        weight_net: Decimal | None,
    ) -> str:
        parts: list[str] = []
        tariff_number = str(customs_tariff_number or "").strip()
        if tariff_number:
            parts.append(f"Statistische Warennummer: {tariff_number}")
        if weight_gross is not None:
            parts.append(f"Gewicht brutto: {cls._format_export_weight(weight_gross)} kg")
        if weight_net is not None:
            parts.append(f"Gewicht netto: {cls._format_export_weight(weight_net)} kg")
        return "\n".join(parts)

    @staticmethod
    def _format_export_weight(value: Decimal) -> str:
        normalized = format(value.normalize(), "f")
        if "." in normalized:
            normalized = normalized.rstrip("0").rstrip(".")
        return normalized.replace(".", ",")

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


__all__ = ["OrderRuleDebugInfo", "OrderUpsertMicrotechService", "OrderUpsertResult"]
