"""Shared execution path for trigger-based order rules.

Task-specific adapters decide how a resolved action is applied.  Selecting the
rule, evaluating its condition tree, rendering values, and loading the related
objects happens here exactly once.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
from uuid import uuid4

from core.services import BaseService
from loguru import logger
from microtech.models import MicrotechOrderRule, RuleEngineExecutionLog
from microtech.rule_builder import (
    get_address_field_defs,
    get_customer_field_defs,
    get_django_field_map,
    get_operator_engine_map,
)
from microtech.rule_engine.context import EvaluationContext
from microtech.rule_engine.evaluation import rule_condition_results, rule_matches
from microtech.rule_engine.templates import render_template


_ADDRESS_CONTEXT_ROOTS = {"customer.Address"}
_CUSTOMER_CONTEXT_ROOT = "customer.Customer"


@dataclass(frozen=True, slots=True)
class ResolvedRuleAction:
    """An action with its destination metadata and rendered value."""

    action_id: int
    action_type: str
    target_scope: str
    graphql_field: str
    dataset_source_identifier: str
    dataset_name: str
    dataset_field_name: str
    dataset_field_type: str
    value: str

    @property
    def field_path(self) -> str:
        """GraphQL targets win; dataset fields remain the compatibility fallback."""
        if self.graphql_field:
            return self.graphql_field.rsplit(".", 1)[-1]
        return self.dataset_field_name


@dataclass(frozen=True, slots=True)
class RuleMatch:
    rule: MicrotechOrderRule
    actions: tuple[ResolvedRuleAction, ...]


@dataclass(frozen=True, slots=True)
class RuleEvaluation:
    """One rule's outcome within an engine run."""

    rule: MicrotechOrderRule
    actions: tuple[ResolvedRuleAction, ...]
    conditions: tuple[dict, ...]
    outcome: str
    reason: str

    @property
    def matches(self) -> bool:
        return self.outcome in {
            RuleEngineExecutionLog.Outcome.APPLIED,
            RuleEngineExecutionLog.Outcome.MATCHED_SHADOW,
        }


