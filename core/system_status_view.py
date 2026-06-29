from __future__ import annotations

import json
import socket
import time
from typing import Any
from urllib.parse import urlsplit

from django.conf import settings
from django.contrib import admin
from django.http import JsonResponse
from django.template.response import TemplateResponse


TASK_LABELS: dict[str, str] = {
    "products.sync_from_microtech": "Microtech → Django importieren",
    "products.sync_to_shopware": "Django → Shopware exportieren",
    "products.sync_to_microtech": "Django → Microtech schreiben",
    "products.expire_special_prices": "Abgelaufene Sonderpreise bereinigen",
    "products.scheduled_product_sync": "Produkt-Sync komplett",
    "products.microtech_sync_products": "Microtech Import",
    "products.microtech_update_product": "Microtech Produkt aktualisieren",
    "products.microtech_update_prices": "Microtech Preise aktualisieren",
    "products.process_product_sync_job": "Produkt Auto-Sync Job",
    "products.shopware_sync_products": "Shopware Export",
    "products.shopware_force_product_image_uploads": "Shopware Bilder neu hochladen",
    "orders.shopware_sync_open_orders": "Offene Bestellungen importieren",
    "orders.microtech_order_upsert": "Bestellung nach Microtech",
    "customer.microtech_customer_upsert": "Kunde nach Microtech",
    "customer.microtech_customer_lookup": "Kunde aus Microtech importieren",
    "mappei.scrape_daily_prices": "Mappei Preise scrapen",
    "hr.sync_holidays": "Ferien & Feiertage synchronisieren",
    "hr.year_transition": "HR Jahreswechsel",
    "emails.queue_due_campaigns_before_send": "E-Mail-Kampagnen vor Sendedatum rendern",
}

_WORKERS_CACHE: dict[str, Any] = {"checked_at": 0.0, "value": None}
_WORKERS_CACHE_SECONDS = 5.0


def _celery_broker_endpoint() -> tuple[str, int] | None:
    broker_url = str(getattr(settings, "CELERY_BROKER_URL", "") or "").strip()
    if not broker_url:
        return None
    try:
        parsed = urlsplit(broker_url)
    except ValueError:
        return None
    scheme = parsed.scheme.lower()
    if scheme in {"redis", "rediss"}:
        return (parsed.hostname or "localhost", parsed.port or 6379)
    if scheme in {"amqp", "pyamqp"}:
        return (parsed.hostname or "localhost", parsed.port or 5672)
    return None


def _is_celery_broker_reachable() -> tuple[bool, str]:
    endpoint = _celery_broker_endpoint()
    if endpoint is None:
        return True, ""
    timeout = float(getattr(settings, "SYSTEM_STATUS_BROKER_CONNECT_TIMEOUT", 0.2))
    host, port = endpoint
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True, ""
    except OSError as exc:
        return False, f"Broker {host}:{port} nicht erreichbar: {exc}"


def _get_graphql_health() -> dict:
    from microtech.services.graphql_client import MicrotechGraphQLConfig

    try:
        cfg = MicrotechGraphQLConfig.from_settings()
        url = cfg.url
    except ValueError:
        return {
            "url": "",
            "status": "not_configured",
            "ok": False,
            "latency_ms": None,
            "error": "MICROTECH_GRAPHQL_URL nicht gesetzt",
        }

    t0 = time.monotonic()
    try:
        from microtech.services import MicrotechGraphQLClientService

        result = MicrotechGraphQLClientService(config=cfg).health()
        latency_ms = round((time.monotonic() - t0) * 1000)
        ok = result == "ok"
        return {
            "url": url,
            "status": result if result else "leer",
            "ok": ok,
            "latency_ms": latency_ms,
            "error": None if ok else f"Unerwartete Antwort: {result!r}",
        }
    except Exception as exc:
        latency_ms = round((time.monotonic() - t0) * 1000)
        return {
            "url": url,
            "status": "error",
            "ok": False,
            "latency_ms": latency_ms,
            "error": str(exc),
        }


def _get_shopware_health() -> dict:
    from core.admin_status import shopware_health_check
    return shopware_health_check()


def _get_workers_with_tasks() -> dict[str, Any]:
    now = time.monotonic()
    cached = _WORKERS_CACHE.get("value")
    if cached is not None and now - float(_WORKERS_CACHE.get("checked_at") or 0.0) < _WORKERS_CACHE_SECONDS:
        return dict(cached)

    broker_available, broker_error = _is_celery_broker_reachable()
    if not broker_available:
        result: dict = {"available": False, "error": broker_error, "workers": [], "broker_url": ""}
        _WORKERS_CACHE.update({"checked_at": now, "value": result})
        return result

    broker_url = str(getattr(settings, "CELERY_BROKER_URL", "") or "")
    try:
        from celery import current_app

        timeout = float(getattr(settings, "SYSTEM_STATUS_CELERY_INSPECT_TIMEOUT", 0.5))
        inspect = current_app.control.inspect(timeout=timeout)
        ping = inspect.ping() or {}
        active_by_worker = inspect.active() or {}

        all_worker_names = sorted(set(ping) | set(active_by_worker))
        workers = []
        for name in all_worker_names:
            tasks = active_by_worker.get(name) or []
            workers.append(
                {
                    "name": name,
                    "online": name in ping,
                    "active_tasks": [
                        {
                            "id": t.get("id", ""),
                            "name": t.get("name", ""),
                            "label": TASK_LABELS.get(
                                t.get("name", ""),
                                t.get("name") or "Unbekannter Task",
                            ),
                            "args": str(t.get("argsrepr") or t.get("args") or ""),
                        }
                        for t in tasks
                    ],
                }
            )

        result = {"available": True, "error": "", "broker_url": broker_url, "workers": workers}
    except Exception as exc:
        result = {"available": False, "error": str(exc), "broker_url": broker_url, "workers": []}

    _WORKERS_CACHE.update({"checked_at": now, "value": result})
    return result


