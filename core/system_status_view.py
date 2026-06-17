from __future__ import annotations

import json
import os
import platform
import socket
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from django.conf import settings
from django.contrib import admin
from django.http import JsonResponse
from django.template.response import TemplateResponse
from django.utils import timezone

from core.log_reader import get_allowed_log_files, tail_log_file
from core.services import CommandRuntimeService

TRIGGERABLE_JOBS = [
    {
        "key": "scheduled_product_sync",
        "label": "Produkt-Sync (komplett)",
        "command": "scheduled_product_sync",
        "icon": "sync",
        "description": "Microtech → Django → Shopware (alle 4 Stufen)",
    },
    {
        "key": "microtech_sync_products",
        "label": "Microtech Import",
        "command": "microtech_sync_products",
        "icon": "download",
        "description": "Produkte von Microtech ERP laden",
    },
    {
        "key": "shopware_sync_products",
        "label": "Shopware Export",
        "command": "shopware_sync_products",
        "icon": "upload",
        "description": "Produkte zu Shopware hochladen",
    },
    {
        "key": "shopware_sync_open_orders",
        "label": "Bestellungen importieren",
        "command": "shopware_sync_open_orders",
        "icon": "shopping_cart",
        "description": "Offene Bestellungen aus Shopware holen",
    },
]

_WINDOWS_SCHEDULED_TASKS = [
    "GC-Bridge-Uvicorn",
    "GC-Bridge-Caddy",
    "GC-Bridge-Mappei-Scrape",
]
_WINDOWS_RUNNER_SERVICES = [
    "actions.runner.Get-Company-GC-Bridge-4.GC-Bridge-v4",
]
_CELERY_QUEUE_CACHE: dict[str, Any] = {"checked_at": 0.0, "value": None}
_CELERY_QUEUE_CACHE_SECONDS = 10.0

SYNC_AREAS = [
    {
        "key": "scheduled_product_sync",
        "label": "Produkt-Sync komplett",
        "description": "Microtech -> Django -> Shopware",
        "icon": "sync",
        "commands": ("scheduled_product_sync",),
        "tasks": ("products.scheduled_product_sync",),
        "log_keys": ("scheduled_product_sync", "products", "microtech", "shopware"),
    },
    {
        "key": "microtech",
        "label": "Microtech",
        "description": "ERP-Verbindung, Produkt- und Kundendaten",
        "icon": "database",
        "commands": (
            "microtech_sync_products",
            "microtech_customer_upsert",
            "microtech_customer_lookup",
            "microtech_order_upsert",
        ),
        "tasks": (
            "products.microtech_sync_products",
            "products.microtech_update_product",
            "products.microtech_update_prices",
            "customer.microtech_customer_upsert",
            "customer.microtech_customer_lookup",
            "orders.microtech_order_upsert",
        ),
        "log_keys": ("microtech", "customer", "orders"),
    },
    {
        "key": "shopware",
        "label": "Shopware",
        "description": "Produkt-Export und Bestellimport",
        "icon": "storefront",
        "commands": (
            "shopware_sync_products",
            "shopware_sync_open_orders",
            "shopware_force_product_image_uploads",
        ),
        "tasks": (
            "products.shopware_sync_products",
            "products.shopware_force_product_image_uploads",
            "orders.shopware_sync_open_orders",
        ),
        "log_keys": ("shopware", "orders"),
    },
    {
        "key": "orders",
        "label": "Bestellungen",
        "description": "Shopware-Bestellungen und Microtech-Vorgaenge",
        "icon": "shopping_cart",
        "commands": ("shopware_sync_open_orders", "microtech_order_upsert"),
        "tasks": (
            "orders.shopware_sync_open_orders",
            "orders.microtech_order_upsert",
        ),
        "log_keys": ("orders",),
    },
    {
        "key": "mappei",
        "label": "Mappei",
        "description": "Preis-Scraping",
        "icon": "travel_explore",
        "commands": ("scrape_mappei",),
        "tasks": ("mappei.scrape_daily_prices",),
        "log_keys": ("mappei",),
    },
    {
        "key": "hr",
        "label": "HR",
        "description": "Ferien, Feiertage und Jahreswechsel",
        "icon": "calendar_month",
        "commands": ("sync_holidays", "year_transition"),
        "tasks": ("hr.sync_holidays", "hr.year_transition"),
        "log_keys": ("hr",),
    },
    {
        "key": "system",
        "label": "System",
        "description": "Django, Celery, Webserver und Fehler",
        "icon": "monitor_heart",
        "commands": (),
        "tasks": (),
        "log_keys": ("core", "django", "celery", "uvicorn", "gunicorn", "errors"),
    },
]

