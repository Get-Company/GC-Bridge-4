# Zentrales Regelwerk — Backend-Fundament: Implementierungsplan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Das Datenmodell, die Ausführungs-Engine und die Alt-Regel-Migration für das zentrale Regelwerk bauen — vollständig per pytest testbar, ohne UI, ohne Eingriff in die produktiven Upsert-Pfade.

**Architecture:** Erweiterung der bestehenden `MicrotechOrderRule`-Modelle um Trigger, verschachtelte Bedingungsgruppen und Template-Aktionswerte. Eine neue, isolierte Engine unter `microtech/rule_engine/` löst Templates (`{{ a | b | funktion }}`, `{{ @resolver }}`) auf, wertet den Bedingungsbaum rekursiv aus und stellt Trigger-Dispatch mit Schatten-Modus bereit. Der bestehende `order_rule_resolver.py` bleibt unangetastet aktiv; die neue Engine läuft additiv.

**Tech Stack:** Django 5, pytest + pytest-django (Django `TestCase`), loguru. Kein Frontend, keine neuen externen Abhängigkeiten.

**Spec:** [docs/superpowers/specs/2026-08-19-zentrales-regelwerk-design.md](../specs/2026-08-19-zentrales-regelwerk-design.md) · Begleitinventar [2026-08-19-hardcoded-regeln-inventar.md](../specs/2026-08-19-hardcoded-regeln-inventar.md)

## Global Constraints

- **Nicht-Regression (HART):** Kein bestehender Pfad darf sich ändern. Diese Plan-Stufe fügt nur additiv hinzu; `order_rule_resolver.py`, `customer_upsert_microtech.py`, `webshop_mapping.py` werden **nicht** modifiziert.
- **Basisklasse:** Alle neuen Modelle erben von `core.models.BaseModel` (liefert `created_at`, `updated_at`).
- **Migrationen** starten bei `microtech/migrations/0027_...` (letzte vorhandene: `0026_alter_microtechorderruleaction_action_type.py`).
- **Tests:** liegen als `microtech/test_*.py` (flach, wie bestehend). Ausführung: `python -m pytest microtech/test_<name>.py -v`. `DJANGO_SETTINGS_MODULE` ist in `pyproject.toml` gesetzt. Django `TestCase` verwenden (DB-Zugriff).
- **Sprache:** `verbose_name`/Kommentare deutsch, Code-Identifier englisch (Projektkonvention).
- **Feldpfade** nutzen `__` als Segmenttrenner (wie `resolve_django_field_value`, z. B. `billing_address__country_code`).
- **Keine Co-Authored-By-Zeilen** in Commits.

---

## Dateistruktur

Neu:
- `microtech/rule_engine/__init__.py` — Re-Exports der öffentlichen Engine-API
- `microtech/rule_engine/context.py` — `EvaluationContext` (Wurzelinstanz + Feldauflösung)
- `microtech/rule_engine/transforms.py` — Transform-Whitelist (`anrede_de`, `anrede_kontakt`, `upper`, `split`)
- `microtech/rule_engine/resolvers.py` — benannte Resolver-Registry (`@steuerkategorie`, `@na1`)
- `microtech/rule_engine/templates.py` — Template-Auflösung (`{{ a | b | fn }}`, `{{ @resolver }}`, Konstanten)
- `microtech/rule_engine/operators.py` — Operator-Handler inkl. `between/before/after/is_true/is_false`
- `microtech/rule_engine/evaluation.py` — rekursive Bedingungsbaum-Auswertung
- `microtech/rule_engine/dispatch.py` — Trigger-Dispatch, Phase, Schatten-Modus, Diff-Log
- Tests: `microtech/test_rule_engine_*.py`

Modifiziert:
- `microtech/models.py` — neue Modelle + Feld-Erweiterungen
- `microtech/migrations/0027..` — Schema- und Datenmigrationen

---

## Task 1: Modell `RuleTrigger`

**Files:**
- Modify: `microtech/models.py` (neues Modell am Dateiende vor keinem `__all__` — Datei hat keins)
- Create: `microtech/migrations/0027_ruletrigger.py` (via `makemigrations`)
- Test: `microtech/test_rule_engine_models.py`

**Interfaces:**
- Produces: `RuleTrigger(code, label, task_name, context_root, is_active, priority)` mit Manager-Methode `RuleTrigger.for_task(task_name) -> QuerySet`.

- [ ] **Step 1: Failing test**

```python
# microtech/test_rule_engine_models.py
from django.test import TestCase
from microtech.models import RuleTrigger


class RuleTriggerModelTest(TestCase):
    def test_for_task_returns_active_triggers_for_task_name(self):
        RuleTrigger.objects.create(
            code="order_create", label="Bestellung anlegen",
            task_name="orders.microtech_order_upsert", context_root="orders.Order",
        )
        RuleTrigger.objects.create(
            code="inactive", label="Aus", task_name="orders.microtech_order_upsert",
            context_root="orders.Order", is_active=False,
        )
        result = list(RuleTrigger.for_task("orders.microtech_order_upsert"))
        self.assertEqual([t.code for t in result], ["order_create"])
```

- [ ] **Step 2: Run test, verify it fails**

Run: `python -m pytest microtech/test_rule_engine_models.py::RuleTriggerModelTest -v`
Expected: FAIL — `ImportError: cannot import name 'RuleTrigger'`

- [ ] **Step 3: Implement model**

```python
# microtech/models.py  (anfügen)
class RuleTriggerQuerySet(models.QuerySet):
    def for_task(self, task_name):
        return self.filter(is_active=True, task_name=task_name).order_by("priority", "id")


class RuleTrigger(BaseModel):
    code = models.CharField(max_length=64, unique=True, verbose_name=_("Code"))
    label = models.CharField(max_length=255, verbose_name=_("Bezeichnung"))
    task_name = models.CharField(max_length=128, db_index=True, verbose_name=_("Celery Task"))
    context_root = models.CharField(max_length=128, verbose_name=_("Kontext-Wurzel (app_label.Model)"))
    is_active = models.BooleanField(default=True, verbose_name=_("Aktiv"))
    priority = models.PositiveIntegerField(default=100, verbose_name=_("Prioritaet"))

    objects = RuleTriggerQuerySet.as_manager()

    class Meta:
        verbose_name = _("Regel-Trigger")
        verbose_name_plural = _("Regel-Trigger")
        ordering = ("priority", "id")

    def __str__(self) -> str:
        return f"{self.label} ({self.code})"

    @classmethod
    def for_task(cls, task_name):
        return cls.objects.for_task(task_name)
```

- [ ] **Step 4: Make migration + run test**

Run: `python manage.py makemigrations microtech && python -m pytest microtech/test_rule_engine_models.py::RuleTriggerModelTest -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add microtech/models.py microtech/migrations/0027_ruletrigger.py microtech/test_rule_engine_models.py
git commit -m "Add RuleTrigger model for central rule engine"
```

---

## Task 2: `MicrotechOrderRule` erweitern (trigger, phase, shadow, engine-flag)

**Files:**
- Modify: `microtech/models.py` (Klasse `MicrotechOrderRule`, nach `condition_logic`)
- Create: `microtech/migrations/0028_orderrule_trigger_phase_shadow.py`
- Test: `microtech/test_rule_engine_models.py`

**Interfaces:**
- Consumes: `RuleTrigger` (Task 1).
- Produces: `MicrotechOrderRule.trigger` (FK, null), `.execution_phase` (`"before"`/`"after"`), `.shadow_mode` (bool), `.engine_enabled` (bool). Neue Enum `MicrotechOrderRule.ExecutionPhase`.

