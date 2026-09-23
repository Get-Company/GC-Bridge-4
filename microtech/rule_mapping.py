from __future__ import annotations

from collections import defaultdict

from django.db import transaction
from django.db.models import Max, Q
from django.utils.text import slugify

from microtech.models import (
    MicrotechOrderRule,
    MicrotechOrderRuleAction,
    MicrotechOrderRuleCategory,
)


DEFAULT_RULE_CATEGORIES: tuple[dict[str, object], ...] = (
    {"code": "vorgang", "name": "Vorgang", "priority": 10},
    {"code": "kunde", "name": "Kunde", "priority": 20},
)

TRIGGER_LABELS: dict[str, str] = {
    "orders.microtech_order_upsert": "Bestellung",
    "customer.microtech_customer_upsert": "Kunde",
    "customer.microtech_postal_address": "Anschrift",
}

FIELD_LABELS: dict[str, str] = {
    "orderNumber": "Bestellnummer",
    "description": "Bezeichnung",
    "currency": "Währung",
    "vorgangArt": "Vorgangsart",
    "customerNumber": "Kundennummer",
    "erpNumber": "Artikelnummer",
    "quantity": "Menge",
    "unit": "Einheit",
    "price": "Preis",
    "name": "Positionsbezeichnung",
    "salutation": "Anrede",
    "firstName": "Vorname",
    "lastName": "Nachname",
    "name1": "Name 1",
    "name2": "Name 2",
    "name3": "Name 3",
    "street": "Straße",
    "zipCode": "Postleitzahl",
    "city": "Ort",
    "email": "E-Mail",
    "phone": "Telefon",
    "department": "Abteilung",
    "country": "Land",
    "vatId": "USt-IdNr.",
    "taxCategory": "Steuerkategorie",
    "isDefaultShipping": "Standard-Lieferanschrift",
    "isDefaultBilling": "Standard-Rechnungsanschrift",
    "isDefault": "Standard-Ansprechpartner",
    "displayName": "Anzeigename",
}

# This list mirrors the keys currently built in
# CustomerUpsertMicrotechService and OrderUpsertMicrotechService.  It is the
# checklist baseline while the code mapping is moved into editable rules.
STANDARD_MAPPING_GROUPS: tuple[dict[str, object], ...] = (
    {
        "category_code": "vorgang",
        "label": "Vorgang",
        "task_name": "orders.microtech_order_upsert",
        "target_scope": "order",
        "input_type": "VorgangInput",
        "fields": ("orderNumber", "description", "currency", "vorgangArt", "customerNumber"),
    },
    {
        "category_code": "vorgang",
        "label": "Positionen",
        "task_name": "orders.microtech_order_upsert",
        "target_scope": "position",
        "input_type": "VorgangPositionInput",
        "fields": ("erpNumber", "quantity", "unit", "price", "name"),
    },
    {
        "category_code": "kunde",
        "label": "Kundenstamm",
        "task_name": "customer.microtech_customer_upsert",
        "target_scope": "customer",
        "input_type": "CustomerInput",
        "fields": (
            "salutation", "firstName", "lastName", "name1", "name2", "name3",
            "street", "zipCode", "city", "phone", "department",
            "country", "vatId", "taxCategory",
        ),
    },
    {
        "category_code": "kunde",
        "label": "Lieferanschrift",
        "task_name": "customer.microtech_customer_upsert",
        "target_scope": "shipping_address",
        "input_type": "PostalAddressInput",
        "fields": (
            "isDefaultShipping", "isDefaultBilling", "name1", "name2", "name3",
            "street", "zipCode", "city", "email", "phone", "department", "country",
        ),
    },
    {
        "category_code": "kunde",
        "label": "Rechnungsanschrift",
        "task_name": "customer.microtech_customer_upsert",
        "target_scope": "billing_address",
        "input_type": "PostalAddressInput",
        "fields": (
            "isDefaultShipping", "isDefaultBilling", "name1", "name2", "name3",
            "street", "zipCode", "city", "phone", "department", "country",
        ),
    },
    {
        "category_code": "kunde",
        "label": "Lieferansprechpartner",
        "task_name": "customer.microtech_customer_upsert",
        "target_scope": "shipping_contact",
        "input_type": "ContactPersonInput",
        "fields": (
            "isDefault", "salutation", "firstName", "lastName", "displayName",
            "department", "email", "phone",
        ),
    },
    {
        "category_code": "kunde",
        "label": "Rechnungsansprechpartner",
        "task_name": "customer.microtech_customer_upsert",
        "target_scope": "billing_contact",
        "input_type": "ContactPersonInput",
        "fields": (
            "isDefault", "salutation", "firstName", "lastName", "displayName",
            "department", "email", "phone",
        ),
    },
)


def friendly_trigger_label(trigger) -> str:
    if trigger is None:
        return "Kein Auslöser"
    return TRIGGER_LABELS.get(str(trigger.task_name or "").strip(), str(trigger.label or trigger.code))


