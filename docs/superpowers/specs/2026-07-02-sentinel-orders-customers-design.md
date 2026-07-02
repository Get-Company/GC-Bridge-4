# Sentinel-Migration: Orders- & Customer-Workflow

**Datum:** 2026-07-02
**Status:** Entwurf freigegeben (Design), bereit für Implementierungsplan

## Ziel

Der bestehende Microtech-Sync für Kunden und Bestellungen läuft heute über den
**blockierenden** GraphQL-Pfad (`MicrotechGraphQLClientService` mit synchronem
`poll_job` → `while True / time.sleep`). Nur Produkte laufen bereits über den
asynchronen `MicrotechJobSentinelService`.

Diese Arbeit hängt den order-getriebenen Kunden-/Bestell-Workflow als
**asynchrone, resumebare Multi-Continuity-Kette** an den Sentinel:

1. **Customer-Upsert** (Shopware → Django → Microtech)
2. **AdrNr-Rückschreib** bei Neukunden (Django → Shopware)
3. **Order-Upsert** (Django → Microtech)

mit gezielter Fehlerbehandlung, pro-Schritt-Status und asynchronem Polling statt
blockierendem `poll_dataset_records`.

## Auslöser & Kontext

- Bestellungen werden von einem Scheduled Task aus Shopware nach Django geholt.
- Ein Mitarbeiter **prüft die Bestellung in Django** und **startet dann manuell**
  den Microtech-Workflow (Kunde aktualisieren/erzeugen → AdrNr rückschreiben →
  Bestellung anlegen).
- Der Einstieg ist also eine **manuelle Admin-Action nach menschlicher Prüfung**.
  Die Kette läuft danach asynchron im Hintergrund.

## Entscheidungen

- **Ansatz:** Feingranulare Sentinel-Kette + eigenes, resumebares
  Workflow-Statusobjekt (nicht: grobe blockierende Celery-Stufen, nicht: Kette
  ohne Statusmodell).
- **Fehlerverhalten:** Anhalten am fehlerhaften Schritt, Zustand erhalten,
  gezieltes Resume ab diesem Schritt (kein Neuaufsetzen der ganzen Kette).
- **Sichtbarkeit:** Pro-Schritt-Status pro Bestellung in Django.
- **COM-Pfad:** bleibt **unangetastet** (nur ignoriert, nicht entfernt). Nur der
  GraphQL-Pfad bekommt den async Workflow.
- **Wrapper-Realität:** Jede Wrapper-Mutation (`createCustomer`, `updateCustomer`,
  `createPostalAddress`, `createVorgang`, …) ist ein **eigener Wrapper-Job mit
  eigener jobId**. Es gibt keinen zusammengesetzten „Upsert-komplett"-Job → echte
  Async-Verarbeitung erfordert die feingranulare Kette.

## Architektur & Komponenten

### 1. Modell `MicrotechOrderSyncWorkflow` (`orders/models.py`)

Der resumebare Status-Träger, an `Order` gebunden.

| Feld | Typ | Zweck |
|------|-----|-------|
| `order` | FK → `Order` | Zugehörige Bestellung |
| `status` | Choices: `PENDING`, `RUNNING`, `WAITING`, `FAILED`, `SUCCEEDED` | (`WAITING` = Sentinel-Job in flight) |
| `current_step` | String-Key | z.B. `write_customer` |
| `state` | JSON | Akkumuliert: `erp_nr`, `is_new_customer`, `shipping_ans_nr`, `billing_ans_nr`, `beleg_nr`, … |
| `current_job` | FK → `MicrotechGraphQLJob` (nullable) | Aktuell laufender Sentinel-Job |
| `step_log` | JSON-Liste | `{step, status, at, error}` für die pro-Schritt-Anzeige |
| `error_message` | Text | Letzter Fehler |
| `created_at` / `updated_at` | Timestamps | |

**Constraint:** Höchstens ein aktiver Workflow pro `Order` — partielles Unique auf
`order` für `status in {PENDING, RUNNING, WAITING, FAILED}`. Ein `SUCCEEDED`-Workflow
blockiert einen erneuten manuellen Lauf nicht.

### 2. Service `OrderSyncWorkflowService` (`orders/services/order_sync_workflow.py`)

- `start_for_order(order)` — legt Workflow an (Doppelstart-Guard), berechnet
  Schritt 1, submitted den ersten Sentinel-Job.
- `advance(job)` — der registrierte Continuation-Handler (siehe Datenfluss).
- `resume(workflow)` — re-submitted `current_step` idempotent.
- `next_step(workflow)` — Resolver, der den Folgeschritt dynamisch aus `state`
  ableitet (wegen Branches statt statischer Liste).
- optional `cancel(workflow)`.

### 3. Non-blocking Submit am Client (`MicrotechGraphQLClientService`)