- [ ] **Step 1: Failing test**

```python
class OrderRuleEngineFieldsTest(TestCase):
    def test_new_engine_fields_have_safe_defaults(self):
        from microtech.models import MicrotechOrderRule
        rule = MicrotechOrderRule.objects.create(name="R")
        self.assertEqual(rule.execution_phase, MicrotechOrderRule.ExecutionPhase.BEFORE)
        self.assertTrue(rule.shadow_mode)          # Einführung: Schatten an
        self.assertFalse(rule.engine_enabled)      # Einführung: neue Engine aus
        self.assertIsNone(rule.trigger)
```

- [ ] **Step 2: Run test, verify it fails**

Run: `python -m pytest microtech/test_rule_engine_models.py::OrderRuleEngineFieldsTest -v`
Expected: FAIL — `AttributeError: ... 'execution_phase'`

- [ ] **Step 3: Implement fields**

```python
# in class MicrotechOrderRule, neue Enum + Felder
    class ExecutionPhase(models.TextChoices):
        BEFORE = "before", _("Vor dem Task")
        AFTER = "after", _("Nach dem Task")

    trigger = models.ForeignKey(
        "RuleTrigger", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="rules", verbose_name=_("Trigger"),
    )
    execution_phase = models.CharField(
        max_length=16, choices=ExecutionPhase.choices,
        default=ExecutionPhase.BEFORE, verbose_name=_("Ausfuehrungsphase"),
    )
    shadow_mode = models.BooleanField(default=True, verbose_name=_("Schatten-Modus"))
    engine_enabled = models.BooleanField(default=False, verbose_name=_("Neue Engine aktiv"))
```

- [ ] **Step 4: Migration + run**

Run: `python manage.py makemigrations microtech && python -m pytest microtech/test_rule_engine_models.py::OrderRuleEngineFieldsTest -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add microtech/models.py microtech/migrations/0028_*.py microtech/test_rule_engine_models.py
git commit -m "Add trigger, phase, shadow and engine flags to MicrotechOrderRule"
```

---

## Task 3: Bedingungsbaum — `MicrotechOrderRuleConditionGroup` + `Condition.group`/`expected_value_2`

**Files:**
- Modify: `microtech/models.py`
- Create: `microtech/migrations/0029_conditiongroup.py`
- Test: `microtech/test_rule_engine_models.py`

**Interfaces:**
- Consumes: `MicrotechOrderRule` (Task 2), `MicrotechOrderRuleCondition` (bestehend).
- Produces: `MicrotechOrderRuleConditionGroup(rule, parent, logic, priority, is_active)` mit `logic` aus `ConditionLogic` (bestehend, `ALL`/`ANY`); `MicrotechOrderRuleCondition.group` (FK, null), `.expected_value_2` (CharField).

- [ ] **Step 1: Failing test**

```python
class ConditionGroupModelTest(TestCase):
    def test_nested_groups_and_second_value(self):
        from microtech.models import (
            MicrotechOrderRule, MicrotechOrderRuleConditionGroup, MicrotechOrderRuleCondition,
        )
        rule = MicrotechOrderRule.objects.create(name="R")
        root = MicrotechOrderRuleConditionGroup.objects.create(
            rule=rule, logic=MicrotechOrderRule.ConditionLogic.ALL,
        )
        sub = MicrotechOrderRuleConditionGroup.objects.create(
            rule=rule, parent=root, logic=MicrotechOrderRule.ConditionLogic.ANY,
        )
        cond = MicrotechOrderRuleCondition.objects.create(
            rule=rule, group=sub, django_field_path="total",
            operator_code="between", expected_value="500", expected_value_2="9999",
        )
        self.assertEqual(list(root.children.all()), [sub])
        self.assertEqual(cond.group, sub)
        self.assertEqual(cond.expected_value_2, "9999")
```

- [ ] **Step 2: Run test, verify it fails**

Run: `python -m pytest microtech/test_rule_engine_models.py::ConditionGroupModelTest -v`
Expected: FAIL — `ImportError` / `AttributeError: 'group'`

- [ ] **Step 3: Implement model + fields**

```python
# neues Modell
class MicrotechOrderRuleConditionGroup(BaseModel):
    rule = models.ForeignKey(
        MicrotechOrderRule, on_delete=models.CASCADE,
        related_name="condition_groups", verbose_name=_("Regel"),
    )
    parent = models.ForeignKey(
        "self", on_delete=models.CASCADE, null=True, blank=True,
        related_name="children", verbose_name=_("Uebergeordnete Gruppe"),
    )
    logic = models.CharField(
        max_length=16, choices=MicrotechOrderRule.ConditionLogic.choices,
        default=MicrotechOrderRule.ConditionLogic.ALL, verbose_name=_("Logik"),
    )
    is_active = models.BooleanField(default=True, verbose_name=_("Aktiv"))
    priority = models.PositiveIntegerField(default=100, verbose_name=_("Prioritaet"))

    class Meta:
        verbose_name = _("Bedingungsgruppe")
        verbose_name_plural = _("Bedingungsgruppen")
        ordering = ("rule", "priority", "id")

    def __str__(self) -> str:
        return f"{self.rule_id} | Gruppe {self.pk} ({self.logic})"

# in class MicrotechOrderRuleCondition ergaenzen:
    group = models.ForeignKey(
        "MicrotechOrderRuleConditionGroup", on_delete=models.CASCADE,
        null=True, blank=True, related_name="conditions", verbose_name=_("Gruppe"),
    )
    expected_value_2 = models.CharField(
        max_length=255, blank=True, default="", verbose_name=_("Vergleichswert 2"),
    )
```

- [ ] **Step 4: Migration + run**

Run: `python manage.py makemigrations microtech && python -m pytest microtech/test_rule_engine_models.py::ConditionGroupModelTest -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add microtech/models.py microtech/migrations/0029_*.py microtech/test_rule_engine_models.py
git commit -m "Add nested condition groups and second comparison value"
```

---

## Task 4: Neue Operatoren im Enum + Katalog-Seed

**Files:**
- Modify: `microtech/models.py` (`MicrotechOrderRuleOperator.EngineOperator`)
- Create: `microtech/migrations/0030_seed_engine_operators.py` (Datenmigration)
- Test: `microtech/test_rule_engine_operators.py`

**Interfaces:**
- Produces: Enum-Werte `BETWEEN="between"`, `BEFORE="before"`, `AFTER="after"`, `IS_TRUE="is_true"`, `IS_FALSE="is_false"`; Katalogzeilen in `MicrotechOrderRuleOperator` mit passenden `code`/`engine_operator`.

- [ ] **Step 1: Failing test**

```python
# microtech/test_rule_engine_operators.py
from django.test import TestCase
from django.core.management import call_command


class EngineOperatorSeedTest(TestCase):
    def test_new_operators_present_in_enum(self):
        from microtech.models import MicrotechOrderRuleOperator as Op
        codes = {c for c, _ in Op.EngineOperator.choices}
        self.assertTrue({"between", "before", "after", "is_true", "is_false"} <= codes)
```

- [ ] **Step 2: Run test, verify it fails**

Run: `python -m pytest microtech/test_rule_engine_operators.py::EngineOperatorSeedTest -v`
Expected: FAIL — set not subset

- [ ] **Step 3: Extend enum + data migration**

```python
# in class MicrotechOrderRuleOperator.EngineOperator ergaenzen:
        BETWEEN = "between", _("zwischen")
        BEFORE = "before", _("vor")
        AFTER = "after", _("nach")
        IS_TRUE = "is_true", _("ist wahr")
        IS_FALSE = "is_false", _("ist falsch")
```

