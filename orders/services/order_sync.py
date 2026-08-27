from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

from django.db import transaction
from django.utils.dateparse import parse_datetime
from loguru import logger

from core.services import BaseService
from customer.models import Address, Customer
from orders.models import Order, OrderDetail
from products.models import Product
from shopware.models import ShopwareSettings
from shopware.services import CustomerService, OrderService


def _normalize_entity(data: Any) -> Any:
    if isinstance(data, list):
        return [_normalize_entity(item) for item in data]
    if not isinstance(data, dict):
        return data

    attributes = data.get("attributes")
    result: dict[str, Any] = {}

    if isinstance(attributes, dict):
        result.update(attributes)
        if "id" not in result and data.get("id"):
            result["id"] = data.get("id")
    else:
        result.update(data)

    for source in (data, attributes if isinstance(attributes, dict) else {}):
        for key, value in source.items():
            if key == "attributes":
                continue
            if isinstance(value, (dict, list)):
                result[key] = _normalize_entity(value)
            elif key not in result:
                result[key] = value

    return result


def _to_str(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _to_decimal(value: Any) -> Decimal:
    if value in (None, ""):
        return Decimal("0.00")
    try:
        return Decimal(str(value)).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError, TypeError):
        return Decimal("0.00")


def _to_int(value: Any) -> int:
    if value in (None, ""):
        return 0
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


# Transition applied to orders that the autosync just created.
NEW_ORDER_FROM_STATE = "open"
NEW_ORDER_TRANSITION = "process"
NEW_ORDER_TO_STATE = "in_progress"


