from __future__ import annotations

from collections import defaultdict

from django.db import transaction
from django.db.models import Max, Q
from django.utils.text import slugify

from microtech.models import (
    MicrotechOrderRule,
    MicrotechOrderRuleAction,
    MicrotechOrderRuleCategory,
    RuleTrigger,
)


DEFAULT_RULE_CATEGORIES: tuple[dict[str, object], ...] = (
    {"code": "vorgang", "name": "Vorgang", "priority": 10},
    {"code": "kunde", "name": "Kunde", "priority": 20},
)

TRIGGER_LABELS: dict[str, str] = {
    "orders.microtech_order_upsert": "Bestellung",
    "orders.microtech_order_mapping": "Vorgang",
    "orders.microtech_order_position_mapping": "Bestellposition",
    "customer.microtech_customer_upsert": "Kunde",
    "customer.microtech_customer_mapping": "Kunde und Anschriften",
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
    "Status": "Status",
    "SuchBeg": "Suchbegriff",
    "VsdArt": "Versandart",
    "VsdZWeise": "Versand-Zahlweise",
    "ZahlHBk": "Hausbank",
    "ZahlBed": "Zahlungsbedingung",
    "SktoTg1": "Skontotage",
    "SktoSz1": "Skontosatz",
    "NettoTg": "Nettotage",
    "VtrNr": "Vertreternummer",
    "GspKz": "Gesperrt-Kennzeichen",
    "RabKz": "Rabatt-Kennzeichen",
    "ArtPrGrp": "Artikelpreisgruppe",
    "TextKz1": "Textkennzeichen 1",
    "TextKz2": "Textkennzeichen 2",
    "TextKz3": "Textkennzeichen 3",
    "TextKz4": "Textkennzeichen 4",
    "TextKz5": "Textkennzeichen 5",
    "HistKz": "Historienkennzeichen",
}

# This list is the single catalog for both the visible checklist and the
# grouped standard rules that assign the precomputed code values.
STANDARD_MAPPING_GROUPS: tuple[dict[str, object], ...] = (
    {
        "category_code": "vorgang",
        "label": "Vorgang",
        "task_name": "orders.microtech_order_mapping",
        "target_scope": "order",
        "input_type": "VorgangInput",
        "fields": ("orderNumber", "description", "currency", "vorgangArt", "customerNumber"),
    },
    {
        "category_code": "vorgang",
        "label": "Positionen",
        "task_name": "orders.microtech_order_position_mapping",
        "target_scope": "position",
        "input_type": "VorgangPositionInput",
        "fields": ("erpNumber", "quantity", "unit", "price", "name"),
    },
    {
        "category_code": "kunde",
        "label": "Kundenstamm",
        "task_name": "customer.microtech_customer_mapping",
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
        "label": "Kundenstandardwerte",
        "task_name": "customer.microtech_customer_mapping",
        "target_scope": "customer_defaults",
        "input_type": "WebshopDefaultsInput",
        "fields": (
            "Status", "SuchBeg", "VsdArt", "VsdZWeise", "ZahlHBk", "ZahlBed",
            "SktoTg1", "SktoSz1", "NettoTg", "VtrNr", "GspKz", "RabKz",
            "ArtPrGrp", "TextKz1", "TextKz2", "TextKz3", "TextKz4", "TextKz5",
            "HistKz",
        ),
    },
    {
        "category_code": "kunde",
        "label": "Lieferanschrift",
        "task_name": "customer.microtech_customer_mapping",
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
        "task_name": "customer.microtech_customer_mapping",
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
        "task_name": "customer.microtech_customer_mapping",
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
        "task_name": "customer.microtech_customer_mapping",
        "target_scope": "billing_contact",
        "input_type": "ContactPersonInput",
        "fields": (
            "isDefault", "salutation", "firstName", "lastName", "displayName",
            "department", "email", "phone",
        ),
    },
)

_STANDARD_MAPPING_TRIGGERS: tuple[dict[str, object], ...] = (
    {
        "code": "order_mapping",
        "label": "Vorgang abbilden",
        "task_name": "orders.microtech_order_mapping",
        "context_root": "orders.Order",
        "priority": 5,
    },
    {
        "code": "order_position_mapping",
        "label": "Bestellposition abbilden",
        "task_name": "orders.microtech_order_position_mapping",
        "context_root": "orders.OrderDetail",
        "priority": 6,
    },
    {
        "code": "customer_mapping",
        "label": "Kunde und Anschriften abbilden",
        "task_name": "customer.microtech_customer_mapping",
        "context_root": "customer.Customer",
        "priority": 7,
    },
)


