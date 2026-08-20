# Zentrales Regelwerk — Admin-Aktivierung: Implementierungsplan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Die in v1.9.0 eingeführten Regelwerk-Modelle im Django-Admin bedienbar machen — Trigger, Konstanten und Bedingungsgruppen als eigene Admin-Seiten, die neuen `MicrotechOrderRule`-Felder in der Regelmaske, plus Sidebar-Links — ohne den bestehenden JS-Rule-Builder anzufassen.

**Architecture:** Rein additive Admin-Registrierungen in `microtech/admin.py` für die drei neuen Modelle, ein additives Anhängen der vier neuen Felder an das bestehende `MicrotechOrderRuleAdmin`-Fieldset, und neue Unfold-Sidebar-Einträge in `settings.py`. Die fragile `MicrotechOrderRuleConditionForm` und der JS-Builder bleiben unberührt; die verschachtelten Bedingungsgruppen werden über eine dedizierte `MicrotechOrderRuleConditionGroup`-Adminseite (mit Condition-Inline) gepflegt.

**Tech Stack:** Django 5 Admin (django-unfold), `core.admin.BaseAdmin`/`BaseStackedInline`, pytest + pytest-django.

**Spec:** [docs/superpowers/specs/2026-08-19-zentrales-regelwerk-design.md](../specs/2026-08-19-zentrales-regelwerk-design.md) (§6 Builder; diese Stufe ist die Admin-Vorstufe davor)

## Global Constraints

- **Nicht-Regression (HART):** Der bestehende `MicrotechOrderRuleAdmin` inkl. JS-Builder (`order_rule_builder.js`), `MicrotechOrderRuleConditionForm` und `MicrotechOrderRuleActionForm` dürfen **nicht** geändert werden, außer dem rein additiven Anhängen von vier Feldnamen an ein Fieldset (Task 4). Keine Änderung an Engine-Code oder Migrationen.
- **Engine bleibt abgeschaltet:** Diese Stufe macht Daten editierbar; sie verdrahtet die Engine NICHT in Produktionspfade. `engine_enabled`/`shadow_mode`-Defaults bleiben wie in v1.9.0.
- **Basisklassen:** Admin-Klassen erben von `core.admin.BaseAdmin`; Inlines von `core.admin.BaseStackedInline` (wie die bestehenden Admins in `microtech/admin.py`).
- **Sprache:** deutsche `verbose_name`/Labels, englische Identifier.
- **Python:** `.venv/bin/python`. **Tests:** `.venv/bin/python -m pytest <file> -v` (Postgres-Test-DB via `docker compose up -d db` läuft; sonst starten).
- **Keine `Co-Authored-By`-Zeilen** in Commits.

---

## Dateistruktur

Modifiziert:
- `microtech/admin.py` — 3 neue `@admin.register`-Klassen + additives Fieldset in `MicrotechOrderRuleAdmin`
- `GC_Bridge_4/settings.py` — neue Unfold-Sidebar-Einträge
- Test: `microtech/test_rule_engine_admin.py` (neu) — Admin-Smoke-Tests

Die Modelle (`RuleTrigger`, `RuleConstant`, `MicrotechOrderRuleConditionGroup`, `MicrotechOrderRuleCondition.group/expected_value_2`) existieren bereits (v1.9.0).

---

## Task 1: Admin für `RuleTrigger`

**Files:**
- Modify: `microtech/admin.py` (neue Klasse am Dateiende; Import ergänzen)
- Test: `microtech/test_rule_engine_admin.py`

**Interfaces:**
- Consumes: `RuleTrigger` (bereits in `microtech.models`).
- Produces: registrierter Admin unter `admin:microtech_ruletrigger_changelist` / `_add` / `_change`.

- [ ] **Step 1: Failing test**

