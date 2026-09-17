"""Shared execution path for trigger-based order rules.

Task-specific adapters decide how a resolved action is applied.  Selecting the
rule, evaluating its condition tree, rendering values, and loading the related
objects happens here exactly once.
"""
from __future__ import annotations

from dataclasses import dataclass

from core.services import BaseService
from microtech.models import MicrotechOrderRule
from microtech.rule_builder import (
    get_address_field_defs,
    get_customer_field_defs,
    get_django_field_map,
    get_operator_engine_map,
)
from microtech.rule_engine.context import EvaluationContext
from microtech.rule_engine.evaluation import rule_matches
from microtech.rule_engine.templates import render_template


_ADDRESS_CONTEXT_ROOTS = {"customer.Address"}
_CUSTOMER_CONTEXT_ROOT = "customer.Customer"


@dataclass(frozen=True, slots=True)
class ResolvedRuleAction:
    """An action with its destination metadata and rendered value."""

    action_id: int
    action_type: str
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


class RuleExecutionService(BaseService):
    """Resolve every matching active engine rule for a trigger and phase."""

    model = MicrotechOrderRule

    def resolve_matching_rules(
        self,
        *,
        task_name: str,
        phase: str,
        root_instance: object,
    ) -> tuple[RuleMatch, ...]:
        context = EvaluationContext(root_instance)
        rules = (
            self.get_queryset()
            .filter(
                is_active=True,
                engine_enabled=True,
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
        matches: list[RuleMatch] = []
        for rule in rules:
            context_root = str(getattr(rule.trigger, "context_root", "") or "")
            field_map = field_maps.get(context_root)
            if field_map is None:
                field_map = self._field_map_for_rule(rule)
                field_maps[context_root] = field_map
            if not rule_matches(
                rule,
                context,
                field_map=field_map,
                operator_engine_map=operator_engine_map,
            ):
                continue
            matches.append(RuleMatch(rule=rule, actions=self._resolve_actions(rule, context)))
        return tuple(matches)

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
    def _resolve_actions(rule: MicrotechOrderRule, context: EvaluationContext) -> tuple[ResolvedRuleAction, ...]:
        resolved: list[ResolvedRuleAction] = []
        for action in sorted(
            (item for item in rule.actions.all() if item.is_active),
            key=lambda item: (item.priority, item.id),
        ):
            field = action.dataset_field if action.dataset_field_id else None
            dataset = field.dataset if field is not None else None
            resolved.append(
                ResolvedRuleAction(
                    action_id=action.id,
                    action_type=str(action.action_type or ""),
                    graphql_field=str(action.graphql_field or "").strip(),
                    dataset_source_identifier=str(getattr(dataset, "source_identifier", "") or ""),
                    dataset_name=str(getattr(dataset, "name", "") or ""),
                    dataset_field_name=str(getattr(field, "field_name", "") or ""),
                    dataset_field_type=str(getattr(field, "field_type", "") or ""),
                    value=render_template(action.target_value or "", context),
                )
            )
        return tuple(resolved)


__all__ = ["ResolvedRuleAction", "RuleExecutionService", "RuleMatch"]
