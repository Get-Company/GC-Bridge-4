from __future__ import annotations

from typing import Any

from loguru import logger

from core.services import BaseService
from customer.models import Address, Customer
from orders.models import Order


def _to_str(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


class CustomerMergeSearchService(BaseService):
    """Searches for customer data across Django, Shopware 6, and Microtech."""

    def search_django(self, erp_nr: str) -> dict[str, Any] | None:
        try:
            customer = Customer.objects.filter(erp_nr=erp_nr).first()
            if not customer:
                return None
            addresses = list(
                customer.addresses.all().values(
                    "id", "erp_ans_id", "erp_ans_nr", "name1", "name2", "name3",
                    "street", "postal_code", "city", "country_code", "email",
                    "first_name", "last_name", "phone", "is_shipping", "is_invoice",
                    "api_id",
                )
            )
            orders = list(
                customer.orders.all().values(
                    "id", "api_id", "order_number", "total_price", "order_state",
                    "purchase_date",
                )
            )
            return {
                "id": customer.id,
                "erp_nr": customer.erp_nr,
                "erp_id": customer.erp_id,
                "name": customer.name,
                "email": customer.email,
                "api_id": customer.api_id,
                "vat_id": customer.vat_id,
                "is_gross": customer.is_gross,
                "addresses": addresses,
                "orders": orders,
            }
        except Exception as exc:
            logger.error("Django search failed for {}: {}", erp_nr, exc)
            return {"error": str(exc)}

    def search_shopware(self, erp_nr: str) -> dict[str, Any] | None:
        try:
            from shopware.services import CustomerService
            service = CustomerService()
            response = service.get_by_customer_number(erp_nr)
            data = (response or {}).get("data", []) or []
            if not data:
                return None
            customer = data[0]
            attrs = customer.get("attributes") or customer
            addresses_field = attrs.get("addresses")
            if isinstance(addresses_field, dict):
                addresses_raw = addresses_field.get("data") or list(addresses_field.values())
            elif isinstance(addresses_field, list):
                addresses_raw = addresses_field
            else:
                addresses_raw = []
            addresses = []
            for addr in addresses_raw:
                if not isinstance(addr, dict):
                    continue
                a = addr.get("attributes") or addr
                country_field = a.get("country")
                if isinstance(country_field, dict):
                    country_data = country_field.get("data") or country_field
                else:
                    country_data = {}
                country_attrs = country_data.get("attributes") or country_data if isinstance(country_data, dict) else {}
                addresses.append({
                    "id": addr.get("id") or a.get("id", ""),
                    "firstName": a.get("firstName", ""),
                    "lastName": a.get("lastName", ""),
                    "company": a.get("company", ""),
                    "street": a.get("street", ""),
                    "zipcode": a.get("zipcode", ""),
                    "city": a.get("city", ""),
                    "countryIso": country_attrs.get("iso", ""),
                    "email": a.get("email") or attrs.get("email", ""),
                })

            return {
                "id": customer.get("id") or attrs.get("id", ""),
                "customerNumber": attrs.get("customerNumber", ""),
                "email": attrs.get("email", ""),
                "firstName": attrs.get("firstName", ""),
                "lastName": attrs.get("lastName", ""),
                "company": attrs.get("company", ""),
                "updatedAt": attrs.get("updatedAt", ""),
                "lastLogin": attrs.get("lastLogin", ""),
                "addresses": addresses,
            }
        except Exception as exc:
            logger.error("Shopware search failed for {}: {}", erp_nr, exc)
            return {"error": str(exc)}

    def search_microtech(self, erp_nr: str, *, erp: Any = None) -> dict[str, Any] | None:
        try:
            from microtech.services import (
                MicrotechAdresseService,
                MicrotechAnschriftService,
                MicrotechAnsprechpartnerService,
                microtech_connection,
            )

            def _fetch(connection):
                adresse = MicrotechAdresseService(erp=connection)
                if not adresse.find(erp_nr):
                    return None
                result = {
                    "erp_nr": _to_str(adresse.get_field("AdrNr")),
                    "name": _to_str(adresse.get_field("Na1")),
                    "email": _to_str(adresse.get_field("EMail1")),
                    "erp_id": adresse.get_field("AdrId"),
                    "status": _to_str(adresse.get_field("Status")),
                    "addresses": [],
                }
                anschrift = MicrotechAnschriftService(erp=connection)
                ansprechpartner = MicrotechAnsprechpartnerService(erp=connection)
                if anschrift.set_range(from_range=[erp_nr, 0], to_range=[erp_nr, 999]):
                    while not anschrift.range_eof():
                        ans_nr = anschrift.get_field("AnsNr")
                        contact = {}
                        if ans_nr is not None and ansprechpartner.set_range(
                            from_range=[erp_nr, ans_nr, 0],
                            to_range=[erp_nr, ans_nr, 20],
                        ):
                            contact = {
                                "firstName": _to_str(ansprechpartner.get_field("VNa")),
                                "lastName": _to_str(ansprechpartner.get_field("NNa")),
                                "email": _to_str(ansprechpartner.get_field("EMail1")),
                                "phone": _to_str(ansprechpartner.get_field("Tel1")),
                            }
                        result["addresses"].append({
                            "ans_id": anschrift.get_field("ID"),
                            "ans_nr": ans_nr,
                            "name1": _to_str(anschrift.get_field("Na1")),
                            "name2": _to_str(anschrift.get_field("Na2")),
                            "street": _to_str(anschrift.get_field("Str")),
                            "postal_code": _to_str(anschrift.get_field("PLZ")),
                            "city": _to_str(anschrift.get_field("Ort")),
                            "country_code": _to_str(anschrift.get_field("Land")),
                            "email": _to_str(anschrift.get_field("EMail1")) or contact.get("email", ""),
                            **contact,
                        })
                        anschrift.range_next()
                return result

            if erp is not None:
                return _fetch(erp)
            with microtech_connection() as connection:
                return _fetch(connection)
        except Exception as exc:
            logger.error("Microtech search failed for {}: {}", erp_nr, exc)
            return {"error": str(exc)}


class CustomerMergeService(BaseService):
    """Merges two Django customers: moves orders/addresses from source to target."""

    def merge_customers(
        self,
        *,
        target_erp_nr: str,
        source_erp_nr: str,
        address_mapping: dict[str, str | None],
        merge_shopware_orders: bool = True,
    ) -> dict[str, Any]:
        target = Customer.objects.filter(erp_nr=target_erp_nr).first()
        source = Customer.objects.filter(erp_nr=source_erp_nr).first()
        if not target:
            raise ValueError(f"Ziel-Kunde {target_erp_nr} nicht in Django gefunden.")
        if not source:
            raise ValueError(f"Quell-Kunde {source_erp_nr} nicht in Django gefunden.")
        if target.pk == source.pk:
            raise ValueError("Ziel- und Quell-Kunde sind identisch.")

        result = {
            "orders_moved": 0,
            "addresses_moved": 0,
            "shopware_orders_moved": 0,
            "password_source": None,
            "errors": [],
        }

        # Determine which Shopware customer has the newer password
        password_winner = self._determine_password_winner(target, source)
        result["password_source"] = password_winner

        # Move orders in Django
        orders_moved = Order.objects.filter(customer=source).update(customer=target)
        result["orders_moved"] = orders_moved

        # Move/merge addresses
        result["addresses_moved"] = self._merge_addresses(
            target=target,
            source=source,
            address_mapping=address_mapping,
        )

        # Move orders in Shopware
        if merge_shopware_orders and source.api_id and target.api_id:
            sw_moved, sw_errors = self._move_shopware_orders(
                target_sw_id=target.api_id,
                source_sw_id=source.api_id,
            )
            result["shopware_orders_moved"] = sw_moved
            result["errors"].extend(sw_errors)

        # Update Shopware password/email if needed
        if password_winner == "source" and source.api_id and target.api_id:
            try:
                self._copy_shopware_login(
                    from_sw_id=source.api_id,
                    to_sw_id=target.api_id,
                )
            except Exception as exc:
                result["errors"].append(f"Passwort-Kopie fehlgeschlagen: {exc}")

        # Delete source customer in Django
        source_label = f"{source.erp_nr} ({source.name})"
        source.delete()
        logger.info("Customer merge: source {} deleted, target {}", source_label, target.erp_nr)

        return result

    def _determine_password_winner(self, target: Customer, source: Customer) -> str:
        """Returns 'target' or 'source' based on which has the more recent Shopware login."""
        if not target.api_id or not source.api_id:
            return "target"
        try:
            from shopware.services import CustomerService
            service = CustomerService()

            target_data = service.get_by_id(target.api_id)
            source_data = service.get_by_id(source.api_id)

            def _get_timestamp(resp):
                data = (resp or {}).get("data", []) or []
                if not data:
                    return ""
                attrs = data[0].get("attributes") or data[0]
                return attrs.get("updatedAt") or attrs.get("lastLogin") or ""

            target_ts = _get_timestamp(target_data)
            source_ts = _get_timestamp(source_data)

            if source_ts > target_ts:
                return "source"
            return "target"
        except Exception as exc:
            logger.warning("Could not determine password winner: {}. Using target.", exc)
            return "target"

    def _merge_addresses(
        self,
        *,
        target: Customer,
        source: Customer,
        address_mapping: dict[str, str | None],
    ) -> int:
        """
        Merge addresses from source to target.
        address_mapping: { source_address_id: target_address_id | "new" | None }
        - target_address_id: overwrite target address with source data
        - "new": move source address to target as new address
        - None: discard source address
        """
        moved = 0
        for src_addr_id_str, action in address_mapping.items():
            try:
                src_addr = Address.objects.get(pk=int(src_addr_id_str), customer=source)
            except Address.DoesNotExist:
                continue

            if action is None or action == "":
                continue
            elif action == "new":
                src_addr.customer = target
                src_addr.erp_combined_id = None
                src_addr.save()
                moved += 1
            else:
                try:
                    tgt_addr = Address.objects.get(pk=int(action), customer=target)
                    # Overwrite target address fields from source
                    for field in (
                        "name1", "name2", "name3", "department", "street",
                        "postal_code", "city", "country_code", "email",
                        "title", "first_name", "last_name", "phone",
                    ):
                        setattr(tgt_addr, field, getattr(src_addr, field))
                    tgt_addr.save()
                    src_addr.delete()
                    moved += 1
                except Address.DoesNotExist:
                    continue
        return moved

    def _move_shopware_orders(
        self, *, target_sw_id: str, source_sw_id: str
    ) -> tuple[int, list[str]]:
        """Reassign all Shopware orders from source customer to target customer."""
        moved = 0
        errors = []
        try:
            from shopware.services import CustomerService, Criteria, EqualsFilter
            service = CustomerService()

            # Search for all orders belonging to source customer
            from shopware.services import OrderService
            order_service = OrderService()
            criteria = Criteria(limit=500)
            criteria.associations["orderCustomer"] = Criteria()
            criteria.filter.append(
                EqualsFilter(field="orderCustomer.customerId", value=source_sw_id)
            )
            response = order_service.request_post("/search/order", payload=criteria)
            orders = (response or {}).get("data", []) or []

            for order in orders:
                order_id = order.get("id") or (order.get("attributes") or {}).get("id")
                if not order_id:
                    continue
                # Get the orderCustomer ID
                oc_data = (order.get("orderCustomer") or {}).get("data") or order.get("orderCustomer") or {}
                oc_attrs = oc_data.get("attributes") or oc_data
                oc_id = oc_data.get("id") or oc_attrs.get("id")
                if not oc_id:
                    errors.append(f"Order {order_id}: orderCustomer ID nicht gefunden")
                    continue
                try:
                    order_service.request_patch(
                        f"/order-customer/{oc_id}",
                        payload={"customerId": target_sw_id},
                    )
                    moved += 1
                except Exception as exc:
                    errors.append(f"Order {order_id}: {exc}")

        except Exception as exc:
            errors.append(f"Shopware order migration failed: {exc}")
        return moved, errors

    def _copy_shopware_login(self, *, from_sw_id: str, to_sw_id: str) -> None:
        """Copy password hash and email from source to target in Shopware."""
        from shopware.services import CustomerService
        service = CustomerService()

        source_resp = service.get_by_id(from_sw_id)
        source_data = (source_resp or {}).get("data", []) or []
        if not source_data:
            raise ValueError("Source Shopware customer not found.")

        source_attrs = source_data[0].get("attributes") or source_data[0]
        source_email = source_attrs.get("email", "")

        # Update target customer with source's email
        # Note: password hash cannot be copied via API - Shopware protects this.
        # The workaround is to keep the source email as the login identifier
        # so the user can use "forgot password" if needed.
        if source_email:
            service.update_customer(to_sw_id, {"email": source_email})
            logger.info(
                "Shopware: copied email {} from {} to {}",
                source_email, from_sw_id, to_sw_id,
            )


class CustomerIdUpdateService(BaseService):
    """Updates erp_nr or Shopware api_id with validation against all systems."""

    def update_erp_nr(self, customer_id: int, new_erp_nr: str) -> dict[str, Any]:
        customer = Customer.objects.filter(pk=customer_id).first()
        if not customer:
            raise ValueError("Kunde nicht gefunden.")

        new_erp_nr = _to_str(new_erp_nr)
        if not new_erp_nr:
            raise ValueError("ERP-Nummer darf nicht leer sein.")

        # Check Django uniqueness
        existing = Customer.objects.filter(erp_nr=new_erp_nr).exclude(pk=customer_id).first()
        if existing:
            raise ValueError(f"ERP-Nummer {new_erp_nr} wird bereits von Kunde {existing.name} verwendet.")

        old_erp_nr = customer.erp_nr

        # Update Shopware customerNumber if linked
        if customer.api_id:
            try:
                from shopware.services import CustomerService
                service = CustomerService()
                # Check Shopware uniqueness
                check = service.get_by_customer_number(new_erp_nr)
                check_data = (check or {}).get("data", []) or []
                for item in check_data:
                    item_id = item.get("id") or (item.get("attributes") or {}).get("id", "")
                    if item_id and item_id != customer.api_id:
                        raise ValueError(
                            f"Shopware: customerNumber {new_erp_nr} wird bereits "
                            f"von Kunde {item_id} verwendet."
                        )
                service.update_customer_number(customer.api_id, new_erp_nr)
            except ValueError:
                raise
            except Exception as exc:
                raise ValueError(f"Shopware-Update fehlgeschlagen: {exc}")

        # Update Django
        customer.erp_nr = new_erp_nr
        customer.save(update_fields=["erp_nr", "updated_at"])

        logger.info("ERP-Nr changed: {} -> {} (customer {})", old_erp_nr, new_erp_nr, customer.pk)
        return {"old_erp_nr": old_erp_nr, "new_erp_nr": new_erp_nr}

    def update_shopware_id(self, customer_id: int, new_api_id: str) -> dict[str, Any]:
        customer = Customer.objects.filter(pk=customer_id).first()
        if not customer:
            raise ValueError("Kunde nicht gefunden.")

        new_api_id = _to_str(new_api_id)

        # Check Django uniqueness (if not empty)
        if new_api_id:
            existing = Customer.objects.filter(api_id=new_api_id).exclude(pk=customer_id).first()
            if existing:
                raise ValueError(
                    f"Shopware-ID {new_api_id} wird bereits von Kunde "
                    f"{existing.erp_nr} verwendet."
                )

            # Verify the ID exists in Shopware
            try:
                from shopware.services import CustomerService
                service = CustomerService()
                check = service.get_by_id(new_api_id)
                check_data = (check or {}).get("data", []) or []
                if not check_data:
                    raise ValueError(f"Shopware-Kunde mit ID {new_api_id} nicht gefunden.")
            except ValueError:
                raise
            except Exception as exc:
                raise ValueError(f"Shopware-Validierung fehlgeschlagen: {exc}")

        old_api_id = customer.api_id
        customer.api_id = new_api_id
        customer.save(update_fields=["api_id", "updated_at"])

        logger.info("Shopware-ID changed: {} -> {} (customer {})", old_api_id, new_api_id, customer.pk)
        return {"old_api_id": old_api_id, "new_api_id": new_api_id}
