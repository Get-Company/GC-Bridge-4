# Live-Sync-Messenger Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ein produktgenauer Live-Viewer in der Admin-Oberfläche, der während eines Syncs Schritt-für-Schritt anzeigt, was gerade passiert (Item gespeichert → nach Microtech → nach Shopware → Fehler/OK → Task-Summary), gespeist aus einem Redis Stream, mit persistenter Ablage nur für Fehler/Übersprungen.

**Architecture:** Ein zentraler, best-effort Emitter (`core/live_events.py`) schreibt Events via `XADD` in den Redis Stream `live:events` (MAXLEN ~10000). `error`/`skipped`-Events landen zusätzlich im DB-Modell `SyncEventLog`. Eine staff-only Polling-API liest den Stream ab der letzten ID; ein JS-Frontend pollt sie im Sekundentakt und ersetzt die Celery-Tasks-Ansicht auf der System-Status-Seite. Sync-Tasks werden mit `emit_event`-Aufrufen instrumentiert.

**Tech Stack:** Django (WSGI/Gunicorn), Celery, Redis (`redis>=6.0`, bereits als Broker vorhanden), Django Admin (Unfold), Vanilla-JS-Frontend. Tests: Django `TestCase`/`SimpleTestCase`, ausgeführt mit `python manage.py test`.

## Global Constraints

- Redis-Verbindung immer aus `settings.CELERY_BROKER_URL` via `redis.Redis.from_url(..., decode_responses=True)` — kein neuer Broker, kein RabbitMQ.
- `emit_event` ist **best-effort**: jeder Fehler (Redis down, Serialisierung) wird geloggt, aber **nie** re-raised — ein Sync-Task darf dadurch niemals abbrechen.
- Redis-Stream-Key: `live:events`. Feldwerte sind Strings; `payload` ist ein JSON-String.
- Payload wird vor dem Schreiben auf max. 32768 Bytes gekürzt (JSON-serialisiert).
- Nur `status ∈ {"error","skipped"}` werden in `SyncEventLog` persistiert. `status`-Vokabular gesamt: `"info" | "ok" | "error" | "skipped"`.
- Alle Admin-Endpunkte werden via `admin.site.admin_view(...)` in `core/admin.py` (`_admin_get_urls`) registriert und rendern mit `admin.site.each_context(request)`.
- Neues DB-Modell kommt als eigenes Modul ins Package `core/models/` und wird in `core/models/__init__.py` exportiert (es gibt keine `core/models.py`).
- Loguru-Logger (`from loguru import logger`) wie im übrigen Projekt.

---

### Task 1: Emitter-Grundgerüst (Redis Stream)

**Files:**
- Create: `core/live_events.py`
- Test: `core/test_live_events.py`

**Interfaces:**
- Produces:
  - `emit_event(task: str, entity: str, step: str, status: str, summary: str, *, run_id: str | None = None, target: str | None = None, payload: dict | None = None) -> None`
  - `emit_run_started(task: str, run_id: str, summary: str) -> None`
  - `emit_run_finished(task: str, run_id: str, summary: str, stats: dict | None = None) -> None`
  - `LIVE_EVENTS_STREAM_KEY = "live:events"`
  - `STREAM_MAXLEN = 10000`
  - `PAYLOAD_MAX_BYTES = 32768`
  - `_get_redis()` (mockbar in Tests)
  - `_serialize_payload(payload: dict | None) -> str`

- [ ] **Step 1: Write the failing test**

