"""Non-mutating rule preview for a concrete order."""
from __future__ import annotations

from typing import Any

from core.services import BaseService
from microtech.models import MicrotechSettings, MicrotechOrderRule, RuleEngineExecutionLog
from microtech.rule_engine.address_resolver import ADDRESS_WRITE_TASK
from microtech.rule_engine.customer_resolver import CUSTOMER_WRITE_TASK, CustomerRuleContext
from microtech.rule_engine.execution import RuleExecutionService
from microtech.rule_engine.order_resolver import ORDER_CREATE_TASK
from orders.models import Order
from orders.services.order_sync_workflow import OrderSyncWorkflowService


class OrderRuleTesterService(BaseService):
    """Explain exactly what the rule engine would do for one order."""

    model = Order

    def preview(self, *, order: Order) -> list[dict[str, Any]]:
        if order.customer_id is None:
            raise ValueError("Die Bestellung hat keinen Kunden.")
        shipping, billing = OrderSyncWorkflowService()._resolve_addresses(order)
        settings = MicrotechSettings.load()
        engine = RuleExecutionService()
        sections = (
            (
                "Kunde schreiben",
                CUSTOMER_WRITE_TASK,
                settings.rule_engine_customer_mode,
                CustomerRuleContext(
                    customer=order.customer,
                    shipping_address=shipping,
                    billing_address=billing,
                ),
            ),
            ("Lieferanschrift schreiben", ADDRESS_WRITE_TASK, settings.rule_engine_address_mode, shipping),
            ("Rechnungsanschrift schreiben", ADDRESS_WRITE_TASK, settings.rule_engine_address_mode, billing),
            ("Vorgang schreiben", ORDER_CREATE_TASK, settings.rule_engine_order_mode, order),
        )
        result: list[dict[str, Any]] = []
        for title, task_name, mode, context in sections:
            # The tester is a *theoretical* preview: it must show whether each
            # rule's conditions would match, independent of the live engine
            # mode. Evaluating with the real mode (e.g. OFF) would short-circuit
            # every rule to "Engine-Modus aus" and hide exactly what we want to
            # inspect. We therefore evaluate as if LIVE and surface the real
            # configured mode separately for context.
            evaluations = [
                self._serialize(evaluation)
                for evaluation in engine.inspect_rules(
                    task_name=task_name,
                    phase=MicrotechOrderRule.ExecutionPhase.BEFORE,
                    root_instance=context,
                    mode=MicrotechSettings.EngineMode.LIVE,
                )
            ]
            result.append(
                {
                    "title": title,
                    "task_name": task_name,
                    "mode": mode,
                    "mode_display": MicrotechSettings.EngineMode(mode).label,
                    "mode_is_off": mode == MicrotechSettings.EngineMode.OFF,
                    "rules": evaluations,
                    "fired_count": sum(1 for rule in evaluations if rule["fired"]),
                    "total_count": len(evaluations),
                }
            )
        return result

    @staticmethod
    def _serialize(evaluation) -> dict[str, Any]:
        outcome_code = evaluation.outcome
        fired = outcome_code in {
            RuleEngineExecutionLog.Outcome.APPLIED,
            RuleEngineExecutionLog.Outcome.MATCHED_SHADOW,
        }
        return {
            "rule_id": evaluation.rule.pk,
            "rule_name": evaluation.rule.name,
            "outcome": RuleEngineExecutionLog.Outcome(outcome_code).label,
            "outcome_code": outcome_code,
            "fired": fired,
            "reason": evaluation.reason,
            "conditions": evaluation.conditions,
            "actions": [
                {
                    "type": action.action_type,
                    "target": action.graphql_field or action.dataset_field_name or "–",
                    "value": action.value,
                }
                for action in evaluation.actions
            ],
        }


__all__ = ["OrderRuleTesterService"]