class OrderSyncService(BaseService):
    model = Order

    def sync_open_orders(
        self,
        *,
        sales_channel_ids: list[str] | None = None,
        limit_orders: int | None = None,
    ) -> dict[str, int]:
        sales_channel_ids = sales_channel_ids or self._active_sales_channel_ids()
        if not sales_channel_ids:
            raise ValueError("No active sales channel IDs configured.")

        service = OrderService()
        summary = {
            "orders_seen": 0,
            "orders_created": 0,
            "orders_updated": 0,
            "orders_failed": 0,
            "orders_promoted": 0,
            "customers_upserted": 0,
            "addresses_upserted": 0,
            "details_upserted": 0,
        }

        for sales_channel_id in sales_channel_ids:
            response = service.list_all_open_by_sales_channel(sales_channel_id=sales_channel_id)
            orders = (response or {}).get("data", []) or []
            logger.info(
                "SalesChannel {}: {} offene Bestellung(en) fuer Upsert.",
                sales_channel_id,
                len(orders),
            )

            for order_data in orders:
                if limit_orders and summary["orders_seen"] >= limit_orders:
                    return summary

                summary["orders_seen"] += 1
                try:
                    result = self.upsert_from_shopware_order(
                        order_data=order_data,
                        sales_channel_id=sales_channel_id,
                    )
                except Exception as exc:
                    summary["orders_failed"] += 1
                    logger.error("Order-Upsert fehlgeschlagen: {}", exc)
                    continue

                if result["created"]:
                    summary["orders_created"] += 1
                    if self.promote_new_order_to_in_progress(order=result["order"], service=service):
                        summary["orders_promoted"] += 1
                else:
                    summary["orders_updated"] += 1
                summary["customers_upserted"] += 1 if result["customer_upserted"] else 0
                summary["addresses_upserted"] += result["addresses_upserted"]
                summary["details_upserted"] += result["details_upserted"]

        return summary

    @transaction.atomic
    def upsert_from_shopware_order(
        self,
        *,
        order_data: dict[str, Any],
        sales_channel_id: str = "",
    ) -> dict[str, Any]:
        order_data = _normalize_entity(order_data)
        order_customer = order_data.get("orderCustomer") or {}
        customer, billing_address, shipping_address, addresses_count = self._upsert_customer_block(
            order_data=order_data,
            order_customer=order_customer,
        )

        order_id = _to_str(order_data.get("id"))
        if not order_id:
            raise ValueError("Shopware order has no id.")

        price = order_data.get("price") or {}
        tax_status = _to_str(price.get("taxStatus"))
        total_tax = Decimal("0.00")
        for tax in price.get("calculatedTaxes", []) or []:
            total_tax += _to_decimal((tax or {}).get("tax"))

        delivery = _normalize_entity((order_data.get("deliveries") or [{}])[0] or {})
        transaction = _normalize_entity((order_data.get("transactions") or [{}])[0] or {})
        order_defaults = {
            "api_delivery_id": _to_str(delivery.get("id")),
            "api_transaction_id": _to_str(transaction.get("id")),
            "sales_channel_id": sales_channel_id or _to_str(order_data.get("salesChannelId")),
            "order_number": _to_str(order_data.get("orderNumber")),
            "description": _to_str(order_data.get("customerComment")),
            "total_price": _to_decimal(price.get("totalPrice")),
            "total_tax": total_tax,
            "shipping_costs": self._net_unit_price_from_shopware_price(
                _normalize_entity(order_data.get("shippingCosts") or {"totalPrice": order_data.get("shippingTotal")}),
                quantity=1,
                tax_status=tax_status,
            ),
            "payment_method": _to_str((transaction.get("paymentMethod") or {}).get("name")),
            "shipping_method": _to_str((delivery.get("shippingMethod") or {}).get("name")),
            "order_state": _to_str((order_data.get("stateMachineState") or {}).get("technicalName")),
            "shipping_state": _to_str((delivery.get("stateMachineState") or {}).get("technicalName")),
            "payment_state": _to_str((transaction.get("stateMachineState") or {}).get("technicalName")),
            "purchase_date": parse_datetime(_to_str(order_data.get("createdAt"))),
            "customer": customer,
            "billing_address": billing_address,
            "shipping_address": shipping_address,
        }

        order, created = Order.objects.update_or_create(
            api_id=order_id,
            defaults=order_defaults,
        )
        details_count = self._replace_order_details(
            order=order,
            line_items=order_data.get("lineItems") or [],
            tax_status=tax_status,
        )
        from orders.services.order_sync_workflow import OrderSyncWorkflowService

        workflow, workflow_created = OrderSyncWorkflowService().ensure_pending_for_order(order)
        if workflow_created and workflow is not None:
            from orders.tasks import start_microtech_order_workflow

            transaction.on_commit(
                lambda workflow_id=workflow.pk: start_microtech_order_workflow.delay(workflow_id)
            )

        return {
            "created": created,
            "order": order,
            "workflow_id": workflow.pk if workflow is not None else None,
            "workflow_created": workflow_created,
            "customer_upserted": True,
            "addresses_upserted": addresses_count,
            "details_upserted": details_count,
        }

    def promote_new_order_to_in_progress(
        self,
        *,
        order: Order,
        service: OrderService | None = None,
    ) -> bool:
        """
        Moves a freshly synced order from "open" to "in_progress" in Shopware.

        Only orders that are still in the state the transition starts from are
        touched, and a failing transition never aborts the running sync.
        """
        if _to_str(order.order_state) != NEW_ORDER_FROM_STATE:
            return False
        if not _to_str(order.api_id):
            return False

        service = service or OrderService()
        try:
            service.set_order_state(order_id=order.api_id, action_name=NEW_ORDER_TRANSITION)
        except Exception as exc:
            logger.error(
                "Bestellung {} konnte nicht auf '{}' gesetzt werden: {}",
                order.order_number or order.api_id,
                NEW_ORDER_TO_STATE,
                exc,
            )
            return False

        order.order_state = NEW_ORDER_TO_STATE
        order.save(update_fields=["order_state"])
        logger.info(
            "Bestellung {} nach dem Anlegen auf '{}' gesetzt.",
            order.order_number or order.api_id,
            NEW_ORDER_TO_STATE,
        )
        return True

    def _upsert_customer_block(
        self,
        *,
        order_data: dict[str, Any],
        order_customer: dict[str, Any],
    ) -> tuple[Customer, Address | None, Address | None, int]:
        order_data = _normalize_entity(order_data)
        order_customer = _normalize_entity(order_customer)
        customer_id = _to_str(order_customer.get("customerId")) or _to_str((order_customer.get("customer") or {}).get("id"))
        customer_payload = self._load_shopware_customer(customer_id=customer_id)
        if not customer_id:
            customer_id = _to_str(customer_payload.get("id"))

        customer_number = _to_str(order_customer.get("customerNumber"))
        if not customer_number:
            customer_number = _to_str(customer_payload.get("customerNumber"))
        if not customer_number and customer_id:
            customer_number = f"sw6-{customer_id[:12]}"
        if not customer_number:
            raise ValueError("Order has no customerNumber/customerId.")

        customer = Customer.objects.filter(erp_nr=customer_number).first()
        if not customer and customer_id:
            customer = Customer.objects.filter(api_id=customer_id).first()
        if not customer:
            customer = Customer(erp_nr=customer_number)

        nested_customer = customer_payload or _normalize_entity(order_customer.get("customer") or {})
        vat_ids = nested_customer.get("vatIds") or []
        customer.name = _to_str(nested_customer.get("firstName") or order_customer.get("firstName") or customer.name)
        customer.email = _to_str(order_customer.get("email") or nested_customer.get("email")) or customer.email
        customer.api_id = customer_id or customer.api_id
        customer_group = nested_customer.get("group") or {}
        display_gross = bool(customer_group.get("displayGross", True))
        customer.is_gross = display_gross
        customer.shopware_customer_group = _to_str(customer_group.get("name")) or customer.shopware_customer_group
        customer.vat_id = _to_str(vat_ids[0]) if vat_ids else customer.vat_id
        customer.save()

        billing_data = _normalize_entity(order_data.get("billingAddress") or {})
        billing_address = self._upsert_address(
            customer=customer,
            address_data=billing_data,
            fallback_email=customer.email,
            is_invoice=True,
            is_shipping=False,
        ) if billing_data else None

        deliveries = _normalize_entity(order_data.get("deliveries") or [])
        shipping_data = _normalize_entity((deliveries[0] or {}).get("shippingOrderAddress")) if deliveries else None
        shipping_address = self._upsert_address(
            customer=customer,
            address_data=shipping_data or {},
            fallback_email=customer.email,
            is_invoice=False,
            is_shipping=True,
        ) if shipping_data else None

        (
            default_billing_address,
            default_shipping_address,
            default_address_pks,
        ) = self._upsert_default_customer_addresses(
            customer=customer,
            customer_payload=customer_payload,
            fallback_email=customer.email,
        )

        if shipping_address and not billing_address:
            shipping_address.is_invoice = True
            shipping_address.save(update_fields=["is_invoice", "updated_at"])
            billing_address = shipping_address

        if billing_address and not shipping_address:
            billing_address.is_shipping = True
            billing_address.save(update_fields=["is_shipping", "updated_at"])
            shipping_address = billing_address

        if not billing_address and default_billing_address:
            billing_address = default_billing_address
        if not shipping_address and default_shipping_address:
            shipping_address = default_shipping_address

        if not default_billing_address and billing_address:
            customer.set_billing_address(billing_address)
        if not default_shipping_address and shipping_address:
            customer.set_shipping_address(shipping_address)

        synced_address_ids = set(default_address_pks)
        if billing_address and billing_address.pk:
            synced_address_ids.add(billing_address.pk)
        if shipping_address and shipping_address.pk:
            synced_address_ids.add(shipping_address.pk)
        addresses_count = len(synced_address_ids)

        return customer, billing_address, shipping_address, addresses_count

    def _load_shopware_customer(self, *, customer_id: str) -> dict[str, Any]:
        customer_id = _to_str(customer_id)
        if not customer_id:
            return {}

        cache = getattr(self, "_shopware_customer_cache", None)
        if cache is None:
            cache = {}
            self._shopware_customer_cache = cache

        if customer_id in cache:
            return cache[customer_id]

        try:
            response = CustomerService().get_by_id(customer_id)
            rows = (response or {}).get("data", []) or []
            payload = _normalize_entity(rows[0]) if rows else {}
            if not payload:
                logger.warning("Shopware customer {} konnte nicht geladen werden.", customer_id)
        except Exception as exc:  # pragma: no cover - network/runtime errors
            logger.warning("Shopware customer {} lookup failed: {}", customer_id, exc)
            payload = {}

        cache[customer_id] = payload
        return payload

    def _upsert_default_customer_addresses(
        self,
        *,
        customer: Customer,
        customer_payload: dict[str, Any],
        fallback_email: str,
    ) -> tuple[Address | None, Address | None, set[int]]:
        if not customer_payload:
            return None, None, set()

        default_billing_id = _to_str(customer_payload.get("defaultBillingAddressId"))
        default_shipping_id = _to_str(customer_payload.get("defaultShippingAddressId"))
        if not default_billing_id and not default_shipping_id:
            return None, None, set()

        addresses = self._extract_customer_addresses(customer_payload)
        if not addresses:
            return None, None, set()

        by_id = {
            _to_str(address.get("id")): address
            for address in addresses
            if _to_str(address.get("id"))
        }
        billing_data = by_id.get(default_billing_id)
        shipping_data = by_id.get(default_shipping_id)

        default_billing_address = None
        default_shipping_address = None
        upserted_ids: set[int] = set()

        if billing_data and shipping_data and default_billing_id == default_shipping_id:
            default_billing_address = self._upsert_address(
                customer=customer,
                address_data=billing_data,
                fallback_email=fallback_email,
                is_invoice=True,
                is_shipping=True,
            )
            default_shipping_address = default_billing_address
            if default_billing_address.pk:
                upserted_ids.add(default_billing_address.pk)
        else:
            if billing_data:
                default_billing_address = self._upsert_address(
                    customer=customer,
                    address_data=billing_data,
                    fallback_email=fallback_email,
                    is_invoice=True,
                    is_shipping=False,
                )
                if default_billing_address.pk:
                    upserted_ids.add(default_billing_address.pk)
            if shipping_data:
                default_shipping_address = self._upsert_address(
                    customer=customer,
                    address_data=shipping_data,
                    fallback_email=fallback_email,
                    is_invoice=False,
                    is_shipping=True,
                )
                if default_shipping_address.pk:
                    upserted_ids.add(default_shipping_address.pk)

        if default_billing_address:
            customer.set_billing_address(default_billing_address)
        if default_shipping_address:
            customer.set_shipping_address(default_shipping_address)

        return default_billing_address, default_shipping_address, upserted_ids

    @staticmethod
    def _extract_customer_addresses(customer_payload: dict[str, Any]) -> list[dict[str, Any]]:
        addresses = customer_payload.get("addresses") or []
        if isinstance(addresses, dict):
            addresses = addresses.get("data") or []
        if not isinstance(addresses, list):
            return []
        normalized = _normalize_entity(addresses)
        return [item for item in normalized if isinstance(item, dict)]

    def _upsert_address(
        self,
        *,
        customer: Customer,
        address_data: dict[str, Any],
        fallback_email: str,
        is_invoice: bool,
        is_shipping: bool,
    ) -> Address:
        address_data = _normalize_entity(address_data)
        api_id = _to_str(address_data.get("id"))
        qs = Address.objects.filter(customer=customer)
        address = qs.filter(api_id=api_id).first() if api_id else None

        if not address:
            address = self._find_contact_address(customer=customer, address_data=address_data)

        if not address:
            address = Address(customer=customer)

        if api_id and address.api_id != api_id:
            address.api_id = api_id

        country = address_data.get("country") or {}
        salutation = address_data.get("salutation") or {}
        full_name = f"{_to_str(address_data.get('firstName'))} {_to_str(address_data.get('lastName'))}".strip()

        address.erp_nr = _to_int(customer.erp_nr) or None
        address.name1 = _to_str(address_data.get("company")) or _to_str(salutation.get("displayName"))
        address.name2 = full_name
        address.name3 = ""
        address.department = _to_str(address_data.get("department"))
        address.street = _to_str(address_data.get("street"))
        address.postal_code = _to_str(address_data.get("zipcode"))
        address.city = _to_str(address_data.get("city"))
        address.country_code = _to_str(country.get("iso"))
        address.email = _to_str(address_data.get("email")) or fallback_email
        address.title = _to_str(salutation.get("displayName"))
        address.first_name = _to_str(address_data.get("firstName"))
        address.last_name = _to_str(address_data.get("lastName"))
        address.phone = _to_str(address_data.get("phoneNumber"))
        address.is_invoice = is_invoice
        address.is_shipping = is_shipping
        address.save()
        return address

    @staticmethod
    def _find_contact_address(*, customer: Customer, address_data: dict[str, Any]) -> Address | None:
        street = _to_str(address_data.get("street"))
        postal_code = _to_str(address_data.get("zipcode"))
        city = _to_str(address_data.get("city"))
        first_name = _to_str(address_data.get("firstName"))
        last_name = _to_str(address_data.get("lastName"))
        email = _to_str(address_data.get("email"))
        if not street or not postal_code:
            return None

        candidates = Address.objects.filter(
            customer=customer,
            street=street,
            postal_code=postal_code,
            city=city,
        )
        if first_name or last_name:
            match = candidates.filter(first_name=first_name, last_name=last_name).order_by("-updated_at").first()
            if match:
                return match
        if email:
            match = candidates.filter(email=email).order_by("-updated_at").first()
            if match:
                return match
        return None

    def _replace_order_details(
        self,
        *,
        order: Order,
        line_items: list[dict[str, Any]],
        tax_status: str,
    ) -> int:
        normalized_line_items = [_normalize_entity(item) for item in line_items]
        products_by_sku, products_by_erp_nr = self._product_maps_for_line_items(normalized_line_items)
        resolved_line_items = [
            (
                item,
                self._resolve_line_item_erp_nr(
                    item=item,
                    products_by_sku=products_by_sku,
                    products_by_erp_nr=products_by_erp_nr,
                ),
            )
            for item in normalized_line_items
        ]

        order.details.all().delete()
        created_count = 0

        for item, erp_nr in resolved_line_items:
            price_data = item.get("price") or {}
            calculated_taxes = price_data.get("calculatedTaxes") or []
            tax_value = _to_decimal((calculated_taxes[0] or {}).get("tax")) if calculated_taxes else None

            OrderDetail.objects.create(
                order=order,
                api_id=_to_str(item.get("id")),
                erp_nr=erp_nr,
                name=_to_str(item.get("label")),
                quantity=_to_int(item.get("quantity")),
                unit_price=self._net_unit_price_from_shopware_price(
                    price_data,
                    quantity=_to_int(item.get("quantity")) or 1,
                    tax_status=tax_status,
                ),
                total_price=_to_decimal(price_data.get("totalPrice")),
                tax=tax_value,
                unit=_to_str(item.get("unitName")),
            )
            created_count += 1
        return created_count

    @staticmethod
    def _product_maps_for_line_items(line_items: list[dict[str, Any]]) -> tuple[dict[str, str], dict[str, str]]:
        """Return Django's authoritative mapping for the products in an order."""
        product_ids: set[str] = set()
        product_numbers: set[str] = set()
        for item in line_items:
            payload = item.get("payload") or {}
            product_ids.update(
                product_id
                for product_id in (
                    _to_str(item.get("referencedId")),
                    _to_str(item.get("productId")),
                    _to_str(payload.get("productId")),
                )
                if product_id
            )
            if product_number := _to_str(payload.get("productNumber")):
                product_numbers.add(product_number)

        products = Product.objects.filter(sku__in=product_ids) | Product.objects.filter(erp_nr__in=product_numbers)
        products = products.only("sku", "erp_nr")
        return (
            {product.sku: product.erp_nr for product in products if product.sku},
            {product.erp_nr: product.erp_nr for product in products},
        )

    @staticmethod
    def _resolve_line_item_erp_nr(
        *,
        item: dict[str, Any],
        products_by_sku: dict[str, str],
        products_by_erp_nr: dict[str, str],
    ) -> str:
        """Resolve a Shopware product position to an ERP number stored in Django.

        Shopware's ``payload.productNumber`` is display data from the order, not
        a reliable integration key.  The Shopware product UUID is mapped through
        ``Product.sku`` first; a number is accepted only when it exactly matches
        a Django product.  This prevents auto-generated Shopware variant numbers
        from reaching Microtech.
        """
        payload = item.get("payload") or {}
        product_id = next(
            (
                product_id
                for product_id in (
                    _to_str(item.get("referencedId")),
                    _to_str(item.get("productId")),
                    _to_str(payload.get("productId")),
                )
                if product_id
            ),
            "",
        )
        product_number = _to_str(payload.get("productNumber"))
        line_item_type = _to_str(item.get("type"))

        # Promotion, credit and custom positions do not represent an ERP
        # article. Their effects are transferred by the order total/rules, not
        # by manufacturing an article position in Microtech.
        if line_item_type and line_item_type != "product":
            return ""
        if not product_id and not product_number:
            return ""

        erp_nr_by_id = products_by_sku.get(product_id, "")
        erp_nr_by_number = products_by_erp_nr.get(product_number, "")
        if erp_nr_by_id and erp_nr_by_number and erp_nr_by_id != erp_nr_by_number:
            raise ValueError(
                "Shopware-Produktposition hat widersprüchliche Produktdaten: "
                f"Produkt-ID {product_id} gehört in Django zu {erp_nr_by_id}, "
                f"die übermittelte Artikelnummer lautet jedoch {product_number}."
            )

        erp_nr = erp_nr_by_id or erp_nr_by_number
        if erp_nr:
            return erp_nr

        raise ValueError(
            "Shopware-Produktposition kann keiner Django-Artikelnummer zugeordnet werden: "
            f"Produkt-ID={product_id or '-'}, Artikelnummer={product_number or '-'} "
            f"(Position {(_to_str(item.get('id')) or '-')})."
        )

    @staticmethod
    def _net_unit_price_from_shopware_price(
        price_data: dict[str, Any],
        *,
        quantity: int,
        tax_status: str,
    ) -> Decimal:
        unit_price = _to_decimal(price_data.get("unitPrice"))
        if _to_str(tax_status).casefold() != "gross":
            return unit_price

        total_price = _to_decimal(price_data.get("totalPrice"))
        total_tax = sum(
            (_to_decimal((tax or {}).get("tax")) for tax in price_data.get("calculatedTaxes", []) or []),
            start=Decimal("0.00"),
        )
        if total_price <= Decimal("0.00") or quantity <= 0:
            return unit_price
        return ((total_price - total_tax) / Decimal(quantity)).quantize(Decimal("0.01"))

    @staticmethod
    def _active_sales_channel_ids() -> list[str]:
        return list(
            ShopwareSettings.objects.filter(is_active=True)
            .exclude(sales_channel_id="")
            .values_list("sales_channel_id", flat=True)
        )
