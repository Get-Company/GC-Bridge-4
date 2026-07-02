# Sentinel Orders/Customers Workflow — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Den order-getriebenen Microtech-Sync (Kunde upserten → AdrNr nach Shopware zurückschreiben → Bestellung upserten) als asynchrone, resumebare Multi-Continuity-Kette über den `MicrotechJobSentinelService` ausführen, statt blockierend zu pollen.

**Architecture:** Ein neues Modell `MicrotechOrderSyncWorkflow` hält den resumebaren Zustand pro Bestellung. Ein `OrderSyncWorkflowService` beschreibt die Kette als **datengetriebene Step-Registry**; jeder Schritt submittet genau einen Sentinel-Job (`continuation="microtech_order_sync_advance"`). Der registrierte Continuation-Handler `advance()` wendet das Job-Ergebnis an und submittet den nächsten Schritt. Fehler werden über einen Reconcile-Aufruf erkannt (der Sentinel dispatcht Continuations nur bei Erfolg). Probe-Schritte (`requestCustomer`/`requestVorgang`) behandeln „nicht gefunden" als Branch, nicht als Fehler.

**Tech Stack:** Python 3.12, Django, Celery (django_celery_beat DatabaseScheduler), django-unfold Admin, `MicrotechGraphQLClientService` (HTTP GraphQL Wrapper), pytest/Django `TestCase`.

## Global Constraints

- Paketinstallation: immer `uv pip install` (nicht `pip`).
- Keine `Co-Authored-By`-Zeilen in Commits.
- Antworten/Kommentare/Doku auf Deutsch; Umlaute korrekt (nie ASCII-Ersatz).
- COM-Pfad (`so_vorgang.Post()` in `orders/services/order_upsert_microtech.py`) und die bestehenden **blockierenden** GraphQL-Methoden bleiben **unverändert** — nur additive Änderungen plus die Payload-Builder werden wiederverwendet.
- Standalone „Kunde nach Microtech"-Admin-Action in `customer/admin.py` und das CLI `microtech_order_upsert` bleiben synchron (out of scope).
- Alle Netzwerk-/Wrapper-/Shopware-Aufrufe in Tests mocken (kein echtes Microtech/Shopware).
- Migrationen mit `python manage.py makemigrations` erzeugen; Tests mit `python manage.py test <app>.<modul>`.
- Tests folgen dem bestehenden Muster (`unittest.mock.patch`, Django `TestCase`/`SimpleTestCase`) wie in `customer/test_tasks.py`.

## Referenz — bereits vorhandene Bausteine (nicht neu bauen)

- `microtech/models.py:35` `MicrotechGraphQLJob` mit `Kind` (u.a. `CUSTOMER_READ`, `CUSTOMER_UPSERT`, `ORDER_READ`, `ORDER_UPSERT`), `Status`, Feldern `context`, `request_payload`, `result_payload`, `continuation`, `next_step`, `external_job_id`, `is_terminal`.
- `microtech/services/job_sentinel.py` `MicrotechJobSentinelService`: `submit_product_update`-Muster (Job-Row QUEUED anlegen → Client submit → WAITING + `next_poll_at`; bei Exception FAILED), `register_continuation(name, handler)`, `process_continuation`, `_after_terminal_update` (dispatcht Continuation nur bei `SUCCEEDED`), `_fetch_remote_job` routet `CUSTOMER_*`→`customer_job`, `ORDER_*`→`vorgang_job`.
- `microtech/services/graphql_client.py`: blockierende Methoden `request_customer:317`, `create_customer:331`, `update_customer:345`, `create_postal_address:359`/`_postal_address_mutation:540`, `create_contact_person:379`/`_contact_person_mutation`, `request_vorgang:407`, `create_vorgang:421`, `update_vorgang:435`; Helfer `_mutation_with_job(query, field, variables):527` (führt Mutation aus, liefert `accepted`-dict mit `jobId`, `retryAfterSeconds`), `_accepted:531`. Ergebnis-Queries: `customer_job:449` (liefert `customer`/`postalAddress`/`contactPerson`), `vorgang_job:484` (liefert `vorgang.belegNr`).
- `customer/services/customer_upsert_microtech.py` `CustomerUpsertMicrotechService`: Payload-Builder `_build_customer_input:332`, `_build_postal_address_input:351`, `_build_contact_person_input:381`; Identity-Persistenz `_persist_anschrift_identity`, `_persist_ansprechpartner_identity`, `_resolve_na1_for_anschrift`; `_sync_new_customer_number_to_shopware:405` (AdrNr→Shopware); Helfer `_to_int`, `_to_str`.
- `orders/services/order_upsert_microtech.py` `OrderUpsertMicrotechService`: `_build_graphql_positions(order, resolved_rule, client):333`, `_load_order_defaults`, `_coerce_positive_int`, `_persist_erp_order_id`, `_clear_erp_order_id`; `OrderRuleResolverService().resolve_for_order(order)`.
- `products/tasks.py:395` `register_product_sync_continuations()` + `microtech/tasks.py:6` `process_graphql_job_result` (importiert `products.tasks`, um Continuations zu registrieren) — **Muster für Continuation-Registrierung**.
- `orders/admin.py:186` `_run_microtech_upsert` (aktueller synchroner Trigger), `actions_detail:135`, `@action`-Decorator (django-unfold).
- Basisklassen: `core/models/base.py` `BaseModel` (liefert `created_at`/`updated_at`), `core/services/base.py` `BaseService` (ABC, `model`-Attribut).

---

## Datei-Struktur

- **Neu** `orders/services/order_sync_workflow.py` — `OrderSyncWorkflowService`, Step-Registry, `next_step`/`advance`/`start_for_order`/`resume`/`reconcile_failures`. Eine klare Verantwortung: Orchestrierung der Kette.
- **Neu** `orders/migrations/000X_microtechordersyncworkflow.py` — Modell-Migration (auto-generiert).
- **Neu** `orders/test_order_sync_workflow.py` — Tests für Resolver, advance, start, reconcile, resume.
- **Ändern** `orders/models.py` — Modell `MicrotechOrderSyncWorkflow`.
- **Ändern** `orders/services/__init__.py` — Export `OrderSyncWorkflowService`.
- **Ändern** `orders/tasks.py` — Kickoff-/Reconcile-Tasks + Continuation-Registrierung.
- **Ändern** `orders/admin.py` — Trigger auf Workflow umstellen, Status-Anzeige, Resume-Action.
- **Ändern** `microtech/services/graphql_client.py` — non-blocking `submit_*`-Methoden (additiv).
- **Ändern** `microtech/services/job_sentinel.py` — generische `submit_wrapper_job`.
- **Ändern** `microtech/tasks.py` — `poll_graphql_jobs` ruft Reconcile; `process_graphql_job_result` importiert die Order-Continuation-Registrierung.

---

## Step-Modell (Referenz für alle Tasks)

`state` (JSON auf dem Workflow) sammelt: `is_new_customer` (bool), `erp_nr` (str, = `customer.erp_nr`), `address_number` (int), `shipping_ans_nr` (int), `billing_ans_nr` (int), `beleg_nr` (str).

Geordnete Step-Keys und ihr Verhalten (Branch in Klammern):

| Key | Kind | Operation | Branch |
|-----|------|-----------|--------|
| `probe_customer` | CUSTOMER_READ | requestCustomer | Ergebnis/Fehler → `is_new_customer` |
| `write_customer` | CUSTOMER_UPSERT | createCustomer wenn `is_new_customer` sonst updateCustomer | — |
| `shipping_address` | CUSTOMER_UPSERT | create/updatePostalAddress (update wenn `address.erp_ans_nr`) | → `shipping_ans_nr` |
| `shipping_contact` | CUSTOMER_UPSERT | create/updateContactPerson | — |
| `billing_address` | CUSTOMER_UPSERT | create/updatePostalAddress | nur wenn `billing.pk != shipping.pk`; sonst `billing_ans_nr=shipping_ans_nr` |
| `billing_contact` | CUSTOMER_UPSERT | create/updateContactPerson | nur wenn getrennt |
| `set_default_addresses` | CUSTOMER_UPSERT | updateCustomer(defaultShipping/Billing) | — |
| `writeback_adrnr` | LOKAL | — | nur wenn `is_new_customer` |
| `probe_vorgang` | ORDER_READ | requestVorgang(`order.erp_order_id`) | nur wenn `erp_order_id` gesetzt; Fehler → nicht gefunden |
| `write_vorgang` | ORDER_UPSERT | createVorgang wenn kein `beleg_nr` sonst updateVorgang | → `beleg_nr`, persist `erp_order_id` |

**Probe-Semantik:** `probe_customer`/`probe_vorgang` bewerten sowohl Erfolg als auch Fehler als gültiges Ergebnis. Erfolg mit gefundenem Datensatz → „existiert". Job-Fehler ODER Erfolg-ohne-Datensatz → „nicht gefunden". Die Fehler-als-Branch-Behandlung passiert in `reconcile_failures` (siehe Task 9).

---

### Task 1: Non-blocking Client-Submit-Methoden

**Files:**
- Modify: `microtech/services/graphql_client.py` (additiv, nach den bestehenden blockierenden Methoden)
- Test: `microtech/test_graphql_submit.py` (Create)

**Interfaces:**
- Produces (alle liefern `tuple[str, float]` = `(job_id, retry_after)`):
  - `submit_request_customer(self, customer_number: str) -> tuple[str, float]`
  - `submit_create_customer(self, customer_number: str, input_data: dict) -> tuple[str, float]`
  - `submit_update_customer(self, customer_number: str, input_data: dict) -> tuple[str, float]`
  - `submit_create_postal_address(self, address_number: int, input_data: dict) -> tuple[str, float]`
  - `submit_update_postal_address(self, address_number: int, address_sub_number: int, input_data: dict) -> tuple[str, float]`
  - `submit_create_contact_person(self, address_number: int, address_sub_number: int, input_data: dict) -> tuple[str, float]`
  - `submit_update_contact_person(self, address_number: int, address_sub_number: int, contact_number: int, input_data: dict) -> tuple[str, float]`
  - `submit_request_vorgang(self, beleg_nr: str) -> tuple[str, float]`
  - `submit_create_vorgang(self, input_data: dict) -> tuple[str, float]`
  - `submit_update_vorgang(self, beleg_nr: str, input_data: dict) -> tuple[str, float]`

