from __future__ import annotations

from dataclasses import dataclass, replace

from django.db import OperationalError, ProgrammingError
from django.db.models import Field

from microtech.models import (
    MicrotechDatasetCatalog,
    MicrotechDatasetField,
    MicrotechOrderRuleDjangoField,
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
    catalog_id: int | None
    path: str
    label: str
    value_kind: str
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
    OperatorDef(code="equals", name="=", engine_operator="eq"),
    OperatorDef(code="eq", name="==", engine_operator="eq"),
    OperatorDef(code="ne", name="!=", engine_operator="ne"),
    OperatorDef(code="contains", name="enthaelt", engine_operator="contains"),
    OperatorDef(code="gt", name=">", engine_operator="gt"),
    OperatorDef(code="lt", name="<", engine_operator="lt"),
    OperatorDef(code="is_empty", name="ist leer", engine_operator="is_empty"),
    OperatorDef(code="is_not_empty", name="ist nicht leer", engine_operator="is_not_empty"),
)

_ALLOWED_RELATIONS: tuple[str, ...] = ("customer", "billing_address", "shipping_address")
_ALLOWED_ENGINE_OPERATORS_BY_VALUE_KIND: dict[str, frozenset[str]] = {
    "string": frozenset({"eq", "ne", "contains", "is_empty", "is_not_empty"}),
    "int": frozenset({"eq", "ne", "gt", "lt", "is_empty", "is_not_empty"}),
    "decimal": frozenset({"eq", "ne", "gt", "lt", "is_empty", "is_not_empty"}),
    "bool": frozenset({"eq", "ne", "is_empty", "is_not_empty"}),
    "date": frozenset({"eq", "ne", "gt", "lt", "is_empty", "is_not_empty"}),
    "datetime": frozenset({"eq", "ne", "gt", "lt", "is_empty", "is_not_empty"}),
}


def _db_has_rule_builder_tables() -> bool:
    try:
        MicrotechOrderRuleOperator.objects.exists()
        MicrotechDatasetCatalog.objects.exists()
        MicrotechDatasetField.objects.exists()
        return True
    except (OperationalError, ProgrammingError):
        return False


def _db_has_django_field_catalog_table() -> bool:
    try:
        MicrotechOrderRuleDjangoField.objects.exists()
        return True
    except (OperationalError, ProgrammingError):
        return False


def _db_has_django_field_policy_table() -> bool:
    try:
        MicrotechOrderRuleDjangoFieldPolicy.objects.exists()
        return True
    except (OperationalError, ProgrammingError):
        return False


def get_operator_defs() -> list[OperatorDef]:
    if not _db_has_rule_builder_tables():
        return list(DEFAULT_OPERATOR_DEFS)

    def _normalize_operator_def(item: OperatorDef) -> OperatorDef:
        if item.code == "ne" and item.name in {"", "<>"}:
            return OperatorDef(
                code=item.code,
                name="!=",
                engine_operator=item.engine_operator,
                hint=item.hint,
            )
        return item

    rows = list(
        MicrotechOrderRuleOperator.objects
        .filter(is_active=True)
        .order_by("priority", "id")
    )
    if not rows:
        return list(DEFAULT_OPERATOR_DEFS)
    db_defs = [
        OperatorDef(
            code=str(row.code).strip(),
            name=str(row.name).strip() or str(row.code).strip(),
            engine_operator=str(row.engine_operator).strip(),
            hint=str(row.hint or "").strip(),
        )
        for row in rows
        if str(row.code).strip()
    ]
    existing_codes = {item.code for item in db_defs}
    merged_defs = [_normalize_operator_def(item) for item in db_defs]
    merged_defs.extend(
        _normalize_operator_def(item)
        for item in DEFAULT_OPERATOR_DEFS
        if item.code not in existing_codes
    )
    return merged_defs


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


def _real_examples() -> dict[str, str]:
    """Fetch real example values from the most recent order."""
    try:
        order = (
            Order.objects
            .select_related("customer", "billing_address", "shipping_address")
            .order_by("-id")
            .first()
        )
    except Exception:
        return {}
    if order is None:
        return {}
    examples: dict[str, str] = {}
    try:
        for path, _field, _label in _iter_field_defs_for_model(model=Order):
            val = resolve_django_field_value(order=order, path=path)
            if val is not None and str(val) != "":
                examples[path] = str(val)
        for rel_name in _ALLOWED_RELATIONS:
            prefix = f"{rel_name}__"
            rel_obj = getattr(order, rel_name, None)
            if rel_obj is None:
                continue
            rel_model = type(rel_obj)
            for path, _field, _label in _iter_field_defs_for_model(model=rel_model, prefix=prefix):
                val = resolve_django_field_value(order=order, path=path)
                if val is not None and str(val) != "":
                    examples[path] = str(val)
    except Exception:
        pass
    return examples


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
    examples = _real_examples()

    for path, field, label in _iter_field_defs_for_model(model=Order):
        value_kind = _field_value_kind(field)
        base_defs.append(
            DjangoFieldDef(
                catalog_id=None,
                path=path,
                label=f"Order - {label} ({path})",
                value_kind=value_kind,
                example=examples.get(path, _default_example(value_kind)),
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
                    catalog_id=None,
                    path=path,
                    label=f"{rel_title} - {label} ({path})",
                    value_kind=value_kind,
                    example=examples.get(path, _default_example(value_kind)),
                )
            )

    unique_by_path: dict[str, DjangoFieldDef] = {}
    for item in base_defs:
        unique_by_path[item.path] = item
    return list(unique_by_path.values())


