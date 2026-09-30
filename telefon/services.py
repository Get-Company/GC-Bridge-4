from __future__ import annotations

import json
import os
import re
from datetime import date, datetime, timedelta
from typing import Any
from urllib.parse import urlparse

from django.conf import settings

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
    DESTINATION_RELS = ("destinationIfAllowed", "destinationIfDenied")
    WEEKDAYS = (
        "MONDAY",
        "TUESDAY",
        "WEDNESDAY",
        "THURSDAY",
        "FRIDAY",
        "SATURDAY",
        "SUNDAY",
    )
    TIME_RE = re.compile(r"^(?:[01]\d|2[0-3]):[0-5]\d$")

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
        items = self._get_collection_items(self._collection_path())

        services = []
        for item in items:
            data = item.get("data", [])
            href = item.get("href", "")
            service_id = href.rstrip("/").split("/")[-1]
            display_name = self.data_value(data, "displayName") or self.data_value(data, "name") or service_id
            services.append({"id": service_id, "name": display_name})
        return services

    def get_editor_state(self) -> dict[str, Any]:
        """Return the live NFON time-control graph in editor-friendly form."""
        raw_services = self._get_collection_items(self._collection_path())
        services = []
        for summary in raw_services:
            data_names = {item.get("name") for item in summary.get("data", [])}
            destination_rels = {
                link.get("rel")
                for link in summary.get("links", [])
                if link.get("rel") in self.DESTINATION_RELS
            }
            if not {"fromDay", "fromTimeOfDay", "toDay", "toTimeOfDay"}.issubset(data_names) or not destination_rels:
                service_id = self._service_id(summary)
                summary = self._fetch_time_control(service_id)
            services.append(summary)

        nodes = [self._serialize_editor_node(service) for service in services]
        nodes_by_id = {node["id"]: node for node in nodes}
        partial_day_routes = self._partial_day_routes(nodes_by_id)
        incoming = {node_id: [] for node_id in nodes_by_id}
        warnings: list[str] = []
        broken_node_ids: set[str] = set()

        for node in nodes:
            configured_rels = {destination["rel"] for destination in node["destinations"]}
            missing_rels = [rel for rel in self.DESTINATION_RELS if rel not in configured_rels]
            if missing_rels:
                broken_node_ids.add(node["id"])
                warnings.append(
                    f"{node['name']} hat kein vollständiges Zielpaar ({', '.join(missing_rels)} fehlt). "
                    "Die Kette stoppt hier."
                )
            if node["allowed_dates"]:
                warnings.append(
                    f"{node['name']} enthält referralAllowed-Ausnahmen. Diese lösen nicht den "
                    "üblichen Feiertags-/Ansagepfad aus."
                )
            time_control_links = [
                destination
                for destination in node["destinations"]
                if destination["kind"] == "time-control-services"
            ]
            partial_day_route = partial_day_routes.get(node["id"])
            chain_links = time_control_links
            node["bypass_id"] = None
            node["bypass_relation"] = None
            if partial_day_route:
                chain_links = [partial_day_route["window_link"]]
                node["bypass_id"] = partial_day_route["continuation_link"]["id"]
                node["bypass_relation"] = partial_day_route["continuation_link"]["rel"]

            node["next_ids"] = [destination["id"] for destination in chain_links]
            node["next_id"] = node["next_ids"][0] if len(node["next_ids"]) == 1 else None
            node["next_relation"] = chain_links[0]["rel"] if len(chain_links) == 1 else None
            if len(time_control_links) > 1 and not partial_day_route:
                broken_node_ids.add(node["id"])
                warnings.append(
                    f"{node['name']} verzweigt auf mehrere Zeitsteuerungen. Die Kette stoppt hier."
                )
            for destination in chain_links:
                target_id = destination["id"]
                if target_id in incoming:
                    incoming[target_id].append(node["id"])
                else:
                    broken_node_ids.add(node["id"])
                    warnings.append(
                        f"{node['name']} verweist auf die unbekannte Zeitsteuerung {target_id}."
                    )

        for node_id, sources in incoming.items():
            nodes_by_id[node_id]["incoming_ids"] = sources
            if len(sources) > 1:
                warnings.append(
                    f"{nodes_by_id[node_id]['name']} hat mehrere Vorgänger: {', '.join(sources)}."
                )

        roots = [node for node in nodes if not node["incoming_ids"]]
        for root in roots:
            root["inbound_count"] = self._inbound_count(root["id"])
        main_root = self._select_main_root(roots)

        chain: list[dict[str, Any]] = []
        visited: set[str] = set()
        current = main_root
        stopped_at = None
        while current:
            if current["id"] in visited:
                warnings.append(f"Zyklus bei {current['name']} erkannt. Die Kette stoppt dort.")
                stopped_at = current["id"]
                break
            visited.add(current["id"])
            current["position"] = len(chain) + 1
            current["chain_status"] = "connected"
            chain.append(current)

            if current["id"] in broken_node_ids:
                stopped_at = current["id"]
                break
            if len(current["next_ids"]) > 1:
                stopped_at = current["id"]
                break
            if not current["next_ids"]:
                break

            next_id = current["next_ids"][0]
            next_node = nodes_by_id.get(next_id)
            if next_node is None:
                stopped_at = current["id"]
                break
            current = next_node

        detached = [node for node in nodes if node["id"] not in visited]
        for node in detached:
            node["chain_status"] = "detached"
        if detached:
            names = ", ".join(node["name"] for node in detached[:4])
            suffix = " …" if len(detached) > 4 else ""
            warnings.append(
                f"{len(detached)} Zeitsteuerung(en) liegen außerhalb der Hauptkette: {names}{suffix}"
            )
        if not main_root and nodes:
            warnings.append("Es wurde kein Einstiegspunkt gefunden. Die Kette ist zyklisch oder unvollständig.")
        if len(roots) > 1:
            warnings.append(
                f"Es gibt {len(roots)} mögliche Einstiegspunkte. Verwendet wird der Einstieg "
                "mit direkter Rufnummernzuordnung."
            )

        destination_options = self.list_destination_options()
        destination_names = {}
        for option in destination_options:
            destination_names[option["href"]] = option["name"]
            destination_names[urlparse(option["href"]).path] = option["name"]
        for node in nodes:
            for destination in node["destinations"]:
                destination["name"] = destination_names.get(
                    destination["href"],
                    destination_names.get(destination["path"], destination["id"]),
                )
            node["outcomes"] = [
                destination
                for destination in node["destinations"]
                if destination["kind"] != "time-control-services"
            ]

        return {
            "ok": not warnings,
            "chain_complete": bool(chain) and stopped_at is None and not detached,
            "stopped_at": stopped_at,
            "warnings": warnings,
            "chain": chain,
            "detached": detached,
            "roots": [root["id"] for root in roots],
            "main_root_id": main_root["id"] if main_root else None,
            "node_count": len(nodes),
            "destination_options": destination_options,
            "weekdays": list(self.WEEKDAYS),
            "time_zone": settings.TIME_ZONE,
        }

    def update_editor_node(self, service_id: str, values: dict[str, Any]) -> dict[str, Any]:
        service = self._fetch_time_control(service_id)
        updates = {
            "name": self._required_text(values.get("name"), "Name"),
            "displayName": self._required_text(values.get("name"), "Name"),
            "fromDay": self._validate_weekday(values.get("from_day")),
            "fromTimeOfDay": self._format_api_time(values.get("from_time")),
            "toDay": self._validate_weekday(values.get("to_day")),
            "toTimeOfDay": self._format_api_time(values.get("to_time")),
        }
        if "date_mode" in values:
            updates["referralDenied"] = self._normalize_date_selection(values)
        elif "denied_dates" in values:
            updates["referralDenied"] = self._normalize_dates(values.get("denied_dates"))
        link_updates = {}
        outcome_href = str(values.get("outcome_href") or "").strip()
        if outcome_href:
            outcome_relation = str(values.get("outcome_relation") or "")
            existing_link = next(
                (
                    link
                    for link in service.get("links", [])
                    if link.get("rel") == outcome_relation and link.get("href")
                ),
                None,
            )
            if outcome_relation not in self.DESTINATION_RELS or existing_link is None:
                raise ValueError("Das Ziel der Node konnte nicht eindeutig zugeordnet werden.")
            if self._target_from_href(existing_link["href"])["kind"] == "time-control-services":
                raise ValueError("Die Verbindung zur nächsten Zeitsteuerung darf hier nicht getrennt werden.")
            link_updates[outcome_relation] = self._validate_destination_href(outcome_href)

        payload = self._payload_with_updates(
            service,
            data_updates=updates,
            link_updates=link_updates,
        )
        response = self.client.put(self._detail_path(service_id), json.dumps(payload).encode("utf-8"))
        if response.status_code >= 300:
            raise ValueError(self._format_error_response(response))
        return {"status_code": response.status_code, "service_id": service_id}

    def insert_editor_node(self, values: dict[str, Any]) -> dict[str, Any]:
        """Insert one full-day node or a date-gate/time-window pair after a node."""
        after_id = self._required_text(values.get("after_id"), "Vorgänger")
        name = self._required_text(values.get("name"), "Name")
        dates = self._normalize_date_selection(values)
        if not dates:
            raise ValueError("Mindestens ein Auslösedatum ist erforderlich.")

        mode = str(values.get("mode") or "full_day")
        if mode not in {"full_day", "morning", "afternoon", "custom"}:
            raise ValueError("Unbekannter Zeitfenster-Typ.")

        announcement_href = self._validate_destination_href(values.get("destination_href"))
        predecessor = self._fetch_time_control(after_id)
        continuation = self._continuation_link(predecessor)
        if continuation is None:
            raise ValueError(
                "Der Vorgänger hat kein eindeutiges Weiterleitungsziel. Die Kette wurde nicht verändert."
            )

        created: list[str] = []
        try:
            if mode == "full_day":
                new_service = self._create_time_control(
                    name=name,
                    denied_dates=dates,
                    from_time="00:00",
                    to_time="23:59",
                    allowed_href=continuation["href"],
                    denied_href=announcement_href,
                )
                created.append(new_service["id"])
                inserted_href = new_service["href"]
            else:
                from_time, to_time = self._window_times(mode, values)
                window_service = self._create_time_control(
                    name=f"{name} · Zeitfenster",
                    denied_dates=[],
                    from_time=from_time,
                    to_time=to_time,
                    allowed_href=announcement_href,
                    denied_href=continuation["href"],
                )
                created.append(window_service["id"])
                gate_service = self._create_time_control(
                    name=name,
                    denied_dates=dates,
                    from_time="00:00",
                    to_time="23:59",
                    allowed_href=continuation["href"],
                    denied_href=window_service["href"],
                )
                created.append(gate_service["id"])
                inserted_href = gate_service["href"]

            predecessor_payload = self._payload_with_updates(
                predecessor,
                link_updates={continuation["rel"]: inserted_href},
            )
            response = self.client.put(
                self._detail_path(after_id),
                json.dumps(predecessor_payload).encode("utf-8"),
            )
            if response.status_code >= 300:
                raise ValueError(self._format_error_response(response))
        except Exception:
            for service_id in reversed(created):
                try:
                    self.client.delete(self._detail_path(service_id))
                except Exception:
                    pass
            raise

        return {"created_ids": created, "after_id": after_id}

    def configure_partial_day_node(self, service_id: str, values: dict[str, Any]) -> dict[str, Any]:
        """Turn an existing date node into a date-gate/time-window pair."""
        gate = self._fetch_time_control(service_id)
        name = self._required_text(values.get("name"), "Name")
        dates = self._normalize_date_selection(values)
        if not dates:
            raise ValueError("Mindestens ein Auslösedatum ist erforderlich.")
        from_time, to_time = self._window_times("custom", values)
        announcement_href = self._validate_destination_href(values.get("destination_href"))
        continuation = self._continuation_link(gate)
        if continuation is None:
            raise ValueError(
                "Die Node hat kein eindeutiges Weiterleitungsziel. Die Kette wurde nicht verändert."
            )

        window_service = self._create_time_control(
            name=f"{name} · Zeitfenster",
            denied_dates=[],
            from_time=from_time,
            to_time=to_time,
            allowed_href=announcement_href,
            denied_href=continuation["href"],
        )
        try:
            gate_payload = self._payload_with_updates(
                gate,
                data_updates={
                    "name": name,
                    "displayName": name,
                    "fromDay": "MONDAY",
                    "fromTimeOfDay": self._format_api_time("00:00"),
                    "toDay": "SUNDAY",
                    "toTimeOfDay": self._format_api_time("23:59"),
                    "referralAllowed": [],
                    "referralDenied": dates,
                },
                link_updates={
                    "destinationIfAllowed": continuation["href"],
                    "destinationIfDenied": window_service["href"],
                },
            )
            response = self.client.put(
                self._detail_path(service_id),
                json.dumps(gate_payload).encode("utf-8"),
            )
            if response.status_code >= 300:
                raise ValueError(self._format_error_response(response))
        except Exception:
            try:
                self.client.delete(self._detail_path(window_service["id"]))
            except Exception:
                pass
            raise

        return {
            "service_id": service_id,
            "window_service_id": window_service["id"],
            "dates": dates,
            "from_time": from_time,
            "to_time": to_time,
        }

    def list_destination_options(self) -> list[dict[str, str]]:
        options: list[dict[str, str]] = []
        paths = [
            f"{self._collection_path()}/available-destinations",
            f"/api/customers/{self.customer_id}/targets/ivr-services",
        ]
        for path in paths:
            try:
                items = self._get_collection_items(path)
            except Exception:
                continue
            for item in items:
                href = item.get("href") or ""
                if not href:
                    continue
                data = item.get("data", [])
                name = (
                    self.data_value(data, "displayName")
                    or self.data_value(data, "name")
                    or self.data_value(data, "extensionNumber")
                    or self._target_from_href(href)["id"]
                )
                target = self._target_from_href(href)
                # Time controls are deliberately omitted here: selecting one as an
                # outcome could silently create a branch around the protected chain.
                # Everything else returned by NFON's available-destinations endpoint
                # is a valid outcome and should be visible in the editor.
                if target["kind"] == "time-control-services":
                    continue
                options.append(
                    {
                        "href": href,
                        "name": str(name),
                        "kind": target["kind"],
                        "id": target["id"],
                    }
                )
        unique = {option["href"]: option for option in options}
        return sorted(unique.values(), key=lambda item: (item["kind"], item["name"].casefold()))

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

    def _get_collection_items(self, initial_path: str) -> list[dict[str, Any]]:
        path = initial_path
        seen_paths = set()
        items: list[dict[str, Any]] = []
        while path and path not in seen_paths:
            seen_paths.add(path)
            response = self.client.get(path)
            response.raise_for_status()
            raw = response.json()
            if isinstance(raw, list):
                items.extend(raw)
            elif isinstance(raw, dict):
                page_items = raw.get("items")
                if isinstance(page_items, list):
                    items.extend(page_items)
                elif "data" in raw or "href" in raw:
                    items.append(raw)
            path = self._next_page_path(raw)
        return items

    @staticmethod
    def _service_id(service: dict[str, Any]) -> str:
        return str(service.get("href", "")).rstrip("/").split("/")[-1]

    def _serialize_editor_node(self, service: dict[str, Any]) -> dict[str, Any]:
        data = service.get("data", [])
        service_id = self._service_id(service)
        destinations = []
        for link in service.get("links", []):
            if link.get("rel") not in self.DESTINATION_RELS or not link.get("href"):
                continue
            target = self._target_from_href(link["href"])
            destinations.append(
                {
                    "rel": link["rel"],
                    "href": link["href"],
                    "path": urlparse(link["href"]).path,
                    "kind": target["kind"],
                    "id": target["id"],
                }
            )
        denied_dates = self.data_value(data, "referralDenied") or []
        allowed_dates = self.data_value(data, "referralAllowed") or []
        return {
            "id": service_id,
            "name": self.data_value(data, "displayName") or self.data_value(data, "name") or service_id,
            "from_day": self.data_value(data, "fromDay") or "MONDAY",
            "from_time": self._format_html_time(self.data_value(data, "fromTimeOfDay") or "12:00 AM"),
            "to_day": self.data_value(data, "toDay") or "SUNDAY",
            "to_time": self._format_html_time(self.data_value(data, "toTimeOfDay") or "11:59 PM"),
            "evaluation_strategy": self.data_value(data, "evaluationStrategy") or "AUTO",
            "denied_dates": list(denied_dates),
            "allowed_dates": list(allowed_dates),
            "destinations": destinations,
            "incoming_ids": [],
            "inbound_count": 0,
        }

    @staticmethod
    def _target_from_href(href: str) -> dict[str, str]:
        path = urlparse(href).path
        parts = [part for part in path.split("/") if part]
        try:
            target_index = parts.index("targets")
        except ValueError:
            return {"kind": parts[-2] if len(parts) > 1 else "unknown", "id": parts[-1] if parts else ""}
        tail = parts[target_index + 1 :]
        if len(tail) >= 3 and tail[-1] == "voice-mail":
            return {"kind": "voice-mail", "id": "/".join(tail[-3:])}
        return {
            "kind": tail[-2] if len(tail) >= 2 else "targets",
            "id": tail[-1] if tail else "",
        }

    def _inbound_count(self, service_id: str) -> int:
        try:
            items = self._get_collection_items(f"{self._detail_path(service_id)}/inbound-trunk-numbers")
            return len(items)
        except Exception:
            return 0

    @staticmethod
    def _select_main_root(roots: list[dict[str, Any]]) -> dict[str, Any] | None:
        if not roots:
            return None

        def order_key(node: dict[str, Any]):
            match = re.match(r"\s*(\d+)", str(node.get("name") or ""))
            prefix = int(match.group(1)) if match else 10**9
            return (-int(node.get("inbound_count") or 0), prefix, str(node.get("name") or ""))

        return sorted(roots, key=order_key)[0]

    @staticmethod
    def _partial_day_routes(nodes_by_id: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
        """Recognize date gates whose matching branch passes through a time window."""
        routes: dict[str, dict[str, Any]] = {}
        for gate in nodes_by_id.values():
            gate_links = [
                destination
                for destination in gate["destinations"]
                if destination["kind"] == "time-control-services"
            ]
            if len(gate_links) != 2 or not gate["denied_dates"]:
                continue

            for window_link in gate_links:
                window = nodes_by_id.get(window_link["id"])
                if window is None or window["denied_dates"] or window["allowed_dates"]:
                    continue
                window_links = [
                    destination
                    for destination in window["destinations"]
                    if destination["kind"] == "time-control-services"
                ]
                window_outcomes = [
                    destination
                    for destination in window["destinations"]
                    if destination["kind"] != "time-control-services"
                ]
                if len(window_links) != 1 or len(window_outcomes) != 1:
                    continue
                continuation_link = next(
                    (
                        destination
                        for destination in gate_links
                        if destination["id"] == window_links[0]["id"]
                    ),
                    None,
                )
                if continuation_link is None:
                    continue
                if window_outcomes[0]["rel"] == window_links[0]["rel"]:
                    continue
                routes[gate["id"]] = {
                    "window_link": window_link,
                    "continuation_link": continuation_link,
                }
                break
        return routes

    @classmethod
    def _format_html_time(cls, value: str) -> str:
        value = str(value or "").strip()
        if cls.TIME_RE.fullmatch(value):
            return value
        for fmt in ("%I:%M %p", "%I:%M:%S %p"):
            try:
                return datetime.strptime(value, fmt).strftime("%H:%M")
            except ValueError:
                continue
        return value

    @classmethod
    def _format_api_time(cls, value: Any) -> str:
        text = str(value or "").strip()
        if not cls.TIME_RE.fullmatch(text):
            raise ValueError(f"Ungültige Uhrzeit: {text or '-'}")
        return datetime.strptime(text, "%H:%M").strftime("%I:%M %p")

    @classmethod
    def _validate_weekday(cls, value: Any) -> str:
        weekday = str(value or "").upper()
        if weekday not in cls.WEEKDAYS:
            raise ValueError(f"Ungültiger Wochentag: {value}")
        return weekday

    @staticmethod
    def _required_text(value: Any, label: str) -> str:
        text = str(value or "").strip()
        if not text:
            raise ValueError(f"{label} ist erforderlich.")
        if len(text) > 160:
            raise ValueError(f"{label} darf höchstens 160 Zeichen lang sein.")
        return text

    @classmethod
    def _normalize_dates(cls, values: Any) -> list[str]:
        if values is None:
            return []
        if isinstance(values, str):
            values = [value for value in re.split(r"[,;\n]+", values) if value.strip()]
        if not isinstance(values, list):
            raise ValueError("Auslösedaten müssen als Liste übertragen werden.")
        normalized = set()
        for raw_value in values:
            text = str(raw_value or "").strip()
            if not text:
                continue
            parsed = None
            for fmt in (
                "%Y-%m-%dT%H:%M",
                "%Y-%m-%dT%H:%M:%S",
                "%Y-%m-%d",
                "%d.%m.%Y",
                "%b %d, %Y",
            ):
                try:
                    parsed = datetime.strptime(text, fmt).date()
                    break
                except ValueError:
                    continue
            if parsed is None:
                raise ValueError(f"Ungültiges Auslösedatum: {text}")
            normalized.add(cls._format_nfon_date(parsed))
        return sorted(normalized, key=cls._parse_nfon_date)

    @classmethod
    def _normalize_date_selection(cls, values: dict[str, Any]) -> list[str]:
        """Normalize UI single dates or expand an inclusive range for NFON.

        The NFON time-control API has no range object for referralDenied. It
        accepts only an array of individual ``MMM dd, yyyy`` values, so ranges
        are expanded before the payload is built.
        """
        mode = str(values.get("date_mode") or "single")
        if mode == "single":
            return cls._normalize_dates(values.get("dates"))
        if mode != "range":
            raise ValueError("Unbekannter Auslösedatum-Typ.")

        start_values = cls._normalize_dates([values.get("range_start")])
        end_values = cls._normalize_dates([values.get("range_end")])
        if not start_values or not end_values:
            raise ValueError("Für einen Zeitraum sind Start und Ende erforderlich.")
        start = cls._parse_nfon_date(start_values[0]).date()
        end = cls._parse_nfon_date(end_values[0]).date()
        if end < start:
            raise ValueError("Das Ende des Zeitraums darf nicht vor dem Start liegen.")

        days = (end - start).days
        return [cls._format_nfon_date(start + timedelta(days=offset)) for offset in range(days + 1)]

    def _payload_with_updates(
        self,
        service: dict[str, Any],
        *,
        data_updates: dict[str, Any] | None = None,
        link_updates: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        data_updates = data_updates or {}
        data = [dict(item) for item in service.get("data", [])]
        by_name = {item.get("name"): item for item in data}
        for name, value in data_updates.items():
            if name in by_name:
                by_name[name]["value"] = value
            else:
                data.append({"name": name, "value": value})

        payload = self._build_writable_payload(service, data)
        if link_updates:
            links_by_rel = {link.get("rel"): dict(link) for link in payload.get("links", [])}
            for rel, href in link_updates.items():
                if rel not in self.DESTINATION_RELS:
                    raise ValueError(f"Ungültige Verknüpfung: {rel}")
                links_by_rel[rel] = {"rel": rel, "href": href}
            payload["links"] = list(links_by_rel.values())
        return payload

    def _continuation_link(self, service: dict[str, Any]) -> dict[str, str] | None:
        destinations = [
            {"rel": link.get("rel"), "href": link.get("href")}
            for link in service.get("links", [])
            if link.get("rel") in self.DESTINATION_RELS and link.get("href")
        ]
        time_control_links = [
            link
            for link in destinations
            if self._target_from_href(link["href"])["kind"] == "time-control-services"
        ]
        if len(time_control_links) == 1:
            return time_control_links[0]
        if not time_control_links and len(destinations) == 2:
            # Terminal weekday nodes continue through their denied/fallback route.
            return next((link for link in destinations if link["rel"] == "destinationIfDenied"), None)
        return None

    def _validate_destination_href(self, value: Any) -> str:
        href = str(value or "").strip()
        allowed = {option["href"] for option in self.list_destination_options()}
        if href not in allowed:
            raise ValueError("Das gewählte Ansage-/Anrufbeantworter-Ziel ist nicht verfügbar.")
        return href

    def _window_times(self, mode: str, values: dict[str, Any]) -> tuple[str, str]:
        if mode == "morning":
            from_time = str(values.get("from_time") or "00:00")
            to_time = str(values.get("to_time") or "12:00")
        elif mode == "afternoon":
            from_time = str(values.get("from_time") or "12:00")
            to_time = str(values.get("to_time") or "23:59")
        else:
            from_time = str(values.get("from_time") or "")
            to_time = str(values.get("to_time") or "")
        self._format_api_time(from_time)
        self._format_api_time(to_time)
        if from_time >= to_time:
            raise ValueError("Die Ende-Uhrzeit muss nach der Start-Uhrzeit liegen.")
        return from_time, to_time

    def _create_time_control(
        self,
        *,
        name: str,
        denied_dates: list[str],
        from_time: str,
        to_time: str,
        allowed_href: str,
        denied_href: str,
    ) -> dict[str, str]:
        payload = {
            "data": [
                {"name": "name", "value": name},
                {"name": "displayName", "value": name},
                {"name": "evaluationStrategy", "value": "AUTO"},
                {"name": "fromDay", "value": "MONDAY"},
                {"name": "fromTimeOfDay", "value": self._format_api_time(from_time)},
                {"name": "toDay", "value": "SUNDAY"},
                {"name": "toTimeOfDay", "value": self._format_api_time(to_time)},
                {"name": "referralAllowed", "value": []},
                {"name": "referralDenied", "value": denied_dates},
            ],
            "links": [
                {"rel": "destinationIfAllowed", "href": allowed_href},
                {"rel": "destinationIfDenied", "href": denied_href},
            ],
        }
        response = self.client.post(self._collection_path(), json.dumps(payload).encode("utf-8"))
        if response.status_code >= 300:
            raise ValueError(self._format_error_response(response))
        try:
            body = response.json()
        except Exception:
            body = {}
        href = body.get("href") if isinstance(body, dict) else None
        href = href or response.headers.get("Location")
        if not href:
            raise ValueError("NFON hat die neue Zeitsteuerung ohne ID bestätigt. Die Kette wurde nicht verändert.")
        return {"id": href.rstrip("/").split("/")[-1], "href": href}

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