```python
# microtech/test_rule_engine_admin.py
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from microtech.models import RuleTrigger


class RuleTriggerAdminTest(TestCase):
    def setUp(self):
        self.admin = get_user_model().objects.create_superuser(
            username="root", email="root@example.com", password="pw")
        self.client.force_login(self.admin)

    def test_changelist_and_add_render(self):
        RuleTrigger.objects.create(
            code="order_create", label="Bestellung anlegen",
            task_name="orders.microtech_order_upsert", context_root="orders.Order")
        list_url = reverse("admin:microtech_ruletrigger_changelist")
        add_url = reverse("admin:microtech_ruletrigger_add")
        self.assertEqual(self.client.get(list_url).status_code, 200)
        self.assertEqual(self.client.get(add_url).status_code, 200)
```

- [ ] **Step 2: Run test, verify it fails**

Run: `.venv/bin/python -m pytest microtech/test_rule_engine_admin.py::RuleTriggerAdminTest -v`
Expected: FAIL — `NoReverseMatch` (admin not registered).

- [ ] **Step 3: Implement admin**

Add `RuleTrigger` to the existing `from microtech.models import (...)` block in `microtech/admin.py`, then append:

```python
@admin.register(RuleTrigger)
class RuleTriggerAdmin(BaseAdmin):
    list_display = ("priority", "code", "label", "task_name", "context_root", "is_active", "updated_at")
    list_editable = ("is_active",)
    search_fields = ("code", "label", "task_name", "context_root")
    list_filter = ("is_active", "task_name")
    ordering = ("priority", "id")
    fieldsets = (
        (
            "Trigger",
            {
                "fields": ("is_active", "priority", "code", "label", "task_name", "context_root"),
                "description": (
                    "Ein Geschaefts-Event, das an einen Celery-Task gebunden ist. "
                    "context_root (app_label.Model) definiert den Variablen-Namensraum der Regeln."
                ),
            },
        ),
    )
```

- [ ] **Step 4: Run test → PASS**

Run: `.venv/bin/python -m pytest microtech/test_rule_engine_admin.py::RuleTriggerAdminTest -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add microtech/admin.py microtech/test_rule_engine_admin.py
git commit -m "Register RuleTrigger in admin"
```

---

## Task 2: Admin für `RuleConstant`

**Files:**
- Modify: `microtech/admin.py`
- Test: `microtech/test_rule_engine_admin.py`

**Interfaces:**
- Consumes: `RuleConstant`.
- Produces: `admin:microtech_ruleconstant_changelist` / `_add`.

- [ ] **Step 1: Failing test**

```python
# in microtech/test_rule_engine_admin.py anhaengen
class RuleConstantAdminTest(TestCase):
    def setUp(self):
        self.admin = get_user_model().objects.create_superuser(
            username="root2", email="root2@example.com", password="pw")
        self.client.force_login(self.admin)

    def test_changelist_and_add_render(self):
        from microtech.models import RuleConstant
        RuleConstant.objects.update_or_create(
            key="eu_country_codes", defaults={"value": "DE,IT", "kind": "list"})
        from django.urls import reverse
        self.assertEqual(
            self.client.get(reverse("admin:microtech_ruleconstant_changelist")).status_code, 200)
        self.assertEqual(
            self.client.get(reverse("admin:microtech_ruleconstant_add")).status_code, 200)
```

(Note: `update_or_create` because migration `0033_seed_ruleconstants` already seeds this key in the test DB.)

- [ ] **Step 2: Run test, verify it fails**

Run: `.venv/bin/python -m pytest microtech/test_rule_engine_admin.py::RuleConstantAdminTest -v`
Expected: FAIL — `NoReverseMatch`.

- [ ] **Step 3: Implement admin**

Add `RuleConstant` to the model import block, then append:

```python
@admin.register(RuleConstant)
class RuleConstantAdmin(BaseAdmin):
    list_display = ("key", "kind", "value_short", "updated_at")
    search_fields = ("key", "value")
    list_filter = ("kind",)
    ordering = ("key",)
    fieldsets = (
        (
            "Konstante",
            {
                "fields": ("key", "kind", "value"),
                "description": "Benannte Konstante fuer Resolver und Bedingungen (z. B. EU-Laenderliste).",
            },
        ),
    )

    @admin.display(description="Wert")
    def value_short(self, obj):
        value = (obj.value or "").strip()
        return f"{value[:80]}..." if len(value) > 80 else value
```