```python
# microtech/migrations/0030_seed_engine_operators.py
from django.db import migrations

NEW = [
    ("between", "zwischen (between)", "between", 60),
    ("before", "vor (before)", "before", 61),
    ("after", "nach (after)", "after", 62),
    ("is_true", "ist wahr", "is_true", 63),
    ("is_false", "ist falsch", "is_false", 64),
]

def seed(apps, schema_editor):
    Op = apps.get_model("microtech", "MicrotechOrderRuleOperator")
    for code, name, engine, prio in NEW:
        Op.objects.get_or_create(
            code=code,
            defaults={"name": name, "engine_operator": engine, "priority": prio, "is_active": True},
        )

def unseed(apps, schema_editor):
    Op = apps.get_model("microtech", "MicrotechOrderRuleOperator")
    Op.objects.filter(code__in=[c for c, *_ in NEW]).delete()

class Migration(migrations.Migration):
    dependencies = [("microtech", "0029_conditiongroup")]
    operations = [migrations.RunPython(seed, unseed)]
```

Hinweis: Die Enum-Erweiterung erzeugt ggf. eine automatische `AlterField`-Migration — diese zuerst `makemigrations`, dann die Datenmigration darauf aufsetzen. Abhängigkeitsnummer entsprechend anpassen.

- [ ] **Step 4: Run**

Run: `python manage.py makemigrations microtech && python -m pytest microtech/test_rule_engine_operators.py::EngineOperatorSeedTest -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add microtech/models.py microtech/migrations/0030_*.py microtech/migrations/003*_alter*.py microtech/test_rule_engine_operators.py
git commit -m "Add between/before/after/is_true/is_false operators"
```

---

## Task 5: Transform-Whitelist

**Files:**
- Create: `microtech/rule_engine/__init__.py` (leer, wird in Task 8/12 gefüllt)
- Create: `microtech/rule_engine/transforms.py`
- Test: `microtech/test_rule_engine_transforms.py`

**Interfaces:**
- Produces: `apply_transform(name: str, value: str, arg: str = "") -> str` und `TRANSFORMS: dict[str, callable]`. Bekannte Namen: `upper`, `lower`, `strip`, `split` (arg = Index), `anrede_de`, `anrede_kontakt`. Unbekannter Name → `KeyError`.

- [ ] **Step 1: Failing test**

```python
# microtech/test_rule_engine_transforms.py
from django.test import TestCase
from microtech.rule_engine.transforms import apply_transform


class TransformTest(TestCase):
    def test_anrede_de_normalises_salutation(self):
        self.assertEqual(apply_transform("anrede_de", "mrs"), "Frau")
        self.assertEqual(apply_transform("anrede_de", "hr"), "Herr")
        self.assertEqual(apply_transform("anrede_de", "xyz"), "")

    def test_anrede_kontakt_uses_accusative_for_herr(self):
        self.assertEqual(apply_transform("anrede_kontakt", "herr"), "Herrn")
        self.assertEqual(apply_transform("anrede_kontakt", "frau"), "Frau")

    def test_split_returns_indexed_token(self):
        self.assertEqual(apply_transform("split", "Max Mustermann", "0"), "Max")
        self.assertEqual(apply_transform("split", "Max Mustermann", "1"), "Mustermann")
        self.assertEqual(apply_transform("split", "Max", "1"), "")

    def test_unknown_transform_raises(self):
        with self.assertRaises(KeyError):
            apply_transform("nope", "x")
```

- [ ] **Step 2: Run test, verify it fails**

Run: `python -m pytest microtech/test_rule_engine_transforms.py -v`
Expected: FAIL — `ModuleNotFoundError: microtech.rule_engine.transforms`

- [ ] **Step 3: Implement**

```python
# microtech/rule_engine/transforms.py
from __future__ import annotations

# Wiederverwendung der bestehenden, getesteten Anrede-Normalisierung.
from customer.services.webshop_mapping import CustomerWebshopMappingService as _WS


def _anrede_de(value: str, arg: str = "") -> str:
    return _WS.translate_salutation_to_de(value)


def _anrede_kontakt(value: str, arg: str = "") -> str:
    salutation = _WS.translate_salutation_to_de(value)
    if salutation == "Herr":
        return "Herrn"
    return salutation


def _split(value: str, arg: str = "") -> str:
    try:
        index = int(arg)
    except (TypeError, ValueError):
        index = 0
    tokens = str(value).split(" ", 1)
    return tokens[index] if 0 <= index < len(tokens) else ""


TRANSFORMS = {
    "upper": lambda v, a="": str(v).upper(),
    "lower": lambda v, a="": str(v).lower(),
    "strip": lambda v, a="": str(v).strip(),
    "split": _split,
    "anrede_de": _anrede_de,
    "anrede_kontakt": _anrede_kontakt,
}


def apply_transform(name: str, value: str, arg: str = "") -> str:
    func = TRANSFORMS[name]   # KeyError bei unbekanntem Namen (gewollt)
    return func(value, arg)
```

- [ ] **Step 4: Run**

Run: `python -m pytest microtech/test_rule_engine_transforms.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add microtech/rule_engine/__init__.py microtech/rule_engine/transforms.py microtech/test_rule_engine_transforms.py
git commit -m "Add transform whitelist for rule engine templates"
```

---

## Task 6: Konstanten-Katalog `RuleConstant` + Seed

**Files:**
- Modify: `microtech/models.py`
- Create: `microtech/migrations/0031_ruleconstant.py` (Modell)
- Create: `microtech/migrations/0032_seed_ruleconstants.py` (Seed: EU-Länder, IT-B2B-Gruppe)
- Test: `microtech/test_rule_engine_models.py`

**Interfaces:**
- Produces: `RuleConstant(key, value, kind)` mit `kind in {"scalar","list"}`; Helper `RuleConstant.get_list(key) -> list[str]` und `RuleConstant.get_scalar(key) -> str`.

- [ ] **Step 1: Failing test**

```python
class RuleConstantTest(TestCase):
    def test_seeded_eu_countries_and_it_group(self):
        from microtech.models import RuleConstant
        eu = RuleConstant.get_list("eu_country_codes")
        self.assertIn("DE", eu)
        self.assertIn("IT", eu)
        self.assertTrue(RuleConstant.get_scalar("italian_b2b_group"))
```

- [ ] **Step 2: Run test, verify it fails**

Run: `python -m pytest microtech/test_rule_engine_models.py::RuleConstantTest -v`
Expected: FAIL — `ImportError: RuleConstant`

- [ ] **Step 3: Implement model + seed**

```python
# microtech/models.py
class RuleConstant(BaseModel):
    class Kind(models.TextChoices):
        SCALAR = "scalar", _("Einzelwert")
        LIST = "list", _("Liste (komma-separiert)")

    key = models.CharField(max_length=64, unique=True, verbose_name=_("Schluessel"))
    value = models.TextField(blank=True, default="", verbose_name=_("Wert"))
    kind = models.CharField(max_length=16, choices=Kind.choices, default=Kind.SCALAR, verbose_name=_("Art"))

    class Meta:
        verbose_name = _("Regel-Konstante")
        verbose_name_plural = _("Regel-Konstanten")
        ordering = ("key",)

    def __str__(self) -> str:
        return self.key

    @classmethod
    def get_scalar(cls, key: str) -> str:
        obj = cls.objects.filter(key=key).first()
        return (obj.value or "").strip() if obj else ""

    @classmethod
    def get_list(cls, key: str) -> list[str]:
        raw = cls.get_scalar(key)
        return [part.strip() for part in raw.split(",") if part.strip()]
```