LOG_PURPOSES = {
    "celery": "Celery Worker, Beat und Task-Ausfuehrung.",
    "core": "Admin, Runtime-Status und zentrale Hilfsdienste.",
    "customer": "Kundenimport und Kundenexport mit Microtech.",
    "django": "Django Framework, Requests und Admin-Fehler.",
    "errors": "Zentrale Fehler aller Bereiche.",
    "gunicorn": "Gunicorn Webserver-Prozess.",
    "hr": "HR-Synchronisationen.",
    "mappei": "Mappei Scraping und Preisimporte.",
    "microtech": "Microtech GraphQL/ERP-Kommunikation.",
    "orders": "Bestellimport und Microtech-Vorgaenge.",
    "products": "Produktdaten, Preise und Sync-Orchestrierung.",
    "scheduled_product_sync": "Kompletter Produkt-Sync Lauf.",
    "shopware": "Shopware API, Produkt-Export und Medien-Sync.",
    "uvicorn": "Uvicorn ASGI-Prozess.",
}

TASK_LABELS = {
    "products.scheduled_product_sync": "Produkt-Sync komplett",
    "products.microtech_sync_products": "Microtech Import",
    "products.microtech_update_product": "Microtech Produkt aktualisieren",
    "products.microtech_update_prices": "Microtech Preise aktualisieren",
    "products.shopware_sync_products": "Shopware Export",
    "products.shopware_force_product_image_uploads": "Shopware Bilder neu hochladen",
    "orders.shopware_sync_open_orders": "Offene Bestellungen importieren",
    "orders.microtech_order_upsert": "Bestellung nach Microtech",
    "customer.microtech_customer_upsert": "Kunde nach Microtech",
    "customer.microtech_customer_lookup": "Kunde aus Microtech importieren",
    "mappei.scrape_daily_prices": "Mappei Preise scrapen",
    "hr.sync_holidays": "Ferien & Feiertage synchronisieren",
    "hr.year_transition": "HR Jahreswechsel",
}


def _get_active_processes() -> list[dict]:
    """Scan OS process table for GC-Bridge-related processes."""
    keywords = ["manage.py", "uvicorn", "caddy"]
    base_dir_lower = str(settings.BASE_DIR).lower()
    my_pid = str(os.getpid())
    processes = []

    if platform.system() == "Windows":
        try:
            result = subprocess.run(
                [
                    "wmic", "process", "get",
                    "ProcessId,CommandLine,CreationDate,WorkingSetSize",
                    "/FORMAT:CSV",
                ],
                capture_output=True, text=True, timeout=10,
            )
            for line in result.stdout.strip().splitlines():
                line = line.strip()
                if not line or line.startswith("Node"):
                    continue
                parts = line.split(",")
                if len(parts) < 5:
                    continue
                cmdline = ",".join(parts[1:-3])
                if not any(kw in cmdline.lower() for kw in keywords) and base_dir_lower not in cmdline.lower():
                    continue
                pid = parts[-1].strip()
                mem_bytes = int(parts[-2]) if parts[-2].strip().isdigit() else 0
                processes.append({
                    "pid": int(pid) if pid.isdigit() else 0,
                    "command": cmdline.strip()[:200],
                    "user": "",
                    "mem_mb": round(mem_bytes / 1048576, 1),
                    "started": parts[-3].strip() if len(parts) > 3 else "",
                    "is_self": pid.strip() == my_pid,
                })
        except Exception:
            pass
    else:
        try:
            result = subprocess.run(
                ["ps", "aux", "--no-headers"],
                capture_output=True, text=True, timeout=10,
            )
            for line in result.stdout.splitlines():
                if not any(kw in line for kw in keywords) and base_dir_lower not in line.lower():
                    continue
                if "grep" in line:
                    continue
                parts = line.split(None, 10)
                if len(parts) < 11:
                    continue
                pid = parts[1]
                rss_kb = int(parts[5]) if parts[5].isdigit() else 0
                processes.append({
                    "pid": int(pid) if pid.isdigit() else 0,
                    "command": parts[10][:200],
                    "user": parts[0],
                    "mem_mb": round(rss_kb / 1024, 1),
                    "started": parts[8],
                    "is_self": pid == my_pid,
                })
        except Exception:
            pass

    return sorted(processes, key=lambda p: p.get("pid", 0))


