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


def _anreden(context: EvaluationContext) -> str:
    """Comma-joined salutation tokens, usable as a ``not_in_list`` expected value."""
    from microtech.models import RuleConstant

    return ",".join(RuleConstant.get_list("anreden"))


def _anrede(context: EvaluationContext) -> str:
    """Private-address salutation: German salutation of title, else name1, else title."""
    address = context.get("address")
    if address is None:
        address = context.root
    svc = CustomerWebshopMappingService
    return (
        svc.translate_salutation_to_de(getattr(address, "title", ""))
        or svc.translate_salutation_to_de(getattr(address, "name1", ""))
        or str(getattr(address, "title", "") or "")
    )


RESOLVERS = {
    "steuerkategorie": _steuerkategorie,
    "na1": _na1,
    "anreden": _anreden,
    "anrede": _anrede,
}


def resolve_named(name: str, context: EvaluationContext) -> str:
    func = RESOLVERS[name]   # KeyError bei unbekanntem Namen (gewollt)
    return str(func(context) or "")
