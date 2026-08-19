# microtech/rule_engine/resolvers.py
from __future__ import annotations

from customer.services.webshop_mapping import CustomerWebshopMappingService
from microtech.rule_engine.context import EvaluationContext


def _steuerkategorie(context: EvaluationContext) -> str:
    result = CustomerWebshopMappingService.resolve_tax_category(
        billing_country_code=str(context.get("billing_country_code") or ""),
        vat_id=str(context.get("vat_id") or ""),
        customer_group=str(context.get("customer_group") or ""),
    )
    return str(result)


def _na1(context: EvaluationContext) -> str:
    address = context.get("address")
    if address is None:
        address = context.root
    return CustomerWebshopMappingService.resolve_na1(address=address)


RESOLVERS = {
    "steuerkategorie": _steuerkategorie,
    "na1": _na1,
}


def resolve_named(name: str, context: EvaluationContext) -> str:
    func = RESOLVERS[name]   # KeyError bei unbekanntem Namen (gewollt)
    return str(func(context) or "")
