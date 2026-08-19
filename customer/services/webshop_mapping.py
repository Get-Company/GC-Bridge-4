from __future__ import annotations

from functools import lru_cache
from pathlib import Path
import re
from typing import Any

from core.services import BaseService
from customer.models import Customer


_INTEGER_PATTERN = re.compile(r"^[+-]?\d+$")
_ROOT_DIR = Path(__file__).resolve().parents[1]
_DEFAULT_MAPPING_FILE = _ROOT_DIR / "webshop.yaml"
_GERMAN_MAPPING_FILE = _ROOT_DIR / "webshop_de.yaml"


class CustomerWebshopMappingService(BaseService):
    """Loads the Microtech customer defaults maintained next to the customer app."""

    model = Customer

    def get_microtech_defaults(self, *, country_code: str) -> dict[str, Any]:
        mapping_file = (
            _GERMAN_MAPPING_FILE
            if str(country_code or "").strip().upper() == "DE"
            else _DEFAULT_MAPPING_FILE
        )
        return dict(self._load_mapping_file(mapping_file))

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


__all__ = ["CustomerWebshopMappingService"]
