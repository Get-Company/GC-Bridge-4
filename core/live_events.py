# core/live_events.py
from __future__ import annotations

import json
import time
from typing import Any

import redis
from django.conf import settings
from loguru import logger

LIVE_EVENTS_STREAM_KEY = "live:events"
STREAM_MAXLEN = 10000
PAYLOAD_MAX_BYTES = 32768

_redis_client: redis.Redis | None = None


def _get_redis() -> redis.Redis:
    global _redis_client
    if _redis_client is None:
        _redis_client = redis.Redis.from_url(
            settings.CELERY_BROKER_URL, decode_responses=True
        )
    return _redis_client


def _serialize_payload(payload: dict | None) -> str:
    if payload is None:
        return ""
    try:
        text = json.dumps(payload, default=str, ensure_ascii=False)
    except Exception:
        text = json.dumps({"_error": "payload not serializable"})
    if len(text.encode("utf-8")) > PAYLOAD_MAX_BYTES:
        preview = text[:1000]
        text = json.dumps(
            {"_truncated": True, "_preview": preview}, ensure_ascii=False
        )
    return text


def emit_event(
    task: str,
    entity: str,
    step: str,
    status: str,
    summary: str,
    *,
    run_id: str | None = None,
    target: str | None = None,
    payload: dict | None = None,
) -> None:
    """Best-effort: schreibt ein Live-Event in den Redis Stream. Wirft nie."""
    try:
        fields: dict[str, Any] = {
            "ts": f"{time.time():.3f}",
            "task": str(task or ""),
            "run_id": str(run_id or ""),
            "entity": str(entity or ""),
            "target": str(target or ""),
            "step": str(step or ""),
            "status": str(status or "info"),
            "summary": str(summary or ""),
            "payload": _serialize_payload(payload),
        }
        if status in ("error", "skipped"):
            _persist_incident(
                task=task, run_id=run_id, entity=entity, target=target,
                step=step, status=status, message=summary, payload=payload,
            )
        _get_redis().xadd(
            LIVE_EVENTS_STREAM_KEY,
            fields,
            maxlen=STREAM_MAXLEN,
            approximate=True,
        )
    except Exception:
        logger.opt(exception=False).warning(
            "emit_event fehlgeschlagen (best-effort): task={} entity={}", task, entity
        )


def _persist_incident(*, task, run_id, entity, target, step, status, message, payload) -> None:
    try:
        from core.models import SyncEventLog

        SyncEventLog.objects.create(
            task=str(task or ""),
            run_id=str(run_id or ""),
            entity=str(entity or ""),
            target=str(target or ""),
            step=str(step or ""),
            status=status,
            message=str(message or ""),
            payload=payload,
        )
    except Exception:
        logger.opt(exception=False).warning(
            "SyncEventLog-Persistierung fehlgeschlagen: task={} entity={}", task, entity
        )


def emit_run_started(task: str, run_id: str, summary: str) -> None:
    emit_event(task, entity="", step="run:start", status="info", summary=summary, run_id=run_id)


def emit_run_finished(task: str, run_id: str, summary: str, stats: dict | None = None) -> None:
    emit_event(
        task,
        entity="",
        step="run:finish",
        status="info",
        summary=summary,
        run_id=run_id,
        payload=stats,
    )
