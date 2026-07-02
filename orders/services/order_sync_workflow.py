from __future__ import annotations

from typing import Any

from customer.models import Address
from core.services import BaseService
from orders.models import MicrotechOrderSyncWorkflow

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
