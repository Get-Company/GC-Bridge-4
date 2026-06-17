from __future__ import annotations

import os
import socket
import time
from urllib.parse import urlsplit

from django.conf import settings
from django.http import JsonResponse


_STATUS_CACHE = {
    "checked_at": 0.0,
    "value": None,
}
_STATUS_CACHE_SECONDS = 15.0


def _cached_status() -> dict | None:
    checked_at = float(_STATUS_CACHE.get("checked_at") or 0.0)
    value = _STATUS_CACHE.get("value")
    if value is not None and time.monotonic() - checked_at < _STATUS_CACHE_SECONDS:
        return dict(value)
    return None


def _store_status(value: dict) -> dict:
    _STATUS_CACHE.update({"checked_at": time.monotonic(), "value": value})
    return value


def _microtech_graphql_status() -> dict:
    try:
        from microtech.services.graphql_client import (
            MicrotechGraphQLClientService,
            MicrotechGraphQLConfig,
        )

        configured = MicrotechGraphQLConfig.from_settings()
        config = MicrotechGraphQLConfig(
            url=configured.url,
            request_timeout=float(getattr(settings, "ADMIN_STATUS_GRAPHQL_TIMEOUT", 1.0)),
            poll_timeout=configured.poll_timeout,
            poll_interval=configured.poll_interval,
        )
        health = MicrotechGraphQLClientService(config=config).health()
        ok = health == "ok"
        return {
            "label": "GraphQL",
            "ok": ok,
            "status": "ok" if ok else "error",
            "detail": health or "Unerwartete Antwort",
        }
    except ValueError:
        return {
            "label": "GraphQL",
            "ok": None,
            "status": "not_configured",
            "detail": "nicht konfiguriert",
        }
    except Exception as exc:
        return {
            "label": "GraphQL",
            "ok": False,
            "status": "error",
            "detail": str(exc),
        }


def _shopware_base_url() -> str:
    try:
        from shopware.models import ShopwareConnection

        connection = ShopwareConnection.objects.filter(pk=1).first()
        if connection and connection.api_url:
            return connection.api_url.rstrip("/")
    except Exception:
        pass

    for key in ("SHOPWARE6_ADMIN_API_URL", "SHOPWARE_API_BASE_URL"):
        value = os.getenv(key)
        if value:
            return value.rstrip("/")
    return ""


def _shopware_status() -> dict:
    base_url = _shopware_base_url()
    if not base_url:
        return {
            "label": "Shopware",
            "ok": None,
            "status": "not_configured",
            "detail": "nicht konfiguriert",
        }

    try:
        parsed = urlsplit(base_url)
        host = parsed.hostname
        if not host:
            raise ValueError("ungueltige URL")
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        timeout = float(getattr(settings, "ADMIN_STATUS_SHOPWARE_TIMEOUT", 0.8))
        with socket.create_connection((host, port), timeout=timeout):
            pass
        return {
            "label": "Shopware",
            "ok": True,
            "status": "ok",
            "detail": host,
        }
    except Exception as exc:
        return {
            "label": "Shopware",
            "ok": False,
            "status": "error",
            "detail": str(exc),
        }


def admin_status_bar_api(request):
    cached = _cached_status()
    if cached is not None:
        return JsonResponse(cached)

    payload = {
        "services": {
            "graphql": _microtech_graphql_status(),
            "shopware": _shopware_status(),
        }
    }
    return JsonResponse(_store_status(payload))