Seed-Werte (Datenmigration `0032`): EU-Länderliste aus `customer/services/webshop_mapping.py`-Nachbarschaft übernehmen (`_EU_COUNTRY_CODES`) und `italian_b2b_group` aus `_ITALIAN_B2B_GROUP`. Beide Konstanten dort per `grep` verifizieren und **exakt** kopieren.

```python
# microtech/migrations/0032_seed_ruleconstants.py
from django.db import migrations
from customer.services.webshop_mapping import _EU_COUNTRY_CODES, _ITALIAN_B2B_GROUP

def seed(apps, schema_editor):
    C = apps.get_model("microtech", "RuleConstant")
    C.objects.get_or_create(key="eu_country_codes",
        defaults={"value": ",".join(sorted(_EU_COUNTRY_CODES)), "kind": "list"})
    C.objects.get_or_create(key="italian_b2b_group",
        defaults={"value": _ITALIAN_B2B_GROUP, "kind": "scalar"})

def unseed(apps, schema_editor):
    C = apps.get_model("microtech", "RuleConstant")
    C.objects.filter(key__in=["eu_country_codes", "italian_b2b_group"]).delete()

class Migration(migrations.Migration):
    dependencies = [("microtech", "0031_ruleconstant")]
    operations = [migrations.RunPython(seed, unseed)]
```

Vor Umsetzung prüfen: `grep -n "_EU_COUNTRY_CODES\|_ITALIAN_B2B_GROUP" customer/services/webshop_mapping.py` — Namen/Export sicherstellen; falls nicht importierbar, Werte in die Migration inline kopieren.

- [ ] **Step 4: Migration + run**

Run: `python manage.py makemigrations microtech && python -m pytest microtech/test_rule_engine_models.py::RuleConstantTest -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add microtech/models.py microtech/migrations/0031_*.py microtech/migrations/0032_*.py microtech/test_rule_engine_models.py
git commit -m "Add RuleConstant catalog with EU and Italian-B2B seeds"
```

---

## Task 7: `EvaluationContext` (Wurzelinstanz + Feldauflösung)

**Files:**
- Create: `microtech/rule_engine/context.py`
- Test: `microtech/test_rule_engine_context.py`

**Interfaces:**
- Produces: `EvaluationContext(root)` mit `.get(path: str) -> object` (Segmenttrenner `__`, Callables werden aufgerufen, fehlt ein Segment → `None`). Analog zu `resolve_django_field_value`, aber unabhängig von `Order`.

- [ ] **Step 1: Failing test**

```python
# microtech/test_rule_engine_context.py
from django.test import TestCase
from microtech.rule_engine.context import EvaluationContext


class _Addr:
    country_code = "CH"


class _Order:
    total = 750
    billing_address = _Addr()


class ContextTest(TestCase):
    def test_resolves_nested_path(self):
        ctx = EvaluationContext(_Order())
        self.assertEqual(ctx.get("total"), 750)
        self.assertEqual(ctx.get("billing_address__country_code"), "CH")

    def test_missing_segment_returns_none(self):
        ctx = EvaluationContext(_Order())
        self.assertIsNone(ctx.get("billing_address__missing"))
        self.assertIsNone(ctx.get("nope"))
```

- [ ] **Step 2: Run test, verify it fails**

Run: `python -m pytest microtech/test_rule_engine_context.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement**

```python
# microtech/rule_engine/context.py
from __future__ import annotations


class EvaluationContext:
    def __init__(self, root: object):
        self.root = root

    def get(self, path: str) -> object:
        current: object = self.root
        for segment in str(path).split("__"):
            if current is None or not hasattr(current, segment):
                return None
            current = getattr(current, segment)
            if callable(current):
                current = current()
        return current
```

- [ ] **Step 4: Run**

Run: `python -m pytest microtech/test_rule_engine_context.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add microtech/rule_engine/context.py microtech/test_rule_engine_context.py
git commit -m "Add EvaluationContext for rule engine field resolution"
```

---

## Task 8: Benannte Resolver-Registry (`@steuerkategorie`, `@na1`)

**Files:**
- Create: `microtech/rule_engine/resolvers.py`
- Test: `microtech/test_rule_engine_resolvers.py`

**Interfaces:**
- Consumes: `EvaluationContext` (Task 7), `RuleConstant` (Task 6), `CustomerWebshopMappingService`.
- Produces: `resolve_named(name: str, context: EvaluationContext) -> str`; Registry `RESOLVERS`. Bekannt: `steuerkategorie`, `na1`. Unbekannt → `KeyError`. Die Resolver rufen die **bestehende** Logik auf (keine Neuimplementierung).

- [ ] **Step 1: Failing test**

```python
# microtech/test_rule_engine_resolvers.py
from django.test import TestCase
from microtech.models import RuleConstant
from microtech.rule_engine.context import EvaluationContext
from microtech.rule_engine.resolvers import resolve_named


class _Order:
    def __init__(self, country, vat, group):
        self.billing_country_code = country
        self.vat_id = vat
        self.customer_group = group


class ResolverTest(TestCase):
    def setUp(self):
        RuleConstant.objects.create(key="eu_country_codes", value="DE,IT,FR", kind="list")
        RuleConstant.objects.create(key="italian_b2b_group", value="italien-b2b", kind="scalar")

    def test_steuerkategorie_domestic_is_1(self):
        ctx = EvaluationContext(_Order("DE", "", ""))
        self.assertEqual(resolve_named("steuerkategorie", ctx), "1")

    def test_steuerkategorie_swiss_is_2(self):
        ctx = EvaluationContext(_Order("CH", "", ""))
        self.assertEqual(resolve_named("steuerkategorie", ctx), "2")

    def test_unknown_resolver_raises(self):
        with self.assertRaises(KeyError):
            resolve_named("nope", EvaluationContext(_Order("DE", "", "")))
```

- [ ] **Step 2: Run test, verify it fails**

Run: `python -m pytest microtech/test_rule_engine_resolvers.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement**

```python
# microtech/rule_engine/resolvers.py
from __future__ import annotations

from customer.services.webshop_mapping import CustomerWebshopMappingService
from microtech.rule_engine.context import EvaluationContext


def _steuerkategorie(context: EvaluationContext) -> str:
    result = CustomerWebshopMappingService.resolve_tax_category(
        billing_country_code=str(context.get("billing_country_code") or ""),
        vat_id=str(context.get("vat_id") or ""),
        customer_group=str(context.get("customer_group") or ""),
    )
    return str(result)


def _na1(context: EvaluationContext) -> str:
    address = context.get("address")
    if address is None:
        address = context.root
    return CustomerWebshopMappingService.resolve_na1(address=address)


RESOLVERS = {
    "steuerkategorie": _steuerkategorie,
    "na1": _na1,
}


def resolve_named(name: str, context: EvaluationContext) -> str:
    func = RESOLVERS[name]   # KeyError bei unbekanntem Namen (gewollt)
    return str(func(context) or "")
```

Hinweis: `resolve_tax_category` nutzt eine interne EU-Liste. Für diese Plan-Stufe ist es Absicht, die **bestehende** Methode aufzurufen (Parität). Die Ablösung durch `RuleConstant` (falls gewünscht) ist ein späterer, separater Schritt und **nicht** Teil dieses Plans.

- [ ] **Step 4: Run**

Run: `python -m pytest microtech/test_rule_engine_resolvers.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add microtech/rule_engine/resolvers.py microtech/test_rule_engine_resolvers.py
git commit -m "Add named resolver registry reusing existing tax/Na1 logic"
```

---

## Task 9: Template-Auflösung (`{{ a | b | fn }}`, `{{ @resolver }}`, Literale)

