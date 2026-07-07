from __future__ import annotations

import logging
from typing import Any

from customer.models import Address
from customer.services.customer_upsert_microtech import CustomerUpsertMicrotechService, _to_int
from core.services import BaseService
from microtech.models import MicrotechGraphQLJob
from microtech.services import MicrotechJobSentinelService
from microtech.services.graphql_client import MicrotechGraphQLClientService
from orders.models import MicrotechOrderSyncWorkflow
from orders.services.order_rule_resolver import OrderRuleResolverService
from orders.services.order_upsert_microtech import OrderUpsertMicrotechService

CONTINUATION_NAME = "microtech_order_sync_advance"

logger = logging.getLogger(__name__)

# Fehlermeldungs-Fragmente, die einen Probe-Fehlschlag als fachliches
# "nicht gefunden" (Branch) statt als technischen Fehler kennzeichnen.
NOT_FOUND_FRAGMENTS = ("nicht gefunden", "not found", "wurde nicht gefunden")


class OrderSyncWorkflowService(BaseService):
    """Verwaltet den schrittweisen Ablauf der Microtech-Auftrags- und Kundensynchronisierung."""

    model = MicrotechOrderSyncWorkflow

    STEP_ORDER = (
        "probe_customer",
        "write_customer",
        "shipping_address",
        "shipping_contact",
        "billing_address",
        "billing_contact",
        "clear_default_shipping_address",
        "clear_default_billing_address",
        "set_default_addresses",
        "writeback_adrnr",
        "probe_vorgang",
        "write_vorgang",
    )

    def _completed_steps(self, workflow: MicrotechOrderSyncWorkflow) -> set[str]:
        """Gibt die Menge aller bereits abgeschlossenen Step-Keys zurück."""
        return {
            str(entry.get("step"))
            for entry in (workflow.step_log or [])
            if entry.get("status") == "completed"
        }

    def _is_step_applicable(self, workflow: MicrotechOrderSyncWorkflow, step: str) -> bool:
        """Prüft anhand des Workflow-Zustands, ob ein Step ausgeführt werden soll."""
        state = workflow.state or {}
        if step in ("billing_address", "billing_contact"):
            # Rechnungsadresse identisch mit Lieferadresse → überspringen
            return not bool(state.get("billing_same_as_shipping"))
        if step == "writeback_adrnr":
            # Adressnummer-Rückschreiben nur bei Neukunden
            return bool(state.get("is_new_customer"))
        if step == "probe_vorgang":
            # Vorgang sondieren nur wenn bereits eine ERP-Auftragsnummer vorhanden
            return bool(str(state.get("erp_order_id") or "").strip())
        if step == "clear_default_shipping_address":
            old_shipping = _to_int(state.get("existing_default_shipping_ans_nr")) or 0
            shipping_ans_nr, _billing_ans_nr = self._target_default_ans_nrs(workflow)
            return old_shipping > 0 and old_shipping != shipping_ans_nr
        if step == "clear_default_billing_address":
            old_billing = _to_int(state.get("existing_default_billing_ans_nr")) or 0
            _shipping_ans_nr, billing_ans_nr = self._target_default_ans_nrs(workflow)
            return old_billing > 0 and old_billing != billing_ans_nr
        return True

    def next_step(self, workflow: MicrotechOrderSyncWorkflow) -> str | None:
        """Liefert den nächsten ausstehenden und anwendbaren Step-Key, oder None wenn fertig."""
        done = self._completed_steps(workflow)
        for step in self.STEP_ORDER:
            if step in done:
                continue
            if self._is_step_applicable(workflow, step):
                return step
        return None

    def _resolve_addresses(self, order) -> tuple[Address, Address]:
        """Ermittelt Liefer- und Rechnungsadresse aus den Order-eigenen FKs."""
        # Order trägt shipping_address/billing_address selbst (orders/tests.py:56).
        shipping = order.shipping_address or order.customer.shipping_address
        if shipping is None:
            raise ValueError("Order hat keine Lieferadresse zum Synchronisieren.")
        billing = order.billing_address or shipping
        return shipping, billing

    def _target_default_ans_nrs(self, workflow: MicrotechOrderSyncWorkflow) -> tuple[int, int]:
        """Liefert die Ziel-AnsNr für Standard-Liefer- und Rechnungsanschrift."""
        shipping, billing = self._resolve_addresses(workflow.order)
        state = workflow.state or {}
        shipping_ans_nr = int(state.get("shipping_ans_nr") or 0) or (_to_int(shipping.erp_ans_nr) or 0)
        billing_ans_nr = (
            int(state.get("billing_ans_nr") or 0) or (_to_int(billing.erp_ans_nr) or 0) or shipping_ans_nr
        )
        return shipping_ans_nr, billing_ans_nr

    @staticmethod
    def _remember_existing_default_ans_nrs(state: dict[str, Any], customer: dict[str, Any]) -> None:
        """Merkt sich vorhandene Microtech-Default-Flags für späteres Zurücksetzen."""
        shipping_ans_nr = _to_int(customer.get("defaultShippingAddressNumber")) or 0
        billing_ans_nr = _to_int(customer.get("defaultBillingAddressNumber")) or 0

        for address in customer.get("addresses") or []:
            if not isinstance(address, dict):
                continue
            ans_nr = _to_int(address.get("addressSubNumber")) or 0
            if ans_nr <= 0:
                continue
            if address.get("isDefaultShipping"):
                shipping_ans_nr = ans_nr
            if address.get("isDefaultBilling"):
                billing_ans_nr = ans_nr

        if shipping_ans_nr > 0:
            state["existing_default_shipping_ans_nr"] = shipping_ans_nr
        if billing_ans_nr > 0:
            state["existing_default_billing_ans_nr"] = billing_ans_nr

    @staticmethod
    def _beleg_nr_from_vorgang_result(result: dict[str, Any] | None) -> str:
        """Liest die Microtech-BelegNr aus Polling- und Webhook-Payloads."""
        from customer.services.customer_upsert_microtech import _to_str

        def extract(node: Any) -> str:
            if not isinstance(node, dict):
                return ""
            vorgang = node.get("vorgang")
            if isinstance(vorgang, dict):
                beleg = _to_str(vorgang.get("belegNr"))
                if beleg:
                    return beleg
            return _to_str(node.get("belegNr"))

        root = result if isinstance(result, dict) else {}
        data = root.get("data") if isinstance(root.get("data"), dict) else {}
        for container in (root, data):
            for key in ("", "vorgangJob", "requestVorgang", "createVorgang", "updateVorgang"):
                node = container if not key else container.get(key)
                beleg = extract(node)
                if beleg:
                    return beleg
        return ""

    def _build_customer_service(self) -> CustomerUpsertMicrotechService:
        """Erzeugt den bestehenden Customer-Upsert-Service für Payload-Builder-Reuse."""
        return CustomerUpsertMicrotechService()

    def start_for_order(self, order) -> MicrotechOrderSyncWorkflow:
        """Legt einen Workflow für eine Bestellung an und startet den ersten Schritt."""
        active = MicrotechOrderSyncWorkflow.objects.filter(
            order=order,
            status__in=MicrotechOrderSyncWorkflow.ACTIVE_STATUSES,
        ).first()
        if active is not None:
            raise ValueError(f"Für Bestellung {order.pk} läuft bereits ein Sync-Workflow (#{active.pk}).")

        if order.customer is None:
            raise ValueError("Order hat keinen Kunden zum Synchronisieren.")

        shipping, billing = self._resolve_addresses(order)
        erp_nr = (order.customer.erp_nr or "").strip()
        address_number = _to_int(erp_nr)
        if address_number is None:
            raise ValueError("Order-Kunde hat keine numerische erp_nr; GraphQL-Upsert erfordert eine Adressnummer.")

        workflow = MicrotechOrderSyncWorkflow.objects.create(
            order=order,
            status=MicrotechOrderSyncWorkflow.Status.RUNNING,
            state={
                "erp_nr": erp_nr,
                "address_number": address_number,
                "billing_same_as_shipping": billing.pk == shipping.pk,
                "erp_order_id": (order.erp_order_id or "").strip(),
            },
        )
        logger.info(
            "Order-Sync-Workflow #%s für Bestellung %s (erp_nr=%s) gestartet.", workflow.pk, order.pk, erp_nr
        )
        self._advance(workflow)
        return workflow

    # --- Ergebnis-Anwendung -------------------------------------------------

    def _apply_result(
        self,
        workflow: MicrotechOrderSyncWorkflow,
        step: str,
        result: dict[str, Any],
        job: MicrotechGraphQLJob | None = None,
    ) -> None:
        """Überträgt das Job-Ergebnis in den Workflow-Zustand."""
        from customer.services.customer_upsert_microtech import _to_int

        state = dict(workflow.state or {})
        if step == "probe_customer":
            customer = (result or {}).get("customer") or {}
            found = bool(customer.get("customerNumber"))
            state["is_new_customer"] = not found
            if found:
                state["address_number"] = _to_int(customer.get("erpAddressNumber")) or state.get("address_number")
                self._remember_existing_default_ans_nrs(state, customer)
        elif step == "write_customer":
            customer = (result or {}).get("customer") or {}
            state["address_number"] = _to_int(customer.get("erpAddressNumber")) or state.get("address_number")
        elif step in ("shipping_address", "billing_address"):
            shipping, billing = self._resolve_addresses(workflow.order)
            address = shipping if step == "shipping_address" else billing
            sub = self._address_sub_number_from_result(
                result,
                step=step,
                address=address,
                operation=job.operation if job else "",
            )
            key = "shipping_ans_nr" if step == "shipping_address" else "billing_ans_nr"
            if sub:
                state[key] = sub
                self._persist_address_sub_number(workflow=workflow, address=address, sub_number=sub, result=result)
            if step == "shipping_address" and state.get("billing_same_as_shipping"):
                state["billing_ans_nr"] = state.get("shipping_ans_nr")
        elif step in ("shipping_contact", "billing_contact"):
            shipping, billing = self._resolve_addresses(workflow.order)
            address = shipping if step == "shipping_contact" else billing
            sub_key = "shipping_ans_nr" if step == "shipping_contact" else "billing_ans_nr"
            address_step = "shipping_address" if step == "shipping_contact" else "billing_address"
            sub = int(state.get(sub_key) or 0) or self._address_sub_number_from_result(
                result,
                step=address_step,
                address=address,
                operation=job.operation if job else "",
            )
            if sub:
                state[sub_key] = sub
                self._persist_address_sub_number(workflow=workflow, address=address, sub_number=sub, result=result)
            contact_number = self._contact_number_from_result(result, address_sub_number=sub or None)
            if contact_number:
                self._persist_contact_number(address=address, contact_number=contact_number)
        elif step == "probe_vorgang":
            beleg = self._beleg_nr_from_vorgang_result(result)
            if beleg:
                state["beleg_nr"] = beleg
                state["erp_order_id"] = beleg
        elif step == "write_vorgang":
            beleg = self._beleg_nr_from_vorgang_result(result) or state.get("beleg_nr", "")
            state["beleg_nr"] = beleg
            if beleg:
                state["erp_order_id"] = beleg
                OrderUpsertMicrotechService()._persist_erp_order_id(order=workflow.order, erp_order_id=beleg)
        workflow.state = state

    # --- Continuation -------------------------------------------------------

    def advance(self, job) -> None:
        """Continuation-Handler: wendet Job-Ergebnis an und treibt die Sync-Kette weiter."""
        from django.db import transaction

        workflow_id = int((job.context or {}).get("workflow_id") or 0)
        step = str((job.context or {}).get("step") or "")
        if not workflow_id or not step:
            return
        with transaction.atomic():
            workflow = (
                MicrotechOrderSyncWorkflow.objects.select_for_update()
                .filter(pk=workflow_id)
                .first()
            )
            if workflow is None or workflow.current_step != step:
                return
            self._apply_result(workflow, step, job.result_payload or {}, job=job)
            self._log_step(workflow, step, "completed")
            workflow.error_message = ""
            workflow.save(update_fields=("state", "step_log", "error_message", "updated_at"))
        self._advance(workflow)

    def _advance(self, workflow: MicrotechOrderSyncWorkflow) -> None:
        """Schleife: lokale Steps inline ausführen, Remote-Steps submitten, sonst SUCCEEDED setzen."""
        while True:
            step = self.next_step(workflow)
            if step is None:
                workflow.status = MicrotechOrderSyncWorkflow.Status.SUCCEEDED
                workflow.current_step = ""
                workflow.current_job = None
                workflow.save(update_fields=("status", "current_step", "current_job", "updated_at"))
                logger.info("Order-Sync-Workflow #%s für Bestellung %s erfolgreich abgeschlossen.", workflow.pk, workflow.order_id)
                return
            if step == "writeback_adrnr":
                try:
                    self._run_local_step(workflow, step)
                except Exception as exc:
                    self._mark_step_failed(workflow, step, exc)
                    raise
                self._log_step(workflow, step, "completed")
                workflow.save(update_fields=("state", "step_log", "updated_at"))
                logger.info("Order-Sync-Workflow #%s: lokaler Schritt '%s' abgeschlossen.", workflow.pk, step)
                continue
            try:
                self.submit_step(workflow, step)
            except Exception as exc:
                self._mark_step_failed(workflow, step, exc)
                raise
            return

    def _mark_step_failed(self, workflow: MicrotechOrderSyncWorkflow, step: str, exc: Exception) -> None:
        """Setzt den Workflow auf FAILED, damit er nicht aktiv hängen bleibt und resumebar ist."""
        logger.exception("Order-Sync-Workflow #%s: Schritt '%s' fehlgeschlagen.", workflow.pk, step)
        workflow.status = MicrotechOrderSyncWorkflow.Status.FAILED
        workflow.current_step = step
        workflow.error_message = str(exc)
        self._log_step(workflow, step, "failed", error=str(exc))
        workflow.save(update_fields=("status", "current_step", "error_message", "step_log", "updated_at"))

    def submit_step(self, workflow: MicrotechOrderSyncWorkflow, step: str) -> MicrotechGraphQLJob:
        """Submittet einen Customer-Remote-Step an den Sentinel."""
        order = workflow.order
        shipping, billing = self._resolve_addresses(order)
        state = workflow.state or {}
        address_number = int(state.get("address_number") or 0)
        customer_service = self._build_customer_service()
        client = MicrotechGraphQLClientService()

        kind = MicrotechGraphQLJob.Kind.CUSTOMER_UPSERT
        if step == "probe_customer":
            kind = MicrotechGraphQLJob.Kind.CUSTOMER_READ
            operation = "requestCustomer"
            submit = lambda: client.submit_request_customer(state["erp_nr"])
            payload = {"customerNumber": state["erp_nr"]}
        elif step == "write_customer":
            operation = "upsertCustomer"
            input_data = customer_service._build_customer_input(customer=order.customer, address=shipping)
            submit = lambda: client.submit_upsert_customer(state["erp_nr"], input_data)
            payload = {"customerNumber": state["erp_nr"], "input": input_data}
        elif step in ("shipping_address", "billing_address"):
            address = shipping if step == "shipping_address" else billing
            is_shipping = step == "shipping_address"
            sub_number = _to_int(address.erp_ans_nr) or self._copy_matching_anschrift_identity(address)
            input_data = customer_service._build_postal_address_input(
                address=address,
                is_shipping=is_shipping,
                is_invoice=not is_shipping or bool(state.get("billing_same_as_shipping")),
                na1_mode="auto",
                na1_static_value="",
            )
            operation = "updatePostalAddress" if sub_number else "createPostalAddress"
            if sub_number:
                submit = lambda: client.submit_update_postal_address(address_number, sub_number, input_data)
                payload = {"addressNumber": address_number, "addressSubNumber": sub_number, "input": input_data}
            else:
                submit = lambda: client.submit_create_postal_address(address_number, input_data)
                payload = {"addressNumber": address_number, "input": input_data}
        elif step in ("shipping_contact", "billing_contact"):
            address = shipping if step == "shipping_contact" else billing
            sub_key = "shipping_ans_nr" if step == "shipping_contact" else "billing_ans_nr"
            sub_number = int(state.get(sub_key) or 0) or (_to_int(address.erp_ans_nr) or 0)
            if sub_number <= 0:
                sub_number = self._copy_matching_anschrift_identity(address) or 0
            if sub_number <= 0:
                address_step = "shipping_address" if step == "shipping_contact" else "billing_address"
                current_job = workflow.current_job
                if current_job is not None:
                    sub_number = self._address_sub_number_from_result(
                        current_job.result_payload or {},
                        step=address_step,
                        address=address,
                        operation=current_job.operation,
                    ) or 0
                    if sub_number > 0:
                        state = dict(state)
                        state[sub_key] = sub_number
                        workflow.state = state
                        self._persist_address_sub_number(
                            workflow=workflow,
                            address=address,
                            sub_number=sub_number,
                            result=current_job.result_payload or {},
                        )
                        workflow.save(update_fields=("state", "updated_at"))
            if sub_number <= 0:
                raise ValueError(
                    f"{step} ohne bekannte Anschrift-Nummer (weder im Workflow-Zustand noch an der Adresse persistiert)."
                )
            input_data = customer_service._build_contact_person_input(address=address)
            contact_number = _to_int(address.erp_asp_nr)
            operation = "updateContactPerson" if contact_number else "createContactPerson"
            if contact_number:
                submit = lambda: client.submit_update_contact_person(
                    address_number,
                    sub_number,
                    contact_number,
                    input_data,
                )
                payload = {
                    "addressNumber": address_number,
                    "addressSubNumber": sub_number,
                    "contactNumber": contact_number,
                    "input": input_data,
                }
            else:
                submit = lambda: client.submit_create_contact_person(address_number, sub_number, input_data)
                payload = {"addressNumber": address_number, "addressSubNumber": sub_number, "input": input_data}
        elif step in ("clear_default_shipping_address", "clear_default_billing_address"):
            operation = "updatePostalAddress"
            if step == "clear_default_shipping_address":
                sub_number = _to_int(state.get("existing_default_shipping_ans_nr")) or 0
                input_data = {"isDefaultShipping": False}
            else:
                sub_number = _to_int(state.get("existing_default_billing_ans_nr")) or 0
                input_data = {"isDefaultBilling": False}
            if sub_number <= 0:
                raise ValueError(f"{step} ohne bekannte alte Standard-Anschrift.")
            submit = lambda: client.submit_update_postal_address(address_number, sub_number, input_data)
            payload = {"addressNumber": address_number, "addressSubNumber": sub_number, "input": input_data}
        elif step == "set_default_addresses":
            operation = "updateCustomer"
            shipping_ans_nr, billing_ans_nr = self._target_default_ans_nrs(workflow)
            if shipping_ans_nr <= 0:
                raise ValueError(
                    "set_default_addresses ohne bekannte Anschrift-Nummer (weder im Workflow-Zustand "
                    "noch an der Adresse persistiert)."
                )
            input_data = {
                "defaultShippingAddressNumber": shipping_ans_nr,
                "defaultBillingAddressNumber": billing_ans_nr,
            }
            submit = lambda: client.submit_update_customer(state["erp_nr"], input_data)
            payload = {"customerNumber": state["erp_nr"], "input": input_data}
        else:
            return self._submit_order_step(workflow, step)

        job = MicrotechJobSentinelService().submit_wrapper_job(
            kind=kind,
            operation=operation,
            submit=submit,
            request_payload=payload,
            context={"workflow_id": workflow.pk, "step": step},
            continuation=CONTINUATION_NAME,
            next_step=f"Microtech {operation} ({step}).",
        )
        workflow.status = MicrotechOrderSyncWorkflow.Status.WAITING
        workflow.current_step = step
        update_fields = ["status", "current_step", "updated_at"]
        if isinstance(job, MicrotechGraphQLJob):
            workflow.current_job = job
            update_fields.append("current_job")
        workflow.save(update_fields=update_fields)
        return job

    def _run_local_step(self, workflow: MicrotechOrderSyncWorkflow, step: str) -> None:
        """Führt lokale Workflow-Schritte ohne Sentinel-Job aus."""
        if step == "writeback_adrnr":
            CustomerUpsertMicrotechService()._sync_new_customer_number_to_shopware(
                customer=workflow.order.customer,
                erp_nr=(workflow.state or {}).get("erp_nr", ""),
            )
            return
        raise ValueError(f"Unbekannter lokaler Step: {step}")

    def _submit_order_step(self, workflow: MicrotechOrderSyncWorkflow, step: str) -> MicrotechGraphQLJob:
        """Submittet einen Order-Remote-Step an den Sentinel."""
        order = workflow.order
        state = workflow.state or {}
        client = MicrotechGraphQLClientService()

        if step == "probe_vorgang":
            beleg = (state.get("erp_order_id") or "").strip()
            operation = "requestVorgang"
            submit = lambda: client.submit_request_vorgang(beleg)
            payload = {"belegNr": beleg}
            kind = MicrotechGraphQLJob.Kind.ORDER_READ
        elif step == "write_vorgang":
            upsert = OrderUpsertMicrotechService()
            resolved_rule = OrderRuleResolverService().resolve_for_order(order=order)
            positions, _rule_debug = upsert._build_graphql_positions(
                order=order,
                resolved_rule=resolved_rule,
                client=client,
            )
            defaults = upsert._load_order_defaults()
            order_type_number = upsert._coerce_positive_int(
                resolved_rule.vorgangsart_id,
                defaults.order_type_number,
            )
            input_data = {
                "orderNumber": (order.order_number or "").strip() or (order.api_id or "").strip(),
                "description": order.description or f"Shopware Bestellung {order.order_number}",
                "currency": "EUR",
                "positions": positions,
            }
            beleg = (state.get("beleg_nr") or "").strip()
            kind = MicrotechGraphQLJob.Kind.ORDER_UPSERT
            if beleg:
                operation = "updateVorgang"
                submit = lambda: client.submit_update_vorgang(beleg, input_data)
                payload = {"belegNr": beleg, "input": input_data}
            else:
                operation = "createVorgang"
                create_input = {
                    **input_data,
                    "vorgangArt": order_type_number,
                    "customerNumber": order.customer.erp_nr,
                }
                submit = lambda: client.submit_create_vorgang(create_input)
                payload = {"input": create_input}
        else:
            raise ValueError(f"Unbekannter Order-Step: {step}")

        job = MicrotechJobSentinelService().submit_wrapper_job(
            kind=kind,
            operation=operation,
            submit=submit,
            request_payload=payload,
            context={"workflow_id": workflow.pk, "step": step},
            continuation=CONTINUATION_NAME,
            next_step=f"Microtech {operation} ({step}).",
        )
        workflow.status = MicrotechOrderSyncWorkflow.Status.WAITING
        workflow.current_step = step
        update_fields = ["status", "current_step", "updated_at"]
        if isinstance(job, MicrotechGraphQLJob):
            workflow.current_job = job
            update_fields.append("current_job")
        workflow.save(update_fields=update_fields)
        return job

    def _log_step(self, workflow: MicrotechOrderSyncWorkflow, step: str, status: str, error: str = "") -> None:
        """Hängt einen Eintrag an das Step-Log des Workflows an (completed wird dedupliziert)."""
        from django.utils import timezone

        log = list(workflow.step_log or [])
        if status == "completed" and any(
            entry.get("step") == step and entry.get("status") == "completed" for entry in log
        ):
            return
        log.append({"step": step, "status": status, "at": timezone.now().isoformat(), "error": error})
        workflow.step_log = log

    def _apply_probe_not_found(self, workflow: MicrotechOrderSyncWorkflow, step: str) -> None:
        """Wendet das fachliche Nicht-gefunden-Ergebnis eines Probe-Schritts an."""
        state = dict(workflow.state or {})
        if step == "probe_customer":
            state["is_new_customer"] = True
        workflow.state = state

    @staticmethod
    def _address_sub_number_from_result(
        result: dict[str, Any],
        *,
        step: str,
        address: Address,
        operation: str = "",
    ) -> int | None:
        postal = (result or {}).get("postalAddress") or {}
        sub = _to_int(postal.get("addressSubNumber"))
        if sub:
            return sub

        contact = (result or {}).get("contactPerson") or {}
        sub = _to_int(contact.get("addressSubNumber"))
        if sub:
            return sub

        addresses = ((result or {}).get("customer") or {}).get("addresses") or []
        flag = "isDefaultShipping" if step == "shipping_address" else "isDefaultBilling"
        for candidate in addresses:
            candidate_sub = _to_int((candidate or {}).get("addressSubNumber"))
            if candidate_sub and candidate.get(flag):
                return candidate_sub
        if len(addresses) == 1:
            return _to_int((addresses[0] or {}).get("addressSubNumber")) or _to_int(address.erp_ans_nr)
        return _to_int(address.erp_ans_nr) or (1 if operation == "createPostalAddress" else None)

    @staticmethod
    def _persist_address_sub_number(
        *,
        workflow: MicrotechOrderSyncWorkflow,
        address: Address,
        sub_number: int,
        result: dict[str, Any],
    ) -> None:
        postal = (result or {}).get("postalAddress") or {}
        contact = (result or {}).get("contactPerson") or {}
        CustomerUpsertMicrotechService()._persist_anschrift_identity(
            erp_nr=str(
                _to_int(postal.get("addressNumber"))
                or _to_int(contact.get("addressNumber"))
                or (workflow.state or {}).get("address_number")
                or address.erp_nr
                or ""
            ),
            address=address,
            ans_id=address.erp_ans_id,
            ans_nr=sub_number,
        )

    @staticmethod
    def _copy_matching_anschrift_identity(address: Address) -> int | None:
        if not address.street or not address.postal_code:
            return None
        sibling = (
            Address.objects.filter(
                customer=address.customer,
                street=address.street,
                postal_code=address.postal_code,
                city=address.city,
                country_code=address.country_code,
                erp_ans_nr__isnull=False,
            )
            .exclude(pk=address.pk)
            .order_by("-updated_at")
            .first()
        )
        if sibling is None:
            return None

        CustomerUpsertMicrotechService()._persist_anschrift_identity(
            erp_nr=str(sibling.erp_nr or address.customer.erp_nr or ""),
            address=address,
            ans_id=sibling.erp_ans_id,
            ans_nr=sibling.erp_ans_nr,
        )
        return sibling.erp_ans_nr

    @staticmethod
    def _contact_number_from_result(result: dict[str, Any], *, address_sub_number: int | None = None) -> int | None:
        contact = (result or {}).get("contactPerson") or {}
        contact_number = _to_int(contact.get("contactNumber"))
        if contact_number:
            return contact_number

        postal = (result or {}).get("postalAddress") or {}
        postal_sub = _to_int(postal.get("addressSubNumber"))
        if address_sub_number is None or not postal_sub or postal_sub == address_sub_number:
            contact_number = OrderSyncWorkflowService._contact_number_from_contacts(postal.get("contacts") or [])
            if contact_number:
                return contact_number

        addresses = ((result or {}).get("customer") or {}).get("addresses") or []
        for candidate in addresses:
            if address_sub_number is not None and _to_int((candidate or {}).get("addressSubNumber")) != address_sub_number:
                continue
            contact_number = OrderSyncWorkflowService._contact_number_from_contacts((candidate or {}).get("contacts") or [])
            if contact_number:
                return contact_number
        return None

    @staticmethod
    def _contact_number_from_contacts(contacts: list[dict[str, Any]]) -> int | None:
        for contact in contacts:
            if (contact or {}).get("isDefault"):
                contact_number = _to_int((contact or {}).get("contactNumber"))
                if contact_number:
                    return contact_number
        if len(contacts) == 1:
            return _to_int((contacts[0] or {}).get("contactNumber"))
        return None

    @staticmethod
    def _persist_contact_number(*, address: Address, contact_number: int) -> None:
        CustomerUpsertMicrotechService()._persist_ansprechpartner_identity(
            address=address,
            asp_id=contact_number,
            asp_nr=contact_number,
        )

    @staticmethod
    def _looks_like_not_found_error(message: str) -> bool:
        lowered = str(message or "").lower()
        return any(fragment in lowered for fragment in NOT_FOUND_FRAGMENTS)

    def reconcile_failures(self) -> int:
        """Verarbeitet terminale fehlgeschlagene Jobs wartender Workflows."""
        from django.db import transaction

        changed = 0
        waiting = list(
            MicrotechOrderSyncWorkflow.objects.filter(
                status=MicrotechOrderSyncWorkflow.Status.WAITING,
                current_job__isnull=False,
            ).select_related("current_job")
        )
        for workflow in waiting:
            job = workflow.current_job
            if job is None or not job.is_terminal:
                continue
            if job.status == MicrotechGraphQLJob.Status.SUCCEEDED:
                continue

            step = workflow.current_step
            if step in ("probe_customer", "probe_vorgang") and self._looks_like_not_found_error(job.error_message):
                with transaction.atomic():
                    wf = MicrotechOrderSyncWorkflow.objects.select_for_update().get(pk=workflow.pk)
                    self._apply_probe_not_found(wf, step)
                    self._log_step(wf, step, "completed", error="probe-not-found")
                    wf.save(update_fields=("state", "step_log", "updated_at"))
                logger.info(
                    "Order-Sync-Workflow #%s: Probe '%s' als 'nicht gefunden' verbucht.", workflow.pk, step
                )
                try:
                    self._advance(MicrotechOrderSyncWorkflow.objects.get(pk=workflow.pk))
                except Exception:
                    # _advance hat den Workflow bereits FAILED markiert und geloggt;
                    # die übrigen Workflows sollen trotzdem reconciled werden.
                    pass
                changed += 1
                continue

            if step in ("probe_customer", "probe_vorgang"):
                logger.warning(
                    "Order-Sync-Workflow #%s: Probe-Fehler nicht als 'nicht gefunden' erkennbar, "
                    "Workflow wird FAILED markiert: %s",
                    workflow.pk,
                    job.error_message,
                )

            with transaction.atomic():
                wf = MicrotechOrderSyncWorkflow.objects.select_for_update().get(pk=workflow.pk)
                wf.status = MicrotechOrderSyncWorkflow.Status.FAILED
                wf.error_message = job.error_message or "Microtech-Job fehlgeschlagen."
                self._log_step(wf, step, "failed", error=wf.error_message)
                wf.save(update_fields=("status", "error_message", "step_log", "updated_at"))
            logger.error(
                "Order-Sync-Workflow #%s: Schritt '%s' fehlgeschlagen: %s", workflow.pk, step, wf.error_message
            )
            changed += 1
        if changed:
            logger.info("Order-Sync-Reconcile: %s Workflow(s) verarbeitet.", changed)
        return changed

    def resume(self, workflow: MicrotechOrderSyncWorkflow) -> MicrotechGraphQLJob | None:
        """Startet den aktuellen fehlgeschlagenen Workflow-Schritt erneut."""
        if workflow.status != MicrotechOrderSyncWorkflow.Status.FAILED:
            return None

        workflow.error_message = ""
        workflow.save(update_fields=("error_message", "updated_at"))
        logger.info("Order-Sync-Workflow #%s wird fortgesetzt (Schritt '%s').", workflow.pk, workflow.current_step)

        step = workflow.current_step
        # Bereits erledigte oder lokale Steps nicht erneut submitten,
        # sondern die Kette regulär über den Resolver weitertreiben.
        if not step or step in self._completed_steps(workflow) or step == "writeback_adrnr":
            self._advance(workflow)
            return workflow.current_job

        return self.submit_step(workflow, step)
