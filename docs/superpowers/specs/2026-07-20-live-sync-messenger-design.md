# Live-Sync-Messenger — Design

**Datum:** 2026-07-20
**Status:** Genehmigt (Brainstorming abgeschlossen)

## Ziel

Ein Live-Viewer in der Admin-Oberfläche, der produktgenau (bzw. item-genau)
anzeigt, was während eines Syncs gerade passiert. Beispiel-Verlauf für ein
Produkt:

1. Produkt in Django gespeichert.
2. Produkt wird mit Payload nach Microtech geschrieben.
3. Microtech erfolgreich.
4. Produkt wird mit Payload nach Shopware6 geschrieben.
5. Fehler: Preis konnte nicht gesetzt werden → Produkt wird übersprungen.
   5.1 Der Vorfall wird persistent festgehalten.
6. Task-Abschluss: „430 Produkte synchronisiert, 6 übersprungen".

Der Viewer ist read-only, staff-only, filterbar nach Task und ergänzt die
System-Status-Seite. Die bisherige Celery-Tasks-Detailansicht wird durch den
Live-Viewer **ersetzt**.

## Entscheidungen (aus dem Brainstorming)

- **Kein RabbitMQ.** Redis ist bereits Celery-Broker + Result-Backend
  (`GC_Bridge_4/settings.py:309`, `docker-compose.yml`). Redis Streams tragen
  den Live-Strom.
- **Keine ASGI-Migration.** Transport ist **Polling** (~1 s) gegen einen
  JSON-Endpunkt, WSGI-kompatibel unter Gunicorn.
- **Persistenz:** ephemer im Redis Stream (Live + kurze Reconnect-History);
  **nur** `error`/`skipped` zusätzlich persistent in einem neuen, schlanken
  DB-Modell `SyncEventLog`. Erfolgs-/Info-Events werden nicht in die DB
  geschrieben (kein DB-Wachstum durch Massen-Erfolge).
- **Detailgrad:** Live-Zeilen tragen kompakten `summary`-Text; der volle
  Payload liegt im selben Stream-Eintrag und wird nur auf Klick angezeigt.
- **Scope:** Ein generischer, wiederverwendbarer Emitter; instrumentiert werden
  alle item-schleifenden Sync-Tasks. Nicht-item-Tasks (Backup, Feiertage)
  erhalten nur Start/Abschluss-Events.

## Architektur / Datenfluss

```
Celery-Worker (Task-Schleife)
   │  emit_event(task, run_id, entity, target, step, status, summary, payload)
   ▼
core/live_events.py  ──XADD──►  Redis Stream  "live:events"  (MAXLEN ~10000, approx.)
   │                                    ▲
   │ (nur status=error/skipped)         │ XRANGE ab letzter ID (+ optionaler task-Filter)
   ▼                                    │
SyncEventLog (DB) + issues/      Polling-API (staff-only)  ◄── Admin-Live-Viewer (JS, ~1 s Poll)
```

## Komponenten

### 1. Emitter — `core/live_events.py`

Zentrale, wiederverwendbare Funktion:

```python
emit_event(
    task: str,            # Task-Name, z.B. "products.scheduled_product_sync"
    entity: str,          # Item-Kennung, z.B. erp_nr / order_nr / customer_nr
    step: str,            # z.B. "gespeichert", "→ microtech", "→ shopware6"
    status: str,          # "info" | "ok" | "error" | "skipped"
    summary: str,         # kompakte, menschenlesbare Zeile
    *,
    run_id: str | None = None,   # = Celery task_id; gruppiert einen Lauf
    target: str | None = None,   # "microtech" | "shopware6" | "shopware5" | ...
    payload: dict | None = None, # voller Payload, nur auf Klick sichtbar
) -> None
```

Verhalten:
- Schreibt einen Eintrag via `XADD live:events MAXLEN ~ 10000`. Feldwerte werden
  als Strings/JSON abgelegt (`ts, task, run_id, entity, target, step, status,
  summary, payload`).
- **Best-effort:** komplett in `try/except`. Ein Redis-Ausfall oder
  Serialisierungsfehler darf **niemals** den Sync-Task crashen — Fehler nur
  loggen, dann weiter.
- Bei `status ∈ {error, skipped}`: zusätzlich `SyncEventLog`-Zeile anlegen
  (siehe §2).
- Payload wird vor dem Schreiben auf eine Obergrenze gekürzt (z.B. 32 KB), um
  Redis-Speicher zu schützen; bei Kürzung ein Marker im Payload.

Zwei Komfort-Helfer für die Lauf-Rahmung:
- `emit_run_started(task, run_id, summary)`
- `emit_run_finished(task, run_id, summary, stats: dict)` → trägt die
  Abschluss-Summary (Punkt 6).

