from __future__ import annotations

import json
from typing import Any

from django.core.management.base import CommandError
from core.management.base import MonitoredBaseCommand

from microtech.services import MicrotechGraphQLClientService


ENTITY_DEFAULTS = {
    "article": {
        "dataset": "Artikel",
        "index": "Nr",
        "range": (["000000"], ["99999999ZZ"]),
        "fields": [
            "Nr",
            "ArtNr",
            "KuBez5",
            "WShopKz",
            "Vk0.Preis",
            "StSchl",
            "Bild",
        ],
    },
    "customer": {
        "dataset": "Adressen",
        "index": "Nr",
        "range": (["0"], ["999999999"]),
        "fields": [
            "AdrNr",
            "AdrId",
            "Na1",
            "EMail1",
            "ReAnsNr",
            "LiAnsNr",
        ],
    },
    "vorgang": {
        "dataset": "Vorgang",
        "index": "BelegNr",
        "range": ([""], ["ZZZZZZZZZZZZZZ"]),
        "fields": [
            "BelegNr",
            "VorgangArt",
            "AdrNr",
            "AuftrNr",
            "Dat",
            "Bez",
            "Netto",
            "Brutto",
            "Status",
        ],
    },
}


class Command(MonitoredBaseCommand):
    help = "Probe the external Microtech GraphQL wrapper without touching the local database."

    def add_arguments(self, parser):
        parser.add_argument("entity", choices=sorted(ENTITY_DEFAULTS), help="article, customer, or vorgang")
        parser.add_argument("mode", choices=("normal", "range", "filter"), help="normal typed lookup, range read, or filtered range read")
        parser.add_argument("--key", default="", help="Key for normal lookup. Article=erpNumber, customer=customerNumber, Vorgang=belegNr.")
        parser.add_argument("--index-field", default="", help="Override Dataset index field for range/filter reads.")
        parser.add_argument("--from-values", nargs="+", default=None, help="Range start values.")
        parser.add_argument("--to-values", nargs="+", default=None, help="Range end values.")
        parser.add_argument(
            "--filter",
            action="append",
            default=[],
            metavar="FIELD:OP:VALUE",
            help="Dataset filter, e.g. WShopKz:EQ:1 or AuftrNr:EQ:SW10001. Can be used multiple times.",
        )
        parser.add_argument("--fields", default="", help="Comma-separated Dataset fields for range/filter reads.")
        parser.add_argument("--limit", type=int, default=10, help="Maximum records for range/filter reads.")
        parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON output.")

    def handle(self, *args, **options):
        client = MicrotechGraphQLClientService()
        entity = options["entity"]
        mode = options["mode"]

        if mode == "normal":
            result = self._normal_lookup(client=client, entity=entity, key=(options.get("key") or "").strip())
        else:
            result = self._dataset_lookup(client=client, entity=entity, mode=mode, options=options)

        self.stdout.write(json.dumps(result, ensure_ascii=False, indent=2 if options.get("pretty") else None))

    def _normal_lookup(self, *, client: MicrotechGraphQLClientService, entity: str, key: str) -> dict[str, Any]:
        if not key:
            raise CommandError("--key is required for normal lookup.")
        if entity == "article":
            return client.request_product(key)
        if entity == "customer":
            return client.request_customer(key)
        if entity == "vorgang":
            return client.request_vorgang(key)
        raise CommandError(f"Unsupported entity: {entity}")

    def _dataset_lookup(
        self,
        *,
        client: MicrotechGraphQLClientService,
        entity: str,
        mode: str,
        options: dict[str, Any],
    ) -> dict[str, Any]:
        defaults = ENTITY_DEFAULTS[entity]
        default_from, default_to = defaults["range"]
        input_data: dict[str, Any] = {
            "dataset": defaults["dataset"],
            "indexField": options.get("index_field") or defaults["index"],
            "range": {
                "fromValues": self._values(options.get("from_values"), default_from),
                "toValues": self._values(options.get("to_values"), default_to),
            },
            "fields": self._fields(options.get("fields"), defaults["fields"]),
            "limit": options.get("limit") or 10,
        }
        if mode == "filter":
            filters = [self._parse_filter(raw_filter) for raw_filter in options.get("filter") or []]
            if not filters:
                raise CommandError("--filter FIELD:OP:VALUE is required for filter mode.")
            input_data["filter"] = " AND ".join(filters)
        return client.poll_dataset_records(input_data)

    @staticmethod
    def _fields(raw_fields: str, default: list[str]) -> list[str]:
        if not raw_fields:
            return default
        return [field.strip() for field in raw_fields.split(",") if field.strip()]

    @classmethod
    def _values(cls, values: list[str] | None, default: list[Any]) -> list[Any]:
        if not values:
            return default
        return [cls._coerce_value(value) for value in values]

    @classmethod
    def _parse_filter(cls, raw_filter: str) -> str:
        if "=" in raw_filter:
            return raw_filter.strip()
        parts = raw_filter.split(":", 2)
        if len(parts) != 3:
            raise CommandError("--filter must use FIELD:OP:VALUE format.")
        field, op, value = parts
        if op.strip().upper() != "EQ":
            raise CommandError("Only EQ filters can be converted to the GraphQL filter string.")
        return f"{field.strip()} = {cls._format_filter_value(cls._coerce_value(value))}"

    @staticmethod
    def _format_filter_value(value: Any) -> str:
        if isinstance(value, bool):
            return "1" if value else "0"
        if isinstance(value, (int, float)):
            return str(value)
        text = str(value).replace("'", "''")
        return f"'{text}'"

    @staticmethod
    def _coerce_value(value: str) -> Any:
        value = str(value).strip()
        lower = value.lower()
        if lower in {"true", "false"}:
            return lower == "true"
        if lower in {"null", "none"}:
            return None
        try:
            return int(value)
        except ValueError:
            return value
