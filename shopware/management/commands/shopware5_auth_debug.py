from __future__ import annotations

import hashlib
import json
import os
from types import SimpleNamespace
from typing import Any

import requests
from django.core.management.base import CommandError
from loguru import logger
from requests.auth import HTTPBasicAuth, HTTPDigestAuth

from core.management.base import MonitoredBaseCommand
from shopware.models import Shopware5Settings
from shopware.services import Shopware5ProductSyncService


def _body_preview(response: requests.Response, *, limit: int = 800) -> str:
    text = response.text or ""
    return text[:limit]


def _authorization_summary(response: requests.Response) -> dict[str, Any]:
    authorization = response.request.headers.get("Authorization", "")
    return {
        "present": bool(authorization),
        "scheme": authorization.split(" ", 1)[0] if authorization else "",
        "is_digest": authorization.startswith("Digest "),
        "is_basic": authorization.startswith("Basic "),
    }


def _response_summary(response: requests.Response) -> dict[str, Any]:
    return {
        "status_code": response.status_code,
        "url": response.request.url,
        "elapsed_ms": round(response.elapsed.total_seconds() * 1000, 2),
        "www_authenticate": response.headers.get("WWW-Authenticate", ""),
        "content_type": response.headers.get("Content-Type", ""),
        "authorization": _authorization_summary(response),
        "history": [
            {
                "status_code": item.status_code,
                "www_authenticate": item.headers.get("WWW-Authenticate", ""),
                "authorization": _authorization_summary(item),
            }
            for item in response.history
        ],
        "body_preview": _body_preview(response),
    }


def _fingerprint(value: str) -> str:
    if not value:
        return ""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]


def _env_value(names: tuple[str, ...]) -> tuple[str, str]:
    for name in names:
        value = os.getenv(name)
        if value:
            return name, value.strip()
    return "", ""


def _config_field_summary(
    *,
    settings_obj: Shopware5Settings | None,
    field_name: str,
    env_names: tuple[str, ...],
    effective_value: str,
    is_secret: bool = False,
) -> dict[str, Any]:
    db_value = str(getattr(settings_obj, field_name, "") or "").strip() if settings_obj else ""
    env_name, env_value = _env_value(env_names)
    if db_value:
        source = "db"
    elif env_value:
        source = env_name
    else:
        source = "missing"

    result: dict[str, Any] = {
        "source": source,
        "db_set": bool(db_value),
        "env_name": env_name,
        "env_set": bool(env_value),
    }
    if is_secret:
        result.update(
            {
                "effective_len": len(effective_value or ""),
                "effective_fingerprint": _fingerprint(effective_value or ""),
                "db_len": len(db_value),
                "db_fingerprint": _fingerprint(db_value),
                "env_len": len(env_value),
                "env_fingerprint": _fingerprint(env_value),
                "db_env_match": bool(db_value and env_value and db_value == env_value),
            }
        )
    else:
        result.update(
            {
                "effective": effective_value,
                "db": db_value,
                "env": env_value,
                "db_env_match": bool(db_value and env_value and db_value == env_value),
            }
        )
    return result


class Command(MonitoredBaseCommand):
    help = "Debug Shopware5 API authentication step by step without writing product data."

    def add_arguments(self, parser):
        parser.add_argument(
            "product_number",
            nargs="?",
            default="091300",
            help="Artikelnummer fuer den Test-Lookup mit useNumberAsId=true (Default: 091300).",
        )
        parser.add_argument(
            "--auth-mode",
            choices=("digest", "basic", "both"),
            default="both",
            help="Welche Auth-Methode getestet wird (Default: both).",
        )
        parser.add_argument(
            "--config-source",
            choices=("auto", "env"),
            default="auto",
            help="Konfigurationsquelle fuer den Test. auto nutzt DB mit .env-Fallback, env ignoriert DB-Werte.",
        )
        parser.add_argument(
            "--timeout",
            type=int,
            default=30,
            help="Request-Timeout in Sekunden (Default: 30).",
        )
        parser.add_argument(
            "--fail-on-error",
            action="store_true",
            help="Mit CommandError abbrechen, wenn kein Auth-Test erfolgreich ist.",
        )

    def handle(self, *args, **options):
        product_number = str(options["product_number"] or "").strip()
        timeout = int(options["timeout"] or 30)
        auth_mode = options["auth_mode"]
        config_source = options["config_source"]
        if not product_number:
            raise CommandError("Keine Artikelnummer angegeben.")

        settings_obj = None
        if config_source == "env":
            settings_obj = SimpleNamespace(api_url="", username="", api_token="")
        service = Shopware5ProductSyncService(settings_obj=settings_obj)
        loaded_settings = None if config_source == "env" else service.settings
        path = f"/articles/{product_number}?useNumberAsId=true"
        url = f"{service.base_url}{path}"

        self._step(
            "config",
            {
                "base_url": service.base_url,
                "config_source": config_source,
                "config_fields": {
                    "api_url": _config_field_summary(
                        settings_obj=loaded_settings,
                        field_name="api_url",
                        env_names=("SHOPWARE5_API_URL", "SHOPWARE_API_URL"),
                        effective_value=service.base_url,
                    ),
                    "username": _config_field_summary(
                        settings_obj=loaded_settings,
                        field_name="username",
                        env_names=("SHOPWARE5_API_USER", "SHOPWARE_API_USER"),
                        effective_value=service.username,
                    ),
                    "api_token": _config_field_summary(
                        settings_obj=loaded_settings,
                        field_name="api_token",
                        env_names=("SHOPWARE5_API_TOKEN", "SHOPWARE_API_TOKEN"),
                        effective_value=service.api_token,
                        is_secret=True,
                    ),
                },
                "product_number": product_number,
                "url": url,
                "username": service.username,
                "has_token": bool(service.api_token),
                "token_len": len(service.api_token or ""),
                "token_is_alnum": bool((service.api_token or "").isalnum()),
            },
        )
        service._validate_config()

        self._step("request_without_auth_start", {"url": url})
        without_auth = requests.Session()
        without_auth_response = without_auth.get(url, timeout=timeout)
        self._step("request_without_auth_result", _response_summary(without_auth_response))

        results: dict[str, bool] = {}
        if auth_mode in {"digest", "both"}:
            results["digest"] = self._run_auth_request(
                name="digest",
                url=url,
                auth=HTTPDigestAuth(service.username, service.api_token),
                timeout=timeout,
            )

        if auth_mode in {"basic", "both"}:
            results["basic"] = self._run_auth_request(
                name="basic",
                url=url,
                auth=HTTPBasicAuth(service.username, service.api_token),
                timeout=timeout,
            )

        self._step("summary", {"results": results, "success": any(results.values())})
        if options["fail_on_error"] and not any(results.values()):
            raise CommandError("Shopware5 Auth-Debug: kein Auth-Test war erfolgreich.")

    def _run_auth_request(self, *, name: str, url: str, auth, timeout: int) -> bool:
        self._step(f"{name}_request_start", {"url": url})
        session = requests.Session()
        session.auth = auth
        try:
            response = session.get(url, timeout=timeout)
        except requests.RequestException as exc:
            self._step(f"{name}_request_exception", {"error": str(exc)})
            return False

        summary = _response_summary(response)
        self._step(f"{name}_request_result", summary)
        return 200 <= response.status_code < 300

    def _step(self, name: str, payload: dict[str, Any]) -> None:
        message = f"Shopware5 auth debug step={name} payload={json.dumps(payload, ensure_ascii=False, sort_keys=True)}"
        logger.info(message)
        self.stdout.write(message)
