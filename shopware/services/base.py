import json
import os
import urllib.error
import urllib.parse
import urllib.request
from abc import ABC, abstractmethod
from typing import Any

from loguru import logger

from core.services import BaseService


class ShopwareBaseService(BaseService, ABC):
    api_base_url_env = ("SHOPWARE6_ADMIN_API_URL", "SHOPWARE_API_BASE_URL")
    client_id_env = ("SHOPWARE6_ID", "SHOPWARE_CLIENT_ID")
    client_secret_env = ("SHOPWARE6_SECRET", "SHOPWARE_CLIENT_SECRET")
    access_token_env = ("SHOPWARE6_ACCESS_TOKEN", "SHOPWARE_ACCESS_TOKEN")
    grant_type_env = ("SHOPWARE6_GRANT_TYPE", "SHOPWARE_GRANT_TYPE")
    username_env = ("SHOPWARE6_USER", "SHOPWARE_USERNAME")
    password_env = ("SHOPWARE6_PASSWORD", "SHOPWARE_PASSWORD")

    timeout_seconds = 30

    def __init__(self) -> None:
        self.base_url = self._get_env(self.api_base_url_env).rstrip("/")
        self.client_id = self._get_env(self.client_id_env)
        self.client_secret = self._get_env(self.client_secret_env)
        self.access_token = self._get_env(self.access_token_env)
        self.grant_type = self._get_env(self.grant_type_env) or "resource_owner"
        self.username = self._get_env(self.username_env)
        self.password = self._get_env(self.password_env)
        self.logger = logger

    @abstractmethod
    def authenticate(self) -> str:
        raise NotImplementedError

    def request(
        self,
        method: str,
        path: str,
        *,
        payload: dict | None = None,
        params: dict | None = None,
        headers: dict | None = None,
        require_auth: bool = True,
    ) -> Any:
        if not self.base_url:
            raise ValueError("Missing Shopware API base URL environment variable.")

        if require_auth and not self.access_token:
            self.access_token = self.authenticate()

        url = self._build_url(path, params)
        body = json.dumps(payload).encode("utf-8") if payload is not None else None

        request_headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        if require_auth:
            request_headers["Authorization"] = f"Bearer {self.access_token}"
        if headers:
            request_headers.update(headers)

        request = urllib.request.Request(url=url, data=body, headers=request_headers, method=method.upper())
        self.logger.debug("Shopware request: {} {}", method.upper(), url)
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                parsed = self._parse_response(response.read())
                self.logger.debug("Shopware response: {} {} -> {}", method.upper(), url, parsed)
                return parsed
        except urllib.error.HTTPError as error:
            detail = self._parse_response(error.read())
            self.logger.error("Shopware error {} {} -> {}", method.upper(), url, detail)
            raise RuntimeError(f"Shopware request failed ({error.code}): {detail}") from error
        except urllib.error.URLError as error:
            self.logger.error("Shopware connection error {} {} -> {}", method.upper(), url, error)
            raise RuntimeError("Shopware request failed (connection error)") from error

    def _build_url(self, path: str, params: dict | None) -> str:
        path = path if path.startswith("/") else f"/{path}"
        url = f"{self.base_url}{path}"
        if params:
            query = urllib.parse.urlencode(params)
            url = f"{url}?{query}"
        return url

    @staticmethod
    def _parse_response(raw: bytes) -> Any:
        if not raw:
            return None
        try:
            return json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError:
            return raw.decode("utf-8")

    @staticmethod
    def _get_env(keys: tuple[str, ...]) -> str:
        for key in keys:
            value = os.getenv(key)
            if value:
                return value
        return ""