Jede Methode nutzt exakt die GraphQL-Query der bestehenden blockierenden Zwilling-Methode (gleiche `field`/Variablen), ruft `_mutation_with_job(...)` und gibt statt `poll_job(...)` sofort `(jobId, retryAfterSeconds)` zurück — analog zu `submit_dataset_job:135` / `submit_update_product:282`.

- [ ] **Step 1: Failing test schreiben**

`microtech/test_graphql_submit.py`:

```python
from unittest.mock import patch

from django.test import SimpleTestCase

from microtech.services.graphql_client import MicrotechGraphQLClientService


class SubmitMutationTest(SimpleTestCase):
    def _accepted(self):
        return {"accepted": True, "jobId": "job-123", "retryAfterSeconds": 42}

    @patch.object(MicrotechGraphQLClientService, "_mutation_with_job")
    def test_submit_update_customer_returns_job_id_without_polling(self, mock_mutation):
        mock_mutation.return_value = self._accepted()
        client = MicrotechGraphQLClientService.__new__(MicrotechGraphQLClientService)

        job_id, retry_after = client.submit_update_customer("100012", {"city": "Kassel"})

        self.assertEqual(job_id, "job-123")
        self.assertEqual(retry_after, 42.0)
        mock_mutation.assert_called_once()
        # field-Argument der Mutation ist updateCustomer
        self.assertEqual(mock_mutation.call_args.args[1], "updateCustomer")

    @patch.object(MicrotechGraphQLClientService, "_mutation_with_job")
    def test_submit_create_postal_address_uses_create_field(self, mock_mutation):
        mock_mutation.return_value = self._accepted()
        client = MicrotechGraphQLClientService.__new__(MicrotechGraphQLClientService)

        job_id, _ = client.submit_create_postal_address(100012, {"city": "Kassel"})

        self.assertEqual(job_id, "job-123")
        self.assertEqual(mock_mutation.call_args.args[1], "createPostalAddress")
```

- [ ] **Step 2: Test ausführen, Fehlschlag verifizieren**

Run: `python manage.py test microtech.test_graphql_submit -v 2`
Expected: FAIL (`AttributeError: 'MicrotechGraphQLClientService' object has no attribute 'submit_update_customer'`)

- [ ] **Step 3: Minimal-Implementierung**

In `microtech/services/graphql_client.py`, direkt nach `update_vorgang` (Zeile ~448) einfügen. Muster (hier `submit_update_customer` und `submit_create_postal_address` vollständig; die übrigen spiegeln jeweils die gleichnamige blockierende Methode, nur mit `return str(accepted["jobId"]), float(accepted.get("retryAfterSeconds") or self.config.poll_interval)` statt `poll_job(...)`):

```python
    def _submit_accepted(self, accepted: dict[str, Any]) -> tuple[str, float]:
        return str(accepted["jobId"]), float(accepted.get("retryAfterSeconds") or self.config.poll_interval)

    def submit_request_customer(self, customer_number: str) -> tuple[str, float]:
        accepted = self._mutation_with_job(
            """
            mutation RequestCustomer($customerNumber: String!) {
              requestCustomer(customerNumber: $customerNumber) {
                accepted jobId status message retryAfterSeconds
              }
            }
            """,
            "requestCustomer",
            {"customerNumber": customer_number},
        )
        return self._submit_accepted(accepted)

    def submit_create_customer(self, customer_number: str, input_data: dict[str, Any]) -> tuple[str, float]:
        accepted = self._mutation_with_job(
            """
            mutation CreateCustomer($customerNumber: String!, $input: CustomerInput!) {
              createCustomer(customerNumber: $customerNumber, input: $input) {
                accepted jobId status message retryAfterSeconds
              }
            }
            """,
            "createCustomer",
            {"customerNumber": customer_number, "input": input_data},
        )
        return self._submit_accepted(accepted)

    def submit_update_customer(self, customer_number: str, input_data: dict[str, Any]) -> tuple[str, float]:
        accepted = self._mutation_with_job(
            """
            mutation UpdateCustomer($customerNumber: String!, $input: CustomerInput!) {
              updateCustomer(customerNumber: $customerNumber, input: $input) {
                accepted jobId status message retryAfterSeconds
              }
            }
            """,
            "updateCustomer",
            {"customerNumber": customer_number, "input": input_data},
        )
        return self._submit_accepted(accepted)

    def submit_create_postal_address(self, address_number: int, input_data: dict[str, Any]) -> tuple[str, float]:
        accepted = self._mutation_with_job(
            """
            mutation CreatePostalAddress($addressNumber: Int!, $input: PostalAddressInput!) {
              createPostalAddress(addressNumber: $addressNumber, input: $input) {
                accepted jobId status message retryAfterSeconds
              }
            }
            """,
            "createPostalAddress",
            {"addressNumber": address_number, "input": input_data},
        )
        return self._submit_accepted(accepted)

    def submit_update_postal_address(self, address_number: int, address_sub_number: int, input_data: dict[str, Any]) -> tuple[str, float]:
        accepted = self._mutation_with_job(
            """
            mutation UpdatePostalAddress($addressNumber: Int!, $addressSubNumber: Int!, $input: PostalAddressInput!) {
              updatePostalAddress(addressNumber: $addressNumber, addressSubNumber: $addressSubNumber, input: $input) {
                accepted jobId status message retryAfterSeconds
              }
            }
            """,
            "updatePostalAddress",
            {"addressNumber": address_number, "addressSubNumber": address_sub_number, "input": input_data},
        )
        return self._submit_accepted(accepted)

    def submit_create_contact_person(self, address_number: int, address_sub_number: int, input_data: dict[str, Any]) -> tuple[str, float]:
        accepted = self._mutation_with_job(
            """
            mutation CreateContactPerson($addressNumber: Int!, $addressSubNumber: Int!, $input: ContactPersonInput!) {
              createContactPerson(addressNumber: $addressNumber, addressSubNumber: $addressSubNumber, input: $input) {
                accepted jobId status message retryAfterSeconds
              }
            }
            """,
            "createContactPerson",
            {"addressNumber": address_number, "addressSubNumber": address_sub_number, "input": input_data},
        )
        return self._submit_accepted(accepted)

    def submit_update_contact_person(self, address_number: int, address_sub_number: int, contact_number: int, input_data: dict[str, Any]) -> tuple[str, float]:
        accepted = self._mutation_with_job(
            """
            mutation UpdateContactPerson($addressNumber: Int!, $addressSubNumber: Int!, $contactNumber: Int!, $input: ContactPersonInput!) {
              updateContactPerson(addressNumber: $addressNumber, addressSubNumber: $addressSubNumber, contactNumber: $contactNumber, input: $input) {
                accepted jobId status message retryAfterSeconds
              }
            }
            """,
            "updateContactPerson",
            {"addressNumber": address_number, "addressSubNumber": address_sub_number, "contactNumber": contact_number, "input": input_data},
        )
        return self._submit_accepted(accepted)

    def submit_request_vorgang(self, beleg_nr: str) -> tuple[str, float]:
        accepted = self._mutation_with_job(
            """
            mutation RequestVorgang($belegNr: String!) {
              requestVorgang(belegNr: $belegNr) {
                accepted jobId status message retryAfterSeconds
              }
            }
            """,
            "requestVorgang",
            {"belegNr": beleg_nr},
        )
        return self._submit_accepted(accepted)

    def submit_create_vorgang(self, input_data: dict[str, Any]) -> tuple[str, float]:
        accepted = self._mutation_with_job(
            """
            mutation CreateVorgang($input: CreateVorgangInput!) {
              createVorgang(input: $input) {
                accepted jobId status message retryAfterSeconds
              }
            }
            """,
            "createVorgang",
            {"input": input_data},
        )
        return self._submit_accepted(accepted)

    def submit_update_vorgang(self, beleg_nr: str, input_data: dict[str, Any]) -> tuple[str, float]:
        accepted = self._mutation_with_job(
            """
            mutation UpdateVorgang($belegNr: String!, $input: UpdateVorgangInput!) {
              updateVorgang(belegNr: $belegNr, input: $input) {
                accepted jobId status message retryAfterSeconds
              }
            }
            """,
            "updateVorgang",
            {"belegNr": beleg_nr, "input": input_data},
        )
        return self._submit_accepted(accepted)
```

Hinweis: `_contact_person_mutation` in der blockierenden Variante nutzt exakt diese Query-Felder — die non-blocking Variante spiegelt sie 1:1.

- [ ] **Step 4: Test ausführen, Erfolg verifizieren**

Run: `python manage.py test microtech.test_graphql_submit -v 2`
Expected: PASS (2 Tests)

- [ ] **Step 5: Commit**

```bash
git add microtech/services/graphql_client.py microtech/test_graphql_submit.py
git commit -m "feat(microtech): non-blocking submit-Methoden fuer Customer/Vorgang-Mutationen"
```

---

### Task 2: Generischer Sentinel-Submit `submit_wrapper_job`

**Files:**
- Modify: `microtech/services/job_sentinel.py`
- Test: `microtech/test_job_sentinel_wrapper.py` (Create)

**Interfaces:**
- Consumes: `MicrotechGraphQLJob.Kind`, `.Status`; Client-`submit_*` aus Task 1.
- Produces:
  `submit_wrapper_job(self, *, kind: str, operation: str, submit: Callable[[], tuple[str, float]], request_payload: dict, context: dict, continuation: str, next_step: str, delete_after_completion: bool = True) -> MicrotechGraphQLJob`
  Legt Job-Row `QUEUED` an, ruft `submit()`, setzt `external_job_id`/`WAITING_WEBHOOK`/`next_poll_at`; bei Exception FAILED + reraise. Spiegelt `submit_product_update:112`.

- [ ] **Step 1: Failing test schreiben**

`microtech/test_job_sentinel_wrapper.py`:

```python
from unittest.mock import patch

from django.test import TestCase

from microtech.models import MicrotechGraphQLJob
from microtech.services.job_sentinel import MicrotechJobSentinelService


class SubmitWrapperJobTest(TestCase):
    def test_submit_wrapper_job_creates_waiting_job(self):
        sentinel = MicrotechJobSentinelService()
        job = sentinel.submit_wrapper_job(
            kind=MicrotechGraphQLJob.Kind.CUSTOMER_UPSERT,
            operation="updateCustomer",
            submit=lambda: ("ext-1", 30.0),
            request_payload={"customerNumber": "100012"},
            context={"workflow_id": 7, "step": "write_customer"},
            continuation="microtech_order_sync_advance",
            next_step="Kunde schreiben.",
        )
        job.refresh_from_db()
        self.assertEqual(job.external_job_id, "ext-1")
        self.assertEqual(job.status, MicrotechGraphQLJob.Status.WAITING_WEBHOOK)
        self.assertEqual(job.continuation, "microtech_order_sync_advance")
        self.assertEqual(job.context["step"], "write_customer")

    def test_submit_wrapper_job_marks_failed_on_submit_error(self):
        sentinel = MicrotechJobSentinelService()

        def boom():
            raise RuntimeError("wrapper down")

        with self.assertRaises(RuntimeError):
            sentinel.submit_wrapper_job(
                kind=MicrotechGraphQLJob.Kind.CUSTOMER_UPSERT,
                operation="updateCustomer",
                submit=boom,
                request_payload={},
                context={"workflow_id": 7, "step": "write_customer"},
                continuation="microtech_order_sync_advance",
                next_step="Kunde schreiben.",
            )
        job = MicrotechGraphQLJob.objects.get(context__step="write_customer")
        self.assertEqual(job.status, MicrotechGraphQLJob.Status.FAILED)
        self.assertIn("wrapper down", job.error_message)
```

- [ ] **Step 2: Test ausführen, Fehlschlag verifizieren**

Run: `python manage.py test microtech.test_job_sentinel_wrapper -v 2`
Expected: FAIL (`AttributeError: ... 'submit_wrapper_job'`)

- [ ] **Step 3: Minimal-Implementierung**

In `microtech/services/job_sentinel.py`, `from collections.abc import Callable, Sequence` ist bereits importiert. Methode nach `submit_product_batch_read` einfügen:

```python
    def submit_wrapper_job(
        self,
        *,
        kind: str,
        operation: str,
        submit: Callable[[], tuple[str, float]],
        request_payload: dict[str, Any],
        context: dict[str, Any],
        continuation: str,
        next_step: str,
        delete_after_completion: bool = True,
    ) -> MicrotechGraphQLJob:
        job = MicrotechGraphQLJob.objects.create(
            kind=kind,
            operation=operation,
            status=MicrotechGraphQLJob.Status.QUEUED,
            request_payload=request_payload,
            context=context or {},
            continuation=str(continuation or "").strip(),
            next_step=next_step or "Warte auf Microtech GraphQL Job.",
            delete_after_completion=delete_after_completion,
        )
        try:
            external_job_id, retry_after = submit()
        except Exception as exc:
            job.status = MicrotechGraphQLJob.Status.FAILED
            job.error_message = str(exc)
            job.completed_at = timezone.now()
            job.save(update_fields=("status", "error_message", "completed_at", "updated_at"))
            raise

        now = timezone.now()
        job.external_job_id = external_job_id
        job.status = MicrotechGraphQLJob.Status.WAITING_WEBHOOK
        job.submitted_at = now
        job.started_at = now
        job.next_poll_at = now + timedelta(seconds=max(int(retry_after), 30))
        job.save(
            update_fields=(
                "external_job_id",
                "status",
                "submitted_at",
                "started_at",
                "next_poll_at",
                "updated_at",
            )
        )
        return job
```

- [ ] **Step 4: Test ausführen, Erfolg verifizieren**

Run: `python manage.py test microtech.test_job_sentinel_wrapper -v 2`
Expected: PASS (2 Tests)

- [ ] **Step 5: Commit**

```bash
git add microtech/services/job_sentinel.py microtech/test_job_sentinel_wrapper.py
git commit -m "feat(microtech): generischer submit_wrapper_job fuer Continuation-Ketten"
```

---

### Task 3: Modell `MicrotechOrderSyncWorkflow`

**Files:**
- Modify: `orders/models.py`
- Create: `orders/migrations/000X_microtechordersyncworkflow.py` (via makemigrations)
- Test: `orders/test_order_sync_workflow.py` (Create — flache Datei, da `orders/tests.py` bereits als Modul existiert; Muster wie `orders/test_swiss_customs_csv.py`)

**Interfaces:**
- Produces: `MicrotechOrderSyncWorkflow` mit Feldern `order` (FK), `status`, `current_step`, `state` (JSON), `current_job` (FK nullable → `MicrotechGraphQLJob`), `step_log` (JSON list), `error_message`; Klassen `Status` (`PENDING`,`RUNNING`,`WAITING`,`FAILED`,`SUCCEEDED`); Property `is_active`; Konstante `ACTIVE_STATUSES`.
- Produces (Test-Helfer, Modulebene in `orders/test_order_sync_workflow.py`): `make_order() -> Order` — legt Customer (`erp_nr`), zwei Adressen und eine Order mit `billing_address`/`shipping_address` an (Muster: `orders/tests.py:25` `_create_order`). Alle folgenden Task-Tests importieren diesen Helfer aus diesem Modul.

- [ ] **Step 1: Failing test + Fixture schreiben**

`orders/test_order_sync_workflow.py` (Modulkopf mit Fixture, den alle folgenden Task-Tests mitnutzen):

```python
from decimal import Decimal

from django.db import IntegrityError
from django.test import TestCase

from customer.models import Address, Customer
from orders.models import MicrotechOrderSyncWorkflow, Order

_ORDER_SEQ = [0]


def make_order() -> Order:
    _ORDER_SEQ[0] += 1
    n = _ORDER_SEQ[0]
    api_id = f"WF{n}"
    customer = Customer.objects.create(erp_nr=f"100{n:05d}", name="Testkunde GmbH", is_gross=True)
    billing = Address.objects.create(customer=customer, first_name="Max", last_name="Mustermann", country_code="DE", is_invoice=True)
    shipping = Address.objects.create(customer=customer, first_name="Max", last_name="Mustermann", country_code="DE", is_shipping=True)
    return Order.objects.create(
        api_id=api_id,
        order_number=f"ORDER-{api_id}",
        customer=customer,
        billing_address=billing,
        shipping_address=shipping,
        payment_method="Rechnung",
        shipping_method="Standard",
        total_price=Decimal("0.00"),
        total_tax=Decimal("0.00"),
        shipping_costs=Decimal("0.00"),
    )


class WorkflowModelTest(TestCase):
    def test_defaults(self):
        order = make_order()
        wf = MicrotechOrderSyncWorkflow.objects.create(order=order)
        self.assertEqual(wf.status, MicrotechOrderSyncWorkflow.Status.PENDING)
        self.assertEqual(wf.state, {})
        self.assertEqual(wf.step_log, [])
        self.assertTrue(wf.is_active)

    def test_only_one_active_workflow_per_order(self):
        order = make_order()
        MicrotechOrderSyncWorkflow.objects.create(order=order, status=MicrotechOrderSyncWorkflow.Status.WAITING)
        with self.assertRaises(IntegrityError):
            MicrotechOrderSyncWorkflow.objects.create(order=order, status=MicrotechOrderSyncWorkflow.Status.PENDING)
```

Hinweis Step 3: Es existiert bereits Order-Test-Infrastruktur. Falls kein `make_order`-Helper vorhanden ist, ersetze den Import durch das in `orders/tests.py` genutzte Muster zum Anlegen einer `Order` (dort nachsehen und dieselbe minimale Objekt-Erzeugung verwenden). `make_order` steht hier stellvertretend für „eine gültige Order-Instanz erzeugen".

- [ ] **Step 2: Test ausführen, Fehlschlag verifizieren**

Run: `python manage.py test orders.test_order_sync_workflow -v 2`
Expected: FAIL (`ImportError` / Modell existiert nicht)

- [ ] **Step 3: Modell implementieren**

In `orders/models.py` (Imports oben: `from core.models import BaseModel` prüfen/ergänzen; `from django.db import models`; `from django.utils.translation import gettext_lazy as _`):

```python
class MicrotechOrderSyncWorkflow(BaseModel):
    class Status(models.TextChoices):
        PENDING = "pending", _("Wartend")
        RUNNING = "running", _("Laeuft")
        WAITING = "waiting", _("Wartet auf Microtech")
        FAILED = "failed", _("Fehlgeschlagen")
        SUCCEEDED = "succeeded", _("Erfolgreich")

    ACTIVE_STATUSES = (Status.PENDING, Status.RUNNING, Status.WAITING, Status.FAILED)

    order = models.ForeignKey(
        "orders.Order",
        on_delete=models.CASCADE,
        related_name="microtech_sync_workflows",
        verbose_name=_("Bestellung"),
    )
    status = models.CharField(
        max_length=16, choices=Status.choices, default=Status.PENDING, db_index=True, verbose_name=_("Status")
    )
    current_step = models.CharField(max_length=64, blank=True, default="", verbose_name=_("Aktueller Schritt"))
    state = models.JSONField(blank=True, default=dict, verbose_name=_("Workflow-Zustand"))
    current_job = models.ForeignKey(
        "microtech.MicrotechGraphQLJob",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        verbose_name=_("Aktueller Job"),
    )
    step_log = models.JSONField(blank=True, default=list, verbose_name=_("Schritt-Protokoll"))
    error_message = models.TextField(blank=True, default="", verbose_name=_("Fehler"))

    class Meta:
        verbose_name = _("Microtech Bestell-Sync Workflow")
        verbose_name_plural = _("Microtech Bestell-Sync Workflows")
        ordering = ("-created_at",)
        constraints = [
            models.UniqueConstraint(
                fields=("order",),
                condition=models.Q(status__in=("pending", "running", "waiting", "failed")),
                name="unique_active_order_sync_workflow",
            )
        ]

    def __str__(self) -> str:
        return f"OrderSync #{self.pk} order={self.order_id} [{self.get_status_display()}]"

    @property
    def is_active(self) -> bool:
        return self.status in self.ACTIVE_STATUSES
```