- [ ] **Step 4: Run test → PASS**

Run: `.venv/bin/python -m pytest microtech/test_rule_engine_admin.py::RuleConstantAdminTest -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add microtech/admin.py microtech/test_rule_engine_admin.py
git commit -m "Register RuleConstant in admin"
```

---

## Task 3: Admin für `MicrotechOrderRuleConditionGroup` mit Condition-Inline

**Files:**
- Modify: `microtech/admin.py`
- Test: `microtech/test_rule_engine_admin.py`

**Interfaces:**
- Consumes: `MicrotechOrderRuleConditionGroup`, `MicrotechOrderRuleCondition` (mit Feldern `group`, `expected_value_2`).
- Produces: `admin:microtech_microtechorderruleconditiongroup_changelist` / `_add`, mit inline editierbaren Bedingungen (inkl. `expected_value_2`).
- **Wichtig:** Das Inline verwendet KEINE Custom-Form (nicht `MicrotechOrderRuleConditionForm`), sondern die Standard-ModelForm mit expliziter `fields`-Liste — damit die neuen Felder `group`/`expected_value_2` ohne die Builder-Logik editierbar sind und der bestehende Builder unberührt bleibt.

- [ ] **Step 1: Failing test**

```python
# in microtech/test_rule_engine_admin.py anhaengen
class ConditionGroupAdminTest(TestCase):
    def setUp(self):
        self.admin = get_user_model().objects.create_superuser(
            username="root3", email="root3@example.com", password="pw")
        self.client.force_login(self.admin)

    def test_changelist_and_add_render(self):
        from django.urls import reverse
        from microtech.models import MicrotechOrderRule, MicrotechOrderRuleConditionGroup
        rule = MicrotechOrderRule.objects.create(name="R")
        MicrotechOrderRuleConditionGroup.objects.create(
            rule=rule, logic=MicrotechOrderRule.ConditionLogic.ALL)
        self.assertEqual(
            self.client.get(reverse(
                "admin:microtech_microtechorderruleconditiongroup_changelist")).status_code, 200)
        self.assertEqual(
            self.client.get(reverse(
                "admin:microtech_microtechorderruleconditiongroup_add")).status_code, 200)
```

- [ ] **Step 2: Run test, verify it fails**

Run: `.venv/bin/python -m pytest microtech/test_rule_engine_admin.py::ConditionGroupAdminTest -v`
Expected: FAIL — `NoReverseMatch`.

- [ ] **Step 3: Implement admin + inline**

Add `MicrotechOrderRuleConditionGroup` to the model import block, then append:

```python
@admin.register(MicrotechOrderRuleConditionGroup)
class MicrotechOrderRuleConditionGroupAdmin(BaseAdmin):
    class GroupConditionInline(BaseStackedInline):
        model = MicrotechOrderRuleCondition
        fields = (
            "is_active",
            "priority",
            "django_field_path",
            "operator_code",
            "expected_value",
            "expected_value_2",
        )
        extra = 0
        verbose_name = "Bedingung"
        verbose_name_plural = "Bedingungen dieser Gruppe"

    list_display = ("id", "rule", "logic", "parent", "is_active", "priority", "updated_at")
    list_filter = ("logic", "is_active", "rule")
    search_fields = ("rule__name",)
    ordering = ("rule", "priority", "id")
    autocomplete_fields = ("rule", "parent")
    inlines = (GroupConditionInline,)
    fieldsets = (
        (
            "Bedingungsgruppe",
            {
                "fields": ("rule", "parent", "logic", "is_active", "priority"),
                "description": (
                    "Verschachtelbare UND/ODER-Gruppe. 'parent' leer = Wurzelgruppe der Regel. "
                    "Bedingungen dieser Gruppe unten. django_field_path/operator_code als Klartext "
                    "(z. B. 'billing_address__country_code', Operator 'eq'/'between'/'before')."
                ),
            },
        ),
    )
```