Neue Variante(n), die nur `_mutation_with_job(...)` aufrufen und
`(job_id, retry_after)` zurückgeben **ohne** `poll_job` — z.B. eine generische
`submit_mutation(name, variables) -> (str, float)`. Die bestehenden blockierenden
Methoden (`create_customer`, `update_vorgang`, …) bleiben unverändert.

### 4. Submit-Methoden am Sentinel (`MicrotechJobSentinelService`)

- `submit_customer_job(...)` → Kind `CUSTOMER_UPSERT`
- `submit_vorgang_job(...)` → Kind `ORDER_UPSERT`

Beide legen den `MicrotechGraphQLJob` an mit
`context={workflow_id, step}`, `continuation="microtech_order_sync_advance"`,
`delete_after_completion=True`. Die vorhandenen Payload-Builder
(`_build_customer_input`, `_build_postal_address_input`, `_build_graphql_positions`)
werden **wiederverwendet**. Die Sentinel-Kinds `CUSTOMER_READ/UPSERT`,
`ORDER_READ/UPSERT` und die Routing-Cases in `_fetch_remote_job` existieren bereits.

### 5. Continuation-Registrierung

`register_continuation("microtech_order_sync_advance", OrderSyncWorkflowService().advance)`.

## Schrittplan & Datenfluss

Der `next_step()`-Resolver berechnet nach jedem Job-Ergebnis den Folgeschritt aus
`state`. Mögliche Schrittfolge (Branches in `[…]`):

| # | Step-Key | Typ | Aktion | Branch-Logik |
|---|----------|-----|--------|--------------|
| 1 | `probe_customer` | Wrapper (`requestCustomer`) | Prüft, ob Kunde existiert | Ergebnis setzt `state.is_new_customer` |
| 2 | `write_customer` | Wrapper (`create`/`updateCustomer`) | Kundenstamm schreiben | `create` wenn `is_new`, sonst `update` |
| 3 | `upsert_shipping_address` | Wrapper (`create`/`updatePostalAddress`) | Versand-Anschrift | create/update aus lokal persistierter Anschrift-Identität; Ergebnis → `state.shipping_ans_nr` |
| 4 | `upsert_billing_address` | Wrapper | Rechnungs-Anschrift | **nur wenn** `billing.pk != shipping.pk`; sonst `billing_ans_nr = shipping_ans_nr` |
| 5 | `set_default_addresses` | Wrapper (`updateCustomer`) | Default-Versand/-Rechnung setzen | immer |
| 6 | `writeback_adrnr` | **Lokal** (kein Wrapper-Job) | AdrNr → Shopware | **nur wenn** `is_new_customer` |
| 7 | `probe_vorgang` | Wrapper (`requestVorgang`) | Bestehenden Beleg finden | nur wenn `beleg_nr` bekannt/auffindbar |
| 8 | `write_vorgang` | Wrapper (`create`/`updateVorgang`) | Bestellung inkl. Positionen (ein Mutation-Payload) | create/update je nach `beleg_nr`; Ergebnis → `state.beleg_nr`, persistiert als `erp_order_id` |

**Datenfluss pro Zyklus** (getrieben durch den Sentinel):

1. `start_for_order()` legt Workflow an, berechnet Schritt 1, submitted den ersten
   Sentinel-Job (`status=WAITING`, `current_job` gesetzt).
2. Sentinel pollt / empfängt Webhook → Job `SUCCEEDED` → dispatcht Continuation
   `microtech_order_sync_advance`.
3. **`advance(job)`**: lädt Workflow unter `select_for_update`, prüft
   `job.context.step == current_step`; liest `job.result_payload` (z.B.
   `erpAddressNumber`, `belegNr`, Existenz-Flag) → merged in `state`; schreibt
   `step_log`-Eintrag `completed`.
4. `next_step()` berechnet den Folgeschritt:
   - **Lokaler Schritt** (`writeback_adrnr`): sofort inline im Handler ausführen
     (Shopware-Update), loggen, dann erneut `next_step()`.
   - **Wrapper-Schritt**: Payload bauen → `submit_*_job(...)` → `current_step` /
     `current_job` aktualisieren, `status=WAITING`.
   - **Kein Schritt mehr**: `status=SUCCEEDED`.

**Idempotenz:** Jeder Schritt entscheidet create-vs-update aus lokal bekanntem
`state` / persistierten Identitäten. Ein erneutes Ausführen desselben Schritts
(Resume) ist sicher — es aktualisiert statt zu duplizieren.

## Fehlerbehandlung, Resume & Nebenläufigkeit

### Fehlererkennung (zweigleisig)

- **Erfolg** treibt die Kette *sofort* über die Sentinel-Continuation
  (`_after_terminal_update` → dispatch bei `SUCCEEDED`).
