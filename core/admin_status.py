from __future__ import annotations

import socket
import time
from urllib.parse import urlsplit

from django.conf import settings
from django.http import JsonResponse


_STATUS_CACHE: dict = {
    "checked_at": 0.0,
    "value": None,
}
_STATUS_CACHE_SECONDS = 15.0

_CELERY_STATUS_CACHE: dict = {
    "checked_at": 0.0,
    "value": None,
}
_CELERY_STATUS_CACHE_SECONDS = 10.0


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
    import os

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
            "url": "",
            "detail": "nicht konfiguriert",
            "latency_ms": None,
        }

    try:
        parsed = urlsplit(base_url)
        host = parsed.hostname
        if not host:
            raise ValueError("ungültige URL")
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        timeout = float(getattr(settings, "ADMIN_STATUS_SHOPWARE_TIMEOUT", 0.8))
        t0 = time.monotonic()
        with socket.create_connection((host, port), timeout=timeout):
            pass
        latency_ms = round((time.monotonic() - t0) * 1000)
        return {
            "label": "Shopware",
            "ok": True,
            "status": "ok",
            "url": base_url,
            "detail": host,
            "latency_ms": latency_ms,
        }
    except Exception as exc:
        return {
            "label": "Shopware",
            "ok": False,
            "status": "error",
            "url": base_url,
            "detail": str(exc),
            "latency_ms": None,
        }


def shopware_health_check() -> dict:
    return _shopware_status()


def _celery_status() -> dict:
    now = time.monotonic()
    cached = _CELERY_STATUS_CACHE.get("value")
    if cached is not None and now - float(_CELERY_STATUS_CACHE.get("checked_at") or 0.0) < _CELERY_STATUS_CACHE_SECONDS:
        return dict(cached)

    broker_url = str(getattr(settings, "CELERY_BROKER_URL", "") or "").strip()
    if not broker_url:
        status: dict = {
            "label": "Celery",
            "ok": None,
            "status": "not_configured",
            "detail": "kein Broker konfiguriert",
            "active_count": 0,
        }
        _CELERY_STATUS_CACHE.update({"checked_at": now, "value": status})
        return status

    try:
        parsed = urlsplit(broker_url)
        scheme = parsed.scheme.lower()
        if scheme in {"redis", "rediss"}:
            host, port = parsed.hostname or "localhost", parsed.port or 6379
        elif scheme in {"amqp", "pyamqp"}:
            host, port = parsed.hostname or "localhost", parsed.port or 5672
        else:
            raise ValueError(f"Unbekanntes Schema: {scheme}")

        timeout = float(getattr(settings, "ADMIN_STATUS_BROKER_TIMEOUT", 0.3))
        with socket.create_connection((host, port), timeout=timeout):
            pass
    except Exception as exc:
        status = {
            "label": "Celery",
            "ok": False,
            "status": "error",
            "detail": str(exc),
            "active_count": 0,
        }
        _CELERY_STATUS_CACHE.update({"checked_at": now, "value": status})
        return status

    try:
        from celery import current_app

        inspect = current_app.control.inspect(timeout=0.3)
        active_by_worker = inspect.active() or {}

        all_active = []
        for worker, tasks in active_by_worker.items():
            worker_short = worker.split("@")[0] if "@" in worker else worker
            for task in tasks or []:
                all_active.append({"worker": worker_short, "name": task.get("name", "")})

        count = len(all_active)
        if count:
            first = all_active[0]
            task_name = first["name"]
            label = task_name.split(".")[-1] if "." in task_name else task_name
            detail = f"{label} · {first['worker']}"
        else:
            detail = "ruhig"

        status = {
            "label": "Celery",
            "ok": True,
            "status": "active" if count else "idle",
            "detail": detail,
            "active_count": count,
        }
    except Exception:
        status = {
            "label": "Celery",
            "ok": True,
            "status": "idle",
            "detail": "ruhig",
            "active_count": 0,
        }

    _CELERY_STATUS_CACHE.update({"checked_at": now, "value": status})
    return status


def admin_status_bar_api(request):
    cached = _cached_status()
    if cached is not None:
        celery = _celery_status()
        cached["services"]["celery"] = celery
        return JsonResponse(cached)

    payload = {
        "services": {
            "graphql": _microtech_graphql_status(),
            "shopware": _shopware_status(),
            "celery": _celery_status(),
        }
    }
    return JsonResponse(_store_status(payload))
