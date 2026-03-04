from __future__ import annotations

import json
import platform
import subprocess
import sys
from datetime import timedelta
from pathlib import Path

from django.conf import settings
from django.contrib import admin
from django.http import JsonResponse
from django.template.response import TemplateResponse

from core.log_reader import get_allowed_log_files, tail_log_file
from core.services import CommandRuntimeService
from microtech.services import MicrotechQueueService

TRIGGERABLE_JOBS = [
    {
        "key": "microtech_worker",
        "label": "Microtech Worker",
        "command": "microtech_worker",
        "icon": "memory",
        "description": "Queue-Worker fuer exklusive Microtech COM-Connection",
    },
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
    "GC-Bridge-Microtech-Worker",
    "GC-Bridge Scheduled Product Sync",
]
_WINDOWS_RUNNER_SERVICES = [
    "actions.runner.Get-Company-GC-Bridge-4.GC-Bridge-v4",
]


def _get_runtime_entries() -> list[dict]:
    entries = CommandRuntimeService().list_runs(include_stale=False, cleanup_stale=True)
    for entry in entries:
        entry["duration"] = str(timedelta(seconds=max(0, int(entry.get("age_seconds") or 0))))
    return entries


def _get_microtech_queue_summary() -> dict:
    try:
        return MicrotechQueueService().summarize()
    except Exception:
        return {"counts": {}, "oldest_queued_at": "", "running_job_id": None, "running_job_type": ""}


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
        "runtime_entries": _get_runtime_entries(),
        "microtech_queue": _get_microtech_queue_summary(),
        "triggerable_jobs": TRIGGERABLE_JOBS,
        "scheduled_tasks": _get_scheduled_tasks_status(),
        "runner_services": _get_runner_services_status(),
        "file_options": [{"index": i, "path": str(p), "name": p.name} for i, p in enumerate(file_options)],
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

    log_lines: list[str] = []
    file_name = ""
    if file_options:
        selected_path = file_options[selected_index]
        log_lines = tail_log_file(selected_path, line_count)
        file_name = selected_path.name

    return JsonResponse(
        {
            "runtime_entries": _get_runtime_entries(),
            "microtech_queue": _get_microtech_queue_summary(),
            "log_lines": log_lines,
            "log_filename": file_name,
            "scheduled_tasks": _get_scheduled_tasks_status(),
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
