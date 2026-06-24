# Design: Automatische Issue-Erstellung für Task-Fehler

**Datum:** 2026-06-24  
**Status:** Approved

## Ziel

Fehler aus Celery-Tasks und Management Commands werden automatisch als Issues im Admin angelegt. Bestehende offene Issues mit gleichem Titel werden aktualisiert statt dupliziert.

---

## Kategorie

Eine neue `IssueCategory` wird per Data Migration in der `issues`-App erstellt:

| Feld        | Wert                       |
|-------------|----------------------------|
| `name`      | `Automatische Task-Fehler` |
| `color`     | `#f97316` (orange)         |
| `is_active` | `True`                     |

Die Migration läuft beim Deploy automatisch — kein manueller Schritt nötig.

---

## `issues/services.py` — `create_task_issue(...)`

```python
def create_task_issue(
    *,
    title: str,
    error_text: str,
    description: str = "",
    priority: str = Issue.Priority.HIGH,
) -> Issue:
```

**Logik:**
1. Sucht ein `Issue` mit `title=title` und `status=OPEN`.
2. **Gefunden:** Hängt neuen Fehlertext mit Zeitstempel an `error_text` an (`APPEND`), speichert.
3. **Nicht gefunden:** Erstellt neues `Issue` mit `status=OPEN`, `priority=HIGH`, Kategorie "Automatische Task-Fehler".
4. Gibt das Issue zurück.

**Fehlerverhalten:** Exceptions beim Issue-Erstellen/Updaten werden intern geloggt (`logger.exception`) aber nicht weitergegeben — der aufrufende Task soll nicht durch ein fehlgeschlagenes Issue-Schreiben brechen.

---

## Titelformat (Dedup-Schlüssel)

```
[Task-Fehler] <task_name> › <step>
```

Beispiele:
- `[Task-Fehler] shopware_force_product_image_uploads › upload`
- `[Task-Fehler] shopware_force_product_image_uploads › delete`
- `[Task-Fehler] shopware_force_product_image_uploads › assignment`

**Kein Batch-Nr im Titel** — der Titel ist der Dedup-Schlüssel. Batch-Nr, betroffene Produkte und Stacktrace gehen in `error_text`.

---

## `error_text`-Format bei Append

```
--- 2026-06-24 09:48:47 | Batch 13 | Produkte: ['204045/01', ...] ---
ShopwareAPIError: 400 Bad Request ...
(Stacktrace)

--- 2026-06-24 10:12:03 | Batch 7 | Produkte: ['204046/02', ...] ---
...
```

---

## Einbindung: `shopware_force_product_image_uploads`

In `_record_error` der Command-Klasse wird nach dem Loguru-Log `create_task_issue(...)` aufgerufen:

```python
create_task_issue(
    title=f"[Task-Fehler] shopware_force_product_image_uploads › {step}",
    error_text=f"Batch {batch_no} | Produkte: {products}\n{traceback_str}",
    description=f"Automatisch erstellt. Batch {batch_no}, Schritt '{step}'.",
)
```

Der Stacktrace wird via `traceback.format_exc()` oder `str(exc)` erfasst.

---

## Dateien

| Datei | Änderung |
|-------|----------|
| `issues/services.py` | Neu: `create_task_issue(...)` |
| `issues/migrations/XXXX_add_task_fehler_category.py` | Neu: Data Migration |
| `shopware/management/commands/shopware_force_product_image_uploads.py` | `_record_error` erweitert |

---

## Nicht im Scope

- Kein E-Mail-Versand bei Issue-Erstellung
- Kein automatisches Schließen von Issues
- Kein allgemeiner Loguru-Sink (nur expliziter Aufruf pro Task)
