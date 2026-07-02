from __future__ import annotations

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
        self._advance(workflow)
        return workflow

    # --- Ergebnis-Anwendung -------------------------------------------------

    def _apply_result(self, workflow: MicrotechOrderSyncWorkflow, step: str, result: dict[str, Any]) -> None:
        """Überträgt das Job-Ergebnis in den Workflow-Zustand."""
        from customer.services.customer_upsert_microtech import _to_int, _to_str

        state = dict(workflow.state or {})
        if step == "probe_customer":
            customer = (result or {}).get("customer") or {}
            found = bool(customer.get("customerNumber"))
            state["is_new_customer"] = not found
            if found:
                state["address_number"] = _to_int(customer.get("erpAddressNumber")) or state.get("address_number")
        elif step == "write_customer":
            customer = (result or {}).get("customer") or {}
            state["address_number"] = _to_int(customer.get("erpAddressNumber")) or state.get("address_number")
        elif step in ("shipping_address", "billing_address"):
            postal = (result or {}).get("postalAddress") or {}
            sub = _to_int(postal.get("addressSubNumber"))
            key = "shipping_ans_nr" if step == "shipping_address" else "billing_ans_nr"
            if sub:
                state[key] = sub
            if step == "shipping_address" and state.get("billing_same_as_shipping"):
                state["billing_ans_nr"] = state.get("shipping_ans_nr")
        elif step == "probe_vorgang":
            vorgang = (result or {}).get("vorgang") or {}
            beleg = _to_str(vorgang.get("belegNr"))
            if beleg:
                state["beleg_nr"] = beleg
        elif step == "write_vorgang":
            vorgang = (result or {}).get("vorgang") or {}
            beleg = _to_str(vorgang.get("belegNr")) or state.get("beleg_nr", "")
            state["beleg_nr"] = beleg
            if beleg:
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
            self._apply_result(workflow, step, job.result_payload or {})
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
                return
            if step == "writeback_adrnr":
                self._run_local_step(workflow, step)
                self._log_step(workflow, step, "completed")
                workflow.save(update_fields=("state", "step_log", "updated_at"))
                continue
            self.submit_step(workflow, step)
            return

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
            operation = "createCustomer" if state.get("is_new_customer") else "updateCustomer"
            input_data = customer_service._build_customer_input(customer=order.customer, address=shipping)
            if state.get("is_new_customer"):
                submit = lambda: client.submit_create_customer(state["erp_nr"], input_data)
            else:
                submit = lambda: client.submit_update_customer(state["erp_nr"], input_data)
            payload = {"customerNumber": state["erp_nr"], "input": input_data}
        elif step in ("shipping_address", "billing_address"):
            address = shipping if step == "shipping_address" else billing
            is_shipping = step == "shipping_address"
            input_data = customer_service._build_postal_address_input(
                address=address,
                is_shipping=is_shipping,
                is_invoice=not is_shipping or bool(state.get("billing_same_as_shipping")),
                na1_mode="auto",
                na1_static_value="",
            )
            sub_number = _to_int(address.erp_ans_nr)
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
            sub_number = int(state.get(sub_key) or 0)
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
        elif step == "set_default_addresses":
            operation = "updateCustomer"
            input_data = {
                "defaultShippingAddressNumber": int(state.get("shipping_ans_nr") or 0),
                "defaultBillingAddressNumber": int(state.get("billing_ans_nr") or state.get("shipping_ans_nr") or 0),
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
        """Hängt einen Eintrag an das Step-Log des Workflows an."""
        from django.utils import timezone

        log = list(workflow.step_log or [])
        log.append({"step": step, "status": status, "at": timezone.now().isoformat(), "error": error})
        workflow.step_log = log

    def _apply_probe_not_found(self, workflow: MicrotechOrderSyncWorkflow, step: str) -> None:
        """Wendet das fachliche Nicht-gefunden-Ergebnis eines Probe-Schritts an."""
        state = dict(workflow.state or {})
        if step == "probe_customer":
            state["is_new_customer"] = True
        workflow.state = state

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
            if step in ("probe_customer", "probe_vorgang"):
                with transaction.atomic():
                    wf = MicrotechOrderSyncWorkflow.objects.select_for_update().get(pk=workflow.pk)
                    self._apply_probe_not_found(wf, step)
                    self._log_step(wf, step, "completed", error="probe-not-found")
                    wf.save(update_fields=("state", "step_log", "updated_at"))
                self._advance(MicrotechOrderSyncWorkflow.objects.get(pk=workflow.pk))
                changed += 1
                continue

            with transaction.atomic():
                wf = MicrotechOrderSyncWorkflow.objects.select_for_update().get(pk=workflow.pk)
                wf.status = MicrotechOrderSyncWorkflow.Status.FAILED
                wf.error_message = job.error_message or "Microtech-Job fehlgeschlagen."
                self._log_step(wf, step, "failed", error=wf.error_message)
                wf.save(update_fields=("status", "error_message", "step_log", "updated_at"))
            changed += 1
        return changed

    def resume(self, workflow: MicrotechOrderSyncWorkflow) -> MicrotechGraphQLJob | None:
        """Startet den aktuellen fehlgeschlagenen Workflow-Schritt erneut."""
        if workflow.status != MicrotechOrderSyncWorkflow.Status.FAILED:
            return None

        step = workflow.current_step
        if not step:
            workflow.error_message = ""
            workflow.save(update_fields=("error_message", "updated_at"))
            self._advance(workflow)
            return workflow.current_job

        workflow.error_message = ""
        workflow.save(update_fields=("error_message", "updated_at"))
        return self.submit_step(workflow, step)