**Files:**
- Create: `microtech/rule_engine/templates.py`
- Test: `microtech/test_rule_engine_templates.py`

**Interfaces:**
- Consumes: `EvaluationContext` (Task 7), `apply_transform` (Task 5), `resolve_named` (Task 8).
- Produces: `render_template(template: str, context: EvaluationContext) -> str`. Regeln:
  - Kein `{{ }}` → Literal unverändert.
  - `{{ path }}` → Feldwert (leer → "").
  - `{{ a | b | c }}` innerhalb eines Ausdrucks: Pipe trennt **Fallback-Kette**, ausser der Pipe-Teil ist eine bekannte Transform (dann wird sie auf das Zwischenergebnis angewandt). Konvention: Fallback-Glieder sind Feldpfade/`@resolver`/Literale-in-Anführungszeichen; ist ein Glied ein bekannter Transform-Name (opt. `name:arg`), wird es als Transform behandelt.
  - `{{ @name }}` → benannter Resolver.
  - Gemischt: `"Auftrag {{ Order__nr }}"` → Literal + eingesetzter Wert.

- [ ] **Step 1: Failing test**

```python
# microtech/test_rule_engine_templates.py
from django.test import TestCase
from microtech.models import RuleConstant
from microtech.rule_engine.context import EvaluationContext
from microtech.rule_engine.templates import render_template


class _Order:
    nr = "4711"
    firma = ""
    name = "Mustermann GmbH"
    anrede = "mrs"
    billing_country_code = "DE"
    vat_id = ""
    customer_group = ""


class TemplateTest(TestCase):
    def setUp(self):
        RuleConstant.objects.create(key="eu_country_codes", value="DE,IT", kind="list")
        RuleConstant.objects.create(key="italian_b2b_group", value="it-b2b", kind="scalar")
        self.ctx = EvaluationContext(_Order())

    def test_plain_literal(self):
        self.assertEqual(render_template("Webshop-Kunde", self.ctx), "Webshop-Kunde")

    def test_single_variable(self):
        self.assertEqual(render_template("{{ nr }}", self.ctx), "4711")

    def test_fallback_chain_picks_first_non_empty(self):
        self.assertEqual(render_template("{{ firma | name }}", self.ctx), "Mustermann GmbH")

    def test_transform_applied(self):
        self.assertEqual(render_template("{{ anrede | anrede_de }}", self.ctx), "Frau")

    def test_named_resolver(self):
        self.assertEqual(render_template("{{ @steuerkategorie }}", self.ctx), "1")

    def test_mixed_literal_and_variable(self):
        self.assertEqual(render_template("Auftrag {{ nr }}", self.ctx), "Auftrag 4711")
```

- [ ] **Step 2: Run test, verify it fails**

Run: `python -m pytest microtech/test_rule_engine_templates.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement**

```python
# microtech/rule_engine/templates.py
from __future__ import annotations

import re

from microtech.rule_engine.context import EvaluationContext
from microtech.rule_engine.resolvers import resolve_named
from microtech.rule_engine.transforms import TRANSFORMS, apply_transform

_EXPR = re.compile(r"\{\{(.*?)\}\}")


def _resolve_atom(atom: str, context: EvaluationContext) -> str:
    atom = atom.strip()
    if not atom:
        return ""
    if atom.startswith("@"):
        return resolve_named(atom[1:].strip(), context)
    if len(atom) >= 2 and atom[0] == atom[-1] and atom[0] in {'"', "'"}:
        return atom[1:-1]
    value = context.get(atom)
    return "" if value is None else str(value)


def _eval_expression(expr: str, context: EvaluationContext) -> str:
    parts = [p.strip() for p in expr.split("|")]
    value = ""
    have_value = False
    for part in parts:
        name, _, arg = part.partition(":")
        name = name.strip()
        if have_value and name in TRANSFORMS:
            value = apply_transform(name, value, arg.strip())
            continue
        # Fallback-Glied: nimm ersten nicht-leeren Wert
        candidate = _resolve_atom(part, context)
        if candidate:
            value = candidate
            have_value = True
    return value


def render_template(template: str, context: EvaluationContext) -> str:
    template = "" if template is None else str(template)
    if "{{" not in template:
        return template
    return _EXPR.sub(lambda m: _eval_expression(m.group(1), context), template)
```

- [ ] **Step 4: Run**

Run: `python -m pytest microtech/test_rule_engine_templates.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add microtech/rule_engine/templates.py microtech/test_rule_engine_templates.py
git commit -m "Add template resolver with fallback chains, transforms and resolvers"
```

---

## Task 10: Operator-Handler inkl. `between/before/after/is_true/is_false`

**Files:**
- Create: `microtech/rule_engine/operators.py`
- Test: `microtech/test_rule_engine_operators.py` (Klasse ergänzen)

**Interfaces:**
- Produces: `evaluate_operator(operator, actual_value, expected_raw, expected_raw_2, value_kind) -> bool`. Baut auf der bestehenden Logik in `order_rule_resolver._evaluate_condition` auf (gleiche Typ-Coercion `_to_decimal/_to_date/_to_datetime/_to_bool`), ergänzt die neuen Operatoren. `before`≈`lt`, `after`≈`gt` auf Datum/Zeit; `between` = `expected_raw <= actual <= expected_raw_2`; `is_true`/`is_false` prüfen Bool.

- [ ] **Step 1: Failing test**

```python
# in microtech/test_rule_engine_operators.py ergaenzen
from microtech.rule_engine.operators import evaluate_operator


class OperatorHandlerTest(TestCase):
    def test_between_decimal_inclusive(self):
        self.assertTrue(evaluate_operator("between", "750", "500", "9999", "decimal"))
        self.assertFalse(evaluate_operator("between", "12000", "500", "9999", "decimal"))

    def test_before_after_date(self):
        self.assertTrue(evaluate_operator("before", "2026-01-01", "2026-06-01", "", "date"))
        self.assertTrue(evaluate_operator("after", "2026-12-01", "2026-06-01", "", "date"))

    def test_is_true_is_false(self):
        self.assertTrue(evaluate_operator("is_true", "ja", "", "", "bool"))
        self.assertTrue(evaluate_operator("is_false", "nein", "", "", "bool"))

    def test_eq_delegates_like_legacy(self):
        self.assertTrue(evaluate_operator("eq", "CH", "ch", "", "string"))
```

- [ ] **Step 2: Run test, verify it fails**

Run: `python -m pytest microtech/test_rule_engine_operators.py::OperatorHandlerTest -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement**

```python
# microtech/rule_engine/operators.py
from __future__ import annotations

from orders.services.order_rule_resolver import (
    OrderRuleResolverService, _to_bool, _to_date, _to_datetime, _to_decimal, _to_str,
)


def _between(actual, lo, hi, value_kind) -> bool:
    if value_kind in {"int", "decimal"}:
        a, l, h = _to_decimal(actual), _to_decimal(lo), _to_decimal(hi)
    elif value_kind == "date":
        a, l, h = _to_date(actual), _to_date(lo), _to_date(hi)
    elif value_kind == "datetime":
        a, l, h = _to_datetime(actual), _to_datetime(lo), _to_datetime(hi)
    else:
        a, l, h = _to_str(actual).lower(), _to_str(lo).lower(), _to_str(hi).lower()
    if a is None or l is None or h is None:
        return False
    return l <= a <= h


def evaluate_operator(operator, actual_value, expected_raw, expected_raw_2, value_kind) -> bool:
    if operator == "between":
        return _between(actual_value, expected_raw, expected_raw_2, value_kind)
    if operator == "before":
        return OrderRuleResolverService._evaluate_condition(
            operator="lt", actual_value=actual_value, expected_raw=expected_raw, value_kind=value_kind)
    if operator == "after":
        return OrderRuleResolverService._evaluate_condition(
            operator="gt", actual_value=actual_value, expected_raw=expected_raw, value_kind=value_kind)
    if operator == "is_true":
        return _to_bool(actual_value) is True
    if operator == "is_false":
        return _to_bool(actual_value) is False
    return OrderRuleResolverService._evaluate_condition(
        operator=operator, actual_value=actual_value, expected_raw=expected_raw, value_kind=value_kind)
```

