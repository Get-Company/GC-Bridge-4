from __future__ import annotations

# Wiederverwendung der bestehenden, getesteten Anrede-Normalisierung.
from customer.services.webshop_mapping import CustomerWebshopMappingService as _WS


def _anrede_de(value: str, arg: str = "") -> str:
    return _WS.translate_salutation_to_de(value)


def _anrede_kontakt(value: str, arg: str = "") -> str:
    salutation = _WS.translate_salutation_to_de(value)
    if salutation == "Herr":
        return "Herrn"
    return salutation


def _split(value: str, arg: str = "") -> str:
    try:
        index = int(arg)
    except (TypeError, ValueError):
        index = 0
    tokens = str(value).split(" ", 1)
    return tokens[index] if 0 <= index < len(tokens) else ""


TRANSFORMS = {
    "upper": lambda v, a="": str(v).upper(),
    "lower": lambda v, a="": str(v).lower(),
    "strip": lambda v, a="": str(v).strip(),
    "split": _split,
    "anrede_de": _anrede_de,
    "anrede_kontakt": _anrede_kontakt,
}


def apply_transform(name: str, value: str, arg: str = "") -> str:
    func = TRANSFORMS[name]   # KeyError bei unbekanntem Namen (gewollt)
    return func(value, arg)
