"""A reviewed consolidation of exact address copies, never a customer merge."""
from __future__ import annotations

import json

from django.db import transaction
from django.db.models import Q
from django.core.serializers.json import DjangoJSONEncoder
from core.services import BaseService
from customer.models import Address, Customer
from customer.services.customer_merge import ShopwareCustomerMergeService


class AddressConsolidationRejected(ValueError):
    """An explicit client error rejected the atomic Shopware operation."""


class AddressConsolidationService(BaseService):
    BUSINESS_FIELDS = ("company", "name1", "name2", "name3", "department", "street", "postal_code", "city",
                       "country_code", "email", "title", "first_name", "last_name", "phone")
    MAPPING_FIELDS = ("erp_nr", "erp_ans_nr", "erp_asp_nr", "erp_ans_id", "erp_asp_id", "erp_combined_id")

    @staticmethod
    def identity(fields, keys):
        return tuple(" ".join(str(fields.get(key) or "").split()).casefold() for key in keys)

    @classmethod
    def local_identity(cls, fields):
        if not all(str(fields.get(key) or "").strip() for key in ("street", "postal_code", "city")):
            return None
        if not any(str(fields.get(key) or "").strip() for key in ("company", "name1", "first_name", "last_name")):
            return None
        return cls.identity(fields, cls.BUSINESS_FIELDS)

    @classmethod
    def preview(cls, snapshot, target_ref):
        records = snapshot["records"]
        refs = {r["ref"]: r for r in records}
        target = refs.get(target_ref)
        if not target or (target["system"], target["kind"]) != ("dj", "address"):
            raise ValueError("Die erhaltene Adresse muss in GC-Bridge vorhanden sein.")
        identity = cls.local_identity(target["fields"])
        if identity is None:
            raise ValueError("Unvollständige Adressen dürfen nicht zusammengelegt werden.")
        group = [r for r in records if r["system"] == "dj" and r["kind"] == "address"
                 and r["parent"] == target["parent"] and cls.local_identity(r["fields"]) == identity]
        # A more specific contact can retain its own postal-address association;
        # different contacts or address numbers must never be discarded.
        mapping = {}
        for key in cls.MAPPING_FIELDS:
            values = {r["fields"].get(key) for r in group if r["fields"].get(key) not in (None, "")}
            if len(values) > 1:
                raise ValueError("Die identischen Anschriften haben unterschiedliche Microtech-Zuordnungen. Bitte diese zuerst klären.")
            mapping[key] = next(iter(values), None)
        customer = refs.get(target["parent"])
        if not customer or customer["system"] != "dj" or customer["kind"] != "customer":
            raise ValueError("Der zugehörige Bridge-Kunde fehlt.")
        if mapping["erp_nr"] is not None and str(mapping["erp_nr"]) != target["number"]:
            raise ValueError("Die Adressen enthalten eine abweichende Microtech-Kundenzuordnung. Bitte diese zuerst klären.")
        linked = {str(r["fields"].get("api_id") or "").lower() for r in group} - {""}
        sw_customer = None
        sw_group = []
        keep_sw_id = ""
        if linked:
            keep_id = str(target["fields"].get("api_id") or "").lower()
            sw_target = next((r for r in records if r["system"] == "sw" and r["kind"] == "address" and str(r["fields"].get("id", "")).lower() == keep_id), None)
            if not sw_target:
                raise ValueError("Die erhaltene Adresse benötigt ihre vorhandene Shopware-Zuordnung.")
            keep_sw_id = sw_target["fields"]["id"]
            sw_customer = refs.get(sw_target["parent"])
            if not sw_customer or str(customer["fields"].get("api_id") or "").lower() != str(sw_customer["fields"].get("id") or "").lower() or sw_target["number"] != target["number"]:
                raise ValueError("Die Shopware-Adressen müssen zum selben zugeordneten Kunden gehören.")
            keys = tuple(key for key in ShopwareCustomerMergeService.ADDRESS_COMPARISON_FIELDS if key not in ("id", "customerId"))
            sw_identity = cls.identity(sw_target["fields"], keys)
            sw_group = [r for r in records if r["system"] == "sw" and r["kind"] == "address"
                        and r["parent"] == sw_target["parent"] and cls.identity(r["fields"], keys) == sw_identity]
            sw_ids = {str(r["fields"]["id"]).lower() for r in sw_group}
            if not linked <= sw_ids or any(r["fields"].get("hasMergeMetadata") for r in sw_group):
                raise ValueError("Shopware-Zusatzdaten oder abweichende Adressfelder verhindern eine sichere Zusammenlegung.")
            local_refs = {r["ref"] for r in group}
            if any(r["system"] == "dj" and r["kind"] == "address" and r["ref"] not in local_refs
                   and str(r["fields"].get("api_id") or "").lower() in sw_ids for r in records):
                raise ValueError("Eine Shopware-Adresse ist noch einem anderen Bridge-Datensatz zugeordnet.")
        local_sources = [r for r in group if r["ref"] != target_ref]
        sw_sources = [r for r in sw_group if str(r["fields"]["id"]).lower() != str(target["fields"].get("api_id") or "").lower()]
        if not local_sources and not sw_sources:
            raise ValueError("Es sind keine identischen Adresskopien zum Zusammenlegen vorhanden.")
        roles = {key: any(r["fields"].get(key) for r in group) for key in ("is_invoice", "is_shipping")}
        defaults = {}
        if sw_customer:
            sw_ids = {r["fields"]["id"] for r in sw_group}
            for field, role in (("defaultBillingAddressId", "is_invoice"), ("defaultShippingAddressId", "is_shipping")):
                current = sw_customer["fields"].get(field)
                defaults[field] = keep_sw_id if current in sw_ids else current
                # Union existing roles, but never change another physical default.
                if roles[role] != (current in sw_ids):
                    raise ValueError("Rechnungs-/Lieferrollen in Shopware und GC-Bridge widersprechen sich. Bitte diese zuerst klären.")
        source_ids = {r["fields"]["id"] for r in local_sources}
        orders = [r for r in records if r["system"] == "dj" and r["kind"] == "order" and
                  (r["fields"].get("billing_address_id") in source_ids or r["fields"].get("shipping_address_id") in source_ids)]
        if any(r["parent"] != customer["ref"] for r in orders):
            raise ValueError("Bestellverweise eines anderen Kunden verhindern diese Adresszusammenlegung.")
        order_refs = {r["fields"]["id"]: {"id": r["fields"]["id"], "customer_id": customer["fields"]["id"],
                      "billing_address_id": r["fields"].get("billing_address_id"), "shipping_address_id": r["fields"].get("shipping_address_id")} for r in orders}
        return {"target": target, "customer": customer, "local_sources": local_sources, "sw_customer": sw_customer,
                "sw_sources": sw_sources, "sw_group": sw_group, "mapping": mapping, "roles": roles, "defaults": defaults,
                "keep_sw_id": keep_sw_id, "order_count": len(orders), "order_refs": order_refs}

    @classmethod
    def proposals(cls, snapshot):
        seen, plans = set(), []
        addresses = [r for r in snapshot["records"] if r["system"] == "dj" and r["kind"] == "address"]
        # Prefer a linked, already mapped record, then both roles, then billing.
        addresses.sort(key=lambda r: (not bool(r["fields"].get("api_id")), r["fields"].get("erp_ans_nr") is None,
                       not (r["fields"].get("is_invoice") and r["fields"].get("is_shipping")),
                       not bool(r["fields"].get("is_invoice")), str(r["fields"]["id"])))
        for target in addresses:
            key = (target["parent"], cls.local_identity(target["fields"]))
            if key in seen or key[1] is None:
                continue
            seen.add(key)
            try:
                spec = cls.preview(snapshot, target["ref"])
            except ValueError:
                continue
            source = (spec["local_sources"] or spec["sw_sources"])[0]
            count = max(len(spec["local_sources"]), len(spec["sw_sources"])) + 1
            plans.append({"title": f"{count} identische Adressen zusammenführen", "reason": "Eine Adresse bleibt erhalten und übernimmt die vorhandenen Rollen und Zuordnungen. Bestellanschriften bleiben inhaltlich unverändert.",
                          "certainty": "clear", "questions": [], "evidence": [{"ref": r["ref"], "field": "street", "finding": "Die vollständigen Adressfelder stimmen überein."} for r in (source, target)],
                          "operations": [{"kind": "consolidate_addresses", "source": source["ref"], "target": target["ref"], "reason": "Identische Kopien derselben Anschrift zusammenführen."}]})
            if len(plans) == 2:
                break
        return plans

    @staticmethod
    def changes(spec):
        return {"Adresse": spec["target"]["ref"], "Entfernte Bridge-Adressen": [r["ref"] for r in spec["local_sources"]],
                "Entfernte SW6-Adressen": [r["ref"] for r in spec["sw_sources"]], "Standardrollen": spec["roles"],
                "Microtech-Zuordnung": spec["mapping"], "Bestellverweise": spec["order_count"], "SW6-Standardadressen": spec["defaults"]}

    @staticmethod
    def verify_shopware(spec, before, after):
        refs = {r["ref"]: r for r in after["records"]}
        if any(r["ref"] in refs for r in spec["sw_sources"]):
            raise ValueError("Shopware hat die Zusammenlegung noch nicht vollständig bestätigt. Bitte den Status prüfen.")
        keep = next(r for r in spec["sw_group"] if r["fields"]["id"] == spec["keep_sw_id"])
        if refs.get(keep["ref"], {}).get("fields") != keep["fields"]:
            raise ValueError("Die erhaltene Shopware-Adresse stimmt nicht mit dem bestätigten Vorschlag überein.")
        customer = refs.get(spec["sw_customer"]["ref"], {}).get("fields", {})
        if any(customer.get(key) != value for key, value in spec["defaults"].items()):
            raise ValueError("Die Shopware-Standardadressen sind noch nicht bestätigt.")
        removed = {r["ref"] for r in spec["sw_sources"]}
        for record in before["records"]:
            if record["system"] == "sw" and record["kind"] in ("address", "order") and record["ref"] not in removed:
                if refs.get(record["ref"], {}).get("fields") != record["fields"]:
                    raise ValueError("Andere Adressen oder Bestellanschriften haben sich geändert. Bitte den Stand prüfen.")

    def execute_remote(self, spec):
        from shopware.services import CustomerService
        payload = {
            "keep-defaults": {"entity": "customer", "action": "upsert", "payload": [{"id": spec["sw_customer"]["fields"]["id"], **spec["defaults"]}]},
            "remove-copies": {"entity": "customer_address", "action": "delete", "payload": [{"id": r["fields"]["id"]} for r in spec["sw_sources"]]},
        }
        try:
            # One DAL transaction; no retry after timeouts and no debug dump.
            client = CustomerService().client
            client._get_session()
            response = client.session.post(client._format_admin_api_url('/_action/sync'), json=payload,
                headers={"Content-Type": "application/json", "Accept": "application/json", "single-operation": "1", "fail-on-error": "1"},
                timeout=60, follow_redirects=False)
        except Exception:
            raise ValueError("Der Ausgang der Shopware-Adresszusammenlegung ist unklar. Bitte den Status prüfen; nicht erneut ausführen.") from None
        if 400 <= response.status_code < 500:
            raise AddressConsolidationRejected("Shopware hat die Adresszusammenlegung abgelehnt. Es wurde nichts zusammengeführt; bitte Berechtigungen und Daten prüfen.")
        if not 200 <= response.status_code < 300:
            raise ValueError("Der Ausgang der Shopware-Adresszusammenlegung ist unklar. Bitte den Status prüfen.")
        try:
            result = response.json()
        except Exception:
            raise ValueError("Shopware hat keine lesbare Bestätigung geliefert. Bitte den Status prüfen.") from None
        if not isinstance(result, dict) or result.get("errors") or result.get("notFound"):
            raise ValueError("Shopware hat die Adresszusammenlegung nicht bestätigt. Bitte den Status prüfen.")

    @staticmethod
    def preflight_local(spec):
        from orders.models import Order
        group = [spec["target"], *spec["local_sources"]]
        ids = [r["fields"]["id"] for r in group]
        sw_ids = [r["fields"]["id"] for r in spec["sw_group"]]
        query = Q()
        for identifier in sw_ids:
            query |= Q(api_id__iexact=identifier)
        if sw_ids and Address.objects.filter(query).exclude(pk__in=ids).exists():
            raise ValueError("Eine betroffene Shopware-Adresse ist anderweitig zugeordnet.")
        rows = json.loads(json.dumps(list(Address.objects.filter(pk__in=ids).values()), cls=DjangoJSONEncoder))
        actual = {row["id"]: row for row in rows}
        for record in group:
            fields = record["fields"]
            row = actual.get(fields["id"])
            if not row or any(k not in row or row[k] != v for k, v in fields.items()):
                raise ValueError("Die Bridge-Adressen haben sich geändert. Bitte erneut suchen.")
        source_ids = [r["fields"]["id"] for r in spec["local_sources"]]
        orders = Order.objects.filter(Q(billing_address_id__in=source_ids) | Q(shipping_address_id__in=source_ids)).values("id", "customer_id", "billing_address_id", "shipping_address_id")
        if {r["id"]: r for r in orders} != spec["order_refs"]:
            raise ValueError("Die betroffenen Bestellverweise haben sich geändert. Bitte erneut suchen.")

    def finish_local(self, spec, audit, receipt=lambda: False):
        from orders.models import Order
        ids = [r["fields"]["id"] for r in spec["local_sources"]]
        with transaction.atomic():
            Customer.objects.select_for_update().get(pk=spec["customer"]["fields"]["id"])
            list(Address.objects.select_for_update().filter(customer_id=spec["customer"]["fields"]["id"]))
            list(Order.objects.select_for_update().filter(Q(billing_address_id__in=ids) | Q(shipping_address_id__in=ids)))
            target = Address.objects.get(pk=spec["target"]["fields"]["id"])
            if ids and not Address.objects.filter(pk__in=ids).exists() and receipt():
                expected = {**spec["mapping"], **spec["roles"], "api_id": spec["target"]["fields"].get("api_id"),
                            "customer_id": spec["customer"]["fields"]["id"]}
                if self.local_identity({key: getattr(target, key) for key in self.BUSINESS_FIELDS}) == self.local_identity(spec["target"]["fields"]) and all(getattr(target, key) == value for key, value in expected.items()):
                    return
                raise ValueError("Die bereits zusammengeführte Adresse wurde inzwischen geändert. Bitte manuell prüfen.")
            self.preflight_local(spec)
            Order.objects.filter(billing_address_id__in=ids).update(billing_address_id=target.pk)
            Order.objects.filter(shipping_address_id__in=ids).update(shipping_address_id=target.pk)
            # Record all before/after data on the survivor before deleting copies.
            audit(target)
            Address.objects.filter(pk__in=ids).delete()
            for key, value in {**spec["mapping"], **spec["roles"]}.items():
                setattr(target, key, value)
            target.save()
