from __future__ import annotations

import hashlib
import json
import os
import re
from urllib.parse import quote, unquote, urlsplit

from core.services import BaseService
from core.services.nfon_client import BASE_URL, NfonClient


KEY_TYPES = (
    ("SPEEDDIAL", "Kurzwahl (externe Rufnummer)"),
    ("MONITOR", "Nebenstelle mit Besetztanzeige (BLF)"),
    ("SERVICE", "Dienst"),
    ("INTERCOM", "Gegensprechen"),
    ("FUNCTION_CODE", "Funktionscode"),
)


class NfonFunctionKeyService(BaseService):
    """Manage the shared key assignment of an NFON phone extension."""

    def __init__(self, client=None, customer_id=None):
        self.customer_id = customer_id or os.environ["NFON_CUSTOMER_ID"]
        self.client = client or NfonClient(
            os.environ["NFON_API_KEY_ID"], os.environ["NFON_API_KEY_SECRET"], self.customer_id
        )
        self.root = f"/api/customers/{self.customer_id}"

    @staticmethod
    def _data(item):
        return {field["name"]: field.get("value") for field in item.get("data", [])}

    def _local_path(self, href):
        parsed = urlsplit(str(href))
        if parsed.scheme or parsed.netloc:
            if (parsed.scheme, parsed.netloc) != ("https", urlsplit(BASE_URL).netloc):
                raise ValueError("NFON hat einen ungültigen Verweis geliefert.")
        path = unquote(parsed.path)
        if not path.startswith(self.root + "/") or any(p in {".", ".."} for p in path.split("/")):
            raise ValueError("Der NFON-Verweis gehört nicht zu dieser Telefonanlage.")
        return parsed.path + (f"?{parsed.query}" if parsed.query else "")

    def _collection(self, path):
        items, seen = [], set()
        while path:
            path = self._local_path(path)
            if path in seen:
                raise ValueError("NFON hat eine wiederholte Ergebnisseite geliefert.")
            seen.add(path)
            response = self.client.get(path)
            response.raise_for_status()
            raw = response.json()
            if isinstance(raw, list):
                items.extend(raw)
                break
            raw = raw.get("collection", raw)
            items.extend(raw.get("items", []))
            path = next((l["href"] for l in raw.get("links", []) if l.get("rel") == "next"), None)
        return items

    def _extension_path(self, extension):
        extension = str(extension)
        if not re.fullmatch(r"[0-9]+", extension):
            raise ValueError("Bitte eine gültige Nebenstelle auswählen.")
        return f"{self.root}/targets/phone-extensions/{extension}"

    def list_extensions(self):
        extensions = []
        devices_by_extension = {}
        for device in self._collection(self.root + "/devices"):
            fields = self._data(device)
            number = fields.get("extension")
            if number is not None:
                devices_by_extension.setdefault(str(number), []).append({
                    "model": fields.get("deviceType") or "Telefon",
                    "identifier": fields.get("uniqueIdentifier") or fields.get("deviceId") or "",
                    "active": fields.get("active", False),
                })
        for item in self._collection(f"{self.root}/targets/phone-extensions"):
            data = self._data(item)
            number = str(data["extensionNumber"])
            path = self._extension_path(number)
            devices = devices_by_extension.get(number, [])
            lines = []
            for line in self._collection(path + "/inbound-trunk-numbers"):
                fields = self._data(line)
                # didNumber is the complete dial-in number; didExtension is already included.
                value = fields.get("didNumber") or fields.get("trunkNumber")
                if value and str(value) not in lines:
                    lines.append(str(value))
            name = data.get("displayName") or data.get("name") or f"Nebenstelle {number}"
            alias = data.get("name") if data.get("name") != name else ""
            extensions.append({
                "number": number, "name": name, "alias": alias or "", "devices": devices,
                "lines": lines,
                "search": " ".join([number, name, alias or "", *lines,
                                     *(f"{d['model']} {d['identifier']}" for d in devices)]),
            })
        return sorted(extensions, key=lambda e: (int(e["number"]), e["name"].casefold()))

    def list_targets(self, extension):
        result = []
        for item in self._collection(self._extension_path(extension) + "/function-keys/available-targets"):
            data = self._data(item)
            href = self._local_path(item["href"])
            category = href[len(self.root + "/targets/"):].split("/", 1)[0]
            if category not in {"phone-extensions", "conference-services", "group-services", "ivr-services",
                                 "queue-services", "skill-services", "time-control-services"}:
                continue
            label = data.get("displayName") or data.get("targetName") or data.get("name") or "Ziel"
            number = data.get("extensionNumber")
            result.append({"href": href, "label": f"{label} · {number}" if number else label,
                           "kind": "MONITOR" if category == "phone-extensions" else "SERVICE"})
        return sorted(result, key=lambda t: t["label"].casefold())

    def list_keys(self, extension):
        result = []
        for item in self._collection(self._extension_path(extension) + "/function-keys"):
            data = self._data(item)
            target = next((l["href"] for l in item.get("links", []) if l.get("rel") == "target"), "")
            external = ""
            if target:
                target = self._local_path(target)
                prefix = self.root + "/targets/external/"
                if target.startswith(prefix):
                    external = unquote(urlsplit(target).path[len(prefix):])
            key = {
                "key_number": int(data["keyNumber"]), "type": data.get("type", ""),
                "display_name": data.get("displayName") or "", "target": target,
                "phone_number": external, "function_code": data.get("functionCode") or "",
                "target_name": data.get("targetName") or external or data.get("functionCode") or "",
            }
            key["position"] = key["key_number"] + 1
            key["type_label"] = dict(KEY_TYPES).get(key["type"], key["type"])
            key["fingerprint"] = self.fingerprint(key)
            result.append(key)
        return sorted(result, key=lambda k: k["key_number"])

    @staticmethod
    def fingerprint(key):
        fields = ("key_number", "type", "display_name", "target", "function_code")
        return hashlib.sha256(json.dumps({f: key[f] for f in fields}, sort_keys=True).encode()).hexdigest()

    def _current_key(self, extension, number, expected):
        key = next((k for k in self.list_keys(extension) if k["key_number"] == number), None)
        if not key or not expected or key["fingerprint"] != expected:
            raise ValueError("Die Tastenbelegung wurde inzwischen geändert. Bitte neu laden und erneut prüfen.")
        return key

    def save_key(self, extension, values, *, existing_number=None, expected=""):
        path = self._extension_path(extension) + "/function-keys"
        number = int(values["position"]) - 1
        if not 0 <= number <= 1023:
            raise ValueError("Die Tastenposition muss zwischen 1 und 1024 liegen.")
        if existing_number is not None:
            if number != existing_number:
                raise ValueError("Zum Verschieben bitte die Taste an der neuen Position anlegen.")
            self._current_key(extension, number, expected)
        elif any(k["key_number"] == number for k in self.list_keys(extension)):
            raise ValueError("Diese Position ist bereits belegt. Bitte die vorhandene Taste bearbeiten.")
        kind = values["type"]
        if kind not in dict(KEY_TYPES):
            raise ValueError("Unbekannter Tastentyp.")
        data = [{"name": "type", "value": kind},
                {"name": "displayName", "value": values["display_name"]}]
        links = []
        if kind == "FUNCTION_CODE":
            code = values.get("function_code", "").strip()
            if not re.fullmatch(r"[0-9*#]+", code):
                raise ValueError("Bitte einen gültigen Funktionscode aus Ziffern, * und # eingeben.")
            data.append({"name": "functionCode", "value": code})
        elif kind == "SPEEDDIAL":
            phone = re.sub(r"[\s().-]", "", values.get("phone_number", ""))
            if not re.fullmatch(r"\+?[0-9]+", phone):
                raise ValueError("Bitte eine gültige externe Rufnummer eingeben.")
            links.append({"rel": "target", "href": self.root + "/targets/external/" + quote(phone, safe="+")})
        else:
            target = values.get("target", "")
            required_kind = "MONITOR" if kind == "INTERCOM" else kind
            if not any(t["href"] == target and t["kind"] == required_kind for t in self.list_targets(extension)):
                raise ValueError("Bitte ein zum Tastentyp passendes Ziel dieser Telefonanlage auswählen.")
            links.append({"rel": "target", "href": target})
        if existing_number is None:
            data.append({"name": "keyNumber", "value": number})
        body = json.dumps({"data": data, "links": links}).encode("utf-8")
        response = (self.client.post(path, body) if existing_number is None
                    else self.client.put(f"{path}/{number}", body))
        self._check_write(response)

    def delete_key(self, extension, number, *, expected):
        self._current_key(extension, number, expected)
        response = self.client.delete(self._extension_path(extension) + f"/function-keys/{number}")
        self._check_write(response)

    @staticmethod
    def _check_write(response):
        if 200 <= response.status_code < 300:
            return
        try:
            error = response.json()
            details = "; ".join(str(e.get("message", "")) for e in error.get("errors", []))
            message = details or error.get("detail") or error.get("title")
        except (ValueError, AttributeError):
            message = None
        raise ValueError(f"NFON konnte die Änderung nicht speichern (HTTP {response.status_code}): "
                         f"{message or 'Bitte später erneut versuchen.'}")
