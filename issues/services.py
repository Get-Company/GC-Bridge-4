from __future__ import annotations

from loguru import logger

from issues.models import Issue, IssueCategory

_TASK_CATEGORY_NAME = "Automatische Task-Fehler"


def create_task_issue(
    *,
    title: str,
    error_text: str,
    description: str = "",
    priority: str = Issue.Priority.HIGH,
    category_name: str = _TASK_CATEGORY_NAME,
) -> Issue | None:
    try:
        existing = Issue.objects.filter(title=title, status=Issue.Status.OPEN).first()
        if existing is not None:
            separator = "\n\n" if existing.error_text else ""
            existing.error_text = existing.error_text + separator + error_text
            existing.save(update_fields=["error_text", "updated_at"])
            return existing

        category, _ = IssueCategory.objects.get_or_create(
            name=category_name,
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


class TaskIssueCollector:
    """Loguru-Sink der ERROR+ Meldungen eines Tasks sammelt und am Ende als ein Issue ablegt."""

    def __init__(self, task_name: str, level: str = "ERROR"):
        self.task_name = task_name
        self.level = level
        self._messages: list[str] = []
        self._sink_id: int | None = None

    def __enter__(self) -> TaskIssueCollector:
        self._sink_id = logger.add(
            self._collect,
            level=self.level,
            format="{time:YYYY-MM-DD HH:mm:ss} [{level}] {message}",
            catch=False,
            colorize=False,
        )
        return self

    def _collect(self, message: object) -> None:
        self._messages.append(str(message).rstrip())

    def __exit__(self, exc_type: object, exc_val: object, exc_tb: object) -> bool:
        if self._sink_id is not None:
            logger.remove(self._sink_id)
        if self._messages:
            create_task_issue(
                title=f"[Task] {self.task_name}",
                error_text="\n".join(self._messages),
                description=f"Automatisch gesammelte Fehler aus Task '{self.task_name}'.",
                category_name=self.task_name,
            )
        return False