def _get_graphql_health() -> dict:
    """Probe the configured Microtech GraphQL endpoint and return health details."""
    from microtech.services.graphql_client import MicrotechGraphQLConfig

    try:
        cfg = MicrotechGraphQLConfig.from_settings()
        url = cfg.url
    except ValueError:
        return {"url": "", "status": "not_configured", "ok": False, "latency_ms": None, "error": "MICROTECH_GRAPHQL_URL nicht gesetzt"}

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


def _get_microtech_slot_status() -> dict:
    """Check if the external Microtech GraphQL endpoint is reachable."""
    try:
        from microtech.services import MicrotechGraphQLClientService

        health = MicrotechGraphQLClientService().health()
        return {
            "available": health == "ok",
            "queued": 0,
            "running": 0,
        }
    except Exception:
        return {"available": None, "queued": 0, "running": 0}


def _get_systemd_units() -> list[dict] | None:
    """Query systemd for GC-Bridge-related services/timers. Returns None on Windows."""
    if platform.system() == "Windows":
        return None

    unit_patterns = ["gc-bridge", "GC-Bridge"]
    units = []

    try:
        result = subprocess.run(
            [
                "systemctl", "list-units", "--all", "--no-pager",
                "--no-legend", "--plain",
                "--type=service,timer",
            ],
            capture_output=True, text=True, timeout=10,
        )
        for line in result.stdout.splitlines():
            if not any(pat in line for pat in unit_patterns):
                continue
            parts = line.split(None, 4)
            if len(parts) < 4:
                continue
            units.append({
                "name": parts[0],
                "load": parts[1],
                "active": parts[2],
                "sub": parts[3],
                "description": parts[4] if len(parts) > 4 else "",
                "ok": parts[2] == "active",
            })
    except Exception:
        pass

    return units if units else []


def _get_runtime_entries() -> list[dict]:
    entries = CommandRuntimeService().list_runs(include_stale=False, cleanup_stale=True)
    for entry in entries:
        entry["duration"] = str(timedelta(seconds=max(0, int(entry.get("age_seconds") or 0))))
    return entries


def _log_key_for_path(path: Path) -> str:
    parts = path.parts
    if len(parts) >= 3 and parts[-3] in {"daily", "weekly", "monthly"}:
        return parts[-2]
    stem = path.name.split(".", 1)[0]
    return stem.strip() or "log"


def _area_for_log_key(log_key: str) -> str:
    normalized = str(log_key or "").strip().lower()
    for area in SYNC_AREAS:
        if normalized == area["key"]:
            return area["key"]
    for area in SYNC_AREAS:
        if normalized in area["log_keys"]:
            return area["key"]
    return "system"


def _human_size(size_bytes: int) -> str:
    if size_bytes < 1024:
        return f"{size_bytes} B"
    if size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    return f"{size_bytes / (1024 * 1024):.1f} MB"


def _human_age(seconds: int) -> str:
    if seconds < 60:
        return "gerade eben"
    if seconds < 3600:
        return f"vor {seconds // 60} min"
    if seconds < 86400:
        return f"vor {seconds // 3600} h"
    return f"vor {seconds // 86400} d"


def _build_log_entries(file_options: list[Path]) -> list[dict[str, Any]]:
    now = timezone.now()
    timestamp_tz = timezone.get_current_timezone() if timezone.is_aware(now) else None
    entries: list[dict[str, Any]] = []

    for index, path in enumerate(file_options):
        log_key = _log_key_for_path(path)
        area_key = _area_for_log_key(log_key)
        stat = None
        try:
            stat = path.stat() if path.exists() else None
        except OSError:
            stat = None

        modified_at = datetime.fromtimestamp(stat.st_mtime, tz=timestamp_tz) if stat else None
        age_seconds = int((now - modified_at).total_seconds()) if modified_at else None
        if age_seconds is None:
            activity = "fehlt"
            activity_class = "muted"
        elif age_seconds <= 120:
            activity = "aktiv"
            activity_class = "active"
        elif age_seconds <= 86400:
            activity = _human_age(age_seconds)
            activity_class = "recent"
        else:
            activity = _human_age(age_seconds)
            activity_class = "old"

        entries.append(
            {
                "index": index,
                "path": str(path),
                "name": path.name,
                "log_key": log_key,
                "area_key": area_key,
                "area_label": next(
                    (area["label"] for area in SYNC_AREAS if area["key"] == area_key),
                    "System",
                ),
                "purpose": LOG_PURPOSES.get(log_key, "Nicht zugeordnetes Log."),
                "exists": bool(stat),
                "size": _human_size(stat.st_size) if stat else "-",
                "modified_at": modified_at.isoformat() if modified_at else "",
                "modified_label": (
                    modified_at.strftime("%d.%m.%Y %H:%M:%S") if modified_at else "-"
                ),
                "age_seconds": age_seconds,
                "activity": activity,
                "activity_class": activity_class,
            }
        )

    return sorted(
        entries,
        key=lambda item: (
            item["area_label"],
            item["age_seconds"] if item["age_seconds"] is not None else 10**12,
            item["name"],
        ),
    )