def _ensure_standard_mapping_rules(
    categories: dict[str, MicrotechOrderRuleCategory],
) -> None:
    """Create the former code mapping once as grouped, editable rules.

    ``system_key`` is the durable identity.  Existing standard rules are not
    rewritten on later page loads, so deliberate user edits remain intact.
    """
    triggers: dict[str, RuleTrigger] = {}
    for definition in _STANDARD_MAPPING_TRIGGERS:
        trigger, _created = RuleTrigger.objects.get_or_create(
            code=definition["code"],
            defaults={
                "label": definition["label"],
                "task_name": definition["task_name"],
                "context_root": definition["context_root"],
                "priority": definition["priority"],
                "is_active": True,
            },
        )
        triggers[str(definition["task_name"])] = trigger

    for group_number, definition in enumerate(STANDARD_MAPPING_GROUPS, start=1):
        category_code = str(definition["category_code"])
        target_scope = str(definition["target_scope"])
        input_type = str(definition["input_type"])
        task_name = str(definition["task_name"])
        system_key = f"standard_mapping.{category_code}.{target_scope}"
        rule, created = MicrotechOrderRule.objects.get_or_create(
            system_key=system_key,
            defaults={
                "name": f"Standard · {definition['label']}",
                "category": categories[category_code],
                "trigger": triggers[task_name],
                "priority": group_number * 10,
                "execution_phase": MicrotechOrderRule.ExecutionPhase.BEFORE,
                "is_active": True,
                "engine_enabled": True,
                "shadow_mode": False,
            },
        )
        if not created:
            continue
        MicrotechOrderRuleAction.objects.bulk_create([
            MicrotechOrderRuleAction(
                rule=rule,
                priority=position * 10,
                action_type=MicrotechOrderRuleAction.ActionType.SET_FIELD,
                graphql_field=f"{input_type}.{field_name}",
                target_scope=target_scope,
                target_value=f"{{{{ code_values__{field_name} }}}}",
                is_active=True,
            )
            for position, field_name in enumerate(definition["fields"], start=1)
        ])


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

    _ensure_standard_mapping_rules(categories)

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


def action_target_label(action, *, task_name: str = "") -> str:
    if action.dataset_field_id:
        try:
            return action.dataset_field.display_label
        except Exception:
            return f"Dataset-Feld #{action.dataset_field_id}"
    graphql_field = str(action.graphql_field or "").strip()
    if graphql_field:
        if task_name == "customer.microtech_postal_address":
            return f"Anschrift: {graphql_field}"
        scope = str(action.get_target_scope_display() or action.target_scope or "")
        return f"{scope}: {graphql_field}"
    return "Unbekanntes Zielfeld"


def effective_target_assignments() -> dict[tuple[int, str], list[dict[str, object]]]:
    assignments: dict[tuple[int, str], list[dict[str, object]]] = defaultdict(list)
    rules = (
        MicrotechOrderRule.objects
        .filter(is_active=True, engine_enabled=True, trigger__isnull=False)
        .select_related("trigger", "category")
        .prefetch_related(
            "actions__dataset_field__dataset",
            "conditions",
        )
        .order_by("priority", "id")
    )
    for rule in rules:
        has_conditions = any(condition.is_active for condition in rule.conditions.all())
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
                "rule_priority": rule.priority,
                "has_conditions": has_conditions,
                "category_id": rule.category_id,
                "task_name": rule.trigger.task_name,
                "execution_phase": rule.execution_phase,
                "target_key": target_key,
                "target_label": action_target_label(
                    action,
                    task_name=str(rule.trigger.task_name or ""),
                ),
            })
    return assignments


def mapping_overlaps() -> list[dict[str, object]]:
    """Return informational same-target rule sequences.

    Different conditional rules and the common default-plus-exception pattern
    intentionally write the same target.  The engine evaluates them in stable
    priority order, so these overlaps are useful review information rather than
    save-blocking conflicts.
    """
    overlaps = []
    for (_trigger_id, _target_key), assignments in effective_target_assignments().items():
        assignments_by_phase: dict[str, list[dict[str, object]]] = defaultdict(list)
        for assignment in assignments:
            assignments_by_phase[str(assignment["execution_phase"])].append(assignment)
        for phase, phase_assignments in assignments_by_phase.items():
            if len({item["rule_id"] for item in phase_assignments}) < 2:
                continue
            ordered = sorted(
                phase_assignments,
                key=lambda item: (int(item["rule_priority"]), int(item["rule_id"])),
            )
            overlaps.append({
                "target": ordered[0]["target_label"],
                "phase": (
                    "Vor der Übertragung"
                    if phase == "before"
                    else "Nach der Übertragung"
                ),
                "rules": [
                    (
                        f"{item['rule_name']} (bedingt)"
                        if item["has_conditions"]
                        else f"{item['rule_name']} (Standard)"
                    )
                    for item in ordered
                ],
            })
    return sorted(overlaps, key=lambda item: (str(item["target"]), str(item["phase"])))


def build_mapping_checklist() -> list[dict[str, object]]:
    rule_sources: dict[tuple[str, str, str], set[str]] = defaultdict(set)
    generic_address_sources: dict[str, set[str]] = defaultdict(set)
    for assignments in effective_target_assignments().values():
        for item in assignments:
            key = str(item["target_key"])
            if not key.startswith("graphql:"):
                continue
            _prefix, scope, graphql_field = key.split(":", 2)
            rule_sources[(str(item["task_name"]), scope, graphql_field)].add(str(item["rule_name"]))
            if str(item["task_name"]) == "customer.microtech_postal_address":
                generic_address_sources[graphql_field].add(str(item["rule_name"]))

    groups: list[dict[str, object]] = []
    for definition in STANDARD_MAPPING_GROUPS:
        input_type = str(definition["input_type"])
        task_name = str(definition["task_name"])
        scope = str(definition["target_scope"])
        fields = []
        for field_name in definition["fields"]:
            graphql_field = f"{input_type}.{field_name}"
            field_rule_names = set(rule_sources.get((task_name, scope, graphql_field), set()))
            if input_type == "PostalAddressInput":
                field_rule_names.update(generic_address_sources.get(graphql_field, set()))
            fields.append({
                "name": str(field_name),
                "label": FIELD_LABELS.get(str(field_name), str(field_name)),
                "technical_name": graphql_field,
                "code_mapped": True,
                "rule_names": sorted(field_rule_names),
                "assigned": bool(field_rule_names),
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
    "mapping_overlaps",
    "next_category_code",
    "next_rule_priority",
]