- [ ] **Step 4: Migration erzeugen + Tests ausführen**

Run:
```bash
python manage.py makemigrations orders
python manage.py test orders.test_order_sync_workflow -v 2
```
Expected: Migration erstellt; 2 Tests PASS.

- [ ] **Step 5: Commit**

```bash
git add orders/models.py orders/migrations/ orders/test_order_sync_workflow.py
git commit -m "feat(orders): MicrotechOrderSyncWorkflow-Modell mit aktivem Eindeutigkeits-Constraint"
```

---

### Task 4: `OrderSyncWorkflowService` — Step-Registry + `next_step`-Resolver

**Files:**
- Create: `orders/services/order_sync_workflow.py`
- Modify: `orders/services/__init__.py`
- Test: `orders/test_order_sync_workflow.py` (erweitern)

**Interfaces:**
- Consumes: `MicrotechOrderSyncWorkflow`, `Order`, `Address`.
- Produces:
  - Modulkonstante `CONTINUATION_NAME = "microtech_order_sync_advance"`.
  - `OrderSyncWorkflowService.STEP_ORDER: tuple[str, ...]` (die 10 Keys in Reihenfolge).
  - `OrderSyncWorkflowService.next_step(self, workflow) -> str | None` — nächster ausstehender Step-Key aus `state`, oder `None` wenn fertig.
  - Helfer `_resolve_addresses(self, order) -> tuple[Address, Address]` (shipping, billing) analog `CustomerUpsertMicrotechService.upsert_customer:172-176`.
  - `_is_step_applicable(self, workflow, step) -> bool` — Branch-Logik (billing==shipping, is_new, erp_order_id vorhanden).

Der Resolver arbeitet zustandsbasiert: ein Step gilt als „erledigt", wenn im `step_log` ein Eintrag `{"step": key, "status": "completed"}` existiert. `next_step` liefert den ersten Step aus `STEP_ORDER`, der anwendbar (`_is_step_applicable`) und nicht erledigt ist.

- [ ] **Step 1: Failing tests schreiben** (an `test_order_sync_workflow.py` anhängen)

```python
from orders.services.order_sync_workflow import OrderSyncWorkflowService
from orders.models import MicrotechOrderSyncWorkflow


class NextStepResolverTest(TestCase):
    def _wf(self, *, state=None, completed=None):
        order = make_order()
        wf = MicrotechOrderSyncWorkflow.objects.create(
            order=order,
            state=state or {},
            step_log=[{"step": s, "status": "completed"} for s in (completed or [])],
        )
        return wf

    def test_first_step_is_probe_customer(self):
        wf = self._wf()
        self.assertEqual(OrderSyncWorkflowService().next_step(wf), "probe_customer")

    def test_skips_billing_when_same_as_shipping(self):
        wf = self._wf(
            state={"billing_same_as_shipping": True, "is_new_customer": False},
            completed=["probe_customer", "write_customer", "shipping_address", "shipping_contact"],
        )
        self.assertEqual(OrderSyncWorkflowService().next_step(wf), "set_default_addresses")

    def test_writeback_only_for_new_customer(self):
        wf = self._wf(
            state={"billing_same_as_shipping": True, "is_new_customer": False, "erp_order_id": ""},
            completed=["probe_customer", "write_customer", "shipping_address", "shipping_contact", "set_default_addresses"],
        )
        # Neukunde False -> writeback uebersprungen -> naechster ist write_vorgang (kein erp_order_id -> kein probe_vorgang)
        self.assertEqual(OrderSyncWorkflowService().next_step(wf), "write_vorgang")

    def test_all_done_returns_none(self):
        wf = self._wf(
            state={"billing_same_as_shipping": True, "is_new_customer": False, "erp_order_id": ""},
            completed=["probe_customer", "write_customer", "shipping_address", "shipping_contact", "set_default_addresses", "write_vorgang"],
        )
        self.assertIsNone(OrderSyncWorkflowService().next_step(wf))
```

- [ ] **Step 2: Test ausführen, Fehlschlag verifizieren**

Run: `python manage.py test orders.test_order_sync_workflow.NextStepResolverTest -v 2`
Expected: FAIL (`ModuleNotFoundError: orders.services.order_sync_workflow`)

- [ ] **Step 3: Implementierung**

`orders/services/order_sync_workflow.py`:

```python
from __future__ import annotations

from typing import Any

from customer.models import Address
from core.services import BaseService
from orders.models import MicrotechOrderSyncWorkflow

CONTINUATION_NAME = "microtech_order_sync_advance"


class OrderSyncWorkflowService(BaseService):
    model = MicrotechOrderSyncWorkflow

    STEP_ORDER = (
        "probe_customer",
        "write_customer",
        "shipping_address",
        "shipping_contact",
        "billing_address",
        "billing_contact",
        "set_default_addresses",
        "writeback_adrnr",
        "probe_vorgang",
        "write_vorgang",
    )

    def _completed_steps(self, workflow: MicrotechOrderSyncWorkflow) -> set[str]:
        return {
            str(entry.get("step"))
            for entry in (workflow.step_log or [])
            if entry.get("status") == "completed"
        }

    def _is_step_applicable(self, workflow: MicrotechOrderSyncWorkflow, step: str) -> bool:
        state = workflow.state or {}
        if step in ("billing_address", "billing_contact"):
            return not bool(state.get("billing_same_as_shipping"))
        if step == "writeback_adrnr":
            return bool(state.get("is_new_customer"))
        if step == "probe_vorgang":
            return bool(str(state.get("erp_order_id") or "").strip())
        return True

    def next_step(self, workflow: MicrotechOrderSyncWorkflow) -> str | None:
        done = self._completed_steps(workflow)
        for step in self.STEP_ORDER:
            if step in done:
                continue
            if self._is_step_applicable(workflow, step):
                return step
        return None

    def _resolve_addresses(self, order) -> tuple[Address, Address]:
        # Order traegt shipping_address/billing_address selbst (orders/tests.py:56).
        shipping = order.shipping_address or order.customer.shipping_address
        if shipping is None:
            raise ValueError("Order hat keine Lieferadresse zum Synchronisieren.")
        billing = order.billing_address or shipping
        return shipping, billing
```

Hinweis: `order.shipping_address`/`order.billing_address` sind die für DIESE Bestellung maßgeblichen Adressen (FKs auf dem Order-Modell). Import `from customer.models import Address` verwenden.

In `orders/services/__init__.py` ergänzen:

```python
from .order_sync_workflow import OrderSyncWorkflowService, CONTINUATION_NAME
```
und in `__all__` aufnehmen: `"OrderSyncWorkflowService"`, `"CONTINUATION_NAME"`.

- [ ] **Step 4: Test ausführen, Erfolg verifizieren**

Run: `python manage.py test orders.test_order_sync_workflow.NextStepResolverTest -v 2`
Expected: PASS (4 Tests)

- [ ] **Step 5: Commit**

```bash
git add orders/services/order_sync_workflow.py orders/services/__init__.py orders/test_order_sync_workflow.py
git commit -m "feat(orders): OrderSyncWorkflowService mit zustandsbasiertem next_step-Resolver"
```

---

### Task 5: Step-Submit + `advance()`-Handler

**Files:**
- Modify: `orders/services/order_sync_workflow.py`
- Test: `orders/test_order_sync_workflow.py` (erweitern)

**Interfaces:**
- Consumes: `MicrotechJobSentinelService.submit_wrapper_job` (Task 2), Client-`submit_*` (Task 1), `MicrotechGraphQLJob`.
- Produces:
  - `submit_step(self, workflow, step) -> MicrotechGraphQLJob` — baut Payload + Client-Submit-Lambda, ruft `submit_wrapper_job`, setzt `workflow.current_step`/`current_job`/`status=WAITING`.
  - `advance(self, job) -> None` — Continuation-Handler: lädt Workflow aus `job.context["workflow_id"]` unter `select_for_update`, prüft `job.context["step"] == workflow.current_step`, wendet Ergebnis an (`_apply_result`), loggt `completed`, treibt via `_advance(workflow)` weiter (nächster Step submitten, lokale Steps inline, sonst `SUCCEEDED`).
  - `_apply_result(self, workflow, step, result_payload) -> None` — mappt Job-Ergebnis in `state`.
  - `_advance(self, workflow) -> None` — Schleife: solange nächster Step lokal ist, inline ausführen; sonst submitten; wenn keiner → `SUCCEEDED`.

- [ ] **Step 1: Failing tests schreiben** (anhängen)

```python
from unittest.mock import patch, MagicMock

from microtech.models import MicrotechGraphQLJob


class AdvanceHandlerTest(TestCase):
    def _job(self, workflow, step, result):
        return MicrotechGraphQLJob.objects.create(
            kind=MicrotechGraphQLJob.Kind.CUSTOMER_UPSERT,
            operation="op",
            status=MicrotechGraphQLJob.Status.SUCCEEDED,
            context={"workflow_id": workflow.id, "step": step},
            result_payload=result,
            continuation="microtech_order_sync_advance",
        )

    @patch("orders.services.order_sync_workflow.OrderSyncWorkflowService.submit_step")
    def test_advance_probe_customer_found_marks_existing(self, mock_submit):
        wf = MicrotechOrderSyncWorkflow.objects.create(
            order=make_order(), status=MicrotechOrderSyncWorkflow.Status.WAITING, current_step="probe_customer"
        )
        job = self._job(wf, "probe_customer", {"customer": {"customerNumber": "100012", "erpAddressNumber": 100012}})

        OrderSyncWorkflowService().advance(job)

        wf.refresh_from_db()
        self.assertFalse(wf.state["is_new_customer"])
        self.assertEqual(wf.state["address_number"], 100012)
        self.assertIn({"step": "probe_customer", "status": "completed"}, [
            {"step": e["step"], "status": e["status"]} for e in wf.step_log
        ])
        mock_submit.assert_called_once()  # naechster Step (write_customer) submitted

    @patch("orders.services.order_sync_workflow.OrderSyncWorkflowService.submit_step")
    def test_advance_ignores_stale_step(self, mock_submit):
        wf = MicrotechOrderSyncWorkflow.objects.create(
            order=make_order(), status=MicrotechOrderSyncWorkflow.Status.WAITING, current_step="write_customer"
        )
        job = self._job(wf, "probe_customer", {"customer": None})

        OrderSyncWorkflowService().advance(job)

        mock_submit.assert_not_called()
```