def _flatten_celery_tasks(raw_by_worker: dict | None, *, state: str) -> list[dict[str, Any]]:
    flattened: list[dict[str, Any]] = []
    if not raw_by_worker:
        return flattened

    for worker, task_rows in raw_by_worker.items():
        for raw_task in task_rows or []:
            task = raw_task.get("request") if state == "scheduled" and raw_task.get("request") else raw_task
            task_name = str(task.get("name") or "").strip()
            task_id = str(task.get("id") or "").strip()
            eta = str(raw_task.get("eta") or task.get("eta") or "").strip()
            flattened.append(
                {
                    "id": task_id,
                    "name": task_name,
                    "label": TASK_LABELS.get(task_name, task_name or "Unbekannter Task"),
                    "worker": str(worker),
                    "state": state,
                    "eta": eta,
                    "args": task.get("argsrepr") or task.get("args") or "",
                    "kwargs": task.get("kwargsrepr") or task.get("kwargs") or "",
                }
            )
    return flattened


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


def _get_celery_queue_status() -> dict[str, Any]:
    now = time.monotonic()
    cached = _CELERY_QUEUE_CACHE.get("value")
    checked_at = float(_CELERY_QUEUE_CACHE.get("checked_at") or 0.0)
    if cached is not None and now - checked_at < _CELERY_QUEUE_CACHE_SECONDS:
        return dict(cached)

    broker_available, broker_error = _is_celery_broker_reachable()
    if not broker_available:
        status = {
            "available": False,
            "error": broker_error,
            "active": [],
            "waiting": [],
            "scheduled": [],
            "active_count": 0,
            "waiting_count": 0,
            "scheduled_count": 0,
            "workers": 0,
        }
        _CELERY_QUEUE_CACHE.update({"checked_at": now, "value": status})
        return status

    try:
        from celery import current_app

        inspect_timeout = float(getattr(settings, "SYSTEM_STATUS_CELERY_INSPECT_TIMEOUT", 0.4))
        inspect = current_app.control.inspect(timeout=inspect_timeout)
        active = _flatten_celery_tasks(inspect.active(), state="active")
        reserved = _flatten_celery_tasks(inspect.reserved(), state="reserved")
        scheduled = _flatten_celery_tasks(inspect.scheduled(), state="scheduled")
    except Exception as exc:
        status = {
            "available": False,
            "error": str(exc),
            "active": [],
            "waiting": [],
            "scheduled": [],
            "active_count": 0,
            "waiting_count": 0,
            "scheduled_count": 0,
            "workers": 0,
        }
        _CELERY_QUEUE_CACHE.update({"checked_at": now, "value": status})
        return status

    all_workers = {row["worker"] for row in [*active, *reserved, *scheduled] if row.get("worker")}
    status = {
        "available": True,
        "error": "",
        "active": active,
        "waiting": reserved,
        "scheduled": scheduled,
        "active_count": len(active),
        "waiting_count": len(reserved),
        "scheduled_count": len(scheduled),
        "workers": len(all_workers),
    }
    _CELERY_QUEUE_CACHE.update({"checked_at": now, "value": status})
    return status


def _task_count_for_area(tasks: list[dict[str, Any]], area: dict[str, Any]) -> int:
    area_tasks = set(area.get("tasks") or ())
    return sum(1 for task in tasks if task.get("name") in area_tasks)