Hinweis: `_to_bool` etc. sind im bestehenden Modul definiert (Task-Referenz: `order_rule_resolver.py:34-84`). Prüfen, dass sie importierbar sind; sonst in `operators.py` spiegeln.

- [ ] **Step 4: Run**

Run: `python -m pytest microtech/test_rule_engine_operators.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add microtech/rule_engine/operators.py microtech/test_rule_engine_operators.py
git commit -m "Add operator handlers for between/before/after/is_true/is_false"
```

---

## Task 11: Rekursive Bedingungsbaum-Auswertung

**Files:**
- Create: `microtech/rule_engine/evaluation.py`
- Test: `microtech/test_rule_engine_evaluation.py`

**Interfaces:**
- Consumes: `EvaluationContext`, `evaluate_operator` (Task 10), `render_template` (Task 9, für Variablen-Vergleichswerte), `get_django_field_map`/`get_operator_engine_map` (bestehend in `microtech.rule_builder`).
- Produces: `evaluate_group(group, context) -> bool` und `rule_matches(rule, context) -> bool`. Leere Wurzelgruppe / keine aktiven Bedingungen → `True` (globaler Fallback, wie heute). Vergleichswerte, die `{{ }}` enthalten, werden vor dem Vergleich per `render_template` aufgelöst.

- [ ] **Step 1: Failing test**

```python
# microtech/test_rule_engine_evaluation.py
from django.test import TestCase
from microtech.models import (
    MicrotechOrderRule, MicrotechOrderRuleConditionGroup, MicrotechOrderRuleCondition,
    MicrotechOrderRuleDjangoField,
)
from microtech.rule_engine.context import EvaluationContext
from microtech.rule_engine.evaluation import rule_matches


class _Order:
    country_code = "CH"
    customer_group = "Haendler"
    total = 750


class EvaluationTest(TestCase):
    def setUp(self):
        for path, kind in [("country_code", "string"), ("customer_group", "string"), ("total", "decimal")]:
            MicrotechOrderRuleDjangoField.objects.create(
                field_path=path, label=path, value_kind=kind)

    def _rule_with_tree(self):
        rule = MicrotechOrderRule.objects.create(name="R")
        root = MicrotechOrderRuleConditionGroup.objects.create(
            rule=rule, logic=MicrotechOrderRule.ConditionLogic.ALL)
        sub = MicrotechOrderRuleConditionGroup.objects.create(
            rule=rule, parent=root, logic=MicrotechOrderRule.ConditionLogic.ANY)
        MicrotechOrderRuleCondition.objects.create(
            rule=rule, group=root, django_field_path="country_code",
            operator_code="eq", expected_value="CH")
        MicrotechOrderRuleCondition.objects.create(
            rule=rule, group=sub, django_field_path="customer_group",
            operator_code="eq", expected_value="Haendler")
        MicrotechOrderRuleCondition.objects.create(
            rule=rule, group=sub, django_field_path="total",
            operator_code="between", expected_value="500", expected_value_2="9999")
        return rule

    def test_nested_and_or_matches(self):
        rule = self._rule_with_tree()
        self.assertTrue(rule_matches(rule, EvaluationContext(_Order())))

    def test_empty_root_is_global_fallback(self):
        rule = MicrotechOrderRule.objects.create(name="Empty")
        MicrotechOrderRuleConditionGroup.objects.create(
            rule=rule, logic=MicrotechOrderRule.ConditionLogic.ALL)
        self.assertTrue(rule_matches(rule, EvaluationContext(_Order())))
```

- [ ] **Step 2: Run test, verify it fails**

Run: `python -m pytest microtech/test_rule_engine_evaluation.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement**

```python
# microtech/rule_engine/evaluation.py
from __future__ import annotations

from microtech.models import MicrotechOrderRule
from microtech.rule_builder import get_django_field_map, get_operator_engine_map
from microtech.rule_engine.context import EvaluationContext
from microtech.rule_engine.operators import evaluate_operator
from microtech.rule_engine.templates import render_template


def _value_kind_for(field_path, field_map) -> str:
    field_def = field_map.get(field_path)
    return str(getattr(field_def, "value_kind", "string") or "string") if field_def else "string"


def _evaluate_condition(condition, context, field_map, operator_engine_map) -> bool:
    field_path = str(condition.django_field_path or "")
    value_kind = _value_kind_for(field_path, field_map)
    engine_op = str(operator_engine_map.get(condition.operator_code) or condition.operator_code or "")
    actual = context.get(field_path)
    expected = render_template(condition.expected_value or "", context)
    expected_2 = render_template(condition.expected_value_2 or "", context)
    return evaluate_operator(engine_op, actual, expected, expected_2, value_kind)


def evaluate_group(group, context, *, field_map=None, operator_engine_map=None) -> bool:
    field_map = field_map or get_django_field_map()
    operator_engine_map = operator_engine_map or get_operator_engine_map()

    active_conditions = [c for c in group.conditions.all() if c.is_active]
    active_children = [g for g in group.children.all() if g.is_active]

    results = [
        _evaluate_condition(c, context, field_map, operator_engine_map)
        for c in sorted(active_conditions, key=lambda i: (i.priority, i.id))
    ]
    results += [
        evaluate_group(child, context, field_map=field_map, operator_engine_map=operator_engine_map)
        for child in sorted(active_children, key=lambda i: (i.priority, i.id))
    ]

    if not results:
        return True  # leere Gruppe = neutral (globaler Fallback)
    if group.logic == MicrotechOrderRule.ConditionLogic.ANY:
        return any(results)
    return all(results)


def rule_matches(rule, context) -> bool:
    roots = [g for g in rule.condition_groups.all() if g.is_active and g.parent_id is None]
    if not roots:
        return True
    field_map = get_django_field_map()
    operator_engine_map = get_operator_engine_map()
    return all(
        evaluate_group(root, context, field_map=field_map, operator_engine_map=operator_engine_map)
        for root in roots
    )
```

- [ ] **Step 4: Run**

Run: `python -m pytest microtech/test_rule_engine_evaluation.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add microtech/rule_engine/evaluation.py microtech/test_rule_engine_evaluation.py
git commit -m "Add recursive condition-group tree evaluation"
```

---

## Task 12: Datenmigration — Alt-Regeln in Wurzelgruppe + Trigger-Seed

**Files:**
- Create: `microtech/migrations/0033_seed_triggers.py` (Trigger `order_create`, `customer_create`)
- Create: `microtech/migrations/0034_migrate_flat_conditions_to_groups.py`
- Test: `microtech/test_rule_engine_migration.py`

**Interfaces:**
- Consumes: `RuleTrigger`, `MicrotechOrderRule`, `MicrotechOrderRuleCondition`, `MicrotechOrderRuleConditionGroup`.
- Produces: Für jede bestehende Regel eine aktive Wurzelgruppe mit `logic = rule.condition_logic`; jede bestehende Condition ohne `group` wird dieser Wurzelgruppe zugeordnet. Bestehende Regeln erhalten `trigger = order_create`. Idempotent (Regeln mit vorhandener Wurzelgruppe werden übersprungen).

- [ ] **Step 1: Failing test**

```python
# microtech/test_rule_engine_migration.py
from django.test import TestCase
from microtech.models import (
    RuleTrigger, MicrotechOrderRule, MicrotechOrderRuleCondition,
    MicrotechOrderRuleConditionGroup,
)


