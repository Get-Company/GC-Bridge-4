from __future__ import annotations

import json
import os
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
    "GC-Bridge Scheduled Product Sync",
]
_WINDOWS_RUNNER_SERVICES = [
    "actions.runner.Get-Company-GC-Bridge-4.GC-Bridge-v4",
]


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


def _get_microtech_slot_status() -> dict:
    """Check if the Microtech COM queue status."""
    try:
        from microtech.models import MicrotechJob
        queued = MicrotechJob.objects.filter(status=MicrotechJob.Status.QUEUED).count()
        running = MicrotechJob.objects.filter(status=MicrotechJob.Status.RUNNING).count()
        return {
            "available": running == 0,
            "queued": queued,
            "running": running,
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
        "active_processes": _get_active_processes(),
        "microtech_slot": _get_microtech_slot_status(),
        "triggerable_jobs": TRIGGERABLE_JOBS,
        "scheduled_tasks": _get_scheduled_tasks_status(),
        "systemd_units": _get_systemd_units(),
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
            "active_processes": _get_active_processes(),
            "microtech_slot": _get_microtech_slot_status(),
            "log_lines": log_lines,
            "log_filename": file_name,
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
