# AI-Rewriter Redesign — Design

**Datum:** 2026-07-14
**App:** `ai/`
**Status:** Freigegeben (Brainstorming abgeschlossen)

## Ziel

Der AI-Rewriter ist heute zu kompliziert: viele Felder, viele feste Zuweisungen,
ein sechsstufiger Freigabe-Workflow. Prompts sind fest an genau ein Zielfeld **und**
einen Provider gebunden, sodass für jede Feld/KI-Kombination ein eigenes Prompt-Objekt
nötig ist.

Das Redesign vereinfacht den Ablauf auf: **Feld anklicken → Prompt + KI wählen →
Rewrite-Job erhalten → Ergebnis prüfen/bearbeiten → ins Feld übernehmen.**

## Kernentscheidungen (alle im Brainstorming bestätigt)

1. **Freigabe minimal** — kein mehrstufiges Approval, nur ein „übernommen"-Merker
   über den Status. Weg: `approved_by`, `approved_at`, `is_archived`, Status
   `draft`/`pending_review`/`approved`/`rejected`.
2. **Prompt vollständig entkoppelt** — ein Prompt ist nur noch ein wiederverwendbarer
   Baustein (Name + Anweisung). Feld und KI wählt man erst beim Job.
3. **Keine Iteration** — kein „nochmal drüberlaufen", keine Versionen, kein Re-Run.
   Ein Job = ein Ergebnis. Text manuell nachbearbeitbar. Neuer Prompt = neuer Job.
4. **Einstieg nur über den Feld-Button** in der Produkt-Detailansicht. Das separate
   Formular samt Produkt-Autocomplete entfällt.
5. **Async via Celery** — Job wird angelegt (`queued`), KI läuft im Hintergrund, das
   Ergebnis erscheint, sobald fertig.
6. **Ansatz A — produkt-fokussiert** — direkte `product`-FK statt GenericForeignKey.
   Quell- und Zielfeld verschmelzen zu **einem** `field`. Cross-Field (z.B.
   Kurzbeschreibung aus Beschreibung erzeugen) ist bewusst nicht mehr möglich.

## Datenmodell

### `AIProviderConfig` (die „KI") — unverändert

Repräsentiert das auswählbare KI-Modell. Felder bleiben: `name`, `base_url`,
`model_name`, `api_key`, `timeout_seconds`, `temperature`, `is_active`.

### `AIRewritePrompt` — stark verschlankt

**Behalten:** `name`, `slug` (auto), `description` (optional), `system_prompt` (die
Anweisung), `is_active`.

**Entfällt:** `provider` (FK), `content_type`, `source_field`, `target_field`,
`output_format`, `user_prompt_template`, `temperature_override`.

Das Ausgabeformat (HTML) und der Feldkontext kommen aus **einem** Standard-User-Prompt-
Template im Code, das den aktuellen Feldinhalt + Produktkontext injiziert.

### `AIRewriteJob` — neu geschnitten

| Feld | Typ | Zweck |
|---|---|---|
| `product` | FK(Product, PROTECT) | ersetzt `content_type`/`object_id`/`object_repr`/GenericFK |
| `field` | CharField(120) | das Beschreibungsfeld; Quelle **und** Ziel |
| `prompt` | FK(AIRewritePrompt, PROTECT) | beim Anlegen gewählt |
| `provider` | FK(AIProviderConfig, PROTECT) | die gewählte KI |
| `status` | CharField(choices) | `queued` / `ready` / `applied` / `failed` |
| `source_snapshot` | TextField | Feldinhalt zum Anlege-Zeitpunkt (Vergleich) |
| `result_text` | TextField | KI-Ausgabe, **vom User editierbar** |
| `rendered_prompt` | TextField (readonly) | tatsächlich gesendeter User-Prompt (Debug) |
| `error_message` | TextField | bei Fehler |
| `celery_task_id` | CharField(255) | Task-Tracking (Muster wie `ProductSyncJob`) |
| `requested_by` | FK(User, SET_NULL) | wer angelegt hat |
| `applied_at` | DateTimeField (null) | wann ins Feld geschrieben |

`created_at`/`updated_at` kommen aus `BaseModel`.

**Erlaubte Felder für `field`:** die schon bestehende Whitelist aus
`ai/rewrite_fields.py` (`description*` / `description_short*` inkl. Sprachvarianten).

### Status-Lifecycle

```
                 Celery-Task
   queued  ───────────────────►  ready ───(User: „übernehmen")──►  applied
      │                            ▲
      └──────── Fehler ────────►  failed
```

- `queued` → beim Anlegen; Celery-Task wird dispatcht.
- `ready` → Task erfolgreich, `result_text` gefüllt.
- `failed` → Task-Fehler, `error_message` gefüllt.
- `applied` → User hat übernommen; `result_text` ins Produktfeld geschrieben,
  `applied_at` gesetzt.

## User-Flow

### Einstieg: Feld-Button (Produkt-Detailansicht)

Der bestehende `AI`-Button je Beschreibungsfeld wird von einem POST-Handler auf einen
**GET-Link** umgestellt:

```
/admin/ai/airewritejob/new/?product=<pk>&field=<field_name>
```

`templates/admin/products/includes/ai_rewrite_field_buttons.html` wird entsprechend
angepasst (Link statt Formular-Submit). Produkt + Feld sind über die Query-Parameter
gesetzt.

### Create-Seite

Kleine Admin-View (`UnfoldModelAdminViewMixin` + `FormView`), Template ersetzt das alte
`rewrite_job_request.html`. Formular mit nur zwei Auswahlfeldern:

- **Prompt** — Dropdown aktiver `AIRewritePrompt`.
- **KI** — Dropdown aktiver `AIProviderConfig`.