- [ ] **Step 2: Test ausführen, Fehlschlag verifizieren**

Run: `python manage.py test orders.test_order_sync_workflow.AdvanceHandlerTest -v 2`
Expected: FAIL (`AttributeError: ... 'advance'` / `'submit_step'`)

- [ ] **Step 3: Implementierung** (an `OrderSyncWorkflowService` anhängen)

```python
    # --- Ergebnis-Anwendung -------------------------------------------------

    def _apply_result(self, workflow: MicrotechOrderSyncWorkflow, step: str, result: dict[str, Any]) -> None:
        from customer.services.customer_upsert_microtech import _to_int, _to_str

        state = dict(workflow.state or {})
        if step == "probe_customer":
            customer = (result or {}).get("customer") or {}
            found = bool(customer.get("customerNumber"))
            state["is_new_customer"] = not found
            if found:
                state["address_number"] = _to_int(customer.get("erpAddressNumber")) or state.get("address_number")
        elif step == "write_customer":
            customer = (result or {}).get("customer") or {}
            state["address_number"] = _to_int(customer.get("erpAddressNumber")) or state.get("address_number")
        elif step in ("shipping_address", "billing_address"):
            postal = (result or {}).get("postalAddress") or {}
            sub = _to_int(postal.get("addressSubNumber"))
            key = "shipping_ans_nr" if step == "shipping_address" else "billing_ans_nr"
            if sub:
                state[key] = sub
            if step == "shipping_address" and state.get("billing_same_as_shipping"):
                state["billing_ans_nr"] = state.get("shipping_ans_nr")
        elif step == "write_vorgang":
            vorgang = (result or {}).get("vorgang") or {}
            beleg = _to_str(vorgang.get("belegNr")) or state.get("beleg_nr", "")
            state["beleg_nr"] = beleg
        workflow.state = state

    # --- Continuation -------------------------------------------------------

    def advance(self, job) -> None:
        from django.db import transaction

        workflow_id = int((job.context or {}).get("workflow_id") or 0)
        step = str((job.context or {}).get("step") or "")
        if not workflow_id or not step:
            return
        with transaction.atomic():
            workflow = (
                MicrotechOrderSyncWorkflow.objects.select_for_update()
                .filter(pk=workflow_id)
                .first()
            )
            if workflow is None or workflow.current_step != step:
                return
            self._apply_result(workflow, step, job.result_payload or {})
            self._log_step(workflow, step, "completed")
            workflow.error_message = ""
            workflow.save(update_fields=("state", "step_log", "error_message", "updated_at"))
        self._advance(workflow)

    def _advance(self, workflow: MicrotechOrderSyncWorkflow) -> None:
        while True:
            step = self.next_step(workflow)
            if step is None:
                workflow.status = MicrotechOrderSyncWorkflow.Status.SUCCEEDED
                workflow.current_step = ""
                workflow.current_job = None
                workflow.save(update_fields=("status", "current_step", "current_job", "updated_at"))
                return
            if step == "writeback_adrnr":
                self._run_local_step(workflow, step)
                self._log_step(workflow, step, "completed")
                workflow.save(update_fields=("state", "step_log", "updated_at"))
                continue
            self.submit_step(workflow, step)
            return

    def _log_step(self, workflow: MicrotechOrderSyncWorkflow, step: str, status: str, error: str = "") -> None:
        from django.utils import timezone

        log = list(workflow.step_log or [])
        log.append({"step": step, "status": status, "at": timezone.now().isoformat(), "error": error})
        workflow.step_log = log
```

`submit_step` und `_run_local_step` folgen in Task 6/7. Für die Tests dieser Task ist `submit_step` gepatcht; `_run_local_step` wird hier noch nicht aufgerufen (Neukunde-Branch erst mit vollem Flow getestet).

- [ ] **Step 4: Test ausführen, Erfolg verifizieren**

Run: `python manage.py test orders.test_order_sync_workflow.AdvanceHandlerTest -v 2`
Expected: PASS (2 Tests)

- [ ] **Step 5: Commit**

```bash
git add orders/services/order_sync_workflow.py orders/test_order_sync_workflow.py
git commit -m "feat(orders): advance-Handler und Ergebnis-Anwendung fuer Sync-Kette"
```

---

### Task 6: `submit_step` (Customer-Steps) + `start_for_order`

**Files:**
- Modify: `orders/services/order_sync_workflow.py`
- Test: `orders/test_order_sync_workflow.py` (erweitern)

**Interfaces:**
- Consumes: `CustomerUpsertMicrotechService` (Payload-Builder + Identity-Persistenz), `MicrotechJobSentinelService.submit_wrapper_job`, `MicrotechGraphQLClientService.submit_*`.
- Produces:
  - `submit_step(self, workflow, step) -> MicrotechGraphQLJob`
  - `start_for_order(self, order) -> MicrotechOrderSyncWorkflow` — Doppelstart-Guard (aktiver Workflow → `ValueError`), Workflow anlegen, `billing_same_as_shipping`/`erp_order_id`/`erp_nr` in `state` initialisieren, ersten Step submitten.
  - `_build_customer_service() -> CustomerUpsertMicrotechService` (Instanz für Builder-Reuse).

`submit_step` mappt Step → (Kind, Operation, Client-Submit-Lambda, request_payload). Es baut die Payloads über die vorhandenen Builder und wählt create/update anhand `state`/lokal persistierter Identität (`address.erp_ans_nr`, `address.erp_asp_nr`), exakt wie `_upsert_postal_address_graphql:289` / `_upsert_contact_person_graphql:320`.

- [ ] **Step 1: Failing tests schreiben** (anhängen)

```python
class StartAndSubmitTest(TestCase):
    @patch("orders.services.order_sync_workflow.MicrotechGraphQLClientService")
    @patch("orders.services.order_sync_workflow.MicrotechJobSentinelService.submit_wrapper_job")
    def test_start_creates_workflow_and_submits_probe(self, mock_submit, mock_client):
        job = MagicMock(pk=1)
        mock_submit.return_value = job
        order = make_order()

        wf = OrderSyncWorkflowService().start_for_order(order)

        wf.refresh_from_db()
        self.assertEqual(wf.current_step, "probe_customer")
        self.assertEqual(wf.status, MicrotechOrderSyncWorkflow.Status.WAITING)
        self.assertEqual(wf.state["erp_nr"], order.customer.erp_nr)
        called = mock_submit.call_args.kwargs
        self.assertEqual(called["kind"], MicrotechGraphQLJob.Kind.CUSTOMER_READ)
        self.assertEqual(called["context"]["step"], "probe_customer")
        self.assertEqual(called["continuation"], "microtech_order_sync_advance")

    def test_start_rejects_second_active_workflow(self):
        order = make_order()
        MicrotechOrderSyncWorkflow.objects.create(order=order, status=MicrotechOrderSyncWorkflow.Status.WAITING)
        with self.assertRaises(ValueError):
            OrderSyncWorkflowService().start_for_order(order)
```

- [ ] **Step 2: Test ausführen, Fehlschlag verifizieren**

Run: `python manage.py test orders.test_order_sync_workflow.StartAndSubmitTest -v 2`
Expected: FAIL (`AttributeError: ... 'start_for_order'`)

- [ ] **Step 3: Implementierung** (anhängen; Imports oben in der Datei ergänzen)

```python
from customer.services.customer_upsert_microtech import CustomerUpsertMicrotechService, _to_int
from microtech.models import MicrotechGraphQLJob
from microtech.services import MicrotechJobSentinelService
from microtech.services.graphql_client import MicrotechGraphQLClientService
```

```python
    def start_for_order(self, order) -> MicrotechOrderSyncWorkflow:
        active = MicrotechOrderSyncWorkflow.objects.filter(
            order=order, status__in=MicrotechOrderSyncWorkflow.ACTIVE_STATUSES
        ).first()
        if active is not None:
            raise ValueError(f"Fuer Bestellung {order.pk} laeuft bereits ein Sync-Workflow (#{active.pk}).")

        shipping, billing = self._resolve_addresses(order)
        erp_nr = (order.customer.erp_nr or "").strip()
        if not erp_nr:
            raise ValueError("Order-Kunde hat keine erp_nr; GraphQL-Upsert erfordert eine Adressnummer.")
        workflow = MicrotechOrderSyncWorkflow.objects.create(
            order=order,
            status=MicrotechOrderSyncWorkflow.Status.RUNNING,
            state={
                "erp_nr": erp_nr,
                "address_number": _to_int(erp_nr),
                "billing_same_as_shipping": billing.pk == shipping.pk,
                "erp_order_id": (order.erp_order_id or "").strip(),
            },
        )
        self._advance(workflow)
        return workflow

    def submit_step(self, workflow: MicrotechOrderSyncWorkflow, step: str) -> MicrotechGraphQLJob:
        order = workflow.order
        shipping, billing = self._resolve_addresses(order)
        state = workflow.state or {}
        address_number = int(state.get("address_number") or 0)
        cust = CustomerUpsertMicrotechService()
        client = MicrotechGraphQLClientService()

        kind = MicrotechGraphQLJob.Kind.CUSTOMER_UPSERT
        if step == "probe_customer":
            kind = MicrotechGraphQLJob.Kind.CUSTOMER_READ
            operation = "requestCustomer"
            submit = lambda: client.submit_request_customer(state["erp_nr"])
            payload = {"customerNumber": state["erp_nr"]}
        elif step == "write_customer":
            operation = "createCustomer" if state.get("is_new_customer") else "updateCustomer"
            input_data = cust._build_customer_input(customer=order.customer, address=shipping)
            if state.get("is_new_customer"):
                submit = lambda: client.submit_create_customer(state["erp_nr"], input_data)
            else:
                submit = lambda: client.submit_update_customer(state["erp_nr"], input_data)
            payload = {"customerNumber": state["erp_nr"], "input": input_data}
        elif step in ("shipping_address", "billing_address"):
            address = shipping if step == "shipping_address" else billing
            is_shipping = step == "shipping_address"
            input_data = cust._build_postal_address_input(
                address=address, is_shipping=is_shipping, is_invoice=not is_shipping or state.get("billing_same_as_shipping", False),
                na1_mode="auto", na1_static_value="",
            )
            sub = _to_int(address.erp_ans_nr)
            operation = "updatePostalAddress" if sub else "createPostalAddress"
            if sub:
                submit = lambda: client.submit_update_postal_address(address_number, sub, input_data)
            else:
                submit = lambda: client.submit_create_postal_address(address_number, input_data)
            payload = {"addressNumber": address_number, "input": input_data}
        elif step in ("shipping_contact", "billing_contact"):
            address = shipping if step == "shipping_contact" else billing
            sub_key = "shipping_ans_nr" if step == "shipping_contact" else "billing_ans_nr"
            sub = int(state.get(sub_key) or 0)
            input_data = cust._build_contact_person_input(address=address)
            contact_number = _to_int(address.erp_asp_nr)
            operation = "updateContactPerson" if contact_number else "createContactPerson"
            if contact_number:
                submit = lambda: client.submit_update_contact_person(address_number, sub, contact_number, input_data)
            else:
                submit = lambda: client.submit_create_contact_person(address_number, sub, input_data)
            payload = {"addressNumber": address_number, "addressSubNumber": sub, "input": input_data}
        elif step == "set_default_addresses":
            operation = "updateCustomer"
            input_data = {
                "defaultShippingAddressNumber": int(state.get("shipping_ans_nr") or 0),
                "defaultBillingAddressNumber": int(state.get("billing_ans_nr") or state.get("shipping_ans_nr") or 0),
            }
            submit = lambda: client.submit_update_customer(state["erp_nr"], input_data)
            payload = {"customerNumber": state["erp_nr"], "input": input_data}
        else:
            return self._submit_order_step(workflow, step)  # Task 8

        job = MicrotechJobSentinelService().submit_wrapper_job(
            kind=kind,
            operation=operation,
            submit=submit,
            request_payload=payload,
            context={"workflow_id": workflow.pk, "step": step},
            continuation=CONTINUATION_NAME,
            next_step=f"Microtech {operation} ({step}).",
        )
        MicrotechOrderSyncWorkflow.objects.filter(pk=workflow.pk).update(
            status=MicrotechOrderSyncWorkflow.Status.WAITING,
            current_step=step,
            current_job=job,
        )
        workflow.refresh_from_db()
        return job
```