```python
# core/test_live_events.py
from unittest import mock

from django.test import SimpleTestCase

from core import live_events


class SerializePayloadTests(SimpleTestCase):
    def test_none_payload_serializes_to_empty_string(self):
        self.assertEqual(live_events._serialize_payload(None), "")

    def test_dict_payload_serializes_to_json(self):
        result = live_events._serialize_payload({"price": 12})
        self.assertIn('"price": 12', result)

    def test_oversized_payload_is_truncated(self):
        big = {"blob": "x" * 40000}
        result = live_events._serialize_payload(big)
        self.assertLessEqual(len(result.encode("utf-8")), live_events.PAYLOAD_MAX_BYTES)
        self.assertIn("_truncated", result)


class EmitEventTests(SimpleTestCase):
    def test_emit_event_writes_to_stream(self):
        fake_redis = mock.MagicMock()
        with mock.patch.object(live_events, "_get_redis", return_value=fake_redis):
            live_events.emit_event(
                task="products.auto_sync",
                entity="4711",
                step="→ shopware6",
                status="ok",
                summary="Produkt 4711 nach Shopware6 geschrieben",
                run_id="run-1",
                target="shopware6",
            )
        fake_redis.xadd.assert_called_once()
        args, kwargs = fake_redis.xadd.call_args
        self.assertEqual(args[0], live_events.LIVE_EVENTS_STREAM_KEY)
        fields = args[1]
        self.assertEqual(fields["task"], "products.auto_sync")
        self.assertEqual(fields["entity"], "4711")
        self.assertEqual(fields["status"], "ok")
        self.assertEqual(kwargs["maxlen"], live_events.STREAM_MAXLEN)
        self.assertTrue(kwargs["approximate"])

    def test_emit_event_never_raises_on_redis_error(self):
        fake_redis = mock.MagicMock()
        fake_redis.xadd.side_effect = RuntimeError("redis down")
        with mock.patch.object(live_events, "_get_redis", return_value=fake_redis):
            # Must not raise
            live_events.emit_event(
                task="t", entity="e", step="s", status="info", summary="x"
            )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python manage.py test core.test_live_events -v 2`
Expected: FAIL (`ModuleNotFoundError` / `AttributeError: module 'core.live_events' has no attribute ...`)

- [ ] **Step 3: Write minimal implementation**

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python manage.py test core.test_live_events -v 2`
Expected: PASS (5 Tests)

- [ ] **Step 5: Commit**

```bash
git add core/live_events.py core/test_live_events.py
git commit -m "Add best-effort live event emitter over Redis stream"
```

---

### Task 2: SyncEventLog-Modell + Persistierung von Fehlern

**Files:**
- Create: `core/models/sync_event_log.py`
- Modify: `core/models/__init__.py`
- Modify: `core/live_events.py` (DB-Persistierung in `emit_event` bei error/skipped)
- Create: Migration via `makemigrations core`
- Test: `core/test_sync_event_log.py`

**Interfaces:**
- Consumes: `emit_event(...)` aus Task 1.
- Produces: `core.models.SyncEventLog` mit Feldern `created_at, task, run_id, entity, target, step, status, message, payload`.

- [ ] **Step 1: Write the failing test**

```python
# core/test_sync_event_log.py
from unittest import mock

from django.test import TestCase

from core import live_events
from core.models import SyncEventLog


class SyncEventLogPersistenceTests(TestCase):
    def _emit(self, status):
        fake_redis = mock.MagicMock()
        with mock.patch.object(live_events, "_get_redis", return_value=fake_redis):
            live_events.emit_event(
                task="products.auto_sync",
                entity="4711",
                step="→ shopware6",
                status=status,
                summary="Preis konnte nicht gesetzt werden",
                run_id="run-1",
                target="shopware6",
                payload={"price": "abc"},
            )

    def test_error_event_is_persisted(self):
        self._emit("error")
        row = SyncEventLog.objects.get()
        self.assertEqual(row.task, "products.auto_sync")
        self.assertEqual(row.entity, "4711")
        self.assertEqual(row.status, "error")
        self.assertEqual(row.target, "shopware6")
        self.assertEqual(row.payload, {"price": "abc"})

    def test_skipped_event_is_persisted(self):
        self._emit("skipped")
        self.assertEqual(SyncEventLog.objects.filter(status="skipped").count(), 1)

    def test_ok_event_is_not_persisted(self):
        self._emit("ok")
        self.assertEqual(SyncEventLog.objects.count(), 0)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python manage.py test core.test_sync_event_log -v 2`
Expected: FAIL (`ImportError: cannot import name 'SyncEventLog'`)

- [ ] **Step 3a: Create the model**

```python
# core/models/sync_event_log.py
from __future__ import annotations

from django.db import models
from django.utils.translation import gettext_lazy as _


class SyncEventLog(models.Model):
    """Persistenter Audit-Trail nur für fehlgeschlagene/übersprungene Sync-Items."""

    class Status(models.TextChoices):
        ERROR = "error", _("Fehler")
        SKIPPED = "skipped", _("Übersprungen")

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    task = models.CharField(max_length=120, db_index=True, verbose_name=_("Task"))
    run_id = models.CharField(max_length=64, blank=True, default="", db_index=True)
    entity = models.CharField(max_length=120, blank=True, default="")
    target = models.CharField(max_length=40, blank=True, default="")
    step = models.CharField(max_length=120, blank=True, default="")
    status = models.CharField(max_length=16, choices=Status.choices)
    message = models.TextField(blank=True, default="")
    payload = models.JSONField(null=True, blank=True)

    class Meta:
        verbose_name = _("Sync-Ereignis")
        verbose_name_plural = _("Sync-Ereignisse")
        ordering = ("-created_at",)

    def __str__(self) -> str:
        return f"[{self.status}] {self.task} {self.entity}".strip()
