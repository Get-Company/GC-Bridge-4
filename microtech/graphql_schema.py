"""GraphQL input-field catalog for the rule builder target dropdown.

Fetches the Microtech GraphQL schema via introspection (a normal, synchronous
query — no job queue), cached briefly, and groups the relevant *Input* object
types with their fields. Falls back to a curated list when introspection is
unavailable (dev/CI, wrapper down), so the editor always has targets.
"""
from __future__ import annotations

from loguru import logger

from django.core.cache import cache

_CACHE_KEY = "microtech_graphql_input_catalog_v1"
_CACHE_TTL = 600  # seconds

_INTROSPECTION_QUERY = """
query RuleBuilderIntrospection {
  __schema { types { kind name inputFields { name description } } }
}
"""

# Human labels for the input types we care about; also defines display order.
INPUT_TYPE_LABELS: dict[str, str] = {
    "CustomerInput": "Kunde",
    "PostalAddressInput": "Anschrift",
    "ContactPersonInput": "Ansprechpartner",
    "VorgangInput": "Vorgang (Bestellung)",
    "VorgangPositionInput": "Position",
}

# A rule can only write to the input object that is consumed by its trigger.
# Keeping the mapping next to the schema catalog gives the editor and server
# validation one source of truth without baking Microtech field names into JS.
RULE_TRIGGER_INPUT_TYPES: dict[str, tuple[str, ...]] = {
    "customer.microtech_postal_address": ("PostalAddressInput",),
    # A customer upsert writes the master customer first, then its postal
    # addresses and their contacts.  The action scope below determines which
    # concrete child object receives the selected input field.
    "customer.microtech_customer_upsert": (
        "CustomerInput",
        "PostalAddressInput",
        "ContactPersonInput",
    ),
}

CUSTOMER_UPSERT_ACTION_SCOPES: tuple[dict[str, object], ...] = (
    {
        "code": "customer",
        "label": "Kundenstamm",
        "graphql_input_types": ("CustomerInput",),
    },
    {
        "code": "shipping_address",
        "label": "Lieferanschrift",
        "graphql_input_types": ("PostalAddressInput",),
    },
    {
        "code": "billing_address",
        "label": "Rechnungsanschrift",
        "graphql_input_types": ("PostalAddressInput",),
    },
    {
        "code": "shipping_contact",
        "label": "Lieferansprechpartner",
        "graphql_input_types": ("ContactPersonInput",),
    },
    {
        "code": "billing_contact",
        "label": "Rechnungsansprechpartner",
        "graphql_input_types": ("ContactPersonInput",),
    },
)

# CustomerInput.email is intentionally excluded.  The wrapper can use that
# value while creating its implicit default address, which would also change
# the invoice-address email.  Email mappings must target the explicit shipping
# address or one of the contact scopes instead.
RULE_ACTION_EXCLUDED_FIELDS: dict[tuple[str, str], tuple[str, ...]] = {
    ("customer.microtech_customer_upsert", "customer"): ("CustomerInput.email",),
    ("customer.microtech_customer_upsert", "billing_address"): (
        "PostalAddressInput.email",
    ),
}

# Curated fallback — the fields the wrapper actually accepts (from
# customer_upsert_microtech / order_upsert_microtech). Used when introspection
# is unavailable.
_FALLBACK: dict[str, list[str]] = {
    "CustomerInput": [
        "salutation", "firstName", "lastName", "name1", "name2", "name3",
        "street", "zipCode", "city", "email", "phone", "department", "country",
        "vatId", "taxCategory",
    ],
    "PostalAddressInput": [
        "isDefaultShipping", "isDefaultBilling", "name1", "name2", "name3",
        "street", "zipCode", "city", "email", "phone", "department", "country",
    ],
    "ContactPersonInput": [
        "isDefault", "salutation", "firstName", "lastName", "displayName",
        "department", "email", "phone",
    ],
    "VorgangInput": ["orderNumber", "description", "currency", "vorgangArt", "customerNumber"],
    "VorgangPositionInput": ["erpNumber", "quantity", "unit", "price", "name"],
}


