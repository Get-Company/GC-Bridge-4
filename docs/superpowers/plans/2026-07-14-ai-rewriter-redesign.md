# AI-Rewriter Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Den AI-Rewriter drastisch vereinfachen — Feld-Button → Prompt+KI wählen → asynchroner Rewrite-Job → Ergebnis bearbeiten → ins Produktfeld übernehmen.

**Architecture:** Django-App `ai/`. `AIRewritePrompt` wird auf einen wiederverwendbaren Baustein (Name + Anweisung) reduziert; `AIRewriteJob` bekommt eine direkte `product`-FK statt GenericForeignKey und ein einziges `field` (Quelle=Ziel). Die KI läuft asynchron in einem Celery-`@shared_task`. Ein zweistufiger Freigabe-Workflow entfällt zugunsten eines einfachen Status `queued/ready/applied/failed`.

**Tech Stack:** Python 3.12, Django, Celery (`@shared_task`, `.delay`), Postgres, Unfold-Admin, modeltranslation, requests/urllib.

## Global Constraints

- Tests laufen mit Postgres: vor dem Testen `docker compose up -d db` starten und mit `docker compose exec -T db pg_isready -U gc_bridge_4 -d gc_bridge_4` auf Bereitschaft warten.
- Testbefehl: `DJANGO_SETTINGS_MODULE=GC_Bridge_4.settings uv run python manage.py test <label>`
- Paketinstallation immer mit `uv pip install` (falls nötig).
- Keine `Co-Authored-By`-Zeilen in Commits.
- Kein echter HTTP-Call zur KI in Tests — `AIProviderService.rewrite_text` immer mocken.
- Erlaubte `field`-Werte kommen ausschließlich aus `ai/rewrite_fields.get_rewriteable_product_field_names()` (`description*` / `description_short*` inkl. Sprachvarianten).
- Deutsche verbose_names/UI-Texte, ASCII-Umschreibung im bestehenden Stil des Codes (z.B. „uebernehmen") beibehalten wo der umgebende Code das tut.

---

## Datei-Struktur

- `ai/models.py` — `AIRewritePrompt` verschlanken, `AIRewriteJob` neu schneiden (`AIProviderConfig` unverändert).
- `ai/migrations/000X_ai_rewriter_redesign.py` — Schema- + Daten-Migration (handgeschrieben).
- `ai/services/rewrite.py` — `AIRewriteService.create_job/execute/apply`; `AIRewriteApplyService` entfernen; Standard-User-Prompt-Template.
- `ai/services/__init__.py` — Exporte anpassen.
- `ai/tasks.py` — **neu**: `run_ai_rewrite_job` Celery-Task.
- `ai/admin.py` — `AIRewriteJobAdmin` verschlanken, neue Create-View, alte Request-Form/Autocomplete/Apply-Service entfernen; Apply-Detail-Action.
- `templates/admin/ai/rewrite_job_create.html` — **neu** (ersetzt `rewrite_job_request.html`).
- `templates/admin/ai/airewritejob/change_form.html` — **neu**: Auto-Refresh bei `queued`.
- `templates/admin/ai/rewrite_job_request.html` — **löschen**.
- `templates/admin/products/includes/ai_rewrite_field_buttons.html` — Button von POST auf GET-Link.
- `products/admin.py` — POST-Handler + URL entfernen, `render_change_form`/Targets-JSON auf Link-Bauweise umstellen.
- `ai/management/commands/import_legacy_ai_rewrites.py` — an neues Schema anpassen (minimal) bzw. stilllegen.
- `GC_Bridge_4/settings.py` — Sidebar-Einträge prüfen.
- `ai/tests.py`, `core/tests.py` — Tests neu schreiben/anpassen.

---

## Task 1: Modelle neu schneiden + Migration

**Files:**
- Modify: `ai/models.py`
- Create: `ai/migrations/000X_ai_rewriter_redesign.py`
- Test: `ai/tests.py` (neue Testklasse `AIModelShapeTest`)

**Interfaces:**
- Produces: `AIRewritePrompt(name, slug, description, system_prompt, is_active)`; `AIRewriteJob(product FK, field, prompt FK, provider FK, status, source_snapshot, result_text, rendered_prompt, error_message, celery_task_id, requested_by, applied_at)` mit `AIRewriteJob.Status = {QUEUED="queued", READY="ready", APPLIED="applied", FAILED="failed"}`.

- [ ] **Step 1: Failing test schreiben**

In `ai/tests.py` neue Klasse ergänzen (Imports oben ergänzen: `from ai.models import AIProviderConfig, AIRewriteJob, AIRewritePrompt`, `from products.models import Product`):

```python
class AIModelShapeTest(TestCase):
    def test_prompt_has_only_slim_fields(self):
        prompt = AIRewritePrompt.objects.create(
            name="SEO", system_prompt="Schreibe verkaufsstark um."
        )
        self.assertTrue(prompt.slug)
        self.assertTrue(prompt.is_active)
        field_names = {f.name for f in AIRewritePrompt._meta.get_fields()}
        for removed in ("provider", "content_type", "source_field", "target_field",
                        "output_format", "user_prompt_template", "temperature_override"):
            self.assertNotIn(removed, field_names)

    def test_job_uses_product_fk_and_single_field(self):
        provider = AIProviderConfig.objects.create(name="P", model_name="gpt-5-mini")
        prompt = AIRewritePrompt.objects.create(name="SEO", system_prompt="x")
        product = Product.objects.create(erp_nr="T-1", name="Test")
        job = AIRewriteJob.objects.create(
            product=product, field="description_de", prompt=prompt,
            provider=provider, source_snapshot="<p>alt</p>",
        )
        self.assertEqual(job.status, AIRewriteJob.Status.QUEUED)
        field_names = {f.name for f in AIRewriteJob._meta.get_fields()}
        for removed in ("content_type", "object_id", "object_repr", "approved_by",
                        "approved_at", "is_archived", "source_field", "target_field"):
            self.assertNotIn(removed, field_names)
```

- [ ] **Step 2: Test laufen lassen, Fehlschlag verifizieren**

Run: `DJANGO_SETTINGS_MODULE=GC_Bridge_4.settings uv run python manage.py test ai.tests.AIModelShapeTest -v 2`
Expected: FAIL (alte Modelle haben `content_type` etc., `product`/`field` fehlen).

- [ ] **Step 3: `ai/models.py` neu schreiben**

`AIProviderConfig` bleibt unverändert. `AIRewritePrompt` und `AIRewriteJob` ersetzen durch:

```python
class AIRewritePrompt(BaseModel):
    external_key = models.CharField(max_length=255, blank=True, default="", db_index=True, verbose_name=_("Externe Referenz"))
    name = models.CharField(max_length=255, verbose_name=_("Name"))
    slug = models.SlugField(max_length=255, unique=True, blank=True, verbose_name=_("Slug"))
    description = models.TextField(blank=True, default="", verbose_name=_("Beschreibung"))
    system_prompt = models.TextField(verbose_name=_("Anweisung"))
    is_active = models.BooleanField(default=True, verbose_name=_("Aktiv"))

    class Meta:
        verbose_name = _("AI Rewrite Prompt")
        verbose_name_plural = _("AI Rewrite Prompts")
        ordering = ("name",)

    def __str__(self) -> str:
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)[:255]
        super().save(*args, **kwargs)


class AIRewriteJob(BaseModel):
    class Status(models.TextChoices):
        QUEUED = "queued", _("In Arbeit")
        READY = "ready", _("Ergebnis vorhanden")
        APPLIED = "applied", _("Uebernommen")
        FAILED = "failed", _("Fehlgeschlagen")

    external_key = models.CharField(max_length=255, blank=True, default="", db_index=True, verbose_name=_("Externe Referenz"))
    product = models.ForeignKey(
        "products.Product",
        on_delete=models.PROTECT,
        related_name="ai_rewrite_jobs",
        verbose_name=_("Produkt"),
    )
    field = models.CharField(max_length=120, verbose_name=_("Feld"))
    prompt = models.ForeignKey(
        AIRewritePrompt,
        on_delete=models.PROTECT,
        related_name="jobs",
        verbose_name=_("Prompt"),
    )
    provider = models.ForeignKey(
        AIProviderConfig,
        on_delete=models.PROTECT,
        related_name="jobs",
        verbose_name=_("KI"),
    )
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.QUEUED,
        db_index=True,
        verbose_name=_("Status"),
    )
    source_snapshot = models.TextField(blank=True, default="", verbose_name=_("Quellinhalt"))
    result_text = models.TextField(blank=True, default="", verbose_name=_("Ergebnis"))
    rendered_prompt = models.TextField(blank=True, default="", verbose_name=_("Gerenderter Prompt"))
    error_message = models.TextField(blank=True, default="", verbose_name=_("Fehler"))
    celery_task_id = models.CharField(max_length=255, blank=True, default="", verbose_name=_("Celery Task-ID"))
    requested_by = models.ForeignKey(
        get_user_model(),
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="requested_ai_rewrite_jobs",
        verbose_name=_("Angefordert von"),
    )
    applied_at = models.DateTimeField(null=True, blank=True, verbose_name=_("Uebernommen am"))

    class Meta:
        verbose_name = _("AI Rewrite Job")
        verbose_name_plural = _("AI Rewrite Jobs")
        ordering = ("-created_at",)
        indexes = [models.Index(fields=("product", "field"))]

    def __str__(self) -> str:
        return f"#{self.pk} · {self.product_id} · {self.field} · {self.get_status_display()}"
```

Nicht mehr benötigte Imports entfernen (`GenericForeignKey`, `ContentType`, `ValidationError`, `Decimal`, `Context/Engine` falls ungenutzt). `get_user_model`, `models`, `slugify`, `_`, `BaseModel` bleiben.

- [ ] **Step 4: Migration erzeugen (Gerüst) und durch handgeschriebene ersetzen**

Zuerst Nummer ermitteln: letzte Migration in `ai/migrations/` ansehen. Datei `ai/migrations/000X_ai_rewriter_redesign.py` anlegen (X = nächste Nummer, `dependencies` auf die zuletzt vorhandene ai-Migration setzen):

```python
from django.conf import settings
import django.db.models.deletion
from django.db import migrations, models


def forwards(apps, schema_editor):
    AIRewriteJob = apps.get_model("ai", "AIRewriteJob")
    ContentType = apps.get_model("contenttypes", "ContentType")
    try:
        product_ct = ContentType.objects.get(app_label="products", model="product")
    except ContentType.DoesNotExist:
        product_ct = None

    status_map = {
        "applied": "applied",
        "failed": "failed",
        "draft": "ready",
        "pending_review": "ready",
        "approved": "ready",
        "rejected": "ready",
    }
    for job in AIRewriteJob.objects.all():
        if product_ct is None or job.content_type_id != product_ct.id:
            job.delete()
            continue
        job.product_id = job.object_id
        job.field = job.target_field or job.source_field or ""
        job.status = status_map.get(job.status, "ready")
        job.save(update_fields=["product_id", "field", "status"])


class Migration(migrations.Migration):
    dependencies = [
        ("ai", "000X_previous"),  # an die real letzte ai-Migration anpassen
        ("products", "0001_initial"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        # AIRewritePrompt verschlanken
        migrations.RemoveField("airewriteprompt", "provider"),
        migrations.RemoveField("airewriteprompt", "content_type"),
        migrations.RemoveField("airewriteprompt", "source_field"),
        migrations.RemoveField("airewriteprompt", "target_field"),
        migrations.RemoveField("airewriteprompt", "output_format"),
        migrations.RemoveField("airewriteprompt", "user_prompt_template"),
        migrations.RemoveField("airewriteprompt", "temperature_override"),
        migrations.AlterField(
            "airewriteprompt", "system_prompt",
            models.TextField(verbose_name="Anweisung"),
        ),
        # AIRewriteJob: neue Spalten (nullable), befuellen, alte weg
        migrations.AddField(
            "airewritejob", "product",
            models.ForeignKey(null=True, on_delete=django.db.models.deletion.PROTECT,
                              related_name="ai_rewrite_jobs", to="products.product",
                              verbose_name="Produkt"),
        ),
        migrations.AddField(
            "airewritejob", "field",
            models.CharField(default="", max_length=120, verbose_name="Feld"),
        ),
        migrations.AddField(
            "airewritejob", "celery_task_id",
            models.CharField(blank=True, default="", max_length=255, verbose_name="Celery Task-ID"),
        ),
        migrations.RunPython(forwards, migrations.RunPython.noop),
        migrations.RemoveField("airewritejob", "content_type"),
        migrations.RemoveField("airewritejob", "object_id"),
        migrations.RemoveField("airewritejob", "object_repr"),
        migrations.RemoveField("airewritejob", "approved_by"),
        migrations.RemoveField("airewritejob", "approved_at"),
        migrations.RemoveField("airewritejob", "is_archived"),
        migrations.RemoveField("airewritejob", "source_field"),
        migrations.RemoveField("airewritejob", "target_field"),
        migrations.AlterField(
            "airewritejob", "product",
            models.ForeignKey(on_delete=django.db.models.deletion.PROTECT,
                              related_name="ai_rewrite_jobs", to="products.product",
                              verbose_name="Produkt"),
        ),
        migrations.AlterField(
            "airewritejob", "status",
            models.CharField(choices=[("queued","In Arbeit"),("ready","Ergebnis vorhanden"),
                                      ("applied","Uebernommen"),("failed","Fehlgeschlagen")],
                             db_index=True, default="queued", max_length=16, verbose_name="Status"),
        ),
    ]
```

Hinweis: Die exakte letzte ai-Migrationsnummer per `ls ai/migrations/` ermitteln und `dependencies` + Dateinamen entsprechend setzen. Falls `makemigrations` zusätzlich ein `AlterModelOptions`/Index-Diff erzeugt, dieses per `makemigrations ai --name ai_rewriter_redesign_indexes` nachziehen ODER die Index-Operation (`AddIndex`) am Ende der obigen `operations` ergänzen:

```python
        migrations.AddIndex(
            "airewritejob",
            models.Index(fields=["product", "field"], name="ai_airewr_product_field_idx"),
        ),
```

- [ ] **Step 5: Migration anwenden + Test grün**

```bash
docker compose up -d db
DJANGO_SETTINGS_MODULE=GC_Bridge_4.settings uv run python manage.py makemigrations ai --check --dry-run
DJANGO_SETTINGS_MODULE=GC_Bridge_4.settings uv run python manage.py test ai.tests.AIModelShapeTest -v 2
```
Expected: `makemigrations --check` meldet keine ausstehenden Änderungen (Modell = Migrationen konsistent); Test PASS. Falls `--check` Änderungen meldet, fehlende `AlterField`/`AddIndex` in die Migration übernehmen bis konsistent.

- [ ] **Step 6: Commit**

```bash
git add ai/models.py ai/migrations/ ai/tests.py
git commit -m "Reshape AI rewriter models to product-focused schema"
```

---

## Task 2: Service-Layer (create_job / execute / apply)

**Files:**
- Modify: `ai/services/rewrite.py`
- Modify: `ai/services/__init__.py`
- Test: `ai/tests.py` (Klasse `AIRewriteServiceTest`)

**Interfaces:**
- Consumes: Modelle aus Task 1; `AIProviderService.rewrite_text(*, provider, system_prompt, user_prompt, temperature=None) -> str` (unverändert).
- Produces:
  - `AIRewriteService.create_job(*, product, field, prompt, provider, requested_by=None) -> AIRewriteJob` (legt `queued` an, Snapshot, **kein** direkter KI-Call).
  - `AIRewriteService.execute(job: AIRewriteJob) -> AIRewriteJob` (ruft KI, setzt `ready`/`failed`).
  - `AIRewriteService.apply(*, job: AIRewriteJob) -> AIRewriteJob` (schreibt `result_text` ins Produktfeld, `applied`).

- [ ] **Step 1: Failing tests schreiben**

```python
from unittest.mock import patch
from ai.services import AIRewriteService

class AIRewriteServiceTest(TestCase):
    def setUp(self):
        self.provider = AIProviderConfig.objects.create(name="P", model_name="gpt-5-mini", api_key="k")
        self.prompt = AIRewritePrompt.objects.create(name="SEO", system_prompt="Schreibe um.")
        self.product = Product.objects.create(erp_nr="T-1", name="Test", description_de="<p>alt</p>")

    def test_create_job_is_queued_with_snapshot(self):
        job = AIRewriteService().create_job(
            product=self.product, field="description_de",
            prompt=self.prompt, provider=self.provider,
        )
        self.assertEqual(job.status, AIRewriteJob.Status.QUEUED)
        self.assertEqual(job.source_snapshot, "<p>alt</p>")
        self.assertEqual(job.result_text, "")

    @patch("ai.services.rewrite.AIProviderService.rewrite_text", return_value="<p>neu</p>")
    def test_execute_sets_ready(self, _mock):
        job = AIRewriteService().create_job(
            product=self.product, field="description_de",
            prompt=self.prompt, provider=self.provider,
        )
        AIRewriteService().execute(job)
        job.refresh_from_db()
        self.assertEqual(job.status, AIRewriteJob.Status.READY)
        self.assertEqual(job.result_text, "<p>neu</p>")

    @patch("ai.services.rewrite.AIProviderService.rewrite_text", side_effect=RuntimeError("boom"))
    def test_execute_failure_sets_failed(self, _mock):
        job = AIRewriteService().create_job(
            product=self.product, field="description_de",
            prompt=self.prompt, provider=self.provider,
        )
        AIRewriteService().execute(job)
        job.refresh_from_db()
        self.assertEqual(job.status, AIRewriteJob.Status.FAILED)
        self.assertIn("boom", job.error_message)

    def test_apply_writes_edited_text_to_field(self):
        job = AIRewriteService().create_job(
            product=self.product, field="description_de",
            prompt=self.prompt, provider=self.provider,
        )
        job.result_text = "<p>final</p>"
        job.status = AIRewriteJob.Status.READY
        job.save(update_fields=["result_text", "status"])
        AIRewriteService().apply(job=job)
        job.refresh_from_db(); self.product.refresh_from_db()
        self.assertEqual(self.product.description_de, "<p>final</p>")
        self.assertEqual(job.status, AIRewriteJob.Status.APPLIED)
        self.assertIsNotNone(job.applied_at)
```

- [ ] **Step 2: Test laufen lassen, Fehlschlag verifizieren**

Run: `DJANGO_SETTINGS_MODULE=GC_Bridge_4.settings uv run python manage.py test ai.tests.AIRewriteServiceTest -v 2`
Expected: FAIL (`create_job`/`execute`/`apply` existieren nicht bzw. Signatur passt nicht).

- [ ] **Step 3: `ai/services/rewrite.py` neu schreiben**

Vollständiger neuer Inhalt:

```python
from __future__ import annotations

import json
from decimal import Decimal
from typing import Any

from django.db import transaction
from django.template import Context, Engine
from django.utils import timezone

from core.services import BaseService
from ai.models import AIRewriteJob, AIRewritePrompt, AIProviderConfig
from .provider import AIProviderService


DEFAULT_USER_PROMPT_TEMPLATE = """Bearbeite den Feldinhalt fuer das Feld "{{ field }}".

Objekt: {{ object_repr }}

Aktueller Feldinhalt:
{{ source_value }}

Objektkontext (JSON):
{{ object_context_json }}

Gib ausschliesslich den neuen Feldinhalt fuer "{{ field }}" zurueck.
"""


class AIRewriteService(BaseService):
    model = AIRewriteJob

    def __init__(self) -> None:
        super().__init__()
        self.provider_service = AIProviderService()
        self.template_engine = Engine(autoescape=False)

    @transaction.atomic
    def create_job(self, *, product, field: str, prompt: AIRewritePrompt,
                   provider: AIProviderConfig, requested_by=None) -> AIRewriteJob:
        snapshot = self._get_field_value(product, field)
        return self.model.objects.create(
            product=product,
            field=field,
            prompt=prompt,
            provider=provider,
            source_snapshot=snapshot,
            requested_by=requested_by,
            status=AIRewriteJob.Status.QUEUED,
        )

    def execute(self, job: AIRewriteJob) -> AIRewriteJob:
        rendered = self._render_user_prompt(job)
        job.rendered_prompt = rendered
        try:
            job.result_text = self.provider_service.rewrite_text(
                provider=job.provider,
                system_prompt=job.prompt.system_prompt,
                user_prompt=rendered,
            )
            job.status = AIRewriteJob.Status.READY
            job.error_message = ""
        except Exception as exc:  # noqa: BLE001 - Fehler landet im Job
            job.status = AIRewriteJob.Status.FAILED
            job.error_message = str(exc)
        job.save(update_fields=["rendered_prompt", "result_text", "status", "error_message", "updated_at"])
        return job

    @transaction.atomic
    def apply(self, *, job: AIRewriteJob) -> AIRewriteJob:
        product = job.product
        setattr(product, job.field, job.result_text)
        product.save(update_fields=[job.field, "updated_at"])
        job.status = AIRewriteJob.Status.APPLIED
        job.applied_at = timezone.now()
        job.save(update_fields=["status", "applied_at", "updated_at"])
        return job

    def _render_user_prompt(self, job: AIRewriteJob) -> str:
        context = {
            "field": job.field,
            "object_repr": str(job.product),
            "source_value": job.source_snapshot,
            "object_context_json": json.dumps(self._serialize(job.product), ensure_ascii=True, indent=2),
        }
        template = self.template_engine.from_string(DEFAULT_USER_PROMPT_TEMPLATE)
        return template.render(Context(context)).strip()

    @staticmethod
    def _get_field_value(obj, field_name: str) -> str:
        value = getattr(obj, field_name, "")
        return "" if value is None else str(value)

    def _serialize(self, obj) -> dict[str, Any]:
        data: dict[str, Any] = {}
        for f in obj._meta.fields:
            value = getattr(obj, f.name, None)
            if value is None or isinstance(value, (str, int, float, bool)):
                data[f.name] = value
            elif isinstance(value, Decimal):
                data[f.name] = str(value)
            else:
                data[f.name] = str(value)
        if hasattr(obj, "categories"):
            data["categories"] = list(obj.categories.values_list("name", flat=True))
        return data
```

- [ ] **Step 4: `ai/services/__init__.py` anpassen**

```python
from .provider import AIProviderService
from .rewrite import AIRewriteService

__all__ = [
    "AIProviderService",
    "AIRewriteService",
]
```

- [ ] **Step 5: Test grün**

Run: `DJANGO_SETTINGS_MODULE=GC_Bridge_4.settings uv run python manage.py test ai.tests.AIRewriteServiceTest -v 2`
Expected: PASS (4 Tests).

- [ ] **Step 6: Commit**

```bash
git add ai/services/rewrite.py ai/services/__init__.py ai/tests.py
git commit -m "Rewrite AI rewrite service for async create/execute/apply flow"
```

---

## Task 3: Celery-Task

**Files:**
- Create: `ai/tasks.py`
- Test: `ai/tests.py` (Klasse `AIRewriteTaskTest`)

**Interfaces:**
- Consumes: `AIRewriteService.execute(job)` aus Task 2.
- Produces: `run_ai_rewrite_job(job_id: int) -> None` (Celery `@shared_task`), speichert `celery_task_id` beim Dispatch nicht selbst — das macht der Aufrufer.

- [ ] **Step 1: Failing test schreiben**

```python
class AIRewriteTaskTest(TestCase):
    @patch("ai.services.rewrite.AIProviderService.rewrite_text", return_value="<p>neu</p>")
    def test_task_executes_job(self, _mock):
        provider = AIProviderConfig.objects.create(name="P", model_name="m", api_key="k")
        prompt = AIRewritePrompt.objects.create(name="SEO", system_prompt="x")
        product = Product.objects.create(erp_nr="T-1", name="Test", description_de="<p>alt</p>")
        job = AIRewriteService().create_job(
            product=product, field="description_de", prompt=prompt, provider=provider,
        )
        from ai.tasks import run_ai_rewrite_job
        run_ai_rewrite_job(job.pk)
        job.refresh_from_db()
        self.assertEqual(job.status, AIRewriteJob.Status.READY)
```

- [ ] **Step 2: Fehlschlag verifizieren**

Run: `DJANGO_SETTINGS_MODULE=GC_Bridge_4.settings uv run python manage.py test ai.tests.AIRewriteTaskTest -v 2`
Expected: FAIL (`ai.tasks` existiert nicht).

- [ ] **Step 3: `ai/tasks.py` erstellen**

```python
from __future__ import annotations

from celery import shared_task

from ai.models import AIRewriteJob
from ai.services import AIRewriteService


@shared_task
def run_ai_rewrite_job(job_id: int) -> None:
    try:
        job = AIRewriteJob.objects.select_related("product", "prompt", "provider").get(pk=job_id)
    except AIRewriteJob.DoesNotExist:
        return
    AIRewriteService().execute(job)
```

- [ ] **Step 4: Test grün**

Run: `DJANGO_SETTINGS_MODULE=GC_Bridge_4.settings uv run python manage.py test ai.tests.AIRewriteTaskTest -v 2`
Expected: PASS. (Test läuft synchron, da `CELERY_TASK_ALWAYS_EAGER` in Tests bzw. direkter Funktionsaufruf.)

- [ ] **Step 5: Commit**

```bash
git add ai/tasks.py ai/tests.py
git commit -m "Add Celery task for async AI rewrite execution"
```

---

## Task 4: Create-Seite (View + Form + Template), alte Request-Form entfernen

**Files:**
- Modify: `ai/admin.py`
- Create: `templates/admin/ai/rewrite_job_create.html`
- Delete: `templates/admin/ai/rewrite_job_request.html`
- Test: `ai/tests.py` (Klasse `AIRewriteCreateViewTest`)

**Interfaces:**
- Consumes: `AIRewriteService.create_job(...)`, `run_ai_rewrite_job.delay`, `get_rewriteable_product_field_names()`.
- Produces: URL-Name `admin:ai_airewritejob_create` unter Pfad `new/`; GET erwartet `?product=<pk>&field=<field>`; POST(`prompt`,`provider`) legt Job an und leitet zu `admin:ai_airewritejob_change` weiter.

- [ ] **Step 1: Failing tests schreiben**

```python
from django.urls import reverse
from django.contrib.auth import get_user_model

class AIRewriteCreateViewTest(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_superuser("admin", "a@b.de", "pw")
        self.client.force_login(self.user)
        self.provider = AIProviderConfig.objects.create(name="P", model_name="m", api_key="k")
        self.prompt = AIRewritePrompt.objects.create(name="SEO", system_prompt="x")
        self.product = Product.objects.create(erp_nr="T-1", name="Test", description_de="<p>alt</p>")

    def test_get_renders_with_product_and_field(self):
        url = reverse("admin:ai_airewritejob_create")
        resp = self.client.get(url, {"product": self.product.pk, "field": "description_de"})
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "description_de")

    @patch("ai.admin.run_ai_rewrite_job.delay")
    def test_post_creates_job_and_redirects(self, mock_delay):
        url = reverse("admin:ai_airewritejob_create")
        resp = self.client.post(url, {
            "product": self.product.pk, "field": "description_de",
            "prompt": self.prompt.pk, "provider": self.provider.pk,
        })
        job = AIRewriteJob.objects.get()
        self.assertEqual(job.field, "description_de")
        self.assertEqual(job.status, AIRewriteJob.Status.QUEUED)
        mock_delay.assert_called_once_with(job.pk)
        self.assertRedirects(resp, reverse("admin:ai_airewritejob_change", args=(job.pk,)))

    def test_post_rejects_field_outside_whitelist(self):
        url = reverse("admin:ai_airewritejob_create")
        resp = self.client.post(url, {
            "product": self.product.pk, "field": "sku",
            "prompt": self.prompt.pk, "provider": self.provider.pk,
        })
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(AIRewriteJob.objects.count(), 0)
```

- [ ] **Step 2: Fehlschlag verifizieren**

Run: `DJANGO_SETTINGS_MODULE=GC_Bridge_4.settings uv run python manage.py test ai.tests.AIRewriteCreateViewTest -v 2`
Expected: FAIL (URL `ai_airewritejob_create` existiert nicht).

- [ ] **Step 3: `ai/admin.py` — Imports & Form & View ersetzen**

Oben im Modul die veralteten Importe (`Q`, `HttpResponseForbidden`, `BaseAutocompleteView`, `UnfoldAdminAutocompleteModelChoiceField`, `AIRewriteApplyService`) entfernen, ergänzen:

```python
from django.http import HttpResponseRedirect
from django.urls import path, reverse
from django.views.generic import FormView
from unfold.views import UnfoldModelAdminViewMixin
from unfold.widgets import UnfoldAdminSelect2Widget

from ai.models import AIProviderConfig, AIRewriteJob, AIRewritePrompt
from ai.rewrite_fields import get_rewriteable_product_field_names
from ai.services import AIRewriteService
from ai.tasks import run_ai_rewrite_job
from products.models import Product
```

`AIRewriteJobRequestForm`, `ProductChoiceField`, `PromptChoiceField`, `ProductAutocompleteView`, `AIRewriteJobRequestView` löschen und ersetzen durch:

```python
class AIRewriteJobCreateForm(forms.Form):
    prompt = forms.ModelChoiceField(
        label="Prompt",
        queryset=AIRewritePrompt.objects.filter(is_active=True).order_by("name"),
        widget=UnfoldAdminSelect2Widget,
    )
    provider = forms.ModelChoiceField(
        label="KI",
        queryset=AIProviderConfig.objects.filter(is_active=True).order_by("name"),
        widget=UnfoldAdminSelect2Widget,
    )

    def __init__(self, *args, product=None, field="", **kwargs):
        super().__init__(*args, **kwargs)
        self.product = product
        self.field_name = field

    def clean(self):
        cleaned = super().clean()
        if self.product is None:
            raise forms.ValidationError("Kein gueltiges Produkt uebergeben.")
        if self.field_name not in get_rewriteable_product_field_names():
            raise forms.ValidationError("Dieses Feld kann nicht per KI umgeschrieben werden.")
        return cleaned


class AIRewriteJobCreateView(UnfoldModelAdminViewMixin, FormView):
    title = "AI Rewrite erzeugen"
    permission_required = ("ai.add_airewritejob",)
    template_name = "admin/ai/rewrite_job_create.html"
    form_class = AIRewriteJobCreateForm

    def _get_product(self):
        pk = self.request.GET.get("product") or self.request.POST.get("product")
        return Product.objects.filter(pk=pk).first() if pk else None

    def _get_field(self):
        return self.request.GET.get("field") or self.request.POST.get("field") or ""

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["product"] = self._get_product()
        kwargs["field"] = self._get_field()
        return kwargs

    def form_valid(self, form):
        job = AIRewriteService().create_job(
            product=form.product,
            field=form.field_name,
            prompt=form.cleaned_data["prompt"],
            provider=form.cleaned_data["provider"],
            requested_by=self.request.user,
        )
        async_result = run_ai_rewrite_job.delay(job.pk)
        AIRewriteJob.objects.filter(pk=job.pk, celery_task_id="").update(
            celery_task_id=getattr(async_result, "id", "") or ""
        )
        return HttpResponseRedirect(reverse("admin:ai_airewritejob_change", args=(job.pk,)))

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        product = self._get_product()
        context.update({
            "product": product,
            "field_name": self._get_field(),
            "changelist_url": reverse("admin:ai_airewritejob_changelist"),
        })
        return context
```

In `AIRewriteJobAdmin.get_urls` die alten Pfade ersetzen (nur der Create-Pfad bleibt; product-autocomplete entfällt):

```python
    def get_urls(self):
        create_view = self.admin_site.admin_view(
            AIRewriteJobCreateView.as_view(model_admin=self)
        )
        return [
            path("new/", create_view, name="ai_airewritejob_create"),
        ] + super().get_urls()
```

- [ ] **Step 4: Template `templates/admin/ai/rewrite_job_create.html` anlegen**

```django
{% extends "admin/base_site.html" %}

{% block extrahead %}
  {{ block.super }}
  {{ form.media }}
{% endblock %}

{% block content %}
<div id="content-main" class="flex flex-col gap-6">
  <div class="max-w-3xl">
    <div class="rounded-xl border border-base-200 bg-white px-6 py-6 shadow-sm dark:border-base-800 dark:bg-base-900">
      <div class="flex flex-col gap-1 border-b border-base-200 pb-5 dark:border-base-800">
        <h1 class="text-2xl font-semibold text-font-important-light dark:text-font-important-dark">{{ title }}</h1>
        <p class="text-sm text-font-subtle-light dark:text-font-subtle-dark">
          Produkt: <strong>{{ product }}</strong> · Feld: <strong>{{ field_name }}</strong>
        </p>
      </div>

      <form method="post" novalidate class="mt-6 flex flex-col gap-6">
        {% csrf_token %}
        <input type="hidden" name="product" value="{{ product.pk }}">
        <input type="hidden" name="field" value="{{ field_name }}">

        {% if form.non_field_errors %}
          <div class="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700 dark:border-red-900 dark:bg-red-950/30 dark:text-red-300">
            {{ form.non_field_errors }}
          </div>
        {% endif %}

        <div class="grid gap-6 lg:grid-cols-2">
          <div>{% include "unfold/helpers/field.html" with field=form.prompt %}</div>
          <div>{% include "unfold/helpers/field.html" with field=form.provider %}</div>
        </div>

        <div class="flex flex-wrap items-center gap-3 border-t border-base-200 pt-5 dark:border-base-800">
          <button type="submit" class="inline-flex items-center justify-center rounded-md bg-primary-600 px-4 py-2 text-sm font-medium text-white transition hover:bg-primary-700">
            Rewrite erzeugen
          </button>
          <a href="{{ changelist_url }}" class="inline-flex items-center justify-center rounded-md border border-base-300 px-4 py-2 text-sm font-medium text-font-default-light transition hover:bg-base-50 dark:border-base-700 dark:text-font-default-dark dark:hover:bg-base-800">
            Zurueck zu den Rewrite Jobs
          </a>
        </div>
      </form>
    </div>
  </div>
</div>
{% endblock %}
```

- [ ] **Step 5: Altes Template löschen + Test grün**

```bash
git rm templates/admin/ai/rewrite_job_request.html
DJANGO_SETTINGS_MODULE=GC_Bridge_4.settings uv run python manage.py test ai.tests.AIRewriteCreateViewTest -v 2
```
Expected: PASS (3 Tests).

- [ ] **Step 6: Commit**

```bash
git add ai/admin.py templates/admin/ai/
git commit -m "Add simplified two-field AI rewrite create page"
```

---

## Task 5: Job-Arbeitsflaeche (Admin verschlanken, Apply-Action, Auto-Refresh)

**Files:**
- Modify: `ai/admin.py`
- Create: `templates/admin/ai/airewritejob/change_form.html`
- Test: `ai/tests.py` (Klasse `AIRewriteJobAdminTest` — alte Version ersetzen)

**Interfaces:**
- Consumes: `AIRewriteService.apply(job=...)`.
- Produces: Detail-Action `apply_rewrite_detail`; verschlankte `fieldsets`/`list_display`; Change-Form mit Refresh bei `queued`.

- [ ] **Step 1: Alte `AIRewriteJobAdminTest` ersetzen, neue Tests schreiben**

Die bestehende Klasse `AIRewriteJobAdminTest` in `ai/tests.py` komplett entfernen und ersetzen:

```python
class AIRewriteJobWorkspaceTest(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_superuser("admin2", "a2@b.de", "pw")
        self.client.force_login(self.user)
        self.provider = AIProviderConfig.objects.create(name="P", model_name="m", api_key="k")
        self.prompt = AIRewritePrompt.objects.create(name="SEO", system_prompt="x")
        self.product = Product.objects.create(erp_nr="T-1", name="Test", description_de="<p>alt</p>")

    def _job(self, **overrides):
        data = dict(product=self.product, field="description_de", prompt=self.prompt,
                    provider=self.provider, source_snapshot="<p>alt</p>")
        data.update(overrides)
        return AIRewriteJob.objects.create(**data)

    def test_change_page_renders_for_ready_job(self):
        job = self._job(status=AIRewriteJob.Status.READY, result_text="<p>neu</p>")
        resp = self.client.get(reverse("admin:ai_airewritejob_change", args=(job.pk,)))
        self.assertEqual(resp.status_code, 200)

    def test_apply_detail_writes_field(self):
        job = self._job(status=AIRewriteJob.Status.READY, result_text="<p>neu</p>")
        from ai.admin import AIRewriteJobAdmin
        from django.contrib.admin.sites import AdminSite
        admin_obj = AIRewriteJobAdmin(AIRewriteJob, AdminSite())
        request = self.client.get("/").wsgi_request
        request.user = self.user
        admin_obj.apply_rewrite_detail(request, str(job.pk))
        job.refresh_from_db(); self.product.refresh_from_db()
        self.assertEqual(self.product.description_de, "<p>neu</p>")
        self.assertEqual(job.status, AIRewriteJob.Status.APPLIED)
```

- [ ] **Step 2: Fehlschlag verifizieren**

Run: `DJANGO_SETTINGS_MODULE=GC_Bridge_4.settings uv run python manage.py test ai.tests.AIRewriteJobWorkspaceTest -v 2`
Expected: FAIL (Action/Änderungen fehlen).

- [ ] **Step 3: `AIRewriteJobAdmin` verschlanken**

Klasse ersetzen durch:

```python
@admin.register(AIRewriteJob)
class AIRewriteJobAdmin(BaseAdmin):
    list_display = ("__str__", "product", "field", "prompt", "provider", "status", "requested_by", "created_at")
    list_display_links = ("__str__",)
    search_fields = ("product__erp_nr", "product__name", "field", "prompt__name", "result_text")
    list_filter = ("status", "prompt", "provider", "created_at")
    actions_detail = ("apply_rewrite_detail",)
    change_form_template = "admin/ai/airewritejob/change_form.html"
    readonly_fields = BaseAdmin.readonly_fields + (
        "product", "field", "prompt", "provider", "status",
        "source_snapshot_preview", "rendered_prompt", "error_message",
        "celery_task_id", "requested_by", "applied_at",
    )
    fieldsets = (
        ("Ergebnis", {
            "fields": ("status", "source_snapshot_preview", "result_text", "error_message"),
            "description": "Ergebnis pruefen, bei Bedarf bearbeiten und uebernehmen.",
        }),
        ("Kontext", {
            "fields": ("product", "field", "prompt", "provider", "rendered_prompt",
                       "celery_task_id", "requested_by", "applied_at", "created_at", "updated_at"),
            "classes": ("collapse",),
        }),
    )

    @admin.display(description="Aktueller Quellinhalt")
    def source_snapshot_preview(self, obj: AIRewriteJob):
        from unfold.contrib.forms.widgets import WYSIWYG_CLASSES
        value = obj.source_snapshot or "<p><em>Kein Inhalt.</em></p>"
        return format_html(
            '<div class="max-w-4xl relative"><div class="trix-content {}">{}</div></div>',
            " ".join(WYSIWYG_CLASSES), mark_safe(value),
        )

    @action(description="In Feld uebernehmen", icon="task_alt")
    def apply_rewrite_detail(self, request, object_id: str):
        job = self.get_object(request, object_id)
        if not job:
            self.message_user(request, "Rewrite-Job nicht gefunden.", level=messages.ERROR)
            return HttpResponseRedirect(reverse("admin:ai_airewritejob_changelist"))
        if job.status not in (AIRewriteJob.Status.READY, AIRewriteJob.Status.APPLIED):
            self.message_user(request, "Job hat noch kein Ergebnis.", level=messages.WARNING)
            return HttpResponseRedirect(reverse("admin:ai_airewritejob_change", args=(job.pk,)))
        try:
            AIRewriteService().apply(job=job)
        except Exception as exc:
            self.message_user(request, f"Konnte nicht uebernommen werden: {exc}", level=messages.ERROR)
        else:
            self.message_user(request, "Ergebnis wurde in das Produktfeld uebernommen.")
        return HttpResponseRedirect(reverse("admin:ai_airewritejob_change", args=(job.pk,)))
```

Nötige Imports sicherstellen: `from django.contrib import admin, messages`, `from django.utils.html import format_html`, `from django.utils.safestring import mark_safe`, `from unfold.decorators import action`. Entfernte Admin-Actions (`approve_selected` etc.) und tote Methoden (`job_label`, `product_link`, `target_object_link`, `target_reference`, `product_inline_preview`, `current_target_preview`) löschen.

- [ ] **Step 4: Change-Form-Template mit Auto-Refresh anlegen**

`templates/admin/ai/airewritejob/change_form.html`:

```django
{% extends "admin/change_form.html" %}

{% block content %}
  {% if original.status == "queued" %}
    <div class="mb-4 rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800 dark:border-amber-900 dark:bg-amber-950/30 dark:text-amber-200">
      Die KI verarbeitet diesen Job. Die Seite aktualisiert sich automatisch…
    </div>
    <script>window.setTimeout(function () { window.location.reload(); }, 4000);</script>
  {% endif %}
  {{ block.super }}
{% endblock %}
```

- [ ] **Step 5: Test grün + volle ai-Suite**

```bash
DJANGO_SETTINGS_MODULE=GC_Bridge_4.settings uv run python manage.py test ai -v 1
```
Expected: PASS (alle ai-Tests inkl. neuer Workspace-Tests).

- [ ] **Step 6: Commit**

```bash
git add ai/admin.py templates/admin/ai/
git commit -m "Slim AI rewrite job workspace with apply action and auto-refresh"
```

---

## Task 6: Produkt-Feld-Button auf GET-Link umstellen

**Files:**
- Modify: `templates/admin/products/includes/ai_rewrite_field_buttons.html`
- Modify: `products/admin.py`
- Test: `ai/tests.py` bzw. `products/tests.py` (ein Test)

**Interfaces:**
- Consumes: URL `admin:ai_airewritejob_create` (Task 4).
- Produces: Button je Beschreibungsfeld als `<a href=".../new/?product=X&field=Y">`.

- [ ] **Step 1: Failing test schreiben**

In `ai/tests.py` (nutzt bestehendes Setup-Muster):

```python
class ProductFieldButtonTest(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_superuser("admin3", "a3@b.de", "pw")
        self.client.force_login(self.user)
        self.product = Product.objects.create(erp_nr="T-1", name="Test", description_de="<p>x</p>")

    def test_change_view_exposes_create_link_and_field(self):
        resp = self.client.get(reverse("admin:products_product_change", args=(self.product.pk,)))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "product-ai-rewrite-fields")
        self.assertContains(resp, reverse("admin:ai_airewritejob_create"))
        self.assertContains(resp, "description_de")
```

- [ ] **Step 2: Fehlschlag verifizieren**

Run: `DJANGO_SETTINGS_MODULE=GC_Bridge_4.settings uv run python manage.py test ai.tests.ProductFieldButtonTest -v 2`
Expected: FAIL (create-URL wird noch nicht ausgegeben; alte POST-URL stattdessen).

- [ ] **Step 3: `products/admin.py` anpassen**

`get_urls`-Override für `products_product_request_ai_rewrite` und die Methode `request_ai_rewrite_for_field` **löschen**. `render_change_form` und `_build_ai_rewrite_field_targets_json` ersetzen:

```python
    def render_change_form(self, request, context, add=False, change=False, form_url="", obj=None):
        context = {
            **context,
            "ai_rewrite_field_targets_json": self._build_ai_rewrite_field_targets_json(context),
            "ai_rewrite_create_url": reverse("admin:ai_airewritejob_create"),
            "ai_rewrite_product_id": obj.pk if obj and obj.pk else "",
        }
        return super().render_change_form(request, context, add=add, change=change, form_url=form_url, obj=obj)

    def _build_ai_rewrite_field_targets_json(self, context) -> list[dict[str, object]]:
        adminform = context.get("adminform")
        if adminform is None:
            return []
        rewriteable = get_rewriteable_product_field_names()
        field_names = sorted(set(adminform.form.fields.keys()) & rewriteable)
        return [{"field": name, "label": "AI"} for name in field_names]
```

Ungenutzt gewordene Importe entfernen (`AIRewriteJob`, `AIRewritePrompt`, `AIRewriteService`, `ContentType` — sofern nirgends sonst genutzt; per `grep` prüfen).

- [ ] **Step 4: Button-Template auf Link umstellen**

`templates/admin/products/includes/ai_rewrite_field_buttons.html` ersetzen:

```django
{{ ai_rewrite_field_targets_json|json_script:"product-ai-rewrite-fields" }}

<script>
  (function () {
    "use strict";
    var CREATE_URL = "{{ ai_rewrite_create_url|escapejs }}";
    var PRODUCT_ID = "{{ ai_rewrite_product_id|escapejs }}";

    function getConfig() {
      var node = document.getElementById("product-ai-rewrite-fields");
      if (!node) { return []; }
      try { return JSON.parse(node.textContent || "[]"); } catch (e) { return []; }
    }

    function buildLink(config) {
      var a = document.createElement("a");
      a.href = CREATE_URL + "?product=" + encodeURIComponent(PRODUCT_ID) +
               "&field=" + encodeURIComponent(config.field);
      a.textContent = config.label || "AI";
      a.title = "Rewrite fuer dieses Feld anlegen";
      a.dataset.aiRewriteButton = "true";
      a.className = "ml-3 inline-flex items-center rounded-md border border-primary-200 bg-primary-50 px-2.5 py-1 text-xs font-semibold tracking-wide text-primary-700 transition hover:bg-primary-100 dark:border-primary-900 dark:bg-primary-950/40 dark:text-primary-300";
      return a;
    }

    function appendButtons() {
      if (!CREATE_URL || !PRODUCT_ID) { return; }
      getConfig().forEach(function (config) {
        if (!config.field) { return; }
        var field = document.querySelector('[name="' + CSS.escape(config.field) + '"]');
        if (!field) { return; }
        var label = document.querySelector('label[for="id_' + CSS.escape(config.field) + '"]') ||
                    document.querySelector('label[for="' + CSS.escape(field.id) + '"]');
        var container = label ? (label.parentElement || label) : null;
        if (!container || container.querySelector("[data-ai-rewrite-button='true']")) { return; }
        container.classList.add("flex", "items-center", "gap-2", "flex-wrap");
        container.appendChild(buildLink(config));
      });
    }

    if (document.readyState === "loading") {
      document.addEventListener("DOMContentLoaded", appendButtons);
    } else {
      appendButtons();
    }
  })();
</script>
```

- [ ] **Step 5: Test grün**

Run: `DJANGO_SETTINGS_MODULE=GC_Bridge_4.settings uv run python manage.py test ai.tests.ProductFieldButtonTest -v 2`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add products/admin.py templates/admin/products/includes/ai_rewrite_field_buttons.html
git commit -m "Point product field AI button to new create page via GET link"
```

---

## Task 7: Legacy-Command, Sidebar, Restbereinigung, volle Suite

**Files:**
- Modify: `ai/management/commands/import_legacy_ai_rewrites.py`
- Modify: `GC_Bridge_4/settings.py`
- Modify: `core/tests.py` (falls Sidebar-Erwartungen brechen)
- Test: volle Suite `ai core products`

**Interfaces:** keine neuen; Aufräum-Task.

- [ ] **Step 1: Bestandsaufnahme der Bruchstellen**

```bash
DJANGO_SETTINGS_MODULE=GC_Bridge_4.settings uv run python manage.py check 2>&1 | tail -30
grep -n "airewrite\|AIRewrite\|Rewrite erzeugen" GC_Bridge_4/settings.py
```
Erwartung: `check` meldet ggf. Fehler im Legacy-Command / Sidebar-Referenzen. Liste erstellen.

- [ ] **Step 2: `import_legacy_ai_rewrites.py` stilllegen**

Da der Legacy-Import bereits gelaufen ist und das alte Schema (`source_field`, `provider`, `content_type` an Prompt/Job) nicht mehr existiert, den Command auf einen No-Op mit Hinweis reduzieren:

```python
from __future__ import annotations

from core.management.base import MonitoredBaseCommand


class Command(MonitoredBaseCommand):
    help = "Veraltet: Der Legacy-AI-Rewrite-Import entfaellt nach dem Redesign."

    def handle(self, *args, **options):
        self.stdout.write(
            "Dieser Import ist nach dem AI-Rewriter-Redesign nicht mehr verfuegbar."
        )
```

- [ ] **Step 3: Sidebar in `settings.py` prüfen/anpassen**

Die Einträge um Zeile ~586–604 (`AIRewriteJob` add/view, `AIRewritePrompt`, `AIProviderConfig`) prüfen. „Rewrite erzeugen"-Link zeigte auf das entfernte `ai_airewritejob_request`; falls vorhanden, auf Changelist umbiegen oder Eintrag entfernen (der Einstieg ist jetzt der Feld-Button). Konkret: jeden `reverse("admin:ai_airewritejob_request")`-Bezug entfernen/ersetzen durch `admin:ai_airewritejob_changelist`.

- [ ] **Step 4: `core/tests.py` Sidebar-Test anpassen**

Der Test um `core/tests.py:267` erwartet ein Sidebar-Item „Rewrite erzeugen". Erwartung an den neuen Zustand anpassen (Titel/Permission/URL) bzw. Assertion entfernen, wenn der Eintrag wegfällt.

- [ ] **Step 5: Tote Referenzen sicherstellen**

```bash
grep -rn "AIRewriteApplyService\|ai_airewritejob_request\|rewrite_job_request\|request_ai_rewrite_for_field\|target_field\|source_field" ai/ products/ core/ GC_Bridge_4/ --include="*.py" --include="*.html" | grep -v __pycache__ | grep -v migrations
```
Erwartung: keine Treffer mehr (außer bewusst in Migrationen). Jeden verbleibenden Treffer beheben.

- [ ] **Step 6: Volle Suite + Systemcheck**

```bash
DJANGO_SETTINGS_MODULE=GC_Bridge_4.settings uv run python manage.py check
DJANGO_SETTINGS_MODULE=GC_Bridge_4.settings uv run python manage.py test ai core products -v 1
```
Expected: `check` ohne Fehler; alle Tests grün.

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "Retire legacy AI import and align sidebar with new rewrite flow"
```

---

## Manuelle Verifikation (nach Task 7, vor Deploy)

Lokal (Devserver + `docker compose up -d db`) im Browser prüfen:
1. Produkt-Detailseite → `AI`-Button an „Beschreibung DE" sichtbar, nicht an SKU/ERP/GTIN.
2. Klick → Create-Seite mit Produkt+Feld vorbelegt, Prompt + KI wählbar.
3. Absenden → Job-Seite zeigt „wird verarbeitet", nach Celery-Durchlauf erscheint Ergebnis (`ready`).
4. Ergebnis editieren → „In Feld übernehmen" → Wert steht im Produktfeld, Job `applied`.
5. Danach Deploy per Version-Tag (Konvention: nächste freie `v1.7.x`).

## Self-Review (durchgeführt)

- **Spec-Abdeckung:** Datenmodell (T1), Prompt-Entkopplung (T1), Status-Lifecycle (T1/T2/T5), async Celery (T3/T4), Create-Flow nur Feld-Button (T4/T6), Job-Arbeitsfläche + Apply (T5), Migration/Datenübernahme (T1), Cleanup Request-Form/Autocomplete/ApplyService (T4/T5), Legacy-Command + Sidebar (T7), Tests (jede Task). Keine offene Spec-Anforderung ohne Task.
- **Placeholder-Scan:** Bewusst offen bleibt nur die reale Migrationsnummer/`dependencies` (T1 Step 4) und die konkreten Sidebar-Zeilen (T7) — beide mit exaktem Ermittlungsbefehl versehen, kein „TODO ohne Anleitung".
- **Typ-Konsistenz:** `create_job/execute/apply`-Signaturen identisch in T2 (Definition), T3 (`execute`), T4 (`create_job`), T5 (`apply`). `run_ai_rewrite_job(job_id)` konsistent in T3/T4. Status-Werte `queued/ready/applied/failed` durchgängig.
