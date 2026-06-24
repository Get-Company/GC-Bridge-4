from __future__ import annotations

import traceback

from loguru import logger

from issues.models import Issue, IssueCategory

_TASK_CATEGORY_NAME = "Automatische Task-Fehler"


def create_task_issue(
    *,
    title: str,
    error_text: str,
    description: str = "",
    priority: str = Issue.Priority.HIGH,
) -> Issue | None:
    try:
        existing = Issue.objects.filter(title=title, status=Issue.Status.OPEN).first()
        if existing is not None:
            separator = "\n\n" if existing.error_text else ""
            existing.error_text = existing.error_text + separator + error_text
            existing.save(update_fields=["error_text", "updated_at"])
            return existing

        category, _ = IssueCategory.objects.get_or_create(
            name=_TASK_CATEGORY_NAME,
            defaults={"color": "#f97316", "is_active": True},
        )
        return Issue.objects.create(
            title=title,
            description=description,
            error_text=error_text,
            status=Issue.Status.OPEN,
            priority=priority,
            category=category,
        )
    except Exception:
        logger.exception("create_task_issue fehlgeschlagen: title={}", title)
        return None