def introspect_input_fields() -> dict[str, list[dict]]:
    """Return {InputTypeName: [{name, description}, ...]} from the live GraphQL schema.

    Raises on transport/GraphQL errors so callers can decide to fall back.
    """
    from microtech.services.graphql_client import MicrotechGraphQLClientService

    data = MicrotechGraphQLClientService().execute(
        _INTROSPECTION_QUERY, timeout=15, bypass_backup_mode=True
    )
    types = ((data or {}).get("__schema") or {}).get("types") or []
    result: dict[str, list[dict]] = {}
    for entry in types:
        if not isinstance(entry, dict) or entry.get("kind") != "INPUT_OBJECT":
            continue
        name = str(entry.get("name") or "")
        fields = [
            {"name": str((f or {}).get("name") or ""),
             "description": str((f or {}).get("description") or "")}
            for f in (entry.get("inputFields") or [])
            if (f or {}).get("name")
        ]
        if name and fields:
            result[name] = fields
    return result


def _normalize_field(item) -> dict:
    if isinstance(item, dict):
        return {"name": str(item.get("name") or ""), "description": str(item.get("description") or "")}
    return {"name": str(item), "description": ""}


def _group(raw: dict) -> list[dict]:
    """Group known input types (labelled + ordered) with their fields."""
    groups: list[dict] = []
    for type_name, label in INPUT_TYPE_LABELS.items():
        fields = raw.get(type_name) or []
        if not fields:
            continue
        groups.append({
            "input_type": type_name,
            "label": label,
            "fields": [_normalize_field(f) for f in fields],
        })
    return groups


def get_graphql_input_catalog(*, refresh: bool = False) -> dict:
    """Grouped GraphQL input catalog for the editor, cached with curated fallback."""
    if not refresh:
        cached = cache.get(_CACHE_KEY)
        if cached is not None:
            return cached

    source = "introspection"
    try:
        raw = introspect_input_fields()
        if not raw:
            raise ValueError("empty introspection result")
    except Exception as exc:  # noqa: BLE001 - any failure degrades to fallback
        logger.warning("GraphQL-Introspektion nicht verfügbar → kuratierter Fallback ({}).", exc)
        raw = _FALLBACK
        source = "fallback"

    catalog = {"ok": True, "source": source, "groups": _group(raw)}
    cache.set(_CACHE_KEY, catalog, _CACHE_TTL)
    return catalog


def get_rule_trigger_input_types(task_name: str) -> tuple[str, ...]:
    """Return GraphQL input types that are meaningful for a rule trigger."""
    return RULE_TRIGGER_INPUT_TYPES.get(str(task_name or "").strip(), ())


def get_rule_action_scopes(task_name: str) -> tuple[dict[str, object], ...]:
    """Return the destination scopes available to a trigger's rule actions."""
    if str(task_name or "").strip() == "customer.microtech_customer_upsert":
        return CUSTOMER_UPSERT_ACTION_SCOPES
    return ()


def get_rule_action_input_types(task_name: str, target_scope: str) -> tuple[str, ...]:
    """Return writable input types for one action scope.

    Non-customer triggers have no additional scope and retain their existing
    trigger-wide input-type contract.
    """
    scopes = get_rule_action_scopes(task_name)
    if not scopes:
        return get_rule_trigger_input_types(task_name)
    normalized_scope = str(target_scope or "").strip()
    for scope in scopes:
        if scope["code"] == normalized_scope:
            return tuple(scope["graphql_input_types"])
    return ()


def get_rule_action_excluded_fields(task_name: str, target_scope: str) -> tuple[str, ...]:
    return RULE_ACTION_EXCLUDED_FIELDS.get(
        (str(task_name or "").strip(), str(target_scope or "").strip()),
        (),
    )


__all__ = [
    "INPUT_TYPE_LABELS",
    "RULE_TRIGGER_INPUT_TYPES",
    "CUSTOMER_UPSERT_ACTION_SCOPES",
    "RULE_ACTION_EXCLUDED_FIELDS",
    "get_graphql_input_catalog",
    "get_rule_action_excluded_fields",
    "get_rule_action_input_types",
    "get_rule_action_scopes",
    "get_rule_trigger_input_types",
    "introspect_input_fields",
]