class MigrationBackfillTest(TestCase):
    def test_helper_backfills_root_group_and_trigger(self):
        from microtech.rule_engine.backfill import backfill_condition_groups
        rule = MicrotechOrderRule.objects.create(
            name="Legacy", condition_logic=MicrotechOrderRule.ConditionLogic.ANY)
        cond = MicrotechOrderRuleCondition.objects.create(
            rule=rule, django_field_path="country_code", operator_code="eq", expected_value="CH")
        RuleTrigger.objects.create(
            code="order_create", label="Bestellung anlegen",
            task_name="orders.microtech_order_upsert", context_root="orders.Order")

        backfill_condition_groups(MicrotechOrderRule, MicrotechOrderRuleConditionGroup, RuleTrigger)

        rule.refresh_from_db(); cond.refresh_from_db()
        root = MicrotechOrderRuleConditionGroup.objects.get(rule=rule, parent__isnull=True)
        self.assertEqual(root.logic, MicrotechOrderRule.ConditionLogic.ANY)
        self.assertEqual(cond.group_id, root.id)
        self.assertEqual(rule.trigger.code, "order_create")

    def test_backfill_is_idempotent(self):
        from microtech.rule_engine.backfill import backfill_condition_groups
        rule = MicrotechOrderRule.objects.create(name="R")
        backfill_condition_groups(MicrotechOrderRule, MicrotechOrderRuleConditionGroup, RuleTrigger)
        backfill_condition_groups(MicrotechOrderRule, MicrotechOrderRuleConditionGroup, RuleTrigger)
        self.assertEqual(
            MicrotechOrderRuleConditionGroup.objects.filter(rule=rule, parent__isnull=True).count(), 1)
```

- [ ] **Step 2: Run test, verify it fails**

Run: `python -m pytest microtech/test_rule_engine_migration.py -v`
Expected: FAIL — `ModuleNotFoundError: microtech.rule_engine.backfill`

- [ ] **Step 3: Implement helper + migrations**

```python
# microtech/rule_engine/backfill.py
from __future__ import annotations


def backfill_condition_groups(RuleModel, GroupModel, TriggerModel):
    order_trigger = TriggerModel.objects.filter(code="order_create").first()
    for rule in RuleModel.objects.all():
        root = GroupModel.objects.filter(rule=rule, parent__isnull=True).first()
        if root is None:
            root = GroupModel.objects.create(
                rule=rule, parent=None, logic=rule.condition_logic, is_active=True, priority=100)
            rule.conditions.filter(group__isnull=True).update(group=root)
        if order_trigger is not None and rule.trigger_id is None:
            rule.trigger = order_trigger
            rule.save(update_fields=["trigger", "updated_at"])
```

```python
# microtech/migrations/0033_seed_triggers.py
from django.db import migrations

TRIGGERS = [
    ("order_create", "Bestellung anlegen", "orders.microtech_order_upsert", "orders.Order", 10),
    ("customer_create", "Kunde anlegen", "customer.microtech_customer_upsert", "customer.Customer", 20),
]

def seed(apps, schema_editor):
    T = apps.get_model("microtech", "RuleTrigger")
    for code, label, task, root, prio in TRIGGERS:
        T.objects.get_or_create(code=code, defaults={
            "label": label, "task_name": task, "context_root": root, "priority": prio, "is_active": True})

def unseed(apps, schema_editor):
    T = apps.get_model("microtech", "RuleTrigger")
    T.objects.filter(code__in=[c for c, *_ in TRIGGERS]).delete()

class Migration(migrations.Migration):
    dependencies = [("microtech", "0032_seed_ruleconstants")]
    operations = [migrations.RunPython(seed, unseed)]
```

```python
# microtech/migrations/0034_migrate_flat_conditions_to_groups.py
from django.db import migrations
from microtech.rule_engine.backfill import backfill_condition_groups

def run(apps, schema_editor):
    backfill_condition_groups(
        apps.get_model("microtech", "MicrotechOrderRule"),
        apps.get_model("microtech", "MicrotechOrderRuleConditionGroup"),
        apps.get_model("microtech", "RuleTrigger"),
    )

def noop(apps, schema_editor):
    pass

class Migration(migrations.Migration):
    dependencies = [("microtech", "0033_seed_triggers")]
    operations = [migrations.RunPython(run, noop)]
```

- [ ] **Step 4: Run**

Run: `python manage.py makemigrations microtech --check || true; python -m pytest microtech/test_rule_engine_migration.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add microtech/rule_engine/backfill.py microtech/migrations/0033_*.py microtech/migrations/0034_*.py microtech/test_rule_engine_migration.py
git commit -m "Backfill legacy rules into root condition groups and seed triggers"
```

---

## Task 13: Trigger-Dispatch mit Schatten-Modus & Diff-Log

**Files:**
- Create: `microtech/rule_engine/dispatch.py`
- Modify: `microtech/rule_engine/__init__.py` (öffentliche API re-exportieren)
- Test: `microtech/test_rule_engine_dispatch.py`

**Interfaces:**
- Consumes: `RuleTrigger`, `MicrotechOrderRule`, `EvaluationContext`, `rule_matches` (Task 11), `render_template` (Task 9).
- Produces:
  - `resolve_actions(*, task_name, phase, root_instance) -> list[ResolvedAction]` — sammelt aus allen aktiven Regeln des Triggers (`engine_enabled=True`, passende `execution_phase`) in Prioritätsreihenfolge die Aktionen der ersten passenden Regel; Aktionswerte per Template aufgelöst.
  - `ResolvedAction(action_type, field_path, value)` (dataclass).
  - `shadow_compare(*, task_name, phase, root_instance, legacy_result) -> dict` — evaluiert im Schatten-Modus und loggt einen Diff gegen `legacy_result`, wendet nichts an, gibt Diff-Dict zurück.
- **Wichtig (Nicht-Regression):** Dieses Modul wird in dieser Plan-Stufe von **keinem** Produktionspfad aufgerufen. Die Verdrahtung erfolgt erst im Pilot-Plan.

- [ ] **Step 1: Failing test**

```python
# microtech/test_rule_engine_dispatch.py
from django.test import TestCase
from microtech.models import (
    RuleTrigger, MicrotechOrderRule, MicrotechOrderRuleConditionGroup,
    MicrotechOrderRuleAction, MicrotechDatasetCatalog, MicrotechDatasetField,
)
from microtech.rule_engine.dispatch import resolve_actions, shadow_compare


class _Order:
    firma = "ACME AG"


