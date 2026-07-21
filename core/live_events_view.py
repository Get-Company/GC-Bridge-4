from __future__ import annotations

import json

from django.contrib import admin
from django.http import JsonResponse
from django.template.response import TemplateResponse

from core.live_events import LIVE_EVENTS_STREAM_KEY, _get_redis

INITIAL_COUNT = 60
POLL_COUNT = 200


def _row_to_event(stream_id: str, fields: dict) -> dict:
    return {
        "id": stream_id,
        "ts": fields.get("ts", ""),
        "task": fields.get("task", ""),
        "run_id": fields.get("run_id", ""),
        "entity": fields.get("entity", ""),
        "target": fields.get("target", ""),
        "step": fields.get("step", ""),
        "status": fields.get("status", "info"),
        "summary": fields.get("summary", ""),
        "has_payload": bool(fields.get("payload")),
    }


def _read_events(after, task, count=POLL_COUNT):
    client = _get_redis()
    events = []
    next_id = after
    if after:
        result = client.xread({LIVE_EVENTS_STREAM_KEY: after}, count=count)
    else:
        # Erstaufruf: die letzten INITIAL_COUNT Einträge, chronologisch.
        rows = client.xrevrange(LIVE_EVENTS_STREAM_KEY, count=INITIAL_COUNT)
        rows = list(reversed(rows))
        result = [(LIVE_EVENTS_STREAM_KEY, rows)] if rows else []
    for _stream, rows in result or []:
        for stream_id, fields in rows:
            if task and fields.get("task") != task:
                next_id = stream_id
                continue
            events.append(_row_to_event(stream_id, fields))
            next_id = stream_id
    return events, next_id


def live_events_api(request):
    after = request.GET.get("after") or None
    task = request.GET.get("task") or None
    try:
        events, next_id = _read_events(after, task)
    except Exception:
        events, next_id = [], after
    return JsonResponse({"events": events, "next_id": next_id})


def live_events_detail_api(request):
    stream_id = request.GET.get("id") or ""
    payload = None
    try:
        rows = _get_redis().xrange(LIVE_EVENTS_STREAM_KEY, min=stream_id, max=stream_id)
        if rows:
            raw = rows[0][1].get("payload") or ""
            payload = json.loads(raw) if raw else None
    except Exception:
        payload = None
    return JsonResponse({"payload": payload})


def live_events_view(request):
    context = {
        **admin.site.each_context(request),
        "title": "Live-Sync-Messenger",
    }
    return TemplateResponse(request, "admin/live_events.html", context)