class RuleExecutionService(BaseService):
    """Resolve every matching active engine rule for a trigger and phase."""

    model = MicrotechOrderRule

    def inspect_rules(
        self,
        *,
        task_name: str,
        phase: str,
        root_instance: object,
        mode: str,
    ) -> tuple[RuleEvaluation, ...]:
        """Return every rule outcome without applying actions or writing audit rows."""
        return self._evaluate_rules(
            task_name=task_name,
            phase=phase,
            root_instance=root_instance,
            audit_mode=mode,
        )

    def resolve_matching_rules(
        self,
        *,
        task_name: str,
        phase: str,
        root_instance: object,
        audit_mode: str | None = None,
        audit_subject: str = "",
        action_scope: str | None = None,
    ) -> tuple[RuleMatch, ...]:
        evaluations = self._evaluate_rules(
            task_name=task_name,
            phase=phase,
            root_instance=root_instance,
            audit_mode=audit_mode,
            action_scope=action_scope,
        )
        if audit_mode is not None:
            self._persist_audit(
                task_name=task_name,
                phase=phase,
                mode=audit_mode,
                subject=audit_subject,
                evaluations=evaluations,
            )
        return tuple(
            RuleMatch(rule=evaluation.rule, actions=evaluation.actions)
            for evaluation in evaluations
            if evaluation.matches
        )

    def _evaluate_rules(
        self,
        *,
        task_name: str,
        phase: str,
        root_instance: object,
        audit_mode: str | None,
        action_scope: str | None = None,
    ) -> tuple[RuleEvaluation, ...]:
        context = EvaluationContext(root_instance)
        rules = (
            self.get_queryset()
            .filter(
                execution_phase=phase,
                trigger__task_name=task_name,
            )
            .select_related("trigger")
            .prefetch_related(
                "conditions",
                "condition_groups",
                "condition_groups__conditions",
                "condition_groups__children",
                "actions",
                "actions__dataset_field__dataset",
            )
            .order_by("priority", "id")
        )
        field_maps: dict[str, dict] = {}
        operator_engine_map = get_operator_engine_map()
        evaluations: list[RuleEvaluation] = []
        for rule in rules:
            if audit_mode == "off":
                evaluations.append(RuleEvaluation(
                    rule=rule,
                    actions=(),
                    conditions=(),
                    outcome=RuleEngineExecutionLog.Outcome.SKIPPED_MODE_OFF,
                    reason="Der globale Engine-Modus ist AUS.",
                ))
                continue
            if not rule.is_active:
                evaluations.append(RuleEvaluation(
                    rule=rule,
                    actions=(),
                    conditions=(),
                    outcome=RuleEngineExecutionLog.Outcome.SKIPPED_INACTIVE,
                    reason="Die Regel ist deaktiviert.",
                ))
                continue
            if not rule.engine_enabled:
                evaluations.append(RuleEvaluation(
                    rule=rule,
                    actions=(),
                    conditions=(),
                    outcome=RuleEngineExecutionLog.Outcome.SKIPPED_ENGINE_DISABLED,
                    reason="Neue Engine aktiv ist an dieser Regel deaktiviert.",
                ))
                continue
            context_root = str(getattr(rule.trigger, "context_root", "") or "")
            field_map = field_maps.get(context_root)
            if field_map is None:
                field_map = self._field_map_for_rule(rule)
                field_maps[context_root] = field_map
            conditions = rule_condition_results(
                rule,
                context,
                field_map=field_map,
                operator_engine_map=operator_engine_map,
            )
            if not rule_matches(
                rule,
                context,
                field_map=field_map,
                operator_engine_map=operator_engine_map,
            ):
                evaluations.append(RuleEvaluation(
                    rule=rule,
                    actions=(),
                    conditions=conditions,
                    outcome=RuleEngineExecutionLog.Outcome.SKIPPED_CONDITIONS,
                    reason="Mindestens eine Bedingung trifft nicht zu.",
                ))
                continue
            actions = self._resolve_actions(rule, context, action_scope=action_scope)
            if not actions:
                evaluations.append(RuleEvaluation(
                    rule=rule,
                    actions=(),
                    conditions=conditions,
                    outcome=RuleEngineExecutionLog.Outcome.SKIPPED_NO_ACTIONS,
                    reason="Die Regel trifft zu, enthält aber keine aktive Aktion.",
                ))
                continue
            evaluations.append(RuleEvaluation(
                rule=rule,
                actions=actions,
                conditions=conditions,
                outcome=(
                    RuleEngineExecutionLog.Outcome.MATCHED_SHADOW
                    if audit_mode == "shadow"
                    else RuleEngineExecutionLog.Outcome.APPLIED
                ),
                reason=(
                    "Die Regel trifft zu; im Schattenmodus wird sie nicht angewendet."
                    if audit_mode == "shadow"
                    else "Alle Bedingungen treffen zu; die Aktionen wurden angewendet."
                ),
            ))
        return tuple(evaluations)

    @staticmethod
    def _persist_audit(
        *,
        task_name: str,
        phase: str,
        mode: str,
        subject: str,
        evaluations: tuple[RuleEvaluation, ...],
    ) -> None:
        if not evaluations:
            return
        run_id = uuid4()
        try:
            RuleEngineExecutionLog.objects.bulk_create([
                RuleEngineExecutionLog(
                    run_id=run_id,
                    task_name=task_name,
                    execution_phase=phase,
                    engine_mode=mode,
                    subject=subject,
                    rule=evaluation.rule,
                    rule_name=evaluation.rule.name,
                    outcome=evaluation.outcome,
                    reason=evaluation.reason,
                    conditions_json=json.dumps(evaluation.conditions, ensure_ascii=False),
                    actions_json=json.dumps([
                        {
                            "action_id": action.action_id,
                            "action_type": action.action_type,
                            "target_scope": action.target_scope,
                            "target": action.graphql_field or action.dataset_field_name,
                            "value": action.value,
                        }
                        for action in evaluation.actions
                    ], ensure_ascii=False),
                )
                for evaluation in evaluations
            ])
        except Exception:
            # The audit trail must not stop a business-critical order/customer
            # upsert when the log storage is temporarily unavailable.
            logger.exception("Regel-Engine-Ausführungsprotokoll konnte nicht persistiert werden.")

    def resolve_first_match(
        self,
        *,
        task_name: str,
        phase: str,
        root_instance: object,
    ) -> RuleMatch | None:
        """Compatibility helper for callers that explicitly need only one rule."""
        matches = self.resolve_matching_rules(
            task_name=task_name,
            phase=phase,
            root_instance=root_instance,
        )
        return matches[0] if matches else None

    @staticmethod
    def _field_map_for_rule(rule: MicrotechOrderRule) -> dict:
        context_root = str(getattr(rule.trigger, "context_root", "") or "")
        if context_root in _ADDRESS_CONTEXT_ROOTS:
            return {item.path: item for item in get_address_field_defs(context_root)}
        if context_root == _CUSTOMER_CONTEXT_ROOT:
            return {item.path: item for item in get_customer_field_defs()}
        return get_django_field_map()

    @staticmethod
    def _resolve_actions(
        rule: MicrotechOrderRule,
        context: EvaluationContext,
        *,
        action_scope: str | None = None,
    ) -> tuple[ResolvedRuleAction, ...]:
        resolved: list[ResolvedRuleAction] = []
        for action in sorted(
            (item for item in rule.actions.all() if item.is_active),
            key=lambda item: (item.priority, item.id),
        ):
            if action_scope is not None and action.target_scope != action_scope:
                continue
            field = action.dataset_field if action.dataset_field_id else None
            dataset = field.dataset if field is not None else None
            resolved.append(
                ResolvedRuleAction(
                    action_id=action.id,
                    action_type=str(action.action_type or ""),
                    target_scope=str(action.target_scope or ""),
                    graphql_field=str(action.graphql_field or "").strip(),
                    dataset_source_identifier=str(getattr(dataset, "source_identifier", "") or ""),
                    dataset_name=str(getattr(dataset, "name", "") or ""),
                    dataset_field_name=str(getattr(field, "field_name", "") or ""),
                    dataset_field_type=str(getattr(field, "field_type", "") or ""),
                    value=render_template(action.target_value or "", context),
                )
            )
        return tuple(resolved)


__all__ = ["ResolvedRuleAction", "RuleEvaluation", "RuleExecutionService", "RuleMatch"]
