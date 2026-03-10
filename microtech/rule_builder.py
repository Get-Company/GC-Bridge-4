from __future__ import annotations

from dataclasses import dataclass

from django.db import OperationalError, ProgrammingError
from django.db.models import Field

from microtech.models import (
    MicrotechDatasetCatalog,
    MicrotechDatasetField,
    MicrotechOrderRuleDjangoFieldPolicy,
    MicrotechOrderRuleOperator,
)
from orders.models import Order


@dataclass(frozen=True, slots=True)
class OperatorDef:
    code: str
    name: str
    engine_operator: str
    hint: str = ""


@dataclass(frozen=True, slots=True)
class DjangoFieldDef:
    path: str
    label: str
    value_kind: str
    allowed_operator_codes: tuple[str, ...]
    hint: str = ""
    example: str = ""


@dataclass(frozen=True, slots=True)
class DatasetDef:
    id: int
    code: str
    name: str
    description: str
    source_identifier: str


@dataclass(frozen=True, slots=True)
class DatasetFieldDef:
    id: int
    dataset_id: int
    field_name: str
    label: str
    field_type: str
    can_access: bool
    is_calc_field: bool


DEFAULT_OPERATOR_DEFS: tuple[OperatorDef, ...] = (
    OperatorDef(code="eq", name="==", engine_operator="eq"),
    OperatorDef(code="ne", name="<>", engine_operator="ne"),
    OperatorDef(code="contains", name="enthaelt", engine_operator="contains"),
    OperatorDef(code="gt", name=">", engine_operator="gt"),
    OperatorDef(code="lt", name="<", engine_operator="lt"),
    OperatorDef(code="is_empty", name="ist leer", engine_operator="is_empty"),
    OperatorDef(code="is_not_empty", name="ist nicht leer", engine_operator="is_not_empty"),
)

_ALLOWED_RELATIONS: tuple[str, ...] = ("customer", "billing_address", "shipping_address")


def _db_has_rule_builder_tables() -> bool:
    try:
        MicrotechOrderRuleOperator.objects.exists()
        MicrotechOrderRuleDjangoFieldPolicy.objects.exists()
        MicrotechDatasetCatalog.objects.exists()
        MicrotechDatasetField.objects.exists()
        return True
    except (OperationalError, ProgrammingError):
        return False


def get_operator_defs() -> list[OperatorDef]:
    if not _db_has_rule_builder_tables():
        return list(DEFAULT_OPERATOR_DEFS)
    rows = list(
        MicrotechOrderRuleOperator.objects
        .filter(is_active=True)
        .order_by("priority", "id")
    )
    if not rows:
        return list(DEFAULT_OPERATOR_DEFS)
    return [
        OperatorDef(
            code=str(row.code).strip(),
            name=str(row.name).strip() or str(row.code).strip(),
            engine_operator=str(row.engine_operator).strip(),
            hint=str(row.hint or "").strip(),
        )
        for row in rows
        if str(row.code).strip()
    ]


def get_operator_engine_map() -> dict[str, str]:
    return {item.code: item.engine_operator for item in get_operator_defs()}


def _field_value_kind(field: Field) -> str:
    python_type = field.get_internal_type()
    if python_type in {"BooleanField", "NullBooleanField"}:
        return "bool"
    if python_type in {
        "IntegerField",
        "BigIntegerField",
        "SmallIntegerField",
        "PositiveIntegerField",
        "PositiveSmallIntegerField",
        "AutoField",
        "BigAutoField",
    }:
        return "int"
    if python_type in {"DecimalField", "FloatField"}:
        return "decimal"
    if python_type in {"DateField"}:
        return "date"
    if python_type in {"DateTimeField"}:
        return "datetime"
    return "string"


def _default_operator_codes(value_kind: str) -> tuple[str, ...]:
    if value_kind in {"int", "decimal", "date", "datetime"}:
        return ("eq", "ne", "gt", "lt", "is_empty", "is_not_empty")
    if value_kind == "bool":
        return ("eq", "ne", "is_empty", "is_not_empty")
    return ("eq", "ne", "contains", "is_empty", "is_not_empty")


def _default_example(value_kind: str) -> str:
    if value_kind == "bool":
        return "true"
    if value_kind == "int":
        return "42"
    if value_kind == "decimal":
        return "2.50"
    if value_kind == "date":
        return "2026-01-31"
    if value_kind == "datetime":
        return "2026-01-31T12:30:00"
    return "paypal"


def _iter_field_defs_for_model(*, model, prefix: str = "") -> list[tuple[str, Field, str]]:
    defs: list[tuple[str, Field, str]] = []
    for field in model._meta.concrete_fields:
        if field.auto_created:
            continue
        if getattr(field, "many_to_many", False):
            continue

        if field.is_relation:
            # store FK as *_id for stable scalar comparisons
            path = f"{prefix}{field.attname}"
            label = f"{field.verbose_name} ID"
        else:
            path = f"{prefix}{field.name}"
            label = str(field.verbose_name)
        defs.append((path, field, label))
    return defs


