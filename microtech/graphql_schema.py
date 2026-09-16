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
  __schema { types { kind name inputFields { name } } }
}
"""

# Human labels for the input types we care about; also defines display order.
INPUT_TYPE_LABELS: dict[str, str] = {
    "CustomerInput": "Kunde",
    "PostalAddressInput": "Anschrift",
    "ContactPersonInput": "Ansprechpartner",
    "VorgangInput": "Vorgang (Bestellung)",
    "PositionInput": "Position",
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
    "PositionInput": ["erpNumber", "quantity", "unit", "price"],
}


def introspect_input_fields() -> dict[str, list[str]]:
    """Return {InputTypeName: [field, ...]} from the live GraphQL schema.

    Raises on transport/GraphQL errors so callers can decide to fall back.
    """
    from microtech.services.graphql_client import MicrotechGraphQLClientService

    data = MicrotechGraphQLClientService().execute(
        _INTROSPECTION_QUERY, timeout=15, bypass_backup_mode=True
    )
    types = ((data or {}).get("__schema") or {}).get("types") or []
    result: dict[str, list[str]] = {}
    for entry in types:
        if not isinstance(entry, dict) or entry.get("kind") != "INPUT_OBJECT":
            continue
        name = str(entry.get("name") or "")
        fields = [
            str((f or {}).get("name") or "")
            for f in (entry.get("inputFields") or [])
            if (f or {}).get("name")
        ]
        if name and fields:
            result[name] = fields
    return result


def _group(raw: dict[str, list[str]]) -> list[dict]:
    """Group known input types (labelled + ordered) with their fields."""
    groups: list[dict] = []
    for type_name, label in INPUT_TYPE_LABELS.items():
        fields = raw.get(type_name) or []
        if not fields:
            continue
        groups.append({
            "input_type": type_name,
            "label": label,
            "fields": [{"name": f} for f in fields],
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


__all__ = ["introspect_input_fields", "get_graphql_input_catalog", "INPUT_TYPE_LABELS"]
