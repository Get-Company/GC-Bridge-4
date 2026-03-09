from __future__ import annotations

import re
from typing import Any

from loguru import logger

from django.db import models

from core.services import BaseService
from customer.models import Address, Customer
from orders.models import Order

_UUID_RE = re.compile(r"^[0-9a-f]{32}$|^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)


def _to_str(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _safe_list(value: Any) -> list:
    """Safely coerce a value into a list of dicts."""
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        data = value.get("data")
        if isinstance(data, list):
            return data
        return list(value.values())
    return []


def _safe_attrs(item: Any) -> dict:
    """Extract attributes from a Shopware entity (handles both flat and JSON:API)."""
    if not isinstance(item, dict):
        return {}
    return item.get("attributes") or item


class CustomerMergeSearchService(BaseService):
    """Searches for customer data across Django, Shopware 6, and Microtech."""

    def resolve_query(self, term: str) -> list[str]:
        """Resolve a search term (ERP-Nr, UUID, or name) into a list of ERP numbers."""
        term = term.strip()
        if not term:
            return []

        # 1) Numeric → treat as ERP-Nr directly
        if term.isdigit():
            return [term]

        # 2) UUID → look up in Django and Shopware
        if _UUID_RE.match(term):
            erp_nrs: set[str] = set()
            # Django lookup
            cust = Customer.objects.filter(api_id=term).first()
            if cust:
                erp_nrs.add(cust.erp_nr)
            # Shopware lookup
            try:
                from shopware.services import CustomerService
                service = CustomerService()
                response = service.get_by_id(term)
                for item in (response or {}).get("data", []) or []:
                    attrs = _safe_attrs(item)
                    cn = _to_str(attrs.get("customerNumber"))
                    if cn:
                        erp_nrs.add(cn)
            except Exception as exc:
                logger.warning("Shopware UUID resolve failed for {}: {}", term, exc)
            return sorted(erp_nrs) if erp_nrs else [term]

        # 3) Name search → Django + Shopware
        erp_nrs: set[str] = set()
        # Django: name or email icontains
        for cust in Customer.objects.filter(
            models.Q(name__icontains=term) | models.Q(email__icontains=term)
        )[:20]:
            erp_nrs.add(cust.erp_nr)
        # Shopware: name search
        try:
            from shopware.services import CustomerService
            service = CustomerService()
            response = service.search_by_name(term, limit=20)
            for item in (response or {}).get("data", []) or []:
                attrs = _safe_attrs(item)
                cn = _to_str(attrs.get("customerNumber"))
                if cn:
                    erp_nrs.add(cn)
        except Exception as exc:
            logger.warning("Shopware name resolve failed for '{}': {}", term, exc)
        return sorted(erp_nrs)

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
            attrs = _safe_attrs(customer)
            addresses = []
            for addr in _safe_list(attrs.get("addresses")):
                a = _safe_attrs(addr)
                country = _safe_attrs(a.get("country")) if isinstance(a.get("country"), dict) else {}
                country_a = _safe_attrs(country) if country else {}
                addresses.append({
                    "id": addr.get("id") or a.get("id", ""),
                    "firstName": a.get("firstName", ""),
                    "lastName": a.get("lastName", ""),
                    "company": a.get("company", ""),
                    "street": a.get("street", ""),
                    "zipcode": a.get("zipcode", ""),
                    "city": a.get("city", ""),
                    "countryIso": country_a.get("iso", ""),
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
                attrs = _safe_attrs(data[0])
                return attrs.get("updatedAt") or attrs.get("lastLogin") or ""

            target_ts = _get_timestamp(target_data)
            source_ts = _get_timestamp(source_data)
            return "source" if source_ts > target_ts else "target"
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
        moved = 0
        errors = []
        try:
            from shopware.services import Criteria, EqualsFilter, OrderService
            order_service = OrderService()
            criteria = Criteria(limit=500)
            criteria.associations["orderCustomer"] = Criteria()
            criteria.filter.append(
                EqualsFilter(field="orderCustomer.customerId", value=source_sw_id)
            )
            response = order_service.request_post("/search/order", payload=criteria)
            orders = (response or {}).get("data", []) or []

            for order in orders:
                order_id = order.get("id") or _safe_attrs(order).get("id")
                if not order_id:
                    continue
                oc = order.get("orderCustomer") or {}
                if isinstance(oc, dict):
                    oc_data = oc.get("data") or oc
                else:
                    oc_data = {}
                oc_attrs = _safe_attrs(oc_data)
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
        from shopware.services import CustomerService
        service = CustomerService()
        source_resp = service.get_by_id(from_sw_id)
        source_data = (source_resp or {}).get("data", []) or []
        if not source_data:
            raise ValueError("Source Shopware customer not found.")
        source_attrs = _safe_attrs(source_data[0])
        source_email = source_attrs.get("email", "")
        if source_email:
            service.update_customer(to_sw_id, {"email": source_email})
            logger.info("Shopware: copied email {} from {} to {}", source_email, from_sw_id, to_sw_id)


class CustomerIdUpdateService(BaseService):
    """Updates erp_nr or Shopware api_id with validation against all systems."""

    def update_erp_nr(self, customer_id: int, new_erp_nr: str) -> dict[str, Any]:
        customer = Customer.objects.filter(pk=customer_id).first()
        if not customer:
            raise ValueError("Kunde nicht gefunden.")

        new_erp_nr = _to_str(new_erp_nr)
        if not new_erp_nr:
            raise ValueError("ERP-Nummer darf nicht leer sein.")

        existing = Customer.objects.filter(erp_nr=new_erp_nr).exclude(pk=customer_id).first()
        if existing:
            raise ValueError(f"ERP-Nummer {new_erp_nr} wird bereits von Kunde {existing.name} verwendet.")

        old_erp_nr = customer.erp_nr
        steps = {"django": "ok", "shopware": "skipped", "microtech": "skipped"}

        # 1) Shopware
        if customer.api_id:
            try:
                from shopware.services import CustomerService
                service = CustomerService()
                check = service.get_by_customer_number(new_erp_nr)
                check_data = (check or {}).get("data", []) or []
                for item in check_data:
                    item_id = item.get("id") or _safe_attrs(item).get("id", "")
                    if item_id and item_id != customer.api_id:
                        raise ValueError(
                            f"Shopware: customerNumber {new_erp_nr} wird bereits "
                            f"von Kunde {item_id} verwendet."
                        )
                service.update_customer_number(customer.api_id, new_erp_nr)
                steps["shopware"] = "ok"
            except ValueError:
                raise
            except Exception as exc:
                steps["shopware"] = str(exc)

        # 2) Microtech — rename AdrNr if exists
        try:
            from microtech.services import MicrotechAdresseService, microtech_connection
            with microtech_connection() as erp:
                adresse = MicrotechAdresseService(erp=erp)
                if adresse.find(old_erp_nr):
                    adresse.edit()
                    adresse.set_field("AdrNr", new_erp_nr)
                    adresse.post()
                    steps["microtech"] = "renamed"
                else:
                    steps["microtech"] = "not_found"
        except Exception as exc:
            steps["microtech"] = str(exc)

        # 3) Django
        customer.erp_nr = new_erp_nr
        customer.save(update_fields=["erp_nr", "updated_at"])

        # 4) Microtech full upsert (updates all addresses regardless)
        if steps["microtech"] in ("renamed", "not_found"):
            try:
                sync_svc = CustomerSyncDirectionService()
                sync_svc._django_to_microtech(new_erp_nr)
                label = "umbenannt + Adressen aktualisiert" if steps["microtech"] == "renamed" else "neu angelegt mit Adressen"
                steps["microtech"] = f"ok ({label})"
            except Exception as exc:
                steps["microtech"] = f"upsert fehlgeschlagen: {exc}"

        logger.info("ERP-Nr changed: {} -> {} (customer {}) steps={}", old_erp_nr, new_erp_nr, customer.pk, steps)
        return {"old_erp_nr": old_erp_nr, "new_erp_nr": new_erp_nr, "steps": steps}

    def update_shopware_id(self, customer_id: int, new_api_id: str) -> dict[str, Any]:
        customer = Customer.objects.filter(pk=customer_id).first()
        if not customer:
            raise ValueError("Kunde nicht gefunden.")

        new_api_id = _to_str(new_api_id)
        steps = {"django": "ok", "shopware": "skipped"}

        if new_api_id:
            existing = Customer.objects.filter(api_id=new_api_id).exclude(pk=customer_id).first()
            if existing:
                raise ValueError(
                    f"Shopware-ID {new_api_id} wird bereits von Kunde {existing.erp_nr} verwendet."
                )
            try:
                from shopware.services import CustomerService
                service = CustomerService()
                check = service.get_by_id(new_api_id)
                check_data = (check or {}).get("data", []) or []
                if not check_data:
                    raise ValueError(f"Shopware-Kunde mit ID {new_api_id} nicht gefunden.")
                # Set the customerNumber in Shopware to match our erp_nr
                if customer.erp_nr:
                    service.update_customer_number(new_api_id, customer.erp_nr)
                steps["shopware"] = "ok"
            except ValueError:
                raise
            except Exception as exc:
                steps["shopware"] = str(exc)

        old_api_id = customer.api_id
        customer.api_id = new_api_id
        customer.save(update_fields=["api_id", "updated_at"])

        logger.info("Shopware-ID changed: {} -> {} (customer {}) steps={}", old_api_id, new_api_id, customer.pk, steps)
        return {"old_api_id": old_api_id, "new_api_id": new_api_id, "steps": steps}


class CustomerSyncDirectionService(BaseService):
    """Syncs a single customer between two systems using existing services."""

    def sync(self, erp_nr: str, direction: str) -> dict[str, Any]:
        dispatch = {
            "shopware_to_django": self._shopware_to_django,
            "django_to_shopware": self._django_to_shopware,
            "microtech_to_django": self._microtech_to_django,
            "django_to_microtech": self._django_to_microtech,
        }
        handler = dispatch.get(direction)
        if not handler:
            raise ValueError(f"Unbekannte Richtung: {direction}")
        return handler(erp_nr)

    def _shopware_to_django(self, erp_nr: str) -> dict[str, Any]:
        """Import customer + addresses from Shopware into Django."""
        from shopware.services import CustomerService

        service = CustomerService()
        response = service.get_by_customer_number(erp_nr)
        data = (response or {}).get("data", []) or []
        if not data:
            raise ValueError(f"Kunde {erp_nr} nicht in Shopware gefunden.")

        from orders.services.order_sync import _normalize_entity, _to_str as _os_to_str

        raw = _normalize_entity(data[0])
        customer_id = _os_to_str(raw.get("id"))
        customer_number = _os_to_str(raw.get("customerNumber")) or erp_nr

        customer = Customer.objects.filter(erp_nr=customer_number).first()
        if not customer and customer_id:
            customer = Customer.objects.filter(api_id=customer_id).first()
        if not customer:
            customer = Customer(erp_nr=customer_number)

        vat_ids = raw.get("vatIds") or []
        first = _os_to_str(raw.get("firstName"))
        last = _os_to_str(raw.get("lastName"))
        company = _os_to_str(raw.get("company"))
        customer.name = company or f"{first} {last}".strip() or customer.name
        customer.email = _os_to_str(raw.get("email")) or customer.email
        customer.api_id = customer_id or customer.api_id
        customer.is_gross = bool((raw.get("group") or {}).get("displayGross", True))
        customer.vat_id = _os_to_str(vat_ids[0]) if vat_ids else customer.vat_id
        customer.save()

        # Upsert addresses
        addresses_raw = raw.get("addresses") or []
        if isinstance(addresses_raw, dict):
            addresses_raw = addresses_raw.get("data") or []
        addresses_raw = _normalize_entity(addresses_raw) if isinstance(addresses_raw, list) else []

        default_billing_id = _os_to_str(raw.get("defaultBillingAddressId"))
        default_shipping_id = _os_to_str(raw.get("defaultShippingAddressId"))
        addr_count = 0
        seen_addr_ids: set[int] = set()

        for addr_data in addresses_raw:
            if not isinstance(addr_data, dict):
                continue
            api_id = _os_to_str(addr_data.get("id"))
            if not api_id:
                continue

            # Match by api_id first, then by street+zip to avoid duplicates
            addr = Address.objects.filter(customer=customer, api_id=api_id).first()
            if not addr:
                sw_street = _os_to_str(addr_data.get("street"))
                sw_zip = _os_to_str(addr_data.get("zipcode"))
                if sw_street and sw_zip:
                    addr = Address.objects.filter(
                        customer=customer, street=sw_street, postal_code=sw_zip,
                    ).exclude(id__in=seen_addr_ids).first()
            if not addr:
                addr = Address(customer=customer)

            addr.api_id = api_id
            country = addr_data.get("country") or {}
            if isinstance(country, dict):
                country = country.get("attributes") or country
            # Salutation from Shopware association
            salutation = addr_data.get("salutation") or {}
            if isinstance(salutation, dict):
                salutation = salutation.get("attributes") or salutation
            salutation_name = _os_to_str(salutation.get("displayName") if isinstance(salutation, dict) else "")

            full_name = f"{_os_to_str(addr_data.get('firstName'))} {_os_to_str(addr_data.get('lastName'))}".strip()
            addr.title = salutation_name or addr.title
            addr.name1 = _os_to_str(addr_data.get("company")) or full_name
            addr.name2 = full_name if _os_to_str(addr_data.get("company")) else ""
            addr.department = _os_to_str(addr_data.get("department"))
            addr.street = _os_to_str(addr_data.get("street"))
            addr.postal_code = _os_to_str(addr_data.get("zipcode"))
            addr.city = _os_to_str(addr_data.get("city"))
            addr.country_code = _os_to_str(country.get("iso")) if isinstance(country, dict) else ""
            addr.email = _os_to_str(addr_data.get("email")) or customer.email
            addr.first_name = _os_to_str(addr_data.get("firstName"))
            addr.last_name = _os_to_str(addr_data.get("lastName"))
            addr.phone = _os_to_str(addr_data.get("phoneNumber"))
            addr.is_invoice = (api_id == default_billing_id)
            addr.is_shipping = (api_id == default_shipping_id)
            addr.save()
            seen_addr_ids.add(addr.pk)
            addr_count += 1

        # Remove Django addresses that no longer exist in Shopware
        if seen_addr_ids:
            orphans = Address.objects.filter(customer=customer).exclude(id__in=seen_addr_ids)
            orphan_count = orphans.count()
            if orphan_count:
                orphans.delete()
                logger.info("Shopware->Django: {} removed {} orphan addresses", erp_nr, orphan_count)

        logger.info("Shopware->Django: {} synced ({} addresses)", erp_nr, addr_count)
        return {"message": f"Kunde aus Shopware importiert ({addr_count} Adressen)"}

    def _django_to_shopware(self, erp_nr: str) -> dict[str, Any]:
        """Sync Django customer + addresses to Shopware (upsert)."""
        from orders.services.order_sync import _normalize_entity

        customer = Customer.objects.filter(erp_nr=erp_nr).first()
        if not customer:
            self._shopware_to_django(erp_nr)
            customer = Customer.objects.filter(erp_nr=erp_nr).first()
            if not customer:
                raise ValueError(f"Kunde {erp_nr} weder in Django noch in Shopware gefunden.")

        from shopware.services import CustomerService
        service = CustomerService()

        # Auto-link: if no api_id, try to find Shopware customer by customerNumber
        if not customer.api_id:
            response = service.get_by_customer_number(erp_nr)
            data = (response or {}).get("data", []) or []
            if not data:
                raise ValueError(f"Kunde {erp_nr} nicht in Shopware gefunden — kann nicht verknuepfen.")
            sw_id = _to_str(_safe_attrs(data[0]).get("id") or data[0].get("id"))
            if sw_id:
                customer.api_id = sw_id
                customer.save(update_fields=["api_id", "updated_at"])
                logger.info("Django->Shopware: auto-linked {} -> {}", erp_nr, sw_id)

        # Fetch existing Shopware addresses to match and get countryId/salutationId
        sw_response = service.get_by_id(customer.api_id)
        sw_data = (sw_response or {}).get("data", []) or []
        sw_raw = _normalize_entity(sw_data[0]) if sw_data else {}
        sw_addresses_raw = sw_raw.get("addresses") or []
        if isinstance(sw_addresses_raw, dict):
            sw_addresses_raw = sw_addresses_raw.get("data") or []
        if isinstance(sw_addresses_raw, list):
            sw_addresses_raw = [_normalize_entity(a) if isinstance(a, dict) else a for a in sw_addresses_raw]

        # Build lookup: api_id -> sw_address, street+zip -> sw_address
        sw_by_id: dict[str, dict] = {}
        sw_by_location: dict[str, dict] = {}
        default_country_id = ""
        default_salutation_id = ""
        for swa in sw_addresses_raw:
            if not isinstance(swa, dict):
                continue
            swa_id = _to_str(swa.get("id"))
            if swa_id:
                sw_by_id[swa_id] = swa
            loc_key = f"{_to_str(swa.get('street'))}|{_to_str(swa.get('zipcode'))}".lower()
            if loc_key and loc_key != "|":
                sw_by_location[loc_key] = swa
            if not default_country_id:
                default_country_id = _to_str(swa.get("countryId"))
            if not default_salutation_id:
                default_salutation_id = _to_str(swa.get("salutationId"))

        if not default_salutation_id:
            default_salutation_id = _to_str(sw_raw.get("salutationId"))

        # Upsert Django addresses into Shopware
        django_addresses = list(customer.addresses.all())
        addr_count = 0
        for addr in django_addresses:
            sw_match = None
            if addr.api_id:
                sw_match = sw_by_id.get(addr.api_id)
            if not sw_match:
                loc_key = f"{addr.street}|{addr.postal_code}".lower()
                sw_match = sw_by_location.get(loc_key)

            # Build payload
            payload: dict[str, Any] = {
                "firstName": addr.first_name or addr.name1 or ".",
                "lastName": addr.last_name or addr.name2 or ".",
                "street": addr.street or ".",
                "zipcode": addr.postal_code or ".",
                "city": addr.city or ".",
                "company": addr.name1 if addr.name2 else "",
            }
            if addr.phone:
                payload["phoneNumber"] = addr.phone

            if sw_match:
                # Update existing Shopware address
                sw_addr_id = _to_str(sw_match.get("id"))
                if sw_addr_id:
                    try:
                        service.request_patch(f"/customer-address/{sw_addr_id}", payload=payload)
                        if not addr.api_id:
                            addr.api_id = sw_addr_id
                            addr.save(update_fields=["api_id", "updated_at"])
                        addr_count += 1
                    except Exception as exc:
                        logger.warning("Django->Shopware: failed to update address {}: {}", sw_addr_id, exc)
            else:
                # Create new address in Shopware
                payload["customerId"] = customer.api_id
                payload["countryId"] = default_country_id
                payload["salutationId"] = default_salutation_id
                try:
                    result = service.request_post("/customer-address", payload=payload)
                    # Extract new address ID from response
                    new_id = ""
                    if isinstance(result, dict):
                        new_id = _to_str(result.get("data", {}).get("id") if isinstance(result.get("data"), dict) else result.get("id"))
                    if new_id:
                        addr.api_id = new_id
                        addr.save(update_fields=["api_id", "updated_at"])
                    addr_count += 1
                except Exception as exc:
                    logger.warning("Django->Shopware: failed to create address for {}: {}", erp_nr, exc)

        service.update_customer_number(customer.api_id, erp_nr)
        logger.info("Django->Shopware: {} synced ({} addresses)", erp_nr, addr_count)
        return {"message": f"Shopware verknuepft ({addr_count} Adressen synchronisiert)"}

    def _microtech_to_django(self, erp_nr: str) -> dict[str, Any]:
        """Import customer + addresses from Microtech into Django."""
        from customer.services.customer_sync import CustomerSyncService
        svc = CustomerSyncService()
        customer = svc.sync_from_microtech(erp_nr)
        addr_count = customer.addresses.count()
        logger.info("Microtech->Django: {} synced ({} addresses)", erp_nr, addr_count)
        return {"message": f"Kunde aus Microtech importiert ({addr_count} Adressen)"}

    def _django_to_microtech(self, erp_nr: str) -> dict[str, Any]:
        """Push customer + ALL addresses from Django to Microtech."""
        customer = Customer.objects.filter(erp_nr=erp_nr).first()
        if not customer:
            # Auto-create from Microtech first
            self._microtech_to_django(erp_nr)
            customer = Customer.objects.filter(erp_nr=erp_nr).first()
            if not customer:
                raise ValueError(f"Kunde {erp_nr} weder in Django noch in Microtech gefunden.")

        all_addresses = list(customer.addresses.all())
        if not all_addresses:
            raise ValueError(f"Kunde {erp_nr} hat keine Adressen in Django.")

        from customer.services.customer_upsert_microtech import CustomerUpsertMicrotechService
        from microtech.services import (
            MicrotechAdresseService,
            MicrotechAnschriftService,
            MicrotechAnsprechpartnerService,
            microtech_connection,
        )

        svc = CustomerUpsertMicrotechService()

        with microtech_connection() as erp:
            adresse_service = MicrotechAdresseService(erp=erp)
            anschrift_service = MicrotechAnschriftService(erp=erp)
            ansprechpartner_service = MicrotechAnsprechpartnerService(erp=erp)

            # Upsert the top-level Adresse record (uses first address for UStKat)
            shipping = customer.shipping_address or all_addresses[0]
            actual_erp_nr, is_new = svc._upsert_adresse_record(
                customer=customer,
                shipping=shipping,
                adresse_service=adresse_service,
            )

            # Reset all standard flags before setting new ones
            svc._reset_anschrift_standard_flags(
                erp_nr=actual_erp_nr,
                anschrift_service=anschrift_service,
            )

            # Upsert ALL addresses as Anschrift + Ansprechpartner
            used_ans_nrs: set[int] = set()
            first_shipping_nr = None
            first_billing_nr = None

            for addr in all_addresses:
                ans_nr = svc._determine_ans_nr(
                    erp_nr=actual_erp_nr,
                    address=addr,
                    anschrift_service=anschrift_service,
                    reserved=used_ans_nrs,
                )
                used_ans_nrs.add(ans_nr)

                svc._upsert_anschrift_and_contact(
                    erp_nr=actual_erp_nr,
                    address=addr,
                    ans_nr=ans_nr,
                    is_shipping=bool(addr.is_shipping),
                    is_invoice=bool(addr.is_invoice),
                    anschrift_service=anschrift_service,
                    ansprechpartner_service=ansprechpartner_service,
                    na1_mode="auto",
                    na1_static_value="",
                )

                if addr.is_shipping and first_shipping_nr is None:
                    first_shipping_nr = ans_nr
                if addr.is_invoice and first_billing_nr is None:
                    first_billing_nr = ans_nr

            # Set default Liefer/Rechnungs-AnsNr on the Adresse record
            ship_nr = first_shipping_nr or min(used_ans_nrs)
            bill_nr = first_billing_nr or ship_nr
            adresse_service.edit()
            adresse_service.set_field("LiAnsNr", ship_nr)
            adresse_service.set_field("ReAnsNr", bill_nr)
            adresse_service.post()

        addr_count = len(all_addresses)
        msg = f"Kunde nach Microtech uebertragen ({addr_count} Adressen)"
        if is_new:
            msg += " [NEU]"
        logger.info("Django->Microtech: {} upserted ({} addresses)", erp_nr, addr_count)
        return {"message": msg}