```

- [ ] **Step 3b: Export the model**

Modify `core/models/__init__.py`:

```python
from .base import BaseModel
from .database_backup import DatabaseBackup
from .sync_event_log import SyncEventLog

__all__ = ["BaseModel", "DatabaseBackup", "SyncEventLog"]
```

- [ ] **Step 3c: Add DB persistence to emit_event**

In `core/live_events.py`, direkt vor dem `_get_redis().xadd(...)`-Block (noch innerhalb des `try`, aber DB-Schreiben in eigenem try/except, damit ein DB-Fehler das Stream-Schreiben nicht verhindert), einfügen:

```python
        if status in ("error", "skipped"):
            _persist_incident(
                task=task, run_id=run_id, entity=entity, target=target,
                step=step, status=status, message=summary, payload=payload,
            )
```

Und neue Hilfsfunktion am Dateiende ergänzen:

```python
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
```

- [ ] **Step 4a: Create migration**

Run: `python manage.py makemigrations core`
Expected: neue Migration `core/migrations/00NN_synceventlog.py`

- [ ] **Step 4b: Run tests**

Run: `python manage.py test core.test_sync_event_log core.test_live_events -v 2`
Expected: PASS (8 Tests)

- [ ] **Step 5: Commit**

```bash
git add core/models/sync_event_log.py core/models/__init__.py core/live_events.py core/migrations/
git commit -m "Persist failed and skipped sync items to SyncEventLog"
```

---

### Task 3: Polling-API + Detail-API

**Files:**
- Create: `core/live_events_view.py`
- Modify: `core/admin.py` (URL-Registrierung in `_admin_get_urls`, ~Zeile 403-424)
- Test: `core/test_live_events_view.py`

**Interfaces:**
- Consumes: `LIVE_EVENTS_STREAM_KEY`, `_get_redis` aus Task 1.
- Produces:
  - View `live_events_api(request)` → JSON `{"events": [...], "next_id": "<id>"}`; Query-Params `after` (Stream-ID, optional), `task` (optional Filter).
  - View `live_events_detail_api(request)` → JSON `{"payload": {...}}`; Query-Param `id` (Stream-ID).
  - View `live_events_view(request)` → rendert Template (Task 4).
  - URL-Namen: `core_live_events` (Seite), `core_live_events_api`, `core_live_events_detail`.
  - `_read_events(after: str | None, task: str | None, count: int = 200) -> tuple[list[dict], str | None]`

- [ ] **Step 1: Write the failing test**

```python
# core/test_live_events_view.py
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse


class LiveEventsApiTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.staff = User.objects.create_user(
            username="staff", password="pw", is_staff=True, is_superuser=True
        )
        self.plain = User.objects.create_user(username="plain", password="pw")

    def test_api_requires_staff(self):
        self.client.login(username="plain", password="pw")
        resp = self.client.get(reverse("admin:core_live_events_api"))
        self.assertIn(resp.status_code, (302, 403))

    def test_api_returns_events_after_id(self):
        self.client.login(username="staff", password="pw")
        # xread liefert [(stream_key, [(id, {field: value}), ...])]
        fake_redis = mock.MagicMock()
        fake_redis.xread.return_value = [
            ("live:events", [("5-0", {
                "ts": "1.0", "task": "products.auto_sync", "run_id": "r1",
                "entity": "4711", "target": "shopware6", "step": "→ shopware6",
                "status": "ok", "summary": "OK", "payload": "",
            })])
        ]
        with mock.patch("core.live_events_view._get_redis", return_value=fake_redis):
            resp = self.client.get(reverse("admin:core_live_events_api"), {"after": "4-0"})
        data = resp.json()
        self.assertEqual(data["next_id"], "5-0")
        self.assertEqual(len(data["events"]), 1)
        self.assertEqual(data["events"][0]["entity"], "4711")
        self.assertNotIn("payload", data["events"][0])  # payload nur im Detail-Endpunkt

    def test_api_filters_by_task(self):
        self.client.login(username="staff", password="pw")
        fake_redis = mock.MagicMock()
        fake_redis.xread.return_value = [
            ("live:events", [
                ("6-0", {"task": "orders.upsert", "entity": "A", "status": "ok",
                         "step": "s", "summary": "x", "run_id": "", "target": "", "ts": "1"}),
                ("7-0", {"task": "products.auto_sync", "entity": "B", "status": "ok",
                         "step": "s", "summary": "y", "run_id": "", "target": "", "ts": "1"}),
            ])
        ]
        with mock.patch("core.live_events_view._get_redis", return_value=fake_redis):
            resp = self.client.get(
                reverse("admin:core_live_events_api"),
                {"after": "0", "task": "products.auto_sync"},
            )
        data = resp.json()
        self.assertEqual([e["entity"] for e in data["events"]], ["B"])
        self.assertEqual(data["next_id"], "7-0")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python manage.py test core.test_live_events_view -v 2`
Expected: FAIL (`NoReverseMatch: 'core_live_events_api'`)

- [ ] **Step 3a: Create the views**

```python
# core/live_events_view.py
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
```

- [ ] **Step 3b: Register URLs in core/admin.py**

Import bei den anderen View-Imports (~Zeile 53) ergänzen:

```python
from core.live_events_view import live_events_api, live_events_detail_api, live_events_view
```

In `_admin_get_urls()` in die `custom_urls`-Liste (nach der `system/api/`-Zeile) einfügen:

```python
        path("live-events/", admin.site.admin_view(live_events_view), name="core_live_events"),
        path("live-events/api/", admin.site.admin_view(live_events_api), name="core_live_events_api"),
        path("live-events/detail/", admin.site.admin_view(live_events_detail_api), name="core_live_events_detail"),
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python manage.py test core.test_live_events_view -v 2`
Expected: PASS (3 Tests). Hinweis: der `live_events_view`-Template-Test kommt in Task 4; hier wird nur die API getestet.

- [ ] **Step 5: Commit**

```bash
git add core/live_events_view.py core/admin.py
git commit -m "Add staff-only polling and detail API for live events"
```

---

### Task 4: Frontend-Template + System-Status-Integration

**Files:**
- Create: `core/templates/admin/live_events.html`
- Create: `core/templates/admin/_live_events_panel.html` (wiederverwendbares Panel)
- Modify: `core/templates/admin/system_status.html` (Celery-Ansicht durch Live-Panel ersetzen)
- Modify: `core/admin.py` (`celery-tasks/`-Route entfernen — Zeile 405)
- Test: `core/test_live_events_view.py` (Seiten-Render-Test ergänzen)

**Interfaces:**
- Consumes: URL-Namen `core_live_events_api`, `core_live_events_detail` aus Task 3.

- [ ] **Step 1: Write the failing test (Seiten-Render)**

In `core/test_live_events_view.py` ergänzen:

```python
    def test_live_events_page_renders(self):
        self.client.login(username="staff", password="pw")
        resp = self.client.get(reverse("admin:core_live_events"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "live-events-log")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python manage.py test core.test_live_events_view.LiveEventsApiTests.test_live_events_page_renders -v 2`
Expected: FAIL (`TemplateDoesNotExist: admin/live_events.html`)

- [ ] **Step 3a: Create the reusable panel**

```html
{# core/templates/admin/_live_events_panel.html #}
{# Erwartet keine Kontextvariablen; zieht Daten per JS aus den API-URLs. #}
<div class="live-events" data-api="{% url 'admin:core_live_events_api' %}"
     data-detail="{% url 'admin:core_live_events_detail' %}">
  <div class="live-events-toolbar" style="display:flex;gap:.5rem;align-items:center;margin-bottom:.5rem;">
    <label>Task:
      <select class="live-events-task">
        <option value="">Alle</option>
      </select>
    </label>
    <button type="button" class="live-events-pause">Pause</button>
    <span class="live-events-status" style="margin-left:auto;color:#888;"></span>
  </div>
  <div class="live-events-log" id="live-events-log"
       style="max-height:60vh;overflow:auto;font-family:monospace;font-size:12px;border:1px solid #ccc;padding:.5rem;background:#111;color:#eee;"></div>
</div>
<style>
  .live-events-log .ev { padding:2px 4px; border-bottom:1px solid #222; cursor:pointer; }
  .live-events-log .ev-ok { color:#7ee787; }
  .live-events-log .ev-error { color:#ff7b72; }
  .live-events-log .ev-skipped { color:#e3b341; }
  .live-events-log .ev-info { color:#a0a0a0; }
  .live-events-log .ev-run { font-weight:bold; color:#79c0ff; }
  .live-events-log pre.ev-payload { white-space:pre-wrap; color:#ddd; background:#000; margin:.25rem 0; padding:.25rem; }
</style>
<script>
(function () {
  const root = document.currentScript.closest('.live-events') || document.querySelector('.live-events');
  const logEl = root.querySelector('.live-events-log');
  const taskSel = root.querySelector('.live-events-task');
  const pauseBtn = root.querySelector('.live-events-pause');
  const statusEl = root.querySelector('.live-events-status');
  const apiUrl = root.dataset.api;
  const detailUrl = root.dataset.detail;
  let afterId = null;
  let paused = false;
  const seenTasks = new Set();

  pauseBtn.addEventListener('click', () => {
    paused = !paused;
    pauseBtn.textContent = paused ? 'Weiter' : 'Pause';
  });

  function addTaskOption(task) {
    if (!task || seenTasks.has(task)) return;
    seenTasks.add(task);
    const opt = document.createElement('option');
    opt.value = task; opt.textContent = task;
    taskSel.appendChild(opt);
  }

  function render(ev) {
    const div = document.createElement('div');
    const isRun = ev.step === 'run:start' || ev.step === 'run:finish';
    div.className = 'ev ev-' + ev.status + (isRun ? ' ev-run' : '');
    const time = new Date(parseFloat(ev.ts) * 1000).toLocaleTimeString();
    const parts = [time];
    if (ev.entity) parts.push(ev.entity);
    if (ev.target) parts.push('→' + ev.target);
    parts.push(ev.summary || ev.step);
    div.textContent = parts.join('  ');
    if (ev.has_payload) {
      div.addEventListener('click', () => togglePayload(div, ev.id));
      div.title = 'Klicken für Payload';
    }
    logEl.appendChild(div);
  }

  async function togglePayload(div, id) {
    const existing = div.nextElementSibling;
    if (existing && existing.classList.contains('ev-payload')) { existing.remove(); return; }
    const resp = await fetch(detailUrl + '?id=' + encodeURIComponent(id));
    const data = await resp.json();
    const pre = document.createElement('pre');
    pre.className = 'ev-payload';
    pre.textContent = JSON.stringify(data.payload, null, 2);
    div.after(pre);
  }

  async function poll() {
    if (paused) return;
    const params = new URLSearchParams();
    if (afterId) params.set('after', afterId);
    if (taskSel.value) params.set('task', taskSel.value);
    try {
      const resp = await fetch(apiUrl + '?' + params.toString());
      const data = await resp.json();
      const atBottom = logEl.scrollTop + logEl.clientHeight >= logEl.scrollHeight - 20;
      (data.events || []).forEach((ev) => { addTaskOption(ev.task); render(ev); });
      if (data.next_id) afterId = data.next_id;
      if (atBottom) logEl.scrollTop = logEl.scrollHeight;
      statusEl.textContent = 'verbunden';
    } catch (e) {
      statusEl.textContent = 'Verbindungsfehler';
    }
  }

  taskSel.addEventListener('change', () => { logEl.innerHTML = ''; afterId = null; });
  setInterval(poll, 1000);
  poll();
})();
</script>
```

- [ ] **Step 3b: Create the standalone page**

```html
{# core/templates/admin/live_events.html #}
{% extends "admin/base_site.html" %}
{% block content %}
<h1>Live-Sync-Messenger</h1>
{% include "admin/_live_events_panel.html" %}
{% endblock %}
```

- [ ] **Step 3c: Integrate into system_status.html**

Öffne `core/templates/admin/system_status.html`, finde den Block, der die Celery-Tasks/Worker-Detailliste rendert, und ersetze dessen Inhalt durch:

```html
<section class="live-events-section">
  <h2>Live-Sync-Messenger</h2>
  {% include "admin/_live_events_panel.html" %}
</section>
```

(Die Worker-Health-Statusanzeige oben auf der Seite bleibt erhalten; nur die detaillierte Celery-Tasks-Auflistung wird ersetzt.)

- [ ] **Step 3d: Remove the celery-tasks route**

In `core/admin.py` die Zeile entfernen:

```python
        path("celery-tasks/", admin.site.admin_view(celery_tasks_admin_view), name="core_celery_tasks"),
```

und den zugehörigen Import (`from core.celery_admin import celery_tasks_admin_view`, Zeile 49) entfernen. Falls andere Templates auf `admin:core_celery_tasks` verlinken, diese Links auf `admin:core_live_events` umstellen (mit `grep -rn "core_celery_tasks" core/templates` prüfen).

- [ ] **Step 4: Run tests + manual check**

Run: `python manage.py test core.test_live_events_view -v 2`
Expected: PASS (4 Tests).
Run: `python manage.py check`
Expected: `System check identified no issues`.

- [ ] **Step 5: Commit**

```bash
git add core/templates/admin/live_events.html core/templates/admin/_live_events_panel.html core/templates/admin/system_status.html core/admin.py
git commit -m "Add live events viewer UI and replace celery tasks view"
```

---

### Task 5: Instrumentierung Produkt-Auto-Sync (Django → Ziele)

**Files:**
- Modify: `products/services/product_auto_sync.py` (`process_job`, Zeile 64ff.)
- Test: `products/test_product_auto_sync_events.py`

**Interfaces:**
- Consumes: `emit_event` aus Task 1.

Dies ist der vom Nutzer beschriebene Kern-Flow: pro Produkt wird zu Shopware6, Varianten, Shopware5 und Microtech dispatcht. Jeder Zielaufruf wird gerahmt: ein `info`-Event ("→ target") vor dem Aufruf, ein `ok`-Event bei Erfolg, ein `error`/`skipped`-Event im `except`.

- [ ] **Step 1: Write the failing test**

```python
# products/test_product_auto_sync_events.py
from unittest import mock

from django.test import TestCase

from products.models import Product, ProductSyncJob


class ProductAutoSyncEmitTests(TestCase):
    def test_process_job_emits_target_events(self):
        product = Product.objects.create(erp_nr="4711", name="Test")
        job = ProductSyncJob.objects.create(
            product=product, target=ProductSyncJob.Target.SHOPWARE6,
            status=ProductSyncJob.Status.PENDING, changed_fields="name",
        )
        from products.services.product_auto_sync import ProductAutoSyncService

        with mock.patch("products.services.product_auto_sync.emit_event") as emit, \
             mock.patch("products.services.product_auto_sync.call_command"):
            ProductAutoSyncService().process_job(job_id=job.id)

        steps = [c.kwargs.get("step") or c.args[2] for c in emit.call_args_list]
        entities = {c.kwargs.get("entity") or c.args[1] for c in emit.call_args_list}
        self.assertIn("4711", entities)
        self.assertTrue(any("shopware6" in str(s) for s in steps))
```

(Vor dem Schreiben die genauen Feldnamen von `ProductSyncJob` — `Target`, `Status`, `Target.SHOPWARE6` — mit `grep -n "class Target\|class Status\|SHOPWARE6\|SHOPWARE5\|MICROTECH" products/models.py` verifizieren und den Test ggf. an die realen Choices anpassen.)

- [ ] **Step 2: Run test to verify it fails**

Run: `python manage.py test products.test_product_auto_sync_events -v 2`
Expected: FAIL (`AttributeError: module ... has no attribute 'emit_event'` oder AssertionError)

- [ ] **Step 3: Instrument process_job**

Import am Dateikopf von `products/services/product_auto_sync.py` ergänzen:

```python
from core.live_events import emit_event
```

In `process_job` den Task-Namen und `run_id` bestimmen (`task = "products.auto_sync"`, `run_id = str(job_id)`, `entity = product_erp_nr`). Jeden Ziel-Dispatch umschließen. Beispiel für den Shopware6-Aufruf (der bestehende `call_command("shopware_sync_products", ...)`-Block, ~Zeile 88):

```python
            emit_event(task, entity=product_erp_nr, step="→ shopware6", status="info",
                       summary=f"Produkt {product_erp_nr} → Shopware6", run_id=run_id, target="shopware6")
            try:
                call_command("shopware_sync_products", product_erp_nr, skip_images=True)
                emit_event(task, entity=product_erp_nr, step="→ shopware6", status="ok",
                           summary=f"Produkt {product_erp_nr} nach Shopware6 geschrieben",
                           run_id=run_id, target="shopware6")
            except Exception as exc:
                emit_event(task, entity=product_erp_nr, step="→ shopware6", status="error",
                           summary=f"Shopware6-Fehler: {exc}", run_id=run_id, target="shopware6",
                           payload={"error": str(exc)})
                raise
```

Analog für den Shopware5-Aufruf (`call_command("shopware5_sync_products", ...)`, target `"shopware5"`) und den Microtech-Sentinel-Dispatch (`_submit_microtech_sentinel_jobs`, target `"microtech"`). Bestehende Kontrollflüsse (raise/return) nicht verändern — nur die Emits ergänzen.

- [ ] **Step 4: Run test to verify it passes**

Run: `python manage.py test products.test_product_auto_sync_events -v 2`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add products/services/product_auto_sync.py products/test_product_auto_sync_events.py
git commit -m "Emit live events for product auto-sync targets"
```

---

### Task 6: Instrumentierung übrige Sync-Tasks

**Files:**
- Modify: `microtech/management/commands/microtech_sync_products.py` (`_sync_current_record`, `_save_microtech_price`)
- Modify: `products/tasks.py` (`scheduled_product_sync` — Run-Rahmung; die Schleife bei Zeile 273-295)
- Modify: `orders/tasks.py` (`microtech_order_upsert`, `shopware_sync_open_orders`)
- Modify: `customer/tasks.py` (`microtech_customer_upsert`)
- Modify: `shopware/tasks.py` (`shopware5_sync_products`)
- Modify: `newsletter/tasks.py` (`shopware_sync_recipients`)
- Test: `products/test_scheduled_sync_events.py`

**Interfaces:**
- Consumes: `emit_event`, `emit_run_started`, `emit_run_finished` aus Task 1.

- [ ] **Step 1: Write the failing test (Produkt-Import-Schleife)**

```python
# products/test_scheduled_sync_events.py
from unittest import mock

from django.test import SimpleTestCase


class ScheduledSyncEmitTests(SimpleTestCase):
    def test_record_error_emits_skipped_event(self):
        # Der except-Zweig in der scheduled_product_sync-Schleife soll ein
        # skipped-Event emittieren statt nur zu loggen.
        import products.tasks as tasks
        self.assertTrue(hasattr(tasks, "emit_event"))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python manage.py test products.test_scheduled_sync_events -v 2`
Expected: FAIL (`AssertionError` — `emit_event` noch nicht importiert)

- [ ] **Step 3a: Instrument products/tasks.py scheduled_product_sync**

Import ergänzen: `from core.live_events import emit_event, emit_run_finished, emit_run_started`.

In `scheduled_product_sync` (bzw. dem Continuation-Handler) `run_id` = Celery-`task_id` (via `self.request.id` falls `bind=True`, sonst `str(job.external_job_id)`). Vor der Schleife `emit_run_started("products.scheduled_product_sync", run_id, "Microtech-Import gestartet")`. Im `except`-Zweig (Zeile 292) ergänzen:

```python
            except Exception as exc:
                logger.warning("scheduled_product_sync: record error - {}", exc)
                state["errors"] += 1
                emit_event(
                    "products.scheduled_product_sync",
                    entity=str(product_data.get("artNr") or product_data.get("erpNr") or ""),
                    step="microtech→django", status="skipped",
                    summary=f"Übersprungen: {exc}", run_id=run_id,
                    payload={"error": str(exc)},
                )
```

(Feldname für die ERP-Nr in `product_data` mit `grep -n "artNr\|erpNr\|get_erp_nr" microtech/services/*.py` verifizieren.)

Bei Erfolg (`state["success"] += 1`, Zeile 291) ein `ok`-Event ergänzen. Am Ende (nach der Schleife, vor `logger.info` Zeile 297) `emit_run_finished(...)` mit `stats=state` und Summary `f"{state['processed']} verarbeitet, {state['success']} ok, {state['errors']} übersprungen"`.

- [ ] **Step 3b: Instrument microtech_sync_products _save_microtech_price**

Der `numeric field overflow` bei zu großen Preisen (ursprünglicher Anlass) entsteht hier. In `_save_microtech_price` bzw. dem umschließenden Preis-Block (Zeile 452-496) den `save()`-Aufruf mit try/except umschließen und bei Fehler ein `error`-Event emittieren:

```python
                except Exception as exc:
                    emit_event("products.microtech_import", entity=product.erp_nr,
                               step="preis→django", status="error",
                               summary=f"Preis konnte nicht gespeichert werden: {exc}",
                               target="django", payload={"price": str(price_value)})
                    raise
```

(Import `from core.live_events import emit_event` am Kopf ergänzen.)

- [ ] **Step 3c: Instrument orders/tasks.py und customer/tasks.py**

In `orders/tasks.py` (`microtech_order_upsert`, `shopware_sync_open_orders`) und `customer/tasks.py` (`microtech_customer_upsert`): `emit_event` importieren und je Item ein `ok`- bzw. im `except` ein `error`-Event emittieren, Task-Namen entsprechend (`"orders.microtech_order_upsert"`, `"orders.shopware_sync_open_orders"`, `"customer.microtech_customer_upsert"`), `entity` = Order-/Customer-Nummer, `run_id` = Celery-task_id. Die konkreten Schleifen-/Fehlerstellen vorher mit `grep -n "def \|for \|except\|logger" orders/tasks.py customer/tasks.py` lokalisieren.

- [ ] **Step 3d: Instrument shopware/tasks.py und newsletter/tasks.py**

Nach demselben Muster (Import `from core.live_events import emit_event, emit_run_started, emit_run_finished`):
- `shopware/tasks.py` → `shopware5_sync_products` (`task="shopware.shopware5_sync_products"`, `entity` = ERP-Nr des Produkts, `target="shopware5"`): Run-Rahmung + pro-Produkt `ok`/`error`.
- `newsletter/tasks.py` → `shopware_sync_recipients` (`task="newsletter.shopware_sync_recipients"`, `entity` = Empfänger-/E-Mail-Kennung, `target="shopware6"`): Run-Rahmung + pro-Empfänger `ok`/`error`.

Falls diese Tasks keine explizite Item-Schleife haben (nur ein aggregierter Aufruf), genügt die Run-Rahmung (`emit_run_started`/`emit_run_finished` mit Summary) ohne pro-Item-Events. Vorher mit `grep -n "def \|for \|except" shopware/tasks.py newsletter/tasks.py` prüfen.

- [ ] **Step 4: Run tests + check**

Run: `python manage.py test products.test_scheduled_sync_events -v 2`
Expected: PASS.
Run: `python manage.py check`
Expected: keine Fehler.

- [ ] **Step 5: Commit**

```bash
git add microtech/management/commands/microtech_sync_products.py products/tasks.py orders/tasks.py customer/tasks.py shopware/tasks.py newsletter/tasks.py products/test_scheduled_sync_events.py
git commit -m "Emit live events across microtech import, orders, customer, shopware5 and newsletter sync"
```

---

### Task 7: Retention-Cleanup für SyncEventLog

**Files:**
- Modify: `core/tasks.py` (neuer `@shared_task`)
- Test: `core/test_sync_event_log.py` (Cleanup-Test ergänzen)

**Interfaces:**
- Consumes: `core.models.SyncEventLog` aus Task 2.
- Produces: `@shared_task(name="core.cleanup_sync_event_log")` `cleanup_sync_event_log(max_age_days: int = 30) -> int` (Anzahl gelöschter Zeilen).

- [ ] **Step 1: Write the failing test**

In `core/test_sync_event_log.py` ergänzen:

```python
from datetime import timedelta

from django.utils import timezone


class CleanupTests(TestCase):
    def test_cleanup_removes_old_rows(self):
        from core.tasks import cleanup_sync_event_log

        old = SyncEventLog.objects.create(task="t", status="error", message="x")
        SyncEventLog.objects.filter(pk=old.pk).update(
            created_at=timezone.now() - timedelta(days=40)
        )
        SyncEventLog.objects.create(task="t", status="error", message="fresh")

        deleted = cleanup_sync_event_log(max_age_days=30)
        self.assertEqual(deleted, 1)
        self.assertEqual(SyncEventLog.objects.count(), 1)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python manage.py test core.test_sync_event_log.CleanupTests -v 2`
Expected: FAIL (`ImportError: cannot import name 'cleanup_sync_event_log'`)

- [ ] **Step 3: Implement the task**

In `core/tasks.py` ergänzen:

```python
@shared_task(name="core.cleanup_sync_event_log")
def cleanup_sync_event_log(max_age_days: int = 30) -> int:
    from datetime import timedelta

    from django.utils import timezone

    from core.models import SyncEventLog

    cutoff = timezone.now() - timedelta(days=max_age_days)
    deleted, _ = SyncEventLog.objects.filter(created_at__lt=cutoff).delete()
    return deleted
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python manage.py test core.test_sync_event_log.CleanupTests -v 2`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add core/tasks.py core/test_sync_event_log.py
git commit -m "Add retention cleanup task for SyncEventLog"
```

---

## Verifikation (nach allen Tasks)

- [ ] `python manage.py test core products -v 1` — alle neuen Tests grün.
- [ ] `python manage.py check` — keine Fehler.
- [ ] Manueller Smoke-Test: Admin öffnen → `admin/live-events/`, einen Produkt-Sync auslösen, Events erscheinen live; Task-Filter funktioniert; Payload-Klick lädt JSON; ein erzwungener Fehler landet in `SyncEventLog` (Django-Admin oder Shell prüfen).