Hinweis: `is_invoice`-Logik für Anschriften an `_upsert_customer_graphql:229-248` angleichen (shipping ist invoice, wenn billing==shipping; billing ist immer invoice). Bei Bedarf dort exakt nachziehen. Feldnamen `erp_ans_nr`/`erp_asp_nr` aus dem `Address`-Modell verifizieren (siehe `_upsert_postal_address_graphql`).

- [ ] **Step 4: Test ausführen, Erfolg verifizieren**

Run: `python manage.py test orders.test_order_sync_workflow.StartAndSubmitTest -v 2`
Expected: PASS (2 Tests)

- [ ] **Step 5: Commit**

```bash
git add orders/services/order_sync_workflow.py orders/test_order_sync_workflow.py
git commit -m "feat(orders): submit_step fuer Customer-Steps und start_for_order mit Doppelstart-Guard"
```

---

### Task 7: Lokaler Step `writeback_adrnr` (AdrNr → Shopware)

**Files:**
- Modify: `orders/services/order_sync_workflow.py`
- Test: `orders/test_order_sync_workflow.py` (erweitern)

**Interfaces:**
- Consumes: `CustomerUpsertMicrotechService._sync_new_customer_number_to_shopware:405`.
- Produces: `_run_local_step(self, workflow, step) -> None`.

- [ ] **Step 1: Failing test schreiben** (anhängen)

```python
class LocalStepTest(TestCase):
    @patch("customer.services.customer_upsert_microtech.CustomerUpsertMicrotechService._sync_new_customer_number_to_shopware")
    def test_writeback_adrnr_calls_shopware_sync(self, mock_sync):
        mock_sync.return_value = True
        order = make_order()
        wf = MicrotechOrderSyncWorkflow.objects.create(
            order=order, status=MicrotechOrderSyncWorkflow.Status.WAITING,
            state={"erp_nr": order.customer.erp_nr, "is_new_customer": True},
        )

        OrderSyncWorkflowService()._run_local_step(wf, "writeback_adrnr")

        mock_sync.assert_called_once()
        self.assertEqual(mock_sync.call_args.kwargs["erp_nr"], order.customer.erp_nr)
```

- [ ] **Step 2: Test ausführen, Fehlschlag verifizieren**

Run: `python manage.py test orders.test_order_sync_workflow.LocalStepTest -v 2`
Expected: FAIL (`AttributeError: ... '_run_local_step'`)

- [ ] **Step 3: Implementierung** (anhängen)

```python
    def _run_local_step(self, workflow: MicrotechOrderSyncWorkflow, step: str) -> None:
        if step == "writeback_adrnr":
            order = workflow.order
            CustomerUpsertMicrotechService()._sync_new_customer_number_to_shopware(
                customer=order.customer, erp_nr=(workflow.state or {}).get("erp_nr", ""),
            )
            return
        raise ValueError(f"Unbekannter lokaler Step: {step}")
```

- [ ] **Step 4: Test ausführen, Erfolg verifizieren**

Run: `python manage.py test orders.test_order_sync_workflow.LocalStepTest -v 2`
Expected: PASS (1 Test)

- [ ] **Step 5: Commit**

```bash
git add orders/services/order_sync_workflow.py orders/test_order_sync_workflow.py
git commit -m "feat(orders): lokaler writeback_adrnr-Step schreibt AdrNr nach Shopware"
```

---

### Task 8: Order-Steps (`probe_vorgang`, `write_vorgang`)

**Files:**
- Modify: `orders/services/order_sync_workflow.py`
- Test: `orders/test_order_sync_workflow.py` (erweitern)

**Interfaces:**
- Consumes: `OrderUpsertMicrotechService._build_graphql_positions`, `_load_order_defaults`, `_coerce_positive_int`, `OrderRuleResolverService`; `MicrotechGraphQLClientService.submit_request_vorgang/submit_create_vorgang/submit_update_vorgang`.
- Produces: `_submit_order_step(self, workflow, step) -> MicrotechGraphQLJob`.

- [ ] **Step 1: Failing test schreiben** (anhängen)

```python
class OrderStepTest(TestCase):
    @patch("orders.services.order_sync_workflow.MicrotechGraphQLClientService")
    @patch("orders.services.order_sync_workflow.MicrotechJobSentinelService.submit_wrapper_job")
    def test_write_vorgang_creates_when_no_beleg(self, mock_submit, mock_client_cls):
        mock_submit.return_value = MagicMock(pk=5)
        client = mock_client_cls.return_value
        order = make_order()
        wf = MicrotechOrderSyncWorkflow.objects.create(
            order=order, status=MicrotechOrderSyncWorkflow.Status.WAITING,
            state={"erp_nr": order.customer.erp_nr, "beleg_nr": ""},
        )

        with patch("orders.services.order_upsert_microtech.OrderUpsertMicrotechService._build_graphql_positions", return_value=([], MagicMock())):
            OrderSyncWorkflowService()._submit_order_step(wf, "write_vorgang")

        called = mock_submit.call_args.kwargs
        self.assertEqual(called["kind"], MicrotechGraphQLJob.Kind.ORDER_UPSERT)
        self.assertEqual(called["operation"], "createVorgang")
```

- [ ] **Step 2: Test ausführen, Fehlschlag verifizieren**

Run: `python manage.py test orders.test_order_sync_workflow.OrderStepTest -v 2`
Expected: FAIL (`AttributeError: ... '_submit_order_step'`)

- [ ] **Step 3: Implementierung** (anhängen; Imports ergänzen)

```python
from orders.services.order_upsert_microtech import OrderUpsertMicrotechService
from orders.services.order_rule_resolver import OrderRuleResolverService
```

```python
    def _submit_order_step(self, workflow: MicrotechOrderSyncWorkflow, step: str) -> MicrotechGraphQLJob:
        order = workflow.order
        state = workflow.state or {}
        client = MicrotechGraphQLClientService()

        if step == "probe_vorgang":
            beleg = (state.get("erp_order_id") or "").strip()
            operation = "requestVorgang"
            submit = lambda: client.submit_request_vorgang(beleg)
            payload = {"belegNr": beleg}
            kind = MicrotechGraphQLJob.Kind.ORDER_READ
        elif step == "write_vorgang":
            upsert = OrderUpsertMicrotechService()
            resolved_rule = OrderRuleResolverService().resolve_for_order(order=order)
            positions, _rule_debug = upsert._build_graphql_positions(order=order, resolved_rule=resolved_rule, client=client)
            defaults = upsert._load_order_defaults()
            order_type_number = upsert._coerce_positive_int(resolved_rule.vorgangsart_id, defaults.order_type_number)
            input_data = {
                "orderNumber": (order.order_number or "").strip() or (order.api_id or "").strip(),
                "description": order.description or f"Shopware Bestellung {order.order_number}",
                "currency": "EUR",
                "positions": positions,
            }
            beleg = (state.get("beleg_nr") or "").strip()
            kind = MicrotechGraphQLJob.Kind.ORDER_UPSERT
            if beleg:
                operation = "updateVorgang"
                submit = lambda: client.submit_update_vorgang(beleg, input_data)
                payload = {"belegNr": beleg, "input": input_data}
            else:
                operation = "createVorgang"
                create_input = {**input_data, "vorgangArt": order_type_number, "customerNumber": order.customer.erp_nr}
                submit = lambda: client.submit_create_vorgang(create_input)
                payload = {"input": create_input}
        else:
            raise ValueError(f"Unbekannter Order-Step: {step}")

        job = MicrotechJobSentinelService().submit_wrapper_job(
            kind=kind, operation=operation, submit=submit, request_payload=payload,
            context={"workflow_id": workflow.pk, "step": step},
            continuation=CONTINUATION_NAME, next_step=f"Microtech {operation} ({step}).",
        )
        MicrotechOrderSyncWorkflow.objects.filter(pk=workflow.pk).update(
            status=MicrotechOrderSyncWorkflow.Status.WAITING, current_step=step, current_job=job,
        )
        workflow.refresh_from_db()
        return job
```