Produkt + Feld kommen readonly/versteckt aus der Query. Validierung: `field` muss in der
Whitelist liegen, Produkt muss existieren.

Submit → `AIRewriteService.create_job(...)`: legt Job `queued` an, liest
`source_snapshot`, dispatcht Celery-Task, speichert `celery_task_id`, leitet zur
Job-Arbeitsfläche weiter.

### Job-Arbeitsfläche (Change-Page)

Verschlankte `AIRewriteJobAdmin`-Change-Ansicht:

- Kopf: Produkt-Link, Feld, Prompt, KI, Status.
- **`queued`**: Hinweis „wird verarbeitet…" + Auto-Refresh (einfacher Meta-Refresh
  oder kleines Poll-Snippet), bis Status wechselt.
- **`ready`/`applied`**: Original (`source_snapshot`, readonly) neben editierbarem
  `result_text` (WYSIWYG). Button **„In Feld übernehmen"**.
- **`failed`**: `error_message` anzeigen.

„In Feld übernehmen" → `AIRewriteService.apply(job)`: schreibt (ggf. editiertes)
`result_text` ins Produktfeld, Status → `applied`, `applied_at` = now.

## Async-Ausführung

Neue `ai/tasks.py` mit `@shared_task` (Projekt-Konvention, vgl. `products/tasks.py`):

```python
@shared_task
def run_ai_rewrite_job(job_id: int) -> None:
    ...
```

Der Task: lädt den Job, rendert den User-Prompt (Standard-Template + `source_snapshot`
+ Produktkontext), ruft `AIProviderService.rewrite_text(...)`, speichert `result_text` /
Status `ready` — oder bei Exception `error_message` / Status `failed`.

Dispatch analog `product_auto_sync`: `run_ai_rewrite_job.delay(job.pk)`, danach
`celery_task_id` per Follow-up-Update setzen.

## Services

`ai/services/rewrite.py` wird umgebaut:

- **`AIRewriteService.create_job(*, product, field, prompt, provider, requested_by)`** —
  legt Job an (`queued`), Snapshot, Dispatch. Ersetzt `request_rewrite` (das heute
  synchron ausführt).
- **`AIRewriteService.execute(job)`** — die eigentliche KI-Ausführung (vom Celery-Task
  aufgerufen). Rendert Prompt, ruft Provider, setzt `ready`/`failed`.
- **`AIRewriteService.apply(*, job, ...)`** — schreibt `result_text` ins Produktfeld,
  Status `applied`. Ersetzt `AIRewriteApplyService.apply`.
- **Entfällt:** `AIRewriteApplyService.approve` / `.reject`.

`AIProviderService` bleibt unverändert.

## Cleanup (Entfernen)

- `AIRewriteJobRequestForm`, `ProductAutocompleteView`, `AIRewriteJobRequestView` in
  `ai/admin.py`.
- `templates/admin/ai/rewrite_job_request.html`.
- `AIRewriteApplyService` (approve/reject/apply → in `AIRewriteService` konsolidiert).
- Admin-Actions `approve_selected` / `approve_and_apply_selected` / `reject_selected`.
- Die vielen readonly-Preview-Felder / 4-Tab-Fieldsets in `AIRewriteJobAdmin` auf das
  Nötige reduzieren.

## Migration & Datenübernahme

Django-Migration(en) in `ai/migrations/`:

1. **`AIRewritePrompt`**: entfernte Spalten droppen.
2. **`AIRewriteJob`**:
   - `product`-FK hinzufügen; Daten-Migration: aus `content_type`(=product)+`object_id`
     den Produkt-Bezug übernehmen. Job-Zeilen mit anderem ContentType (in der Praxis
     keine) werden gelöscht.
   - `source_field`+`target_field` → `field` (Wert aus `target_field`).
   - Status mappen: `applied`→`applied`, `failed`→`failed`, alles andere
     (`draft`/`pending_review`/`approved`/`rejected`)→`ready`.
   - Entfernte Spalten (`content_type`, `object_id`, `object_repr`, `approved_by`,
     `approved_at`, `is_archived`, `source_field`, `target_field`) droppen.
   - `celery_task_id` hinzufügen.

## Weitere anzupassende Stellen

- **`ai/management/commands/import_legacy_ai_rewrites.py`** — bricht mit den
  Modelländerungen. Da der Legacy-Import bereits gelaufen ist: auf das neue Schema
  anpassen oder stilllegen (Entscheidung bei Umsetzung; Default: anpassen, minimal).
- **`GC_Bridge_4/settings.py`** — Sidebar-Einträge (Rewrite erzeugen/Jobs/Prompts/
  Provider) auf den neuen Flow/Permissions prüfen.
- **`ai/rewrite_fields.py`** — Whitelist bleibt; ggf. Helfer für Feld-Label/Validierung
  der Create-Seite.

## Tests

- **`ai/tests.py`** — Großteil der `AIRewriteJobAdminTest`-Fälle neu schreiben
  (Create-Seite, Service `create_job`/`execute`/`apply`, Status-Übergänge, Whitelist-
  Validierung). Celery-Task synchron/gemockt testen. Die zwei heute bekannten
  vorbestehenden Fehlschläge in dieser Klasse werden dabei obsolet.
- **`core/tests.py`** — Sidebar-Erwartungen anpassen.
- Provider-Aufruf im Task mocken (kein echter HTTP-Call im Test).

## Nicht im Scope

- Cross-Field-Rewrites (Ziel ≠ Quelle).
- Umschreiben anderer Modelle als `Product`.
- Prompt-Verkettung / Re-Runs / Versionshistorie.
