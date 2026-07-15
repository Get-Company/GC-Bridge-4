from __future__ import annotations

import json
import os
from datetime import date, datetime
from typing import Any

from core.services import BaseService
from core.services.nfon_client import NfonClient


class NfonTimeControlService(BaseService):
    MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    WRITABLE_LINK_RELS = {"destinationIfAllowed", "destinationIfDenied", "inboundTrunkNumbers"}
    WRITABLE_DATA_FIELDS = {
        "name",
        "serviceNumber",
        "serviceCode",
        "extensionNumber",
        "displayName",
        "evaluationStrategy",
        "fromDay",
        "fromTimeOfDay",
        "toDay",
        "toTimeOfDay",
        "referralAllowed",
        "referralDenied",
    }

    def __init__(self, client: NfonClient | None = None, customer_id: str | None = None):
        self.customer_id = customer_id or os.environ["NFON_CUSTOMER_ID"]
        self.client = client or NfonClient(
            api_key_id=os.environ["NFON_API_KEY_ID"],
            api_key_secret=os.environ["NFON_API_KEY_SECRET"],
            customer_id=self.customer_id,
        )

    @staticmethod
    def data_value(data: list[dict[str, Any]], name: str) -> Any:
        for item in data:
            if item.get("name") == name:
                return item.get("value")
        return None

    def list_time_controls(self) -> list[dict[str, str]]:
        path = self._collection_path()
        seen_paths = set()
        items = []

        while path and path not in seen_paths:
            seen_paths.add(path)
            response = self.client.get(path)
            response.raise_for_status()
            raw = response.json()
            items.extend(raw if isinstance(raw, list) else raw.get("items", [raw]))
            path = self._next_page_path(raw)

        services = []
        for item in items:
            data = item.get("data", [])
            href = item.get("href", "")
            service_id = href.rstrip("/").split("/")[-1]
            display_name = self.data_value(data, "displayName") or self.data_value(data, "name") or service_id
            services.append({"id": service_id, "name": display_name})
        return services

    @staticmethod
    def _next_page_path(payload: Any) -> str | None:
        if not isinstance(payload, dict):
            return None

        for link in payload.get("links", []):
            if link.get("rel") == "next" and link.get("href"):
                return link["href"]
        return None

    def get_time_control_dates(self, service_id: str) -> dict[str, Any]:
        service = self._fetch_time_control(service_id)
        data = service.get("data", [])
        return {
            "display_name": self.data_value(data, "displayName") or self.data_value(data, "name") or service_id,
            "denied_dates": self.data_value(data, "referralDenied") or [],
            "allowed_dates": self.data_value(data, "referralAllowed") or [],
            "service_debug": self._build_debug_state(service),
        }

    def add_denied_date(self, service_id: str, value: date) -> dict[str, Any]:
        formatted = self._format_nfon_date(value)
        result = self._update_denied_dates(
            service_id,
            lambda dates: sorted({*dates, formatted}, key=self._parse_nfon_date),
        )
        result["submitted_date"] = value.isoformat()
        result["nfon_date"] = formatted
        persisted_service = self._fetch_time_control(service_id)
        persisted_dates = self.data_value(persisted_service.get("data", []), "referralDenied") or []
        result["persisted_denied"] = persisted_dates
        result["service_debug"] = self._build_debug_state(persisted_service)
        if formatted not in persisted_dates:
            raise ValueError(
                "NFON hat das Datum nach dem Speichern nicht uebernommen. "
                f"Eingabe: {value.isoformat()} | NFON-Format: {formatted} | "
                f"PUT {result['status_code']} | Gesendet: {result['sent_denied']} | "
                f"PUT-Antwort referralDenied: {result['response_denied']} | "
                f"Nachkontrolle referralDenied: {persisted_dates} | "
                f"NFON-State: {result['service_debug']}"
            )
        return result

    def delete_denied_date(self, service_id: str, value: str) -> dict[str, Any]:
        def remove_date(dates: list[str]) -> list[str]:
            updated_dates = [existing_date for existing_date in dates if existing_date != value]
            if len(updated_dates) == len(dates):
                raise ValueError(f"Datum nicht gefunden: '{value}'")
            return updated_dates

        return self._update_denied_dates(service_id, remove_date)

    def _collection_path(self) -> str:
        return f"/api/customers/{self.customer_id}/targets/time-control-services"

    def _detail_path(self, service_id: str) -> str:
        return f"{self._collection_path()}/{service_id}"

    def _fetch_time_control(self, service_id: str) -> dict[str, Any]:
        response = self.client.get(self._detail_path(service_id))
        response.raise_for_status()
        return response.json()

    def _update_denied_dates(self, service_id: str, transform) -> dict[str, Any]:
        service = self._fetch_time_control(service_id)
        data = [dict(item) for item in service.get("data", [])]
        denied_item = next((item for item in data if item.get("name") == "referralDenied"), None)
        current_dates = list(denied_item.get("value", [])) if denied_item else []
        updated_dates = transform(current_dates)

        if denied_item:
            denied_item["value"] = updated_dates
        else:
            data.append({"name": "referralDenied", "value": updated_dates})

        payload = self._build_writable_payload(service, data)
        body = json.dumps(payload).encode("utf-8")
        response = self.client.put(self._detail_path(service_id), body)
        sent_denied = self.data_value(payload["data"], "referralDenied") or []

        if response.status_code < 300:
            return {
                "status_code": response.status_code,
                "sent_denied": sent_denied,
                "response_denied": self._response_denied_dates(response),
                "payload_debug": self._build_debug_state(payload),
            }

        raise ValueError(self._format_error_response(response))

    def _build_writable_payload(self, service: dict[str, Any], data: list[dict[str, Any]]) -> dict[str, Any]:
        payload = dict(service)
        payload.pop("href", None)
        payload["links"] = [
            link
            for link in payload.get("links", [])
            if link.get("rel") in self.WRITABLE_LINK_RELS
        ]
        payload["data"] = [
            item
            for item in data
            if item.get("name") in self.WRITABLE_DATA_FIELDS
        ]
        return payload

    def _build_debug_state(self, service: dict[str, Any]) -> dict[str, Any]:
        data = service.get("data", [])
        return {
            "name": self.data_value(data, "name"),
            "displayName": self.data_value(data, "displayName"),
            "evaluationStrategy": self.data_value(data, "evaluationStrategy"),
            "fromDay": self.data_value(data, "fromDay"),
            "fromTimeOfDay": self.data_value(data, "fromTimeOfDay"),
            "toDay": self.data_value(data, "toDay"),
            "toTimeOfDay": self.data_value(data, "toTimeOfDay"),
            "referralAllowed": self.data_value(data, "referralAllowed") or [],
            "referralDenied": self.data_value(data, "referralDenied") or [],
            "links": [link.get("rel") for link in service.get("links", [])],
        }

    @classmethod
    def _format_nfon_date(cls, value: date) -> str:
        return f"{cls.MONTHS[value.month - 1]} {value.day:02d}, {value.year}"

    @staticmethod
    def _parse_nfon_date(value: str) -> datetime:
        return datetime.strptime(value, "%b %d, %Y")

    @staticmethod
    def _response_denied_dates(response) -> Any:
        try:
            return [
                item["value"]
                for item in response.json().get("data", [])
                if item.get("name") == "referralDenied"
            ]
        except Exception:
            return response.text[:100]

    @staticmethod
    def _format_error_response(response) -> str:
        try:
            error = response.json()
            errors = "; ".join(
                f"{item['path']}: {item['message']}"
                for item in error.get("errors", [])
            )
            return f"{error.get('title', 'Fehler')}: {errors or error.get('detail', '')}"
        except Exception:
            return f"API-Fehler {response.status_code}: {response.text[:300]}"