class DispatchTest(TestCase):
    def _enabled_rule_with_action(self):
        trigger = RuleTrigger.objects.create(
            code="order_create", label="Bestellung anlegen",
            task_name="orders.microtech_order_upsert", context_root="orders.Order")
        rule = MicrotechOrderRule.objects.create(
            name="R", trigger=trigger, engine_enabled=True, shadow_mode=False,
            execution_phase=MicrotechOrderRule.ExecutionPhase.BEFORE)
        MicrotechOrderRuleConditionGroup.objects.create(
            rule=rule, logic=MicrotechOrderRule.ConditionLogic.ALL)  # leer = trifft immer
        ds = MicrotechDatasetCatalog.objects.create(
            code="Vorgang", name="Vorgang", source_identifier="Vorgang")
        field = MicrotechDatasetField.objects.create(dataset=ds, field_name="Na1")
        MicrotechOrderRuleAction.objects.create(
            rule=rule, action_type=MicrotechOrderRuleAction.ActionType.SET_FIELD,
            dataset=ds, dataset_field=field, target_value="{{ firma }}")
        return rule

    def test_resolve_actions_renders_template(self):
        self._enabled_rule_with_action()
        actions = resolve_actions(
            task_name="orders.microtech_order_upsert",
            phase=MicrotechOrderRule.ExecutionPhase.BEFORE, root_instance=_Order())
        self.assertEqual(len(actions), 1)
        self.assertEqual(actions[0].value, "ACME AG")

    def test_shadow_compare_returns_diff_without_applying(self):
        rule = self._enabled_rule_with_action()
        rule.shadow_mode = True
        rule.save(update_fields=["shadow_mode"])
        diff = shadow_compare(
            task_name="orders.microtech_order_upsert",
            phase=MicrotechOrderRule.ExecutionPhase.BEFORE, root_instance=_Order(),
            legacy_result={"Na1": "Alt"})
        self.assertIn("Na1", diff["changed"])
```

- [ ] **Step 2: Run test, verify it fails**

Run: `python -m pytest microtech/test_rule_engine_dispatch.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement**

```python
# microtech/rule_engine/dispatch.py
from __future__ import annotations

from dataclasses import dataclass

from loguru import logger

from microtech.models import MicrotechOrderRule
from microtech.rule_engine.context import EvaluationContext
from microtech.rule_engine.evaluation import rule_matches
from microtech.rule_engine.templates import render_template


@dataclass(frozen=True, slots=True)
class ResolvedAction:
    action_type: str
    field_path: str
    value: str


def _first_matching_rule(*, task_name, phase, context):
    rules = (
        MicrotechOrderRule.objects
        .filter(is_active=True, engine_enabled=True, execution_phase=phase, trigger__task_name=task_name)
        .prefetch_related("condition_groups", "condition_groups__conditions",
                          "actions", "actions__dataset_field")
        .order_by("priority", "id")
    )
    for rule in rules:
        if rule_matches(rule, context):
            return rule
    return None


def _actions_for_rule(rule, context) -> list[ResolvedAction]:
    resolved = []
    for action in sorted((a for a in rule.actions.all() if a.is_active),
                         key=lambda i: (i.priority, i.id)):
        field_path = action.dataset_field.field_name if action.dataset_field_id else ""
        resolved.append(ResolvedAction(
            action_type=str(action.action_type),
            field_path=str(field_path),
            value=render_template(action.target_value or "", context),
        ))
    return resolved


def resolve_actions(*, task_name, phase, root_instance) -> list[ResolvedAction]:
    context = EvaluationContext(root_instance)
    rule = _first_matching_rule(task_name=task_name, phase=phase, context=context)
    if rule is None:
        return []
    return _actions_for_rule(rule, context)


def shadow_compare(*, task_name, phase, root_instance, legacy_result: dict) -> dict:
    engine_actions = {a.field_path: a.value for a in resolve_actions(
        task_name=task_name, phase=phase, root_instance=root_instance)}
    changed = {
        key: {"legacy": legacy_result.get(key), "engine": value}
        for key, value in engine_actions.items()
        if str(legacy_result.get(key, "")) != str(value)
    }
    diff = {"changed": changed, "engine": engine_actions, "legacy": legacy_result}
    if changed:
        logger.warning("Regelwerk Schatten-Diff für {} ({}): {}", task_name, phase, changed)
    else:
        logger.info("Regelwerk Schatten-Diff leer für {} ({}).", task_name, phase)
    return diff
```

```python
# microtech/rule_engine/__init__.py
from microtech.rule_engine.context import EvaluationContext
from microtech.rule_engine.dispatch import ResolvedAction, resolve_actions, shadow_compare
from microtech.rule_engine.evaluation import evaluate_group, rule_matches
from microtech.rule_engine.templates import render_template

__all__ = [
    "EvaluationContext", "ResolvedAction", "resolve_actions", "shadow_compare",
    "evaluate_group", "rule_matches", "render_template",
]
```

- [ ] **Step 4: Run**

Run: `python -m pytest microtech/test_rule_engine_dispatch.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add microtech/rule_engine/dispatch.py microtech/rule_engine/__init__.py microtech/test_rule_engine_dispatch.py
git commit -m "Add trigger dispatch with shadow-mode diff comparison"
```

---

## Task 14: Voller Testlauf & Migrations-Check

**Files:**
- Test: alle `microtech/test_rule_engine_*.py`

- [ ] **Step 1: Migrations vollständig?**

Run: `python manage.py makemigrations --check --dry-run`
Expected: „No changes detected" (alle Modelländerungen sind migriert).

- [ ] **Step 2: Migrationskette anwendbar?**

Run: `python manage.py migrate microtech`
Expected: alle `0027`–`0034` laufen fehlerfrei.

- [ ] **Step 3: Gesamte Engine-Testsuite grün**

Run: `python -m pytest microtech/test_rule_engine_*.py -v`
Expected: alle PASS.

- [ ] **Step 4: Nicht-Regression — Bestandstests unberührt**

Run: `python -m pytest microtech/ orders/ customer/ -q`
Expected: keine neuen Fehlschläge gegenüber dem Stand vor diesem Plan (bestehende Pfade unverändert).

- [ ] **Step 5: Commit (falls Anpassungen nötig waren)**

```bash
git add -A
git commit -m "Verify central rule engine backend suite and migrations"
```

---

## Self-Review (Plan gegen Spec)

- **§4.1 Trigger** → Task 1, Seed Task 12. ✅
- **§4.2 Regel-Felder (trigger/phase/shadow)** + engine-flag → Task 2. ✅
- **§4.3 Bedingungsbaum + expected_value_2** → Task 3, Eval Task 11. ✅
- **§4.4 Operatoren** → Task 4 (Enum/Seed), Task 10 (Handler). ✅
- **§4.5 Template-Aktionswerte** → Task 9, angewandt in Dispatch Task 13. ✅
- **§4.6 Variable Vergleichswerte** → Task 11 (`render_template` auf `expected_value`). ✅
- **§4.7 Erweiterungen:** Fallback/Transform (Task 5, 9), Resolver (Task 8), Konstanten (Task 6). Bedingte Aktion: **verschoben** — siehe Hinweis unten. ⚠️
- **§4.8 Global „leere Werte"** → gehört in den Anwendungs-/Pilot-Plan (Engine liefert Werte; das Nicht-Überschreiben passiert beim Schreiben nach Microtech). Hier bewusst ausgelassen. ⚠️
- **§5 Engine** (Baum-Eval, Template, Phase, Shadow) → Task 9–13. ✅
- **§7a Parallelbetrieb** → `engine_enabled=False`, `shadow_mode=True` Defaults (Task 2); Dispatch wird von keinem Prod-Pfad aufgerufen (Task 13-Hinweis). ✅
- **§7 Migration Alt-Regeln** → Task 12. ✅

**Bewusst NICHT in diesem Plan (Folge-Pläne):**
- Bedingte Einzelaktion (§4.7 Punkt 4) — kommt mit der UI/Pilot-Stufe, wenn der Bedarf (email-nur-bei-Versand) konkret verdrahtet wird.
- Anwendung „leere Werte überschreiben nicht" (§4.8) — Teil des Pilot-Plans (Schreibpfad).
- Block-Builder-UI (§6) — eigener Plan 2.
- Webshop-Defaults-Pilot & YAML-Ablösung (§7/§10 Schritt 5) — eigener Plan 3.