def _build_effective_django_field_defs() -> list[DjangoFieldDef]:
    base_defs = _build_base_django_field_defs()
    if not _db_has_django_field_policy_table():
        return sorted(base_defs, key=lambda item: item.label.lower())

    policies = {
        row.field_path: row
        for row in MicrotechOrderRuleDjangoFieldPolicy.objects
        .filter(is_active=True)
        .order_by("priority", "id")
    }
    effective_defs: list[DjangoFieldDef] = []
    for item in base_defs:
        policy = policies.get(item.path)
        if policy is None:
            effective_defs.append(item)
            continue

        label_override = str(policy.label_override or "").strip()
        hint = str(policy.hint or "").strip() or item.hint
        effective_defs.append(
            replace(
                item,
                label=label_override or item.label,
                hint=hint,
            )
        )
    return sorted(effective_defs, key=lambda item: item.label.lower())


def sync_django_field_catalog() -> dict[str, int]:
    defs = _build_effective_django_field_defs()
    if not _db_has_django_field_catalog_table():
        return {}

    active_paths = {item.path for item in defs}
    existing = {
        row.field_path: row
        for row in MicrotechOrderRuleDjangoField.objects.all()
    }

    for index, item in enumerate(defs, start=1):
        defaults = {
            "label": item.label,
            "value_kind": item.value_kind,
            "hint": item.hint,
            "example": item.example,
            "is_active": True,
            "priority": index * 10,
        }
        row = existing.get(item.path)
        if row is None:
            MicrotechOrderRuleDjangoField.objects.create(
                field_path=item.path,
                **defaults,
            )
            continue

        changed = False
        for key, value in defaults.items():
            if getattr(row, key) != value:
                setattr(row, key, value)
                changed = True
        if changed:
            row.save(update_fields=[*defaults.keys()])

    if active_paths:
        (
            MicrotechOrderRuleDjangoField.objects
            .exclude(field_path__in=active_paths)
            .filter(is_active=True)
            .update(is_active=False)
        )
    else:
        MicrotechOrderRuleDjangoField.objects.filter(is_active=True).update(is_active=False)

    return {
        row.field_path: row.id
        for row in MicrotechOrderRuleDjangoField.objects
        .filter(field_path__in=active_paths, is_active=True)
    }


def get_django_field_defs() -> list[DjangoFieldDef]:
    defs = _build_effective_django_field_defs()
    catalog_ids = sync_django_field_catalog()
    if not catalog_ids:
        return defs
    return [
        replace(item, catalog_id=catalog_ids.get(item.path))
        for item in defs
    ]


def get_django_field_map() -> dict[str, DjangoFieldDef]:
    return {item.path: item for item in get_django_field_defs()}


def get_allowed_operator_codes(*, field_path: str = "", django_field_id: int | None = None) -> set[str]:
    resolved_field_path = str(field_path or "").strip()
    if not resolved_field_path and django_field_id and _db_has_django_field_catalog_table():
        resolved_field_path = str(
            MicrotechOrderRuleDjangoField.objects
            .filter(pk=django_field_id, is_active=True)
            .values_list("field_path", flat=True)
            .first()
            or ""
        ).strip()

    all_operator_codes = {
        str(item.code).strip()
        for item in get_operator_defs()
        if str(item.code).strip()
    }
    if not resolved_field_path:
        return all_operator_codes

    field_def = get_django_field_map().get(resolved_field_path)
    if field_def is None:
        return set()

    allowed_engines = _ALLOWED_ENGINE_OPERATORS_BY_VALUE_KIND.get(
        str(field_def.value_kind or "").strip().lower(),
        _ALLOWED_ENGINE_OPERATORS_BY_VALUE_KIND["string"],
    )
    allowed_codes = {
        str(item.code).strip()
        for item in get_operator_defs()
        if str(item.code).strip() and str(item.engine_operator).strip() in allowed_engines
    }

    if not _db_has_django_field_policy_table():
        return allowed_codes

    policy = (
        MicrotechOrderRuleDjangoFieldPolicy.objects
        .filter(field_path=resolved_field_path, is_active=True)
        .prefetch_related("allowed_operators")
        .order_by("priority", "id")
        .first()
    )
    if policy is None:
        return allowed_codes

    policy_codes = {
        str(operator.code).strip()
        for operator in policy.allowed_operators.filter(is_active=True)
        if str(operator.code).strip()
    }
    if not policy_codes:
        return allowed_codes
    return allowed_codes & policy_codes


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
    "get_allowed_operator_codes",
    "get_dataset_defs",
    "get_dataset_field_defs",
    "get_django_field_defs",
    "get_django_field_map",
    "get_operator_defs",
    "get_operator_engine_map",
    "sync_django_field_catalog",
    "resolve_django_field_value",
]