- **Fehler** löst keine Continuation aus (Sentinel dispatcht nur bei Erfolg).
  Deshalb ein **Reconcile-Beat-Task** `reconcile_order_sync_workflows` (bestehende
  Celery-Beat-Kadenz): findet Workflows mit `status=WAITING`, deren `current_job`
  terminal `FAILED/CANCELLED` ist, und setzt den Workflow auf `FAILED` mit
  übernommener `error_message` + `step_log`-Eintrag `failed`. Nicht-invasiv (kein
  Eingriff in den geteilten Produkt-Sentinel-Pfad); fängt auch Sonderfälle ab
  (verwaister Job, hängender Zustand).

### Resume

Admin-Action `resume` auf einem `FAILED`-Workflow baut den Payload für
`current_step` erneut und submitted einen frischen Sentinel-Job (`status=WAITING`).
Idempotent (siehe oben); bereits erledigte Schritte (`step_log=completed`) werden
nicht wiederholt.

### Job-Lebenszyklus

Workflow-Jobs laufen mit `delete_after_completion=True`. Nach erfolgreicher
Continuation wird der alte Job aufgeräumt — der Handler setzt `current_job` auf den
*neuen* Job, **bevor** der alte gelöscht wird. Fehlgeschlagene Jobs bleiben
(terminal, nicht gelöscht), damit Reconcile + UI die Fehlermeldung lesen können.

### Nebenläufigkeit / Doppelstart-Schutz

- Höchstens **ein aktiver** Workflow pro `Order` (DB-Constraint + Guard in
  `start_for_order()`).
- `advance()` läuft unter `select_for_update` auf dem Workflow und prüft
  `job.context.step == current_step`, um doppelte/verspätete Continuations (z.B.
  Webhook + Poll) zu ignorieren.
- Der Sentinel-eigene Claim-Mechanismus (`CLAIM_BACKOFF_SECONDS`, `skip_locked`)
  verhindert Doppel-Dispatch auf Job-Ebene bereits.

### Abbruch (optional, v1 verzichtbar)

Admin-Action `cancel` → `sentinel.cancel_job(current_job)` + Workflow auf einen
terminalen `CANCELLED`-Status.

## Trigger & UI (Django Admin, `orders/admin.py`)

- Bestehende Action `upsert_order` (aktuell synchron, `orders/admin.py:200`) wird
  auf `OrderSyncWorkflowService().start_for_order(order)` umgestellt — legt den
  Workflow an, submitted Schritt 1, kehrt **sofort** zurück.
- **Status-Anzeige:** readonly-Feld/Spalte pro Order mit `workflow.status`,
  lesbarem `current_step`-Label und `error_message`; `step_log` als kompakte Liste
  im Detail (erledigt/aktiv/fehlgeschlagen). Umsetzung über `readonly_fields` +
  `list_display`, kein eigenes Framework.
- **Actions:** `resume` (nur bei `FAILED`), optional `cancel`.
- Management-Command `microtech_order_upsert` bleibt **unverändert** (synchroner
  CLI-Pfad) — außerhalb des Scopes.

## Tests

Nach bestehenden Mustern (`orders/tests.py`, `customer/test_tasks.py`), alle
Wrapper-/Netzwerkaufrufe gemockt (kein echtes Microtech/Shopware):

1. **`next_step()`-Resolver** — Branch-Matrix: Neukunde vs. Bestandskunde,
   `billing == shipping` vs. getrennt, `is_new` → `writeback_adrnr` ja/nein,
   bekannte vs. unbekannte `beleg_nr`.
2. **`advance()`-Handler** — mit gefälschten `job.result_payload`
   (erpAddressNumber, belegNr, Existenz-Flag): State-Merge korrekt, `step_log`
   fortgeschrieben, korrekter nächster `submit_*_job` aufgerufen.
3. **Lokaler Schritt** `writeback_adrnr` — Shopware-Update nur bei `is_new`, dann
   Fortsetzung.
4. **Reconcile-Beat** — `WAITING`-Workflow mit `FAILED` current_job → wird `FAILED`
   mit übernommener Fehlermeldung.
5. **Resume** — re-submitted `current_step` idempotent, erledigte Schritte nicht
   wiederholt.
6. **Doppelstart-Schutz** — zweiter `start_for_order` bei aktivem Workflow wird
   abgelehnt.
7. **Sentinel-Submit-Methoden** — `submit_customer_job` / `submit_vorgang_job`
   legen Job mit korrektem Kind/context/continuation an; non-blocking Client-
   `submit_mutation` pollt nicht.

## Scope-Grenzen (bewusst außerhalb)

- Standalone „Kunde nach Microtech"-Admin-Action in `customer/admin.py` bleibt
  vorerst synchron.
- COM-Pfad (`so_vorgang.Post()`) bleibt unverändert.
- `microtech_order_upsert` CLI bleibt synchron.
- Der bestehende blockierende GraphQL-Pfad (`_upsert_customer_graphql`,
  `_upsert_order_graphql`) wird nicht entfernt — nur die Payload-Builder daraus
  wiederverwendet.