def _crontab_to_human(minute: str, hour: str, day_of_week: str, day_of_month: str, month_of_year: str) -> str:
    DAYS = {"0": "So", "1": "Mo", "2": "Di", "3": "Mi", "4": "Do", "5": "Fr", "6": "Sa", "7": "So"}

    if minute == "*" and hour == "*" and day_of_week == "*" and day_of_month == "*" and month_of_year == "*":
        return "jede Minute"
    if minute == "0" and hour == "*" and day_of_week == "*" and day_of_month == "*" and month_of_year == "*":
        return "jede Stunde (zur vollen Stunde)"

    is_daily = day_of_week == "*" and day_of_month == "*" and month_of_year == "*"
    is_simple_time = "/" not in hour and "," not in hour and hour != "*"
    is_simple_minute = "/" not in minute and "," not in minute and minute != "*"

    if is_daily and is_simple_time and is_simple_minute:
        h = hour.zfill(2)
        m = minute.zfill(2)
        return f"täglich um {h}:{m}"

    if day_of_week != "*" and day_of_month == "*" and month_of_year == "*" and is_simple_time:
        parts = [d.strip() for d in day_of_week.split(",")]
        day_labels = ", ".join(DAYS.get(d, d) for d in parts)
        h = hour.zfill(2) if hour != "*" else "?"
        m = minute.zfill(2) if minute != "*" else "00"
        return f"{day_labels} um {h}:{m}"

    return f"{minute} {hour} {day_of_month} {month_of_year} {day_of_week}"


def _human_schedule(task: Any) -> str:
    if task.interval:
        s = task.interval
        unit_map = {
            "seconds": "Sekunde(n)",
            "minutes": "Minute(n)",
            "hours": "Stunde(n)",
            "days": "Tag(e)",
            "microseconds": "Mikrosekunde(n)",
        }
        unit = unit_map.get(s.period, s.period)
        every = s.every
        if s.period == "seconds" and every == 60:
            return "jede Minute"
        if s.period == "minutes" and every == 1:
            return "jede Minute"
        if s.period == "minutes" and every == 60:
            return "jede Stunde"
        if s.period == "hours" and every == 1:
            return "jede Stunde"
        if s.period == "hours" and every == 24:
            return "täglich"
        if s.period == "days" and every == 1:
            return "täglich"
        return f"alle {every} {unit}"

    if task.crontab:
        c = task.crontab
        return _crontab_to_human(c.minute, c.hour, c.day_of_week, c.day_of_month, c.month_of_year)

    if task.clocked:
        try:
            return f"einmalig am {task.clocked.clocked_time.strftime('%d.%m.%Y %H:%M')}"
        except Exception:
            return "einmalig (Datum unbekannt)"

    if task.solar:
        return f"solar: {task.solar.event}"

    return "kein Schedule"


def _get_periodic_tasks() -> list[dict]:
    try:
        from django_celery_beat.models import PeriodicTask

        tasks = PeriodicTask.objects.select_related(
            "interval", "crontab", "clocked", "solar"
        ).order_by("name")
        result = []
        for t in tasks:
            result.append(
                {
                    "name": t.name,
                    "task": t.task,
                    "label": TASK_LABELS.get(t.task, t.name),
                    "enabled": t.enabled,
                    "schedule": _human_schedule(t),
                    "last_run_at": t.last_run_at.strftime("%d.%m.%Y %H:%M:%S") if t.last_run_at else "noch nie",
                    "total_run_count": t.total_run_count,
                }
            )
        return result
    except Exception:
        return []


def system_status_view(request):
    graphql_health = _get_graphql_health()
    shopware_health = _get_shopware_health()
    workers_data = _get_workers_with_tasks()
    periodic_tasks = _get_periodic_tasks()

    context = {
        **admin.site.each_context(request),
        "title": "System-Status",
        "graphql_health": graphql_health,
        "shopware_health": shopware_health,
        "workers_data": workers_data,
        "periodic_tasks": periodic_tasks,
    }
    return TemplateResponse(request, "admin/system_status.html", context)


def system_status_api(request):
    graphql_health = _get_graphql_health()
    shopware_health = _get_shopware_health()
    workers_data = _get_workers_with_tasks()

    return JsonResponse(
        {
            "graphql_health": graphql_health,
            "shopware_health": shopware_health,
            "workers_data": workers_data,
        }
    )