### 2. Persistente Fehlerablage — `SyncEventLog` (neues Modell)

App: `core` (oder `issues`, siehe offene Frage in der Umsetzung — Default `core`).

Felder:
- `created_at` (auto, indexed)
- `task` (CharField, indexed)
- `run_id` (CharField, indexed, blank)
- `entity` (CharField, blank)
- `target` (CharField, blank)
- `step` (CharField, blank)
- `status` (CharField: `error` | `skipped`)
- `message` (TextField)
- `payload` (JSONField, null=True)

Nur `error`/`skipped` landen hier → überschaubares Volumen. Filterbar nach Task,
payload-genau. Retention: periodischer Cleanup-Task (z.B. Einträge älter als
30 Tage löschen).

Das bestehende `issues.create_task_issue` / `TaskIssueCollector`
(`issues/services.py`) bleibt **orthogonal** erhalten: ein Issue ist ein
abzuarbeitendes Ticket, `SyncEventLog` ist der payload-genaue Audit-Trail.

### 3. Polling-API — `core/live_events_view.py` (staff-only)

- `GET …/live-events/api/?after=<stream-id>&task=<name>`
  → neue Events ab `after` (nur summary-Felder, ohne vollen Payload) + `next_id`.
  Optionaler `task`-Filter serverseitig.
- `GET …/live-events/api/detail/?id=<stream-id>`
  → voller Payload eines Eintrags fürs Aufklappen.
- Beide `staff_member_required`, read-only.

### 4. Frontend — Admin-Live-Viewer

- Scrollende Nachrichtenliste mit Auto-Scroll und **Pause**-Schalter.
- **Task-Filter-Dropdown** (Task-Namen).
- Farbcodierung nach `status`: ok=grün, error=rot, skipped=gelb, info=grau.
- Pro Zeile aufklappbarer Payload (lädt via detail-Endpunkt).
- „run finished"-Events werden als hervorgehobene **Summary-Zeile** dargestellt.
- Reconnect: Client merkt sich `next_id` (localStorage); kurze Stream-History
  deckt kurzzeitige Disconnects.
- **Integration:** Ersetzt die Celery-Tasks-Detailansicht auf der
  System-Status-Seite (`core/system_status_view.py`) durch das
  Live-Viewer-Panel.

### 5. Instrumentierung

Emit-Punkte in den item-schleifenden Sync-Tasks:

- **Produkt-Sync:**
  `microtech/management/commands/microtech_sync_products.py`
  → `SyncCommand._sync_current_record` (Microtech→Django „gespeichert",
  →Shopware6, →Shopware5). Zusätzlich `products/tasks.py`
  (`scheduled_product_sync`, `_scheduled_product_sync_continuation`,
  `shopware_sync_products`, `microtech_sync_products`).
- **Orders:** `orders/tasks.py` (`microtech_order_upsert`,
  Workflow-`advance`, `shopware_sync_open_orders`).
- **Customers:** `customer/tasks.py` (`microtech_customer_upsert`).
- **Shopware5:** `shopware/tasks.py`.
- **Newsletter:** `newsletter/tasks.py`.

Jeder instrumentierte Task rahmt sich mit `emit_run_started` /
`emit_run_finished`. Nicht-item-Tasks (Backup, Feiertage) erhalten nur diese
Rahmen-Events, kein künstliches pro-Item.

## Fehlerbehandlung

- Emitter ist best-effort und kann nie einen Task abbrechen.
- Übersprungene Items (`skipped`) werden weiterhin als Fehler in der
  Task-Statistik gezählt (bestehendes Verhalten in `products/tasks.py`).
- Redis nicht erreichbar → Live-View leer, aber Sync + `SyncEventLog`
  (DB) laufen weiter.

## Tests

- `emit_event`: schreibt korrekten Stream-Eintrag; bei Redis-Fehler kein Raise.
- `emit_event` mit `error`/`skipped`: legt `SyncEventLog`-Zeile an.
- Payload-Kürzung greift bei Übergröße.
- Polling-API: liefert Events ab `after`, respektiert `task`-Filter,
  staff-only (403 für nicht-staff).
- Detail-API: liefert vollen Payload.
- Instrumentierung des Produkt-Syncs: erwartete Event-Sequenz pro Produkt
  (gespeichert → target → ok/error) wird emittiert (Emitter gemockt).
- Retention-Cleanup löscht alte `SyncEventLog`-Zeilen.

## Nicht im Scope (YAGNI)

- WebSockets / SSE / ASGI.
- Persistenz von Erfolgs-/Info-Events.
- Bidirektionale Steuerung (Task pausieren/abbrechen aus dem Viewer).
- Instrumentierung von Nicht-Sync-Tasks über Start/Abschluss hinaus.