Note on `autocomplete_fields = ("rule", "parent")`: this requires `MicrotechOrderRuleAdmin` and this group admin to expose `search_fields` (rule admin already has `search_fields = ("name",)`; this group admin defines `search_fields` above for the `parent` self-reference). If the autocomplete raises `admin.E040` at check time, replace `autocomplete_fields` with `raw_id_fields = ("rule", "parent")` and note it in the report.

- [ ] **Step 4: Run test → PASS + admin check**

Run: `.venv/bin/python manage.py check 2>&1 | tail -3 && .venv/bin/python -m pytest microtech/test_rule_engine_admin.py::ConditionGroupAdminTest -v`
Expected: `check` clean, test PASS.

- [ ] **Step 5: Commit**

```bash
git add microtech/admin.py microtech/test_rule_engine_admin.py
git commit -m "Register condition-group admin with condition inline"
```

---

## Task 4: Neue Regel-Felder in `MicrotechOrderRuleAdmin` verdrahten

**Files:**
- Modify: `microtech/admin.py` (nur das "Grundregel"-Fieldset von `MicrotechOrderRuleAdmin`)
- Test: `microtech/test_rule_engine_admin.py`

**Interfaces:**
- Consumes: `MicrotechOrderRule` Felder `trigger`, `execution_phase`, `shadow_mode`, `engine_enabled` (v1.9.0).
- Produces: diese vier Felder sind in der Regel-Aenderungsmaske sichtbar/editierbar.
- **Additiv:** NUR die `fields`-Tupel des ersten Fieldsets ("Grundregel") wird erweitert. Keine andere Zeile von `MicrotechOrderRuleAdmin` aendern.

- [ ] **Step 1: Failing test**

```python
# in microtech/test_rule_engine_admin.py anhaengen
class OrderRuleAdminEngineFieldsTest(TestCase):
    def setUp(self):
        self.admin = get_user_model().objects.create_superuser(
            username="root4", email="root4@example.com", password="pw")
        self.client.force_login(self.admin)

    def test_change_form_exposes_new_engine_fields(self):
        from django.urls import reverse
        from microtech.models import MicrotechOrderRule
        rule = MicrotechOrderRule.objects.create(name="R")
        html = self.client.get(
            reverse("admin:microtech_microtechorderrule_change", args=(rule.pk,))).content.decode()
        for field in ("trigger", "execution_phase", "shadow_mode", "engine_enabled"):
            self.assertIn(f'name="{field}"', html)
```

- [ ] **Step 2: Run test, verify it fails**

Run: `.venv/bin/python -m pytest microtech/test_rule_engine_admin.py::OrderRuleAdminEngineFieldsTest -v`
Expected: FAIL — the four fields are not in the form.

- [ ] **Step 3: Extend the "Grundregel" fieldset**

In `MicrotechOrderRuleAdmin.fieldsets`, the first section currently is:

```python
        (
            "Grundregel",
            {
                "fields": ("name", "is_active", "priority", "condition_logic"),
                "description": (
                    "Prioritaet steuert die Reihenfolge. Die erste passende aktive Regel gewinnt."
                ),
            },
        ),
```

Replace ONLY its `"fields"` tuple with:

```python
                "fields": (
                    "name",
                    "is_active",
                    "priority",
                    "condition_logic",
                    "trigger",
                    "execution_phase",
                    "engine_enabled",
                    "shadow_mode",
                ),
```

Leave the description and every other fieldset/attribute unchanged. `trigger` renders as a standard select; do NOT add it to `autocomplete_fields` (that would require extra wiring and risks touching builder behavior).

- [ ] **Step 4: Run test → PASS + non-regression check**

Run: `.venv/bin/python manage.py check 2>&1 | tail -3 && .venv/bin/python -m pytest microtech/test_rule_engine_admin.py::OrderRuleAdminEngineFieldsTest microtech/test_admin_rulebuilder.py microtech/test_rule_forms.py -q`
Expected: `check` clean; new test PASS; existing rule-builder/form tests still PASS (non-regression).

- [ ] **Step 5: Commit**

```bash
git add microtech/admin.py microtech/test_rule_engine_admin.py
git commit -m "Expose trigger, phase, shadow and engine flags in rule admin"
```

