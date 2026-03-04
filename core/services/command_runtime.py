from __future__ import annotations

import json
import os
import socket
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from django.conf import settings

from .base import BaseService


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _to_iso(value: datetime) -> str:
    return value.isoformat(timespec="seconds").replace("+00:00", "Z")


def _from_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    normalized = value.strip().replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(normalized)
    except ValueError:
        return None


def _safe_name(value: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in {"-", "_", "."} else "_" for ch in (value or "").strip())
    return cleaned.strip("_") or "command"


def _is_pid_alive(pid: int | None) -> bool:
    if not pid or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


@dataclass
class CommandRuntimeHandle:
    file_path: Path
    payload: dict[str, Any]
    _closed: bool = field(default=False, init=False)

    def update(self, **metadata: Any) -> None:
        if self._closed:
            return
        clean_updates = {key: value for key, value in metadata.items() if value is not None}
        if clean_updates:
            self.payload.setdefault("metadata", {}).update(clean_updates)
        self.payload["updated_at"] = _to_iso(_now_utc())
        _write_runtime_file(self.file_path, self.payload)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            self.file_path.unlink(missing_ok=True)
        except OSError:
            pass


def _write_runtime_file(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True), encoding="utf-8")
    tmp_path.replace(path)


class CommandRuntimeService(BaseService):
    runtime_subdir = "tmp/runtime"

    def get_runtime_dir(self) -> Path:
        configured = str(getattr(settings, "COMMAND_RUNTIME_DIR", "") or "").strip()
        if configured:
            configured_path = Path(configured)
            if configured_path.is_absolute():
                return configured_path
            return settings.BASE_DIR / configured_path
        return settings.BASE_DIR / self.runtime_subdir

    def start(
        self,
        *,
        command_name: str,
        argv: Iterable[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> CommandRuntimeHandle:
        current_time = _now_utc()
        arguments = list(argv or [])
        pid = os.getpid()
        token = uuid.uuid4().hex
        runtime_dir = self.get_runtime_dir()
        file_name = f"{_safe_name(command_name)}__{pid}__{token}.json"
        file_path = runtime_dir / file_name
        payload = {
            "command_name": command_name,
            "command_line": " ".join(arguments),
            "argv": arguments,
            "hostname": socket.gethostname(),
            "pid": pid,
            "started_at": _to_iso(current_time),
            "updated_at": _to_iso(current_time),
            "metadata": metadata or {},
        }
        _write_runtime_file(file_path, payload)
        return CommandRuntimeHandle(file_path=file_path, payload=payload)

    def list_runs(self, *, include_stale: bool = False, cleanup_stale: bool = False) -> list[dict[str, Any]]:
        runtime_dir = self.get_runtime_dir()
        if not runtime_dir.exists():
            return []

        now = _now_utc()
        results: list[dict[str, Any]] = []
        for path in sorted(runtime_dir.glob("*.json")):
            try:
                raw_data = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue

            pid = raw_data.get("pid")
            try:
                pid = int(pid)
            except (TypeError, ValueError):
                pid = None

            started_at = _from_iso(raw_data.get("started_at"))
            updated_at = _from_iso(raw_data.get("updated_at")) or started_at
            reference_time = updated_at or started_at or now
            age_seconds = max(0, int((now - reference_time).total_seconds()))
            is_running = _is_pid_alive(pid)
            status = "running" if is_running else "stale"

            if status == "stale":
                if cleanup_stale:
                    try:
                        path.unlink(missing_ok=True)
                    except OSError:
                        pass
                if not include_stale:
                    continue

            results.append(
                {
                    "command_name": raw_data.get("command_name", ""),
                    "command_line": raw_data.get("command_line", ""),
                    "hostname": raw_data.get("hostname", ""),
                    "pid": pid,
                    "started_at": raw_data.get("started_at", ""),
                    "updated_at": raw_data.get("updated_at", ""),
                    "age_seconds": age_seconds,
                    "status": status,
                    "metadata": raw_data.get("metadata", {}) or {},
                }
            )

        return sorted(results, key=lambda item: str(item.get("started_at") or ""))