@transaction.atomic
def ensure_default_rule_categories() -> list[MicrotechOrderRuleCategory]:
    categories: dict[str, MicrotechOrderRuleCategory] = {}
    for definition in DEFAULT_RULE_CATEGORIES:
        category, _created = MicrotechOrderRuleCategory.objects.get_or_create(
            code=definition["code"],
            defaults={
                "name": definition["name"],
                "priority": definition["priority"],
                "is_system": True,
                "is_active": True,
            },
        )
        categories[str(definition["code"])] = category

    MicrotechOrderRule.objects.filter(category__isnull=True).filter(
        Q(trigger__context_root="orders.Order") | Q(trigger__isnull=True)
    ).update(category=categories["vorgang"])
    MicrotechOrderRule.objects.filter(category__isnull=True).filter(
        trigger__context_root__startswith="customer."
    ).update(category=categories["kunde"])

    return list(
        MicrotechOrderRuleCategory.objects
        .filter(is_active=True)
        .order_by("priority", "name", "id")
    )


def next_category_code(name: str) -> str:
    base = slugify(str(name or "").strip())[:54] or "kategorie"
    code = base
    number = 2
    while MicrotechOrderRuleCategory.objects.filter(code=code).exists():
        suffix = f"-{number}"
        code = f"{base[:64 - len(suffix)]}{suffix}"
        number += 1
    return code


def next_rule_priority(category: MicrotechOrderRuleCategory) -> int:
    current = category.rules.aggregate(value=Max("priority"))["value"]
    return (int(current) if current is not None else 0) + 10


def action_target_key(action) -> str:
    if str(action.action_type or "") != MicrotechOrderRuleAction.ActionType.SET_FIELD:
        return ""
    if action.dataset_field_id:
        return f"dataset:{action.dataset_field_id}"
    graphql_field = str(action.graphql_field or "").strip()
    if graphql_field:
        scope = str(action.target_scope or MicrotechOrderRuleAction.TargetScope.CUSTOMER).strip()
        return f"graphql:{scope}:{graphql_field}"
    return ""


def action_target_label(action) -> str:
    if action.dataset_field_id:
        try:
            return action.dataset_field.display_label
        except Exception:
            return f"Dataset-Feld #{action.dataset_field_id}"
    graphql_field = str(action.graphql_field or "").strip()
    if graphql_field:
        scope = str(action.get_target_scope_display() or action.target_scope or "")
        return f"{scope}: {graphql_field}"
    return "Unbekanntes Zielfeld"


def effective_target_assignments() -> dict[tuple[int, str], list[dict[str, object]]]:
    assignments: dict[tuple[int, str], list[dict[str, object]]] = defaultdict(list)
    rules = (
        MicrotechOrderRule.objects
        .filter(is_active=True, engine_enabled=True, trigger__isnull=False)
        .select_related("trigger", "category")
        .prefetch_related("actions__dataset_field__dataset")
    )
    for rule in rules:
        for action in rule.actions.all():
            if not action.is_active:
                continue
            target_key = action_target_key(action)
            if not target_key:
                continue
            key = (rule.trigger_id, target_key)
            assignments[key].append({
                "rule_id": rule.id,
                "rule_name": rule.name,
                "category_id": rule.category_id,
                "task_name": rule.trigger.task_name,
                "execution_phase": rule.execution_phase,
                "target_key": target_key,
                "target_label": action_target_label(action),
            })
    return assignments


def mapping_conflicts() -> list[dict[str, object]]:
    conflicts = []
    for (_trigger_id, _target_key), assignments in effective_target_assignments().items():
        rule_ids = {item["rule_id"] for item in assignments}
        if len(rule_ids) < 2:
            continue
        phases = {
            "Vor der Übertragung"
            if item["execution_phase"] == "before"
            else "Nach der Übertragung"
            for item in assignments
        }
        conflicts.append({
            "target": assignments[0]["target_label"],
            "phase": " / ".join(sorted(phases)),
            "rules": sorted({str(item["rule_name"]) for item in assignments}),
        })
    return sorted(conflicts, key=lambda item: (str(item["target"]), str(item["phase"])))


def build_mapping_checklist() -> list[dict[str, object]]:
    rule_sources: dict[tuple[str, str, str], set[str]] = defaultdict(set)
    for assignments in effective_target_assignments().values():
        for item in assignments:
            key = str(item["target_key"])
            if not key.startswith("graphql:"):
                continue
            _prefix, scope, graphql_field = key.split(":", 2)
            rule_sources[(str(item["task_name"]), scope, graphql_field)].add(str(item["rule_name"]))

    groups: list[dict[str, object]] = []
    for definition in STANDARD_MAPPING_GROUPS:
        input_type = str(definition["input_type"])
        task_name = str(definition["task_name"])
        scope = str(definition["target_scope"])
        fields = []
        for field_name in definition["fields"]:
            graphql_field = f"{input_type}.{field_name}"
            fields.append({
                "name": str(field_name),
                "label": FIELD_LABELS.get(str(field_name), str(field_name)),
                "technical_name": graphql_field,
                "code_mapped": True,
                "rule_names": sorted(rule_sources.get((task_name, scope, graphql_field), set())),
                "assigned": True,
            })
        groups.append({
            "category_code": definition["category_code"],
            "label": definition["label"],
            "fields": fields,
        })
    return groups


__all__ = [
    "DEFAULT_RULE_CATEGORIES",
    "action_target_key",
    "build_mapping_checklist",
    "effective_target_assignments",
    "ensure_default_rule_categories",
    "friendly_trigger_label",
    "mapping_conflicts",
    "next_category_code",
    "next_rule_priority",
]