Zusätzlich in `_apply_result` den `probe_vorgang`-Fall ergänzen (nach dem `write_vorgang`-Zweig):

```python
        elif step == "probe_vorgang":
            vorgang = (result or {}).get("vorgang") or {}
            beleg = _to_str(vorgang.get("belegNr"))
            if beleg:
                state["beleg_nr"] = beleg
```

Und `write_vorgang`-Persistenz: nach erfolgreichem `write_vorgang` in `advance` (bzw. in `_apply_result`) `order.erp_order_id` persistieren:

```python
        elif step == "write_vorgang":
            vorgang = (result or {}).get("vorgang") or {}
            beleg = _to_str(vorgang.get("belegNr")) or state.get("beleg_nr", "")
            state["beleg_nr"] = beleg
            if beleg:
                OrderUpsertMicrotechService()._persist_erp_order_id(order=workflow.order, erp_order_id=beleg)
```

- [ ] **Step 4: Test ausführen, Erfolg verifizieren**

Run: `python manage.py test orders.test_order_sync_workflow.OrderStepTest -v 2`
Expected: PASS (1 Test)

- [ ] **Step 5: Commit**

```bash
git add orders/services/order_sync_workflow.py orders/test_order_sync_workflow.py
git commit -m "feat(orders): Order-Steps probe_vorgang/write_vorgang in der Sync-Kette"
```

---

### Task 9: Fehler-Reconcile + Probe-Branch

**Files:**
- Modify: `orders/services/order_sync_workflow.py`
- Test: `orders/test_order_sync_workflow.py` (erweitern)

**Interfaces:**
- Consumes: `MicrotechGraphQLJob.is_terminal`, `.Status`.
- Produces: `reconcile_failures(self) -> int` — für jeden `WAITING`-Workflow mit terminalem `current_job`:
  - Job `SUCCEEDED`: keine Aktion (advance läuft separat).
  - Job `FAILED/CANCELLED` **und** `current_step in ("probe_customer","probe_vorgang")`: als „nicht gefunden" behandeln → `_apply_probe_not_found(workflow, step)` (setzt `is_new_customer=True` bzw. lässt `beleg_nr` leer), Step als `completed` loggen, `_advance` weiter.
  - Job `FAILED/CANCELLED` sonst: Workflow → `FAILED`, `error_message` aus Job, `step_log`-Eintrag `failed`.
  Rückgabe: Anzahl geänderter Workflows.

- [ ] **Step 1: Failing tests schreiben** (anhängen)

```python
class ReconcileTest(TestCase):
    def _waiting_wf(self, step, job_status, error=""):
        order = make_order()
        job = MicrotechGraphQLJob.objects.create(
            kind=MicrotechGraphQLJob.Kind.CUSTOMER_UPSERT, operation="op",
            status=job_status, error_message=error,
            context={"step": step}, external_job_id=f"ext-{step}-{job_status}",
        )
        wf = MicrotechOrderSyncWorkflow.objects.create(
            order=order, status=MicrotechOrderSyncWorkflow.Status.WAITING,
            current_step=step, current_job=job, state={"erp_nr": order.customer.erp_nr},
        )
        return wf

    @patch("orders.services.order_sync_workflow.OrderSyncWorkflowService.submit_step")
    def test_failed_write_step_marks_workflow_failed(self, mock_submit):
        wf = self._waiting_wf("write_customer", MicrotechGraphQLJob.Status.FAILED, error="boom")
        changed = OrderSyncWorkflowService().reconcile_failures()
        wf.refresh_from_db()
        self.assertEqual(changed, 1)
        self.assertEqual(wf.status, MicrotechOrderSyncWorkflow.Status.FAILED)
        self.assertIn("boom", wf.error_message)

    @patch("orders.services.order_sync_workflow.OrderSyncWorkflowService.submit_step")
    def test_failed_probe_customer_treated_as_new(self, mock_submit):
        wf = self._waiting_wf("probe_customer", MicrotechGraphQLJob.Status.FAILED, error="not found")
        OrderSyncWorkflowService().reconcile_failures()
        wf.refresh_from_db()
        self.assertTrue(wf.state["is_new_customer"])
        mock_submit.assert_called_once()  # naechster Step submitted
```

- [ ] **Step 2: Test ausführen, Fehlschlag verifizieren**

Run: `python manage.py test orders.test_order_sync_workflow.ReconcileTest -v 2`
Expected: FAIL (`AttributeError: ... 'reconcile_failures'`)

- [ ] **Step 3: Implementierung** (anhängen)

```python
    def _apply_probe_not_found(self, workflow: MicrotechOrderSyncWorkflow, step: str) -> None:
        state = dict(workflow.state or {})
        if step == "probe_customer":
            state["is_new_customer"] = True
        workflow.state = state

    def reconcile_failures(self) -> int:
        from django.db import transaction

        changed = 0
        waiting = list(
            MicrotechOrderSyncWorkflow.objects.filter(
                status=MicrotechOrderSyncWorkflow.Status.WAITING, current_job__isnull=False
            ).select_related("current_job")
        )
        for workflow in waiting:
            job = workflow.current_job
            if job is None or not job.is_terminal:
                continue
            if job.status == MicrotechGraphQLJob.Status.SUCCEEDED:
                continue
            step = workflow.current_step
            if step in ("probe_customer", "probe_vorgang"):
                with transaction.atomic():
                    wf = MicrotechOrderSyncWorkflow.objects.select_for_update().get(pk=workflow.pk)
                    self._apply_probe_not_found(wf, step)
                    self._log_step(wf, step, "completed", error="probe-not-found")
                    wf.save(update_fields=("state", "step_log", "updated_at"))
                self._advance(workflow.__class__.objects.get(pk=workflow.pk))
                changed += 1
                continue
            with transaction.atomic():
                wf = MicrotechOrderSyncWorkflow.objects.select_for_update().get(pk=workflow.pk)
                wf.status = MicrotechOrderSyncWorkflow.Status.FAILED
                wf.error_message = job.error_message or "Microtech-Job fehlgeschlagen."
                self._log_step(wf, step, "failed", error=wf.error_message)
                wf.save(update_fields=("status", "error_message", "step_log", "updated_at"))
            changed += 1
        return changed
```

- [ ] **Step 4: Test ausführen, Erfolg verifizieren**

Run: `python manage.py test orders.test_order_sync_workflow.ReconcileTest -v 2`
Expected: PASS (2 Tests)

- [ ] **Step 5: Commit**

```bash
git add orders/services/order_sync_workflow.py orders/test_order_sync_workflow.py
git commit -m "feat(orders): Reconcile fuer fehlgeschlagene Steps und Probe-Branch"
```

---

### Task 10: `resume()`

**Files:**
- Modify: `orders/services/order_sync_workflow.py`
- Test: `orders/test_order_sync_workflow.py` (erweitern)

**Interfaces:**
- Produces: `resume(self, workflow) -> MicrotechGraphQLJob | None` — nur bei `status=FAILED`; setzt `error_message=""`, submittet `current_step` (den fehlgeschlagenen) erneut über `submit_step`/`_submit_order_step`. Bereits `completed` geloggte Steps bleiben unangetastet.

- [ ] **Step 1: Failing test schreiben** (anhängen)

```python
class ResumeTest(TestCase):
    @patch("orders.services.order_sync_workflow.OrderSyncWorkflowService.submit_step")
    def test_resume_resubmits_current_step(self, mock_submit):
        mock_submit.return_value = MagicMock(pk=9)
        order = make_order()
        wf = MicrotechOrderSyncWorkflow.objects.create(
            order=order, status=MicrotechOrderSyncWorkflow.Status.FAILED,
            current_step="shipping_address", error_message="boom",
            state={"erp_nr": order.customer.erp_nr},
        )

        OrderSyncWorkflowService().resume(wf)

        wf.refresh_from_db()
        self.assertEqual(wf.error_message, "")
        mock_submit.assert_called_once_with(wf, "shipping_address")

    def test_resume_noop_when_not_failed(self):
        order = make_order()
        wf = MicrotechOrderSyncWorkflow.objects.create(order=order, status=MicrotechOrderSyncWorkflow.Status.WAITING)
        self.assertIsNone(OrderSyncWorkflowService().resume(wf))
```

- [ ] **Step 2: Test ausführen, Fehlschlag verifizieren**

Run: `python manage.py test orders.test_order_sync_workflow.ResumeTest -v 2`
Expected: FAIL (`AttributeError: ... 'resume'`)

- [ ] **Step 3: Implementierung** (anhängen)

```python
    def resume(self, workflow: MicrotechOrderSyncWorkflow):
        if workflow.status != MicrotechOrderSyncWorkflow.Status.FAILED:
            return None
        step = workflow.current_step
        if not step:
            self._advance(workflow)
            return workflow.current_job
        MicrotechOrderSyncWorkflow.objects.filter(pk=workflow.pk).update(error_message="")
        workflow.refresh_from_db()
        return self.submit_step(workflow, step)
```

- [ ] **Step 4: Test ausführen, Erfolg verifizieren**

Run: `python manage.py test orders.test_order_sync_workflow.ResumeTest -v 2`
Expected: PASS (2 Tests)

- [ ] **Step 5: Commit**

```bash
git add orders/services/order_sync_workflow.py orders/test_order_sync_workflow.py
git commit -m "feat(orders): resume startet fehlgeschlagenen Step neu"
```

---

### Task 11: Continuation-Registrierung + Task-/Beat-Verdrahtung

**Files:**
- Modify: `orders/tasks.py`
- Modify: `microtech/tasks.py`
- Test: `orders/test_tasks_workflow.py` (Create)

**Interfaces:**
- Consumes: `register_continuation` (microtech), `OrderSyncWorkflowService`, `CONTINUATION_NAME`.
- Produces:
  - `orders/tasks.py`: `register_order_sync_continuations()` (registriert `CONTINUATION_NAME` → `OrderSyncWorkflowService().advance`); `@shared_task microtech.reconcile_order_sync_workflows` → `OrderSyncWorkflowService().reconcile_failures()`; Modul-Level-Aufruf `register_order_sync_continuations()`.
  - `microtech/tasks.py`: `process_graphql_job_result` importiert zusätzlich `import orders.tasks  # noqa: F401`; `poll_graphql_jobs` ruft nach dem Poll `orders.tasks.reconcile_order_sync_workflows.run()` (guarded import) — kein neuer Beat-Eintrag nötig, nutzt den bestehenden `microtech.poll_graphql_jobs`-Schedule (DatabaseScheduler).

