from __future__ import annotations

from functools import lru_cache
from pathlib import Path
import re
from typing import Any

from core.services import BaseService
from customer.models import Address, Customer


_INTEGER_PATTERN = re.compile(r"^[+-]?\d+$")
_ROOT_DIR = Path(__file__).resolve().parents[1]
_DEFAULT_MAPPING_FILE = _ROOT_DIR / "webshop.yaml"
_GERMAN_MAPPING_FILE = _ROOT_DIR / "webshop_de.yaml"

_SALUTATION_FEMALE_VALUES = {
    "frau",
    "fr",
    "mrs",
    "ms",
    "miss",
    "madam",
    "madame",
    "weiblich",
    "female",
    "w",
    "f",
}
_SALUTATION_MALE_VALUES = {
    "herr",
    "hr",
    "mr",
    "mister",
    "mann",
    "male",
    "monsieur",
    "m",
    "h",
}
_EU_COUNTRY_CODES = {
    "AT",
    "BE",
    "BG",
    "CY",
    "CZ",
    "DE",
    "DK",
    "EE",
    "ES",
    "FI",
    "FR",
    "GR",
    "HR",
    "HU",
    "IE",
    "IT",
    "LT",
    "LU",
    "LV",
    "MT",
    "NL",
    "PL",
    "PT",
    "RO",
    "SE",
    "SI",
    "SK",
}
_ITALIAN_B2B_GROUP = "gc | italien firma b2b"


class CustomerWebshopMappingService(BaseService):
    """Maps Django customer data to the Microtech defaults and address fields."""

    model = Customer

    def get_microtech_defaults(self, *, country_code: str) -> dict[str, Any]:
        mapping_file = (
            _GERMAN_MAPPING_FILE
            if str(country_code or "").strip().upper() == "DE"
            else _DEFAULT_MAPPING_FILE
        )
        return dict(self._load_mapping_file(mapping_file))

    def get_postal_address_mapping(self, *, address: Address) -> dict[str, str]:
        """Return GraphQL postal-address fields (``name1``/``name2`` → ``Na1``/``Na2``)."""
        return {
            "name1": self.resolve_na1(address=address),
            "name2": self.resolve_na2(address=address),
        }

    @classmethod
    def resolve_na1(cls, *, address: Address) -> str:
        """Use ``Firma`` for businesses and the salutation for private addresses.

        Older and newer Shopware imports use different local ``name1``/``name2``
        layouts.  The invariant is that a private person's name equals the
        stored first and last name, while a business address keeps its company
        name in ``name1``.  Microtech's address layout uses a literal type in
        ``Na1`` and the actual company or personal name in ``Na2``.
        """
        if cls.is_company_address(address=address):
            return "Firma"

        salutation = cls.translate_salutation_to_de(address.title)
        if not salutation:
            salutation = cls.translate_salutation_to_de(address.name1)
        return salutation or cls._to_text(address.title)

    @classmethod
    def resolve_na2(cls, *, address: Address) -> str:
        """Return the company name or the full private name for Microtech ``Na2``."""
        if cls.is_company_address(address=address):
            return cls._to_text(address.name1)

        full_name = " ".join(
            value
            for value in (cls._to_text(address.first_name), cls._to_text(address.last_name))
            if value
        )
        return cls._to_text(address.name2) or full_name or cls._to_text(address.name1)

    @classmethod
    def is_company_address(cls, *, address: Address) -> bool:
        company_candidate = cls._to_text(address.name1)
        if not company_candidate:
            return False
        if cls.translate_salutation_to_de(company_candidate):
            return False
        if company_candidate.casefold() == cls._to_text(address.title).casefold():
            return False

        full_name = " ".join(
            value
            for value in (cls._to_text(address.first_name), cls._to_text(address.last_name))
            if value
        )
        return not full_name or company_candidate.casefold() != full_name.casefold()

    @classmethod
    def translate_salutation_to_de(cls, value: Any) -> str:
        normalized = cls._normalize_salutation(value)
        if normalized in _SALUTATION_FEMALE_VALUES:
            return "Frau"
        if normalized in _SALUTATION_MALE_VALUES:
            return "Herr"
        return ""

    @classmethod
    def get_contact_person_salutation(cls, *, address: Address) -> str:
        salutation = cls.translate_salutation_to_de(address.title)
        if salutation == "Herr":
            return "Herrn"
        return salutation or cls._to_text(address.title)

    @classmethod
    def resolve_tax_category(
        cls,
        *,
        billing_country_code: str,
        vat_id: str,
        customer_group: str,
    ) -> int:
        """Resolve Microtech ``UStKat`` from the agreed Shopware rules.

        The invoice country has priority.  Only the Italian B2B group with a
        VAT ID is tax category 3 within the EU; every other EU customer keeps
        the domestic category 1.
        """
        country_code = cls._to_text(billing_country_code).upper()
        if country_code == "DE":
            return 1
        if country_code == "CH" or country_code not in _EU_COUNTRY_CODES:
            return 2
        if (
            cls._to_text(customer_group).casefold() == _ITALIAN_B2B_GROUP
            and bool(cls._to_text(vat_id))
        ):
            return 3
        return 1

    @classmethod
    @lru_cache(maxsize=2)
    def _load_mapping_file(cls, mapping_file: Path) -> dict[str, Any]:
        values: dict[str, Any] = {}
        for line_number, raw_line in enumerate(mapping_file.read_text(encoding="utf-8").splitlines(), start=1):
            line = raw_line.strip()
            if not line or line == "---" or line.startswith("#"):
                continue
            if ":" not in line:
                raise ValueError(f"{mapping_file.name}:{line_number}: Erwartet wird 'MicrotechFeld: Wert'.")

            field_name, raw_value = line.split(":", 1)
            field_name = field_name.strip()
            if not field_name:
                raise ValueError(f"{mapping_file.name}:{line_number}: Microtech-Feldname fehlt.")
            values[field_name] = cls._parse_scalar(cls._strip_inline_comment(raw_value).strip())
        return values

    @staticmethod
    def _strip_inline_comment(value: str) -> str:
        quote = ""
        for index, character in enumerate(value):
            if character in {'"', "'"}:
                if not quote:
                    quote = character
                elif quote == character:
                    quote = ""
            elif character == "#" and not quote:
                return value[:index]
        return value

    @staticmethod
    def _parse_scalar(value: str) -> Any:
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            return value[1:-1]
        if value.casefold() == "true":
            return True
        if value.casefold() == "false":
            return False
        if _INTEGER_PATTERN.fullmatch(value):
            return int(value)
        return value

    @staticmethod
    def _to_text(value: Any) -> str:
        if value is None:
            return ""
        return str(value).strip()

    @classmethod
    def _normalize_salutation(cls, value: Any) -> str:
        text = cls._to_text(value).lower()
        if not text:
            return ""
        for char in (".", ",", ";", ":", "-", "_", "/", "\\", "(", ")", "[", "]", "{", "}"):
            text = text.replace(char, " ")
        return " ".join(text.split())


__all__ = ["CustomerWebshopMappingService"]