---

## Task 5: Unfold-Sidebar-Links für die neuen Admin-Seiten

**Files:**
- Modify: `GC_Bridge_4/settings.py` (UNFOLD navigation)
- Test: manuelle Sichtprüfung + `manage.py check` (Sidebar ist Konfiguration, kein sinnvoller Unit-Test)

**Interfaces:**
- Consumes: die registrierten Admins aus Tasks 1–3.
- Produces: klickbare Sidebar-Eintraege fuer Trigger, Bedingungsgruppen und Konstanten, gruppiert nahe den bestehenden Microtech-Bestellregel-Eintraegen.

- [ ] **Step 1: Locate the existing rule links**

Run: `grep -n "microtech_microtechorderrule_changelist\|Bestellregel" GC_Bridge_4/settings.py`
This shows the sidebar section (around line 703) where the existing `MicrotechOrderRule` / operator / policy links live. The new entries go into the SAME `"items"` list, right after the existing rule-related entries.

- [ ] **Step 2: Add three sidebar entries**

Insert these three dicts into that `"items"` list (match the surrounding dict shape exactly — copy an adjacent entry and adjust `title`/`icon`/`link`/`permission`):

```python
                    {
                        "title": _("Regel-Trigger"),
                        "icon": "bolt",
                        "link": reverse_lazy("admin:microtech_ruletrigger_changelist"),
                        "permission": sidebar_model_view_permission("microtech", "RuleTrigger"),
                    },
                    {
                        "title": _("Bedingungsgruppen"),
                        "icon": "account_tree",
                        "link": reverse_lazy("admin:microtech_microtechorderruleconditiongroup_changelist"),
                        "permission": sidebar_model_view_permission("microtech", "MicrotechOrderRuleConditionGroup"),
                    },
                    {
                        "title": _("Regel-Konstanten"),
                        "icon": "data_object",
                        "link": reverse_lazy("admin:microtech_ruleconstant_changelist"),
                        "permission": sidebar_model_view_permission("microtech", "RuleConstant"),
                    },
```

Use the exact `sidebar_model_view_permission` helper already imported/used in that file (verify its name and signature via `grep -n "sidebar_model_view_permission" GC_Bridge_4/settings.py` before editing; if the surrounding entries use a different permission helper or omit permission, match that pattern instead).

- [ ] **Step 3: Verify config loads**

Run: `.venv/bin/python manage.py check 2>&1 | tail -3`
Expected: `System check identified no issues`. (A broken `reverse_lazy`/permission reference surfaces here.)

- [ ] **Step 4: Commit**

```bash
git add GC_Bridge_4/settings.py
git commit -m "Add sidebar links for rule triggers, condition groups and constants"
```

---

## Self-Review (Plan gegen Spec/Constraints)

- Neue Modelle editierbar (Trigger, Konstanten, Bedingungsgruppen inkl. `expected_value_2`) → Tasks 1–3. ✅
- Neue Regel-Felder sichtbar (trigger/phase/shadow/engine_enabled) → Task 4. ✅
- Auffindbarkeit (Sidebar-Links) → Task 5. ✅
- Nicht-Regression: bestehender Builder/Forms unberührt; Task 4 nur additiv; Task 3 nutzt Standard-ModelForm statt der Builder-Form; Non-Regression-Tests in Task 4 Step 4. ✅
- Engine bleibt abgeschaltet; keine Produktions-Verdrahtung. ✅

## Bewusst NICHT in diesem Plan (Folge-Pläne)

- Grafischer vertikaler Block-Builder (Spec §6, Mockup) — Plan 3.
- Variablen-Picker-Autocomplete über Trigger-Kontext-Feldpfade — Plan 3.
- Verschachtelte Gruppen-im-Regelformular (nested inlines) — der Django-Admin kann das nicht nativ; kommt mit dem Block-Builder (Plan 3). Bis dahin: Gruppen über die dedizierte ConditionGroup-Adminseite pflegen.
- Webshop-Defaults-Pilot & YAML-Ablösung (Schatten-Modus → Cutover) — Plan 4.