- [ ] **Step 1: Failing test schreiben**

`orders/test_tasks_workflow.py`:

```python
from unittest.mock import patch

from django.test import SimpleTestCase

from microtech.services.job_sentinel import CONTINUATIONS
from orders.services.order_sync_workflow import CONTINUATION_NAME


class ContinuationRegistrationTest(SimpleTestCase):
    def test_continuation_is_registered_on_import(self):
        import orders.tasks  # noqa: F401
        self.assertIn(CONTINUATION_NAME, CONTINUATIONS)

    @patch("orders.services.order_sync_workflow.OrderSyncWorkflowService.reconcile_failures")
    def test_reconcile_task_delegates(self, mock_reconcile):
        mock_reconcile.return_value = 3
        import orders.tasks as t
        self.assertEqual(t.reconcile_order_sync_workflows.run(), 3)
```

- [ ] **Step 2: Test ausführen, Fehlschlag verifizieren**

Run: `python manage.py test orders.test_tasks_workflow -v 2`
Expected: FAIL (`ImportError` / Continuation nicht registriert)

- [ ] **Step 3: Implementierung**

In `orders/tasks.py` ergänzen:

```python
from celery import shared_task


@shared_task(name="microtech.reconcile_order_sync_workflows")
def reconcile_order_sync_workflows() -> int:
    from orders.services.order_sync_workflow import OrderSyncWorkflowService

    return OrderSyncWorkflowService().reconcile_failures()


def register_order_sync_continuations() -> None:
    from microtech.services import register_continuation
    from orders.services.order_sync_workflow import CONTINUATION_NAME, OrderSyncWorkflowService

    register_continuation(CONTINUATION_NAME, OrderSyncWorkflowService().advance)


register_order_sync_continuations()
```

In `microtech/tasks.py`:
- `process_graphql_job_result`: nach `import products.tasks` ergänzen `import orders.tasks  # noqa: F401 - registers order sync continuation`.
- `poll_graphql_jobs`: nach `poll_due_jobs`-Aufruf ergänzen:

```python
    try:
        import orders.tasks

        orders.tasks.reconcile_order_sync_workflows.run()
    except Exception:  # pragma: no cover - Reconcile darf Poll nicht brechen
        pass
    return result
```

(dabei `result = MicrotechJobSentinelService().poll_due_jobs(limit=limit)` in Variable ziehen.)

- [ ] **Step 4: Test ausführen, Erfolg verifizieren**

Run:
```bash
python manage.py test orders.test_tasks_workflow -v 2
python manage.py test microtech orders customer -v 1
```
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add orders/tasks.py microtech/tasks.py orders/test_tasks_workflow.py
git commit -m "feat(orders): Continuation-Registrierung und Reconcile im Poll-Beat"
```

---

### Task 12: Admin-Trigger, Status-Anzeige, Resume-Action

**Files:**
- Modify: `orders/admin.py`
- Test: manuelle Verifikation (Admin-UI) + `orders/test_admin_workflow.py` (Create, für die Nicht-UI-Logik)

**Interfaces:**
- Consumes: `OrderSyncWorkflowService.start_for_order`, `.resume`, `MicrotechOrderSyncWorkflow`.
- Produces: `_run_microtech_upsert` ruft künftig `OrderSyncWorkflowService().start_for_order(order)` (statt synchronem `upsert_order`); neue `@action` `resume_microtech_sync_detail`; readonly-Methode `microtech_sync_status(self, obj)` für die Detail-/List-Anzeige (zeigt Status + `current_step` + `error_message` des jüngsten Workflows).

- [ ] **Step 1: Failing test schreiben**

`orders/test_admin_workflow.py`:

```python
from unittest.mock import patch

from django.test import TestCase

from orders.admin import OrderAdmin  # tatsaechlichen Klassennamen in orders/admin.py verifizieren
from orders.models import MicrotechOrderSyncWorkflow, Order
from orders.test_order_sync_workflow import make_order


class AdminTriggerTest(TestCase):
    @patch("orders.admin.OrderSyncWorkflowService.start_for_order")
    def test_run_upsert_starts_workflow(self, mock_start):
        order = make_order()
        admin = OrderAdmin(Order, admin_site=None)
        request = type("R", (), {})()
        with patch.object(admin, "get_object", return_value=order), \
             patch.object(admin, "message_user"):
            admin._run_microtech_upsert(request, str(order.pk))
        mock_start.assert_called_once_with(order)
```

Hinweis: Admin-Klassenname und `message_user`/`get_object`-Signaturen in `orders/admin.py` verifizieren; Test ggf. an die reale Klasse anpassen. Falls das Instanziieren des ModelAdmin ohne echtes `admin_site` scheitert, `admin.site` aus `django.contrib.admin` verwenden.

- [ ] **Step 2: Test ausführen, Fehlschlag verifizieren**

Run: `python manage.py test orders.test_admin_workflow -v 2`
Expected: FAIL (ruft noch `upsert_order` synchron).

- [ ] **Step 3: Implementierung**

In `orders/admin.py`:
- Import ergänzen: `from orders.services import OrderSyncWorkflowService` (und `MicrotechOrderSyncWorkflow` aus `orders.models`).
- `_run_microtech_upsert` umbauen: `microtech_connection()`/`upsert_order` ersetzen durch:

```python
        try:
            workflow = OrderSyncWorkflowService().start_for_order(order)
        except Exception as exc:
            self.message_user(request, f"Microtech-Sync konnte nicht gestartet werden: {exc}", level=messages.ERROR)
            return
        self.message_user(
            request,
            f"Microtech-Sync fuer Bestellung {order.order_number} gestartet (Workflow #{workflow.pk}).",
            level=messages.SUCCESS,
        )
```
(Das File-Sink-Logging kann bleiben; die synchrone Ergebnis-/Rule-Debug-Meldung entfällt, da asynchron.)

- Neue Action + Status-Methode:

```python
    @action(description="Microtech-Sync fortsetzen", icon="refresh", variant=ActionVariant.PRIMARY)
    def resume_microtech_sync_detail(self, request, object_id: str):
        order = self.get_object(request, object_id)
        workflow = (
            MicrotechOrderSyncWorkflow.objects.filter(order=order)
            .order_by("-created_at")
            .first()
        )
        if workflow is None or workflow.status != MicrotechOrderSyncWorkflow.Status.FAILED:
            self.message_user(request, "Kein fehlgeschlagener Sync-Workflow zum Fortsetzen.", level=messages.WARNING)
        else:
            OrderSyncWorkflowService().resume(workflow)
            self.message_user(request, f"Workflow #{workflow.pk} bei Schritt '{workflow.current_step}' fortgesetzt.", level=messages.SUCCESS)
        return self._redirect_to_change_page(object_id)

    @admin.display(description="Microtech-Sync")
    def microtech_sync_status(self, obj):
        workflow = obj.microtech_sync_workflows.order_by("-created_at").first()
        if workflow is None:
            return "—"
        text = f"{workflow.get_status_display()}"
        if workflow.current_step:
            text += f" · {workflow.current_step}"
        if workflow.error_message:
            text += f" · {workflow.error_message[:80]}"
        return text
```

- `resume_microtech_sync_detail` in `actions_detail` aufnehmen; `microtech_sync_status` zu `readonly_fields` (und optional `list_display`) hinzufügen.

- [ ] **Step 4: Test + manuelle Verifikation**

Run: `python manage.py test orders.test_admin_workflow -v 2` → PASS.
Manuell: `python manage.py check`; im Admin eine geprüfte Bestellung öffnen → „Bestellung in Microtech anlegen" startet Workflow (Rückkehr sofort), Status-Feld zeigt Fortschritt; bei simuliertem Fehler „Microtech-Sync fortsetzen" testen.

- [ ] **Step 5: Commit**

```bash
git add orders/admin.py orders/test_admin_workflow.py
git commit -m "feat(orders): Admin-Trigger startet async Sync-Workflow mit Status und Resume"
```

---

## Abschluss-Verifikation (nach Task 12)

- [ ] Volle Testsuite der betroffenen Apps:

```bash
python manage.py test microtech orders customer -v 1
python manage.py check
```
Expected: alle grün, keine Systemcheck-Fehler.

- [ ] `graphify update .` ausführen (Graph aktuell halten, AST-only).

---

## Offene Verifikationspunkte für den Implementierer (vor Start prüfen)

1. **`Address`-Feldnamen**: `erp_ans_nr`, `erp_asp_nr`, `erp_ans_id`, `erp_asp_id`, `country_code`, `postal_code` etc. — in `customer/services/customer_upsert_microtech.py` (Builder) als Wahrheit verwenden.
2. **Order↔Customer↔Address-Beziehungen**: `order.customer`, `customer.shipping_address`, `customer.billing_address`, `customer.addresses`, `order.erp_order_id`, `order.order_number`, `order.api_id`, `order.description` — Zugriffe an `_upsert_order_graphql`/`upsert_customer` angleichen.
3. **Test-Order-Erzeugung**: `make_order` (in Task 3 vollständig definiert) spiegelt `orders/tests.py:25` `_create_order`. Felder `Customer.is_gross`, `Address.is_invoice/is_shipping/country_code`, `Order.billing_address/shipping_address` beim ersten Testlauf gegen das reale Schema verifizieren (falls Pflichtfelder fehlen, aus `_create_order` ergänzen).
4. **`na1_mode`**: Der Workflow verwendet default `"auto"`. Falls Regel-basiertes `na1_mode` (aus `OrderRuleResolverService`) auch für Anschriften gewünscht ist, in `submit_step` analog `_upsert_order_graphql` aus `resolved_rule` beziehen (Erweiterung, nicht v1-kritisch).
5. **Admin-Klassenname** in `orders/admin.py` verifizieren (Test-Import anpassen).