def _build_base_django_field_defs() -> list[DjangoFieldDef]:
    base_defs: list[DjangoFieldDef] = []

    for path, field, label in _iter_field_defs_for_model(model=Order):
        value_kind = _field_value_kind(field)
        base_defs.append(
            DjangoFieldDef(
                path=path,
                label=f"Order - {label} ({path})",
                value_kind=value_kind,
                allowed_operator_codes=_default_operator_codes(value_kind),
                example=_default_example(value_kind),
            )
        )

    relation_models = {
        "customer": Order._meta.get_field("customer").remote_field.model,
        "billing_address": Order._meta.get_field("billing_address").remote_field.model,
        "shipping_address": Order._meta.get_field("shipping_address").remote_field.model,
    }

    for rel_name in _ALLOWED_RELATIONS:
        rel_model = relation_models[rel_name]
        prefix = f"{rel_name}__"
        for path, field, label in _iter_field_defs_for_model(model=rel_model, prefix=prefix):
            value_kind = _field_value_kind(field)
            rel_title = rel_name.replace("_", " ").title()
            base_defs.append(
                DjangoFieldDef(
                    path=path,
                    label=f"{rel_title} - {label} ({path})",
                    value_kind=value_kind,
                    allowed_operator_codes=_default_operator_codes(value_kind),
                    example=_default_example(value_kind),
                )
            )

    unique_by_path: dict[str, DjangoFieldDef] = {}
    for item in base_defs:
        unique_by_path[item.path] = item
    return list(unique_by_path.values())


def get_django_field_defs() -> list[DjangoFieldDef]:
    base_defs = _build_base_django_field_defs()
    if not _db_has_rule_builder_tables():
        return sorted(base_defs, key=lambda item: item.path)

    policies = {
        row.field_path: row
        for row in MicrotechOrderRuleDjangoFieldPolicy.objects
        .prefetch_related("allowed_operators")
        .order_by("priority", "id")
    }

    defs: list[DjangoFieldDef] = []
    for item in base_defs:
        policy = policies.get(item.path)
        if policy and not policy.is_active:
            continue

        allowed_codes = set(item.allowed_operator_codes)
        if policy:
            policy_codes = {
                str(op.code).strip()
                for op in policy.allowed_operators.filter(is_active=True)
                if str(op.code).strip()
            }
            if policy_codes:
                allowed_codes = allowed_codes.intersection(policy_codes)

        if not allowed_codes:
            continue

        label = item.label
        hint = ""
        if policy:
            label_override = str(policy.label_override or "").strip()
            if label_override:
                label = f"{label_override} ({item.path})"
            hint = str(policy.hint or "").strip()

        defs.append(
            DjangoFieldDef(
                path=item.path,
                label=label,
                value_kind=item.value_kind,
                allowed_operator_codes=tuple(sorted(allowed_codes)),
                hint=hint,
                example=item.example,
            )
        )

    return sorted(defs, key=lambda row: row.label.lower())


def get_django_field_map() -> dict[str, DjangoFieldDef]:
    return {item.path: item for item in get_django_field_defs()}


def get_dataset_defs() -> list[DatasetDef]:
    if not _db_has_rule_builder_tables():
        return []
    rows = list(
        MicrotechDatasetCatalog.objects
        .filter(is_active=True)
        .order_by("priority", "id")
    )
    return [
        DatasetDef(
            id=row.id,
            code=str(row.code).strip(),
            name=str(row.name).strip(),
            description=str(row.description or "").strip(),
            source_identifier=str(row.source_identifier).strip(),
        )
        for row in rows
    ]


def get_dataset_field_defs() -> list[DatasetFieldDef]:
    if not _db_has_rule_builder_tables():
        return []
    rows = list(
        MicrotechDatasetField.objects
        .filter(is_active=True, dataset__is_active=True)
        .select_related("dataset")
        .order_by("dataset__priority", "dataset_id", "priority", "id")
    )
    return [
        DatasetFieldDef(
            id=row.id,
            dataset_id=row.dataset_id,
            field_name=str(row.field_name).strip(),
            label=str(row.label or "").strip(),
            field_type=str(row.field_type or "").strip(),
            can_access=bool(row.can_access),
            is_calc_field=bool(row.is_calc_field),
        )
        for row in rows
    ]


def resolve_django_field_value(*, order: Order, path: str) -> object:
    current: object = order
    for segment in str(path).split("__"):
        if current is None:
            return None
        if not hasattr(current, segment):
            return None
        current = getattr(current, segment)
    return current


__all__ = [
    "DatasetDef",
    "DatasetFieldDef",
    "DjangoFieldDef",
    "OperatorDef",
    "get_dataset_defs",
    "get_dataset_field_defs",
    "get_django_field_defs",
    "get_django_field_map",
    "get_operator_defs",
    "get_operator_engine_map",
    "resolve_django_field_value",
]