def _build_dashboard_cards(
    *,
    runtime_entries: list[dict],
    queue_status: dict[str, Any],
    log_entries: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    active_tasks = list(queue_status.get("active") or [])
    waiting_tasks = [*(queue_status.get("waiting") or []), *(queue_status.get("scheduled") or [])]
    cards: list[dict[str, Any]] = []

    for area in SYNC_AREAS:
        area_commands = set(area.get("commands") or ())
        area_logs = set(area.get("log_keys") or ())
        area_runtime = [entry for entry in runtime_entries if entry.get("command_name") in area_commands]
        area_log_entries = [entry for entry in log_entries if entry.get("log_key") in area_logs]
        active_count = len(area_runtime) + _task_count_for_area(active_tasks, area)
        waiting_count = _task_count_for_area(waiting_tasks, area)
        recent_log_count = sum(1 for entry in area_log_entries if entry.get("activity_class") in {"active", "recent"})
        latest_log = min(
            area_log_entries,
            key=lambda item: item["age_seconds"] if item["age_seconds"] is not None else 10**12,
            default=None,
        )
        primary_runtime = area_runtime[0] if area_runtime else None
        stage = str((primary_runtime or {}).get("metadata", {}).get("stage") or "").strip()

        if active_count:
            status = "running"
            status_label = "laeuft"
        elif waiting_count:
            status = "waiting"
            status_label = "wartet"
        elif recent_log_count:
            status = "recent"
            status_label = "kuerzlich aktiv"
        else:
            status = "idle"
            status_label = "ruhig"

        cards.append(
            {
                "key": area["key"],
                "label": area["label"],
                "description": area["description"],
                "icon": area["icon"],
                "status": status,
                "status_label": status_label,
                "running_count": active_count,
                "waiting_count": waiting_count,
                "stage": stage,
                "command": primary_runtime.get("command_name", "") if primary_runtime else "",
                "duration": primary_runtime.get("duration", "") if primary_runtime else "",
                "log_count": len(area_log_entries),
                "latest_log": latest_log,
            }
        )

    return cards


def _get_scheduled_tasks_status() -> list[dict] | None:
    """Query Windows scheduled tasks. Returns None on non-Windows platforms."""
    if platform.system() != "Windows":
        return None

    tasks = []
    for task_name in _WINDOWS_SCHEDULED_TASKS:
        try:
            result = subprocess.run(
                ["schtasks", "/Query", "/TN", task_name, "/FO", "LIST"],
                capture_output=True,
                text=True,
                timeout=10,
                encoding="cp850",
                errors="replace",
            )
            status = "Unbekannt"
            last_run = ""
            next_run = ""
            for line in result.stdout.splitlines():
                if ":" not in line:
                    continue
                key, _, val = line.partition(":")
                key_lower = key.strip().lower()
                val = val.strip()
                if "status" in key_lower:
                    status = val
                elif "letzte" in key_lower or "last run" in key_lower:
                    last_run = val
                elif "nächste" in key_lower or "next run" in key_lower:
                    next_run = val
            tasks.append(
                {
                    "name": task_name,
                    "status": status,
                    "last_run": last_run,
                    "next_run": next_run,
                    "ok": result.returncode == 0,
                }
            )
        except Exception as exc:
            tasks.append(
                {
                    "name": task_name,
                    "status": f"Fehler: {exc}",
                    "last_run": "",
                    "next_run": "",
                    "ok": False,
                }
            )
    return tasks


def _get_runner_services_status() -> list[dict] | None:
    """Query GitHub runner services on Windows. Returns None on non-Windows."""
    if platform.system() != "Windows":
        return None

    services = []
    for service_name in _WINDOWS_RUNNER_SERVICES:
        try:
            result = subprocess.run(
                ["sc", "query", service_name],
                capture_output=True,
                text=True,
                timeout=10,
                encoding="cp850",
                errors="replace",
            )
            state = "Nicht gefunden"
            for line in result.stdout.splitlines():
                if "STATE" in line.upper() and ":" in line:
                    state = line.split(":", 1)[1].strip()
                    break

            services.append(
                {
                    "name": service_name,
                    "state": state,
                    "ok": result.returncode == 0 and "RUNNING" in state.upper(),
                    "exists": result.returncode == 0,
                }
            )
        except Exception as exc:
            services.append(
                {
                    "name": service_name,
                    "state": f"Fehler: {exc}",
                    "ok": False,
                    "exists": False,
                }
            )
    return services


def _spawn_job(command_name: str) -> dict:
    """Spawn a management command as a detached background process."""
    valid_commands = {job["command"] for job in TRIGGERABLE_JOBS}
    if command_name not in valid_commands:
        return {"success": False, "error": "Unbekannter Job-Name"}

    manage_py = Path(settings.BASE_DIR) / "manage.py"
    cmd = [sys.executable, str(manage_py), command_name]

    try:
        kwargs: dict = {
            "stdin": subprocess.DEVNULL,
            "stdout": subprocess.DEVNULL,
            "stderr": subprocess.DEVNULL,
        }
        if platform.system() == "Windows":
            kwargs["creationflags"] = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            kwargs["start_new_session"] = True
            kwargs["close_fds"] = True

        proc = subprocess.Popen(cmd, **kwargs)
        return {"success": True, "pid": proc.pid}
    except Exception as exc:
        return {"success": False, "error": str(exc)}


def _resolve_log_params(request) -> tuple[list[Path], int, int]:
    file_options = get_allowed_log_files()
    try:
        selected_index = int(request.GET.get("file", "0") or "0")
    except (TypeError, ValueError):
        selected_index = 0
    try:
        line_count = int(request.GET.get("lines", "100") or "100")
    except (TypeError, ValueError):
        line_count = 100
    line_count = max(10, min(line_count, 500))
    selected_index = max(0, min(selected_index, len(file_options) - 1 if file_options else 0))
    return file_options, selected_index, line_count


def system_status_view(request):
    file_options, selected_index, line_count = _resolve_log_params(request)
    runtime_entries = _get_runtime_entries()
    queue_status = _get_celery_queue_status()
    log_entries = _build_log_entries(file_options)
    dashboard_cards = _build_dashboard_cards(
        runtime_entries=runtime_entries,
        queue_status=queue_status,
        log_entries=log_entries,
    )

    if file_options:
        selected_path = file_options[selected_index]
        log_lines = tail_log_file(selected_path, line_count)
        file_exists = selected_path.exists()
    else:
        selected_path = None
        log_lines = []
        file_exists = False

    context = {
        **admin.site.each_context(request),
        "title": "System-Status",
        "dashboard_cards": dashboard_cards,
        "runtime_entries": runtime_entries,
        "active_processes": _get_active_processes(),
        "queue_status": queue_status,
        "graphql_health": _get_graphql_health(),
        "microtech_slot": _get_microtech_slot_status(),
        "triggerable_jobs": TRIGGERABLE_JOBS,
        "scheduled_tasks": _get_scheduled_tasks_status(),
        "systemd_units": _get_systemd_units(),
        "runner_services": _get_runner_services_status(),
        "file_options": [{"index": i, "path": str(p), "name": p.name} for i, p in enumerate(file_options)],
        "log_entries": log_entries,
        "selected_file_index": selected_index,
        "selected_path": str(selected_path) if selected_path else "",
        "line_count": line_count,
        "log_lines": log_lines,
        "file_exists": file_exists,
        "is_windows": platform.system() == "Windows",
    }
    return TemplateResponse(request, "admin/system_status.html", context)


def system_status_api(request):
    """JSON endpoint for live polling of jobs + log content."""
    file_options, selected_index, line_count = _resolve_log_params(request)
    runtime_entries = _get_runtime_entries()
    queue_status = _get_celery_queue_status()
    log_entries = _build_log_entries(file_options)

    log_lines: list[str] = []
    file_name = ""
    if file_options:
        selected_path = file_options[selected_index]
        log_lines = tail_log_file(selected_path, line_count)
        file_name = selected_path.name

    return JsonResponse(
        {
            "dashboard_cards": _build_dashboard_cards(
                runtime_entries=runtime_entries,
                queue_status=queue_status,
                log_entries=log_entries,
            ),
            "runtime_entries": runtime_entries,
            "active_processes": _get_active_processes(),
            "queue_status": queue_status,
            "graphql_health": _get_graphql_health(),
            "microtech_slot": _get_microtech_slot_status(),
            "log_lines": log_lines,
            "log_filename": file_name,
            "log_entries": log_entries,
            "scheduled_tasks": _get_scheduled_tasks_status(),
            "systemd_units": _get_systemd_units(),
            "runner_services": _get_runner_services_status(),
        }
    )


def system_status_run(request):
    """POST: trigger a background management command."""
    if request.method != "POST":
        return JsonResponse({"success": False, "error": "POST required"}, status=405)
    try:
        data = json.loads(request.body)
        command_name = str(data.get("command", "")).strip()
    except Exception:
        return JsonResponse({"success": False, "error": "Ungültige Anfrage"}, status=400)

    result = _spawn_job(command_name)
    return JsonResponse(result)
