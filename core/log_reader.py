from __future__ import annotations

import os
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from django.conf import settings

from core.logging import cleanup_old_log_files, get_log_directories, get_log_retention_days

_TAIL_MAX_LINES = 5000
_SEARCH_MAX_RESULTS = 300
_SEARCH_MAX_FILE_MB = 50


def get_allowed_log_files() -> list[Path]:
    cleanup_old_log_files()
    configured = [Path(item) for item in getattr(settings, "ADMIN_LOG_READER_FILES", []) if str(item).strip()]
    cutoff = datetime.now() - timedelta(days=get_log_retention_days())
    discovered: list[Path] = []
    for logs_dir in get_log_directories():
        if logs_dir.exists():
            for path in sorted(logs_dir.rglob("*.log*")):
                if not path.is_file():
                    continue
                try:
                    modified_at = datetime.fromtimestamp(path.stat().st_mtime)
                except OSError:
                    continue
                if modified_at < cutoff:
                    continue
                discovered.append(path)

    unique_paths: list[Path] = []
    seen: set[str] = set()
    for path in [*configured, *discovered]:
        if path.exists() and path.is_file():
            try:
                modified_at = datetime.fromtimestamp(path.stat().st_mtime)
            except OSError:
                continue
            if modified_at < cutoff:
                continue
        normalized = str(path).strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        unique_paths.append(Path(normalized))
    return unique_paths


def tail_log_file(path: Path, line_count: int = 100) -> list[str]:
    max_lines = max(1, min(int(line_count), _TAIL_MAX_LINES))
    if not path.exists() or not path.is_file():
        return []

    chunk_size = 65536
    buffer = bytearray()
    lines: list[str] = []

    with path.open("rb") as handle:
        handle.seek(0, os.SEEK_END)
        file_size = handle.tell()
        position = file_size

        while position > 0 and len(lines) <= max_lines:
            read_size = min(chunk_size, position)
            position -= read_size
            handle.seek(position)
            buffer[:0] = handle.read(read_size)
            lines = buffer.decode("utf-8", errors="replace").splitlines()

    return lines[-max_lines:]


def log_file_info(path: Path) -> dict[str, Any]:
    """Return size and rough line count of a log file."""
    if not path.exists() or not path.is_file():
        return {"size_bytes": 0, "size_label": "-", "exists": False}
    try:
        stat = path.stat()
        size = stat.st_size
        size_label = (
            f"{size / (1024 * 1024):.1f} MB" if size >= 1024 * 1024
            else f"{size / 1024:.1f} KB" if size >= 1024
            else f"{size} B"
        )
        return {"size_bytes": size, "size_label": size_label, "exists": True}
    except OSError:
        return {"size_bytes": 0, "size_label": "-", "exists": False}


def search_log_file(
    path: Path,
    query: str,
    context_lines: int = 3,
    use_regex: bool = False,
    max_results: int = _SEARCH_MAX_RESULTS,
) -> dict[str, Any]:
    """Search a log file for query. Returns matches with context lines and line numbers."""
    if not path.exists() or not path.is_file():
        return {"error": "Datei nicht gefunden", "matches": [], "total": 0, "shown": 0, "query": query}

    if not query.strip():
        return {"error": "Kein Suchbegriff angegeben", "matches": [], "total": 0, "shown": 0, "query": query}

    info = log_file_info(path)
    if info["size_bytes"] > _SEARCH_MAX_FILE_MB * 1024 * 1024:
        return {
            "error": f"Datei zu groß für Volltextsuche ({info['size_label']}). Bitte herunterladen und lokal suchen.",
            "matches": [],
            "total": 0,
            "shown": 0,
            "query": query,
        }

    try:
        if use_regex:
            pattern = re.compile(query, re.IGNORECASE)
        else:
            pattern = re.compile(re.escape(query), re.IGNORECASE)
    except re.error as exc:
        return {"error": f"Ungültiger Regex: {exc}", "matches": [], "total": 0, "shown": 0, "query": query}

    try:
        with path.open("r", encoding="utf-8", errors="replace") as f:
            all_lines = [line.rstrip("\n") for line in f]
    except OSError as exc:
        return {"error": str(exc), "matches": [], "total": 0, "shown": 0, "query": query}

    match_indices = [i for i, line in enumerate(all_lines) if pattern.search(line)]
    total = len(match_indices)

    # Collect context blocks, merging overlapping ranges
    context_lines = max(0, min(int(context_lines), 20))
    ranges: list[tuple[int, int]] = []
    for idx in match_indices[:max_results]:
        start = max(0, idx - context_lines)
        end = min(len(all_lines) - 1, idx + context_lines)
        if ranges and start <= ranges[-1][1] + 1:
            ranges[-1] = (ranges[-1][0], max(ranges[-1][1], end))
        else:
            ranges.append((start, end))

    matches = []
    for start, end in ranges:
        block = []
        for i in range(start, end + 1):
            line = all_lines[i]
            is_match = bool(pattern.search(line))
            # Build highlighted version: wrap matched spans in a marker
            if is_match:
                highlighted = pattern.sub(lambda m: f"\x00{m.group()}\x00", line)
            else:
                highlighted = line
            block.append({
                "lineno": i + 1,
                "text": line,
                "highlighted": highlighted,
                "is_match": is_match,
            })
        matches.append(block)

    return {
        "error": None,
        "matches": matches,
        "total": total,
        "shown": min(total, max_results),
        "query": query,
        "file_lines": len(all_lines),
        "file_size": info["size_label"],
        "truncated": total > max_results,
    }
