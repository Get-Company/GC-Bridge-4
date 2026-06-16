from __future__ import annotations

import hashlib
import hmac
import base64
from datetime import datetime, timezone
from email.utils import formatdate
from urllib.parse import quote
import requests


BASE_URL = "https://portal-api.nfon.net:8090"


class NfonClient:
    def __init__(self, api_key_id: str, api_key_secret: str, customer_id: str, app_name: str = "GC-Bridge", app_version: str = "4"):
        self.api_key_id = api_key_id
        self.api_key_secret = api_key_secret
        self.customer_id = customer_id
        self.user_agent = f"{app_name}/{app_version} ({customer_id})"
        self.session = requests.Session()

    def _date_header(self) -> str:
        return formatdate(usegmt=True)

    def _encode_path(self, path: str) -> str:
        return quote(path, safe="/-_~.:@!$&'()*+,;=?")

    def _sign(self, method: str, path: str, date: str, content_md5: str = "", content_type: str = "") -> str:
        parts = [method.upper()]
        if content_md5:
            parts.append(content_md5)
        if content_type:
            parts.append(content_type)
        parts.append(date)
        parts.append(self._encode_path(path))
        string_to_sign = "\n".join(parts)
        key = self.api_key_secret.encode("utf-8")
        sig = hmac.new(key, string_to_sign.encode("utf-8"), hashlib.sha1).digest()
        return base64.b64encode(sig).decode("utf-8")

    def _auth_header(self, method: str, path: str, date: str, content_md5: str = "", content_type: str = "") -> str:
        sig = self._sign(method, path, date, content_md5, content_type)
        return f"NFON-API {self.api_key_id}:{sig}"

    def get(self, path: str, **kwargs) -> requests.Response:
        date = self._date_header()
        headers = {
            "Authorization": self._auth_header("GET", path, date),
            "x-nfon-date": date,
            "User-Agent": self.user_agent,
            "Content-Type": "application/json",
        }
        return self.session.get(f"{BASE_URL}{path}", headers=headers, timeout=15, **kwargs)

    def post(self, path: str, body: bytes, content_type: str = "application/json") -> requests.Response:
        date = self._date_header()
        content_md5 = hashlib.md5(body).hexdigest()
        headers = {
            "Authorization": self._auth_header("POST", path, date, content_md5, content_type),
            "x-nfon-date": date,
            "Content-MD5": content_md5,
            "Content-Type": content_type,
            "User-Agent": self.user_agent,
        }
        return self.session.post(f"{BASE_URL}{path}", data=body, headers=headers, timeout=15)

    def put(self, path: str, body: bytes, content_type: str = "application/json") -> requests.Response:
        date = self._date_header()
        content_md5 = hashlib.md5(body).hexdigest()
        headers = {
            "Authorization": self._auth_header("PUT", path, date, content_md5, content_type),
            "x-nfon-date": date,
            "Content-MD5": content_md5,
            "Content-Type": content_type,
            "User-Agent": self.user_agent,
        }
        return self.session.put(f"{BASE_URL}{path}", data=body, headers=headers, timeout=15)

    def delete(self, path: str) -> requests.Response:
        date = self._date_header()
        headers = {
            "Authorization": self._auth_header("DELETE", path, date),
            "x-nfon-date": date,
            "User-Agent": self.user_agent,
            "Content-Type": "application/json",
        }
        return self.session.delete(f"{BASE_URL}{path}", headers=headers, timeout=15)
