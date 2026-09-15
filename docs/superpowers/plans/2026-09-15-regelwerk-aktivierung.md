# Regelwerk-Aktivierung (Cutover Order-Pfad) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Die neue Rule-Engine wird — abgesichert per Schatten-Modus und pro-Trigger schaltbar — maßgeblich für den Order→Microtech-Pfad, sodass im grafischen Editor angelegte Regeln tatsächlich angewendet werden.

**Architecture:** Eine neue Engine-Funktion `resolve_order_rule(order)` erzeugt exakt den vorhandenen `ResolvedOrderRule`-Vertrag (customer_type + dataset_actions), den der Microtech-Upsert schon konsumiert — der Downstream-Code bleibt also unverändert. Eine Fassade `resolve_order_rule_with_mode(order)` schaltet je nach `MicrotechSettings.rule_engine_order_mode` zwischen `off` (alter Resolver, heutiges Verhalten), `shadow` (alt maßgeblich, Engine läuft mit und persistiert Abweichungen) und `live` (Engine maßgeblich). Rollback = Modus zurückstellen. Ein persistiertes `RuleEngineShadowRun`-Log dient als Verifikations-Gate vor dem Cutover.

**Tech Stack:** Django 5, django-unfold Admin, Celery-Tasks als Trigger, Postgres (Docker `db`-Container für Tests), pytest + pytest-django, loguru. Kein Build-Chain-Frontend.

**Spec:** `docs/superpowers/specs/2026-08-19-zentrales-regelwerk-design.md` (insb. §7a Paralleler Betrieb) und `docs/superpowers/specs/2026-08-19-hardcoded-regeln-inventar.md`.

## Global Constraints

- Alter Pfad bleibt maßgeblich, bis die Engine verifiziert ist: Default-Modus ist `off` → byte-identisches Alt-Verhalten. Cutover nur per expliziter Modus-Umschaltung, jederzeit per Flag rücksetzbar.
- Paket-Installation ausschließlich mit `uv pip install` (nicht `pip`).
- Tests laufen gegen Postgres (`docker compose up -d db`), nicht SQLite (Produkt-Migrationen nutzen `ADD COLUMN IF NOT EXISTS`).
- Kein `Co-Authored-By` in Commits.
- Der Microtech-COM/GraphQL-Upsert ist in Tests/CI nicht ausführbar → alle Tests testen nur DB-/Auswahl-/Fassaden-Logik, niemals den echten Upsert.
- `ResolvedOrderRule` und `ResolvedDatasetAction` werden aus `orders.services.order_rule_resolver` **wiederverwendet** (nicht dupliziert), damit der Konsumenten-Vertrag identisch bleibt.
- Der Order-Create-Trigger ist `order_create` (task_name `orders.microtech_order_upsert`, context_root `orders.Order`), geseedet in Migration `0034`.

---

## File Structure

- `microtech/rule_engine/order_resolver.py` (neu): `resolve_order_rule(order) -> ResolvedOrderRule` + `detect_customer_type(order) -> str`. Einzige Verantwortung: aus DB-Regeln + Order das `ResolvedOrderRule` der neuen Engine bauen.
- `orders/services/order_rule_resolver.py` (modifizieren): `_detect_customer_type`/`_address_looks_like_company` als wiederverwendbare Funktion faktorisieren, damit Engine und Legacy dieselbe Heuristik nutzen.
- `microtech/models.py` (modifizieren): `MicrotechSettings.rule_engine_order_mode`; neues Modell `RuleEngineShadowRun`.
- `microtech/rule_engine/dispatch.py` (modifizieren): Fassade `resolve_order_rule_with_mode(order) -> ResolvedOrderRule` inkl. Schatten-Persistenz.
- `orders/services/order_upsert_microtech.py` (modifizieren): beide Aufrufstellen auf die Fassade umstellen.
- `orders/services/order_sync_workflow.py` (modifizieren): Aufrufstelle prüfen/umstellen.
- `microtech/admin.py` (modifizieren): Modus-Umschaltung + Schatten-Diff-Übersicht (Verifikations-Gate).
- `microtech/templates/admin/microtech/rule_engine_verify.html` (neu): Verifikations-Ansicht.
- `microtech/test_rule_engine_activation.py` (neu): alle Tests dieses Plans.

---

### Task 1: Engine-Ergebnis im `ResolvedOrderRule`-Vertrag

**Files:**
- Create: `microtech/rule_engine/order_resolver.py`
- Test: `microtech/test_rule_engine_activation.py`

**Interfaces:**
- Consumes: `MicrotechOrderRule`, `MicrotechOrderRuleAction`, `EvaluationContext` (microtech.rule_engine.context), `rule_matches` (microtech.rule_engine.evaluation), `render_template` (microtech.rule_engine.templates), `ResolvedOrderRule`/`ResolvedDatasetAction` (orders.services.order_rule_resolver).
- Produces: `resolve_order_rule(order) -> ResolvedOrderRule` und `detect_customer_type(order) -> str`.

Semantik (muss die gelebte Legacy-Semantik reproduzieren):
1. Kandidaten = aktive Regeln mit `engine_enabled=True`, `trigger__task_name="orders.microtech_order_upsert"`, `execution_phase=MicrotechOrderRule.ExecutionPhase.BEFORE`, sortiert nach `priority, id`.
2. Erste Regel, für die `rule_matches(rule, EvaluationContext(order))` True ist, gewinnt.
3. Aus deren aktiven Aktionen (sortiert `priority, id`) `dataset_actions` bauen:
   - `SET_FIELD`: Dataset aus `action.dataset_field.dataset` ableiten (`source_identifier`, `name`, `field_name`, `field_type`); `target_value = render_template(action.target_value or "", context)`.
   - `CREATE_EXTRA_POSITION` / `CREATE_SHIPPING_POSITION`: `target_value = render_template(...)`, keine Dataset-Felder.
4. `customer_type = detect_customer_type(order)`; übrige Felder bleiben Default (identisch zur Legacy).
5. Keine passende Regel → `ResolvedOrderRule(customer_type=detect_customer_type(order))`.

- [ ] **Step 1: Failing test — Engine baut dataset_actions aus SET_FIELD**

```python
# microtech/test_rule_engine_activation.py
import pytest
from decimal import Decimal
from microtech.models import (
    MicrotechOrderRule, MicrotechOrderRuleAction, MicrotechOrderRuleCondition,
    MicrotechOrderRuleConditionGroup, RuleTrigger, MicrotechDataset, MicrotechDatasetField,
)
from orders.models import Order
from orders.services.order_rule_resolver import ResolvedOrderRule

pytestmark = pytest.mark.django_db


def _order_trigger():
    return RuleTrigger.objects.get_or_create(
        code="order_create",
        defaults=dict(label="Bestellung anlegen", task_name="orders.microtech_order_upsert",
                      context_root="orders.Order", is_active=True, priority=10),
    )[0]


def _make_order(**kw):
    return Order.objects.create(order_number=kw.get("order_number", "A1"), **{
        k: v for k, v in kw.items() if k != "order_number"})


def test_engine_builds_set_field_dataset_action():
    from microtech.rule_engine.order_resolver import resolve_order_rule
    trg = _order_trigger()
    ds = MicrotechDataset.objects.create(source_identifier="Vorgang - Vorgange", name="Vorgang")
    fld = MicrotechDatasetField.objects.create(dataset=ds, field_name="ZahlArt", field_type="Integer")
    rule = MicrotechOrderRule.objects.create(
        name="Engine ZahlArt", is_active=True, engine_enabled=True, trigger=trg,
        execution_phase=MicrotechOrderRule.ExecutionPhase.BEFORE, priority=5)
    MicrotechOrderRuleAction.objects.create(
        rule=rule, action_type=MicrotechOrderRuleAction.ActionType.SET_FIELD,
        dataset=ds, dataset_field=fld, target_value="22", is_active=True)
    order = _make_order()

    resolved = resolve_order_rule(order)

    assert isinstance(resolved, ResolvedOrderRule)
    assert len(resolved.dataset_actions) == 1
    a = resolved.dataset_actions[0]
    assert a.action_type == MicrotechOrderRuleAction.ActionType.SET_FIELD
    assert a.dataset_field_name == "ZahlArt"
    assert a.dataset_field_type == "Integer"
    assert a.target_value == "22"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest microtech/test_rule_engine_activation.py::test_engine_builds_set_field_dataset_action -v`
Expected: FAIL — `ModuleNotFoundError: microtech.rule_engine.order_resolver`.

- [ ] **Step 3: Implement `resolve_order_rule` + `detect_customer_type`**

```python
# microtech/rule_engine/order_resolver.py
from __future__ import annotations

from microtech.models import MicrotechOrderRule, MicrotechOrderRuleAction
from microtech.rule_engine.context import EvaluationContext
from microtech.rule_engine.evaluation import rule_matches
from microtech.rule_engine.templates import render_template
from orders.services.order_rule_resolver import (
    ResolvedDatasetAction, ResolvedOrderRule, detect_customer_type as _legacy_detect,
)

ORDER_CREATE_TASK = "orders.microtech_order_upsert"


def detect_customer_type(order) -> str:
    return _legacy_detect(order=order)


def _dataset_action(action, context) -> ResolvedDatasetAction:
    action_type = str(action.action_type or "")
    value = render_template(action.target_value or "", context)
    if action_type == MicrotechOrderRuleAction.ActionType.SET_FIELD and action.dataset_field_id:
        field = action.dataset_field
        dataset = field.dataset
        return ResolvedDatasetAction(
            action_type=action_type,
            dataset_source_identifier=str(getattr(dataset, "source_identifier", "") or ""),
            dataset_name=str(getattr(dataset, "name", "") or ""),
            dataset_field_name=str(field.field_name or ""),
            dataset_field_type=str(field.field_type or ""),
            target_value=value,
        )
    return ResolvedDatasetAction(action_type=action_type, target_value=value)


def resolve_order_rule(order) -> ResolvedOrderRule:
    context = EvaluationContext(order)
    rules = (
        MicrotechOrderRule.objects
        .filter(is_active=True, engine_enabled=True,
                execution_phase=MicrotechOrderRule.ExecutionPhase.BEFORE,
                trigger__task_name=ORDER_CREATE_TASK)
        .prefetch_related("condition_groups", "condition_groups__conditions",
                          "condition_groups__children",
                          "actions", "actions__dataset", "actions__dataset_field")
        .order_by("priority", "id")
    )
    customer_type = detect_customer_type(order)
    for rule in rules:
        if not rule_matches(rule, context):
            continue
        actions = tuple(
            _dataset_action(a, context)
            for a in sorted((a for a in rule.actions.all() if a.is_active),
                            key=lambda i: (i.priority, i.id))
        )
        from dataclasses import replace
        base = ResolvedOrderRule.from_rule(rule=rule, customer_type=customer_type)
        return replace(base, dataset_actions=actions)
    return ResolvedOrderRule(customer_type=customer_type)


__all__ = ["resolve_order_rule", "detect_customer_type", "ORDER_CREATE_TASK"]
```

(Task 2 stellt `detect_customer_type` in `order_rule_resolver` bereit; bis dahin schlägt der Import fehl — deshalb Task 2 zusammen ausführen bzw. direkt danach.)

- [ ] **Step 4: Run test to verify it passes** (nach Task 2)

Run: `.venv/bin/python -m pytest microtech/test_rule_engine_activation.py::test_engine_builds_set_field_dataset_action -v`
Expected: PASS.

- [ ] **Step 5: Failing test — keine passende Regel → nur customer_type**

```python
def test_engine_no_match_returns_defaults_with_customer_type():
    from microtech.rule_engine.order_resolver import resolve_order_rule
    order = _make_order()
    resolved = resolve_order_rule(order)
    assert resolved.dataset_actions == ()
    assert resolved.rule_id is None
    assert resolved.customer_type in (
        MicrotechOrderRule.CustomerType.PRIVATE, MicrotechOrderRule.CustomerType.COMPANY)
```

- [ ] **Step 6: Run both tests — PASS.**

Run: `.venv/bin/python -m pytest microtech/test_rule_engine_activation.py -v`

- [ ] **Step 7: Commit**

```bash
git add microtech/rule_engine/order_resolver.py microtech/test_rule_engine_activation.py
git commit -m "Add engine order resolver producing ResolvedOrderRule contract"
```

---

### Task 2: Geteilte customer_type-Heuristik

**Files:**
- Modify: `orders/services/order_rule_resolver.py`
- Test: `microtech/test_rule_engine_activation.py`

**Interfaces:**
- Produces: modul-level `detect_customer_type(*, order) -> str` und `address_looks_like_company(address) -> bool` in `orders.services.order_rule_resolver`; die bestehenden `OrderRuleResolverService._detect_customer_type`/`_address_looks_like_company` delegieren darauf (Verhalten unverändert).

- [ ] **Step 1: Failing test — geteilte Funktion existiert und stimmt mit Service überein**

```python
def test_shared_detect_customer_type_matches_service():
    from orders.services.order_rule_resolver import detect_customer_type, OrderRuleResolverService
    from orders.models import Order
    order = Order.objects.create(order_number="C1")
    shared = detect_customer_type(order=order)
    service = OrderRuleResolverService()._detect_customer_type(order=order)
    assert shared == service
```

- [ ] **Step 2: Run — FAIL** (`ImportError: cannot import name 'detect_customer_type'`).

Run: `.venv/bin/python -m pytest microtech/test_rule_engine_activation.py::test_shared_detect_customer_type_matches_service -v`

- [ ] **Step 3: Faktorisieren**

Modul-Funktionen ergänzen (verschiebt die Logik aus den `@classmethod`s):

```python
# orders/services/order_rule_resolver.py  (Modulebene, nach den _to_* Helfern)
def address_looks_like_company(address) -> bool:
    name1 = _to_str(getattr(address, "name1", ""))
    title = _to_str(getattr(address, "title", ""))
    lowered = name1.lower()
    if not name1:
        return False
    if title and name1.casefold() == title.casefold():
        return False
    if lowered in _SALUTATION_VALUES:
        return False
    return True


def detect_customer_type(*, order) -> str:
    for address in (order.billing_address, order.shipping_address):
        if address and address_looks_like_company(address):
            return MicrotechOrderRule.CustomerType.COMPANY
    return MicrotechOrderRule.CustomerType.PRIVATE
```

Die Klassenmethoden auf Delegation umstellen:

```python
    @classmethod
    def _detect_customer_type(cls, *, order: Order) -> str:
        return detect_customer_type(order=order)

    @classmethod
    def _address_looks_like_company(cls, address) -> bool:
        return address_looks_like_company(address)
```

`__all__` um `"detect_customer_type", "address_looks_like_company"` erweitern.

- [ ] **Step 4: Run — PASS.** Zusätzlich vorhandene Order-Tests grün halten:

Run: `.venv/bin/python -m pytest microtech/test_rule_engine_activation.py orders/tests.py -q`
Expected: PASS (keine Regression).

- [ ] **Step 5: Commit**

```bash
git add orders/services/order_rule_resolver.py microtech/test_rule_engine_activation.py
git commit -m "Factor out shared customer-type heuristic for rule engine reuse"
```

---

### Task 3: Modus-Feld + Schatten-Lauf-Modell

**Files:**
- Modify: `microtech/models.py`
- Create (Migration): `microtech/migrations/00XX_rule_engine_mode_and_shadowrun.py` (via `makemigrations`)
- Test: `microtech/test_rule_engine_activation.py`

**Interfaces:**
- Produces: `MicrotechSettings.rule_engine_order_mode` (TextChoices `OFF="off"`, `SHADOW="shadow"`, `LIVE="live"`, default `OFF`) mit innerer Klasse `MicrotechSettings.EngineMode`; Modell `RuleEngineShadowRun(created_at, order_number, task_name, engine_rule_id, legacy_rule_id, is_equal, changed_json)` mit `Meta.ordering = ("-created_at",)`.

- [ ] **Step 1: Failing test — Default-Modus ist off, Choices vorhanden**

```python
def test_engine_mode_default_off_and_choices():
    from microtech.models import MicrotechSettings
    s = MicrotechSettings.load()
    assert s.rule_engine_order_mode == MicrotechSettings.EngineMode.OFF
    values = {c[0] for c in MicrotechSettings.EngineMode.choices}
    assert values == {"off", "shadow", "live"}


def test_shadow_run_model_orders_newest_first():
    from microtech.models import RuleEngineShadowRun
    RuleEngineShadowRun.objects.create(order_number="X1", task_name="t", is_equal=True, changed_json="{}")
    RuleEngineShadowRun.objects.create(order_number="X2", task_name="t", is_equal=False, changed_json="{}")
    assert list(RuleEngineShadowRun.objects.values_list("order_number", flat=True))[:2] == ["X2", "X1"]
```

- [ ] **Step 2: Run — FAIL** (`AttributeError: EngineMode` / `RuleEngineShadowRun`).

- [ ] **Step 3: Modell-Änderungen**

```python
# microtech/models.py  — in MicrotechSettings
    class EngineMode(models.TextChoices):
        OFF = "off", _("Aus (nur alter Resolver)")
        SHADOW = "shadow", _("Schatten (alt maßgeblich, Engine vergleicht)")
        LIVE = "live", _("Live (neue Engine maßgeblich)")

    rule_engine_order_mode = models.CharField(
        max_length=10, choices=EngineMode.choices, default=EngineMode.OFF,
        verbose_name=_("Regel-Engine Modus (Bestellungen)"))
```

```python
# microtech/models.py  — neues Modell (Modulebene, BaseModel-Konvention folgen)
class RuleEngineShadowRun(BaseModel):
    order_number = models.CharField(max_length=64, blank=True, default="")
    task_name = models.CharField(max_length=128, blank=True, default="")
    engine_rule_id = models.IntegerField(null=True, blank=True)
    legacy_rule_id = models.IntegerField(null=True, blank=True)
    is_equal = models.BooleanField(default=True)
    changed_json = models.TextField(blank=True, default="")

    class Meta:
        ordering = ("-created_at",)
        verbose_name = _("Regel-Engine Schatten-Lauf")
        verbose_name_plural = _("Regel-Engine Schatten-Läufe")
```

(Falls `BaseModel` kein `created_at` hat: `created_at = models.DateTimeField(auto_now_add=True, db_index=True)` ergänzen. Vor Implementierung `BaseModel` prüfen.)

- [ ] **Step 4: Migration erzeugen + prüfen**

Run:
```bash
.venv/bin/python manage.py makemigrations microtech
.venv/bin/python manage.py migrate
.venv/bin/python -m pytest microtech/test_rule_engine_activation.py -k "engine_mode or shadow_run" -v
```
Expected: Migration erstellt, Tests PASS.

- [ ] **Step 5: Commit**

```bash
git add microtech/models.py microtech/migrations/00*_rule_engine*.py microtech/test_rule_engine_activation.py
git commit -m "Add rule-engine order mode setting and shadow-run log model"
```

---

### Task 4: Modus-Fassade mit Schatten-Persistenz

**Files:**
- Modify: `microtech/rule_engine/dispatch.py`
- Test: `microtech/test_rule_engine_activation.py`

**Interfaces:**
- Consumes: `resolve_order_rule` (Task 1), `OrderRuleResolverService.resolve_for_order` (Legacy), `MicrotechSettings` (Task 3), `RuleEngineShadowRun` (Task 3).
- Produces: `resolve_order_rule_with_mode(order) -> ResolvedOrderRule`.

Verhalten:
- `off`: nur Legacy, kein Engine-Aufruf, kein Log → return Legacy.
- `shadow`: Legacy = Ergebnis; Engine zusätzlich berechnen; `_persist_shadow_run(order, legacy, engine)`; return **Legacy**.
- `live`: Engine = Ergebnis; Legacy zusätzlich berechnen und `_persist_shadow_run(...)` (weiter Diffs beobachten); return **Engine**.
- Vergleich über `dataset_actions` (feld→wert-Abbildung wie `shadow_compare`) + `rule_id`. Engine-Fehler in `shadow`/`live` dürfen den Order-Pfad **nie** brechen: try/except → loggen, im Fehlerfall auf Legacy zurückfallen (auch in `live`).

- [ ] **Step 1: Failing test — off = Legacy, kein Log**

```python
def test_mode_off_returns_legacy_no_log(monkeypatch):
    from microtech.models import MicrotechSettings, RuleEngineShadowRun
    from microtech.rule_engine import dispatch
    from orders.services.order_rule_resolver import ResolvedOrderRule
    s = MicrotechSettings.load(); s.rule_engine_order_mode = MicrotechSettings.EngineMode.OFF; s.save()
    order = Order.objects.create(order_number="OFF1")
    monkeypatch.setattr(dispatch, "_legacy_resolve", lambda o: ResolvedOrderRule(rule_id=99, rule_name="legacy"))
    def _boom(o):  # Engine darf in off nicht laufen
        raise AssertionError("engine must not run in off mode")
    monkeypatch.setattr(dispatch, "resolve_order_rule", _boom)
    result = dispatch.resolve_order_rule_with_mode(order)
    assert result.rule_id == 99
    assert RuleEngineShadowRun.objects.count() == 0
```

- [ ] **Step 2: Run — FAIL** (`AttributeError: resolve_order_rule_with_mode`).

- [ ] **Step 3: Fassade implementieren**

```python
# microtech/rule_engine/dispatch.py  (ergänzen)
import json
from microtech.models import MicrotechSettings, RuleEngineShadowRun
from microtech.rule_engine.order_resolver import resolve_order_rule, ORDER_CREATE_TASK


def _legacy_resolve(order):
    from orders.services.order_rule_resolver import OrderRuleResolverService
    return OrderRuleResolverService().resolve_for_order(order=order)


def _actions_map(resolved):
    out = {}
    for a in getattr(resolved, "dataset_actions", ()) or ():
        key = a.dataset_field_name or a.action_type
        out[key] = a.target_value
    return out


def _persist_shadow_run(order, legacy, engine):
    legacy_map, engine_map = _actions_map(legacy), _actions_map(engine)
    keys = set(legacy_map) | set(engine_map)
    changed = {k: {"legacy": legacy_map.get(k), "engine": engine_map.get(k)}
               for k in keys if str(legacy_map.get(k, "")) != str(engine_map.get(k, ""))}
    is_equal = not changed and (legacy.rule_id == engine.rule_id)
    try:
        RuleEngineShadowRun.objects.create(
            order_number=str(getattr(order, "order_number", "") or ""),
            task_name=ORDER_CREATE_TASK,
            engine_rule_id=engine.rule_id, legacy_rule_id=legacy.rule_id,
            is_equal=is_equal, changed_json=json.dumps(changed, ensure_ascii=False))
    except Exception:
        logger.exception("Schatten-Lauf konnte nicht persistiert werden.")
    if not is_equal:
        logger.warning("Regelwerk Schatten-Diff (order={}): rule legacy={} engine={} changed={}",
                       getattr(order, "order_number", ""), legacy.rule_id, engine.rule_id, changed)


def resolve_order_rule_with_mode(order):
    try:
        mode = MicrotechSettings.load().rule_engine_order_mode
    except Exception:
        logger.exception("Engine-Modus nicht ladbar → off.")
        mode = MicrotechSettings.EngineMode.OFF

    if mode == MicrotechSettings.EngineMode.OFF:
        return _legacy_resolve(order)

    legacy = _legacy_resolve(order)
    try:
        engine = resolve_order_rule(order)
    except Exception:
        logger.exception("Engine-Auswertung fehlgeschlagen → Legacy maßgeblich (order={}).",
                         getattr(order, "order_number", ""))
        return legacy

    _persist_shadow_run(order, legacy, engine)
    if mode == MicrotechSettings.EngineMode.LIVE:
        return engine
    return legacy
```

- [ ] **Step 4: Run — PASS.**

- [ ] **Step 5: Failing tests — shadow loggt & gibt Legacy zurück; live gibt Engine zurück; Engine-Fehler in live → Legacy**

```python
def test_mode_shadow_logs_and_returns_legacy(monkeypatch):
    from microtech.models import MicrotechSettings, RuleEngineShadowRun
    from microtech.rule_engine import dispatch
    from orders.services.order_rule_resolver import ResolvedOrderRule, ResolvedDatasetAction
    s = MicrotechSettings.load(); s.rule_engine_order_mode = MicrotechSettings.EngineMode.SHADOW; s.save()
    order = Order.objects.create(order_number="SH1")
    monkeypatch.setattr(dispatch, "_legacy_resolve", lambda o: ResolvedOrderRule(
        rule_id=1, dataset_actions=(ResolvedDatasetAction(action_type="set_field", dataset_field_name="ZahlArt", target_value="10"),)))
    monkeypatch.setattr(dispatch, "resolve_order_rule", lambda o: ResolvedOrderRule(
        rule_id=2, dataset_actions=(ResolvedDatasetAction(action_type="set_field", dataset_field_name="ZahlArt", target_value="22"),)))
    result = dispatch.resolve_order_rule_with_mode(order)
    assert result.rule_id == 1  # Legacy maßgeblich
    run = RuleEngineShadowRun.objects.latest("created_at")
    assert run.is_equal is False and '"ZahlArt"' in run.changed_json


def test_mode_live_returns_engine(monkeypatch):
    from microtech.models import MicrotechSettings
    from microtech.rule_engine import dispatch
    from orders.services.order_rule_resolver import ResolvedOrderRule
    s = MicrotechSettings.load(); s.rule_engine_order_mode = MicrotechSettings.EngineMode.LIVE; s.save()
    order = Order.objects.create(order_number="LV1")
    monkeypatch.setattr(dispatch, "_legacy_resolve", lambda o: ResolvedOrderRule(rule_id=1))
    monkeypatch.setattr(dispatch, "resolve_order_rule", lambda o: ResolvedOrderRule(rule_id=2))
    assert dispatch.resolve_order_rule_with_mode(order).rule_id == 2


def test_mode_live_engine_error_falls_back_to_legacy(monkeypatch):
    from microtech.models import MicrotechSettings
    from microtech.rule_engine import dispatch
    from orders.services.order_rule_resolver import ResolvedOrderRule
    s = MicrotechSettings.load(); s.rule_engine_order_mode = MicrotechSettings.EngineMode.LIVE; s.save()
    order = Order.objects.create(order_number="ERR1")
    monkeypatch.setattr(dispatch, "_legacy_resolve", lambda o: ResolvedOrderRule(rule_id=1, rule_name="legacy"))
    def _boom(o): raise RuntimeError("engine down")
    monkeypatch.setattr(dispatch, "resolve_order_rule", _boom)
    assert dispatch.resolve_order_rule_with_mode(order).rule_id == 1
```

- [ ] **Step 6: Run all — PASS.**

Run: `.venv/bin/python -m pytest microtech/test_rule_engine_activation.py -v`

- [ ] **Step 7: Commit**

```bash
git add microtech/rule_engine/dispatch.py microtech/test_rule_engine_activation.py
git commit -m "Add mode facade with shadow persistence and safe engine fallback"
```

---

### Task 5: Order-Pfad auf die Fassade umstellen

**Files:**
- Modify: `orders/services/order_upsert_microtech.py:149`, `orders/services/order_upsert_microtech.py:318`
- Modify: `orders/services/order_sync_workflow.py:913`
- Test: `microtech/test_rule_engine_activation.py`

**Interfaces:**
- Consumes: `resolve_order_rule_with_mode` (Task 4).
- Der Rückgabetyp bleibt `ResolvedOrderRule` → keine weitere Downstream-Änderung.

- [ ] **Step 1: Failing test — Aufrufstellen nutzen die Fassade (off = byte-identisch)**

```python
def test_upsert_uses_mode_facade(monkeypatch):
    # off-Modus: Fassade delegiert an Legacy → identisches ResolvedOrderRule
    from microtech.models import MicrotechSettings
    from microtech.rule_engine import dispatch
    from orders.services import order_upsert_microtech as oum
    s = MicrotechSettings.load(); s.rule_engine_order_mode = MicrotechSettings.EngineMode.OFF; s.save()
    order = Order.objects.create(order_number="U1")
    calls = {"facade": 0}
    real = dispatch.resolve_order_rule_with_mode
    def spy(o):
        calls["facade"] += 1
        return real(o)
    monkeypatch.setattr(oum, "resolve_order_rule_with_mode", spy)
    # Nur die Auflösung testen, nicht den COM-Upsert:
    resolved = oum.resolve_order_rule_with_mode(order)
    assert calls["facade"] == 1
    assert resolved.rule_id is None  # keine aktiven Regeln → Defaults
```

- [ ] **Step 2: Run — FAIL** (`AttributeError: order_upsert_microtech has no attribute 'resolve_order_rule_with_mode'`).

- [ ] **Step 3: Import + Aufrufstellen ersetzen**

In `orders/services/order_upsert_microtech.py` Import ergänzen und beide Zeilen ersetzen:

```python
from microtech.rule_engine.dispatch import resolve_order_rule_with_mode
```
```python
        resolved_rule = resolve_order_rule_with_mode(order)   # ersetzt OrderRuleResolverService().resolve_for_order(order=order) an :149 und :318
```

In `orders/services/order_sync_workflow.py:913` analog ersetzen (Import oben ergänzen).
`OrderRuleResolverService`-Import in `order_upsert_microtech.py` nur entfernen, wenn nicht mehr referenziert (sonst belassen — `ResolvedDatasetAction`/`ResolvedOrderRule` bleiben importiert).

- [ ] **Step 4: Run — PASS + volle Nicht-Regression**

Run:
```bash
.venv/bin/python -m pytest microtech/test_rule_engine_activation.py orders/tests.py -q
.venv/bin/python manage.py check
```
Expected: PASS, `check` sauber.

- [ ] **Step 5: Commit**

```bash
git add orders/services/order_upsert_microtech.py orders/services/order_sync_workflow.py microtech/test_rule_engine_activation.py
git commit -m "Route order path through rule-engine mode facade"
```

---

### Task 6: Admin — Modus-Steuerung + Verifikations-Gate

**Files:**
- Modify: `microtech/admin.py`
- Create: `microtech/templates/admin/microtech/rule_engine_verify.html`
- Test: `microtech/test_rule_engine_activation.py`

**Interfaces:**
- Consumes: `MicrotechSettings.rule_engine_order_mode`, `RuleEngineShadowRun`.
- Produces: Admin-URL `rule-engine/verify/` (GET: Übersicht letzter Schatten-Läufe + aktueller Modus; POST: Modus setzen), verlinkt aus der Regelwerk-Übersicht. Permission-gated (`has_change_permission`), CSRF via `admin_view`.

Verifikations-Gate (im Template dargestellt): Anzahl Läufe gesamt, Anzahl mit `is_equal=False` (letzte 200), Liste der jüngsten Diffs. „Auf Live schalten" nur anbieten, wenn in den letzten 200 Läufen **keine** Abweichung — sonst Hinweis „Erst Abweichungen prüfen".

- [ ] **Step 1: Failing test — Verify-View rendert & POST setzt Modus**

```python
def test_verify_view_get_and_post_sets_mode(admin_client):
    from django.urls import reverse
    from microtech.models import MicrotechSettings
    url = reverse("admin:microtech_orderrule_engine_verify")
    assert admin_client.get(url).status_code == 200
    resp = admin_client.post(url, {"mode": "shadow"})
    assert resp.status_code in (200, 302)
    assert MicrotechSettings.load().rule_engine_order_mode == "shadow"
```

(Hinweis: `admin_client`/`admin_user` via pytest-django; URL-Name analog zu bestehenden Editor-URLs in `microtech/admin.py` vergeben.)

- [ ] **Step 2: Run — FAIL** (URL/View fehlt).

- [ ] **Step 3: View + URL + Template**

In `MicrotechOrderRuleAdmin.get_urls()` ergänzen (Muster der bestehenden `builder/`-URLs):

```python
    path("rule-engine/verify/", self.admin_site.admin_view(self.rule_engine_verify_view),
         name="microtech_orderrule_engine_verify"),
```

```python
    def rule_engine_verify_view(self, request, *args, **kwargs):
        from django.shortcuts import render, redirect
        from django.contrib import messages
        from microtech.models import MicrotechSettings, RuleEngineShadowRun
        if not self.has_change_permission(request):
            from django.http import HttpResponseForbidden
            return HttpResponseForbidden("Keine Berechtigung.")
        settings_obj = MicrotechSettings.load()
        if request.method == "POST":
            mode = request.POST.get("mode", "")
            valid = {c[0] for c in MicrotechSettings.EngineMode.choices}
            if mode in valid:
                settings_obj.rule_engine_order_mode = mode
                settings_obj.save(update_fields=["rule_engine_order_mode"])
                messages.success(request, f"Regel-Engine-Modus auf '{mode}' gesetzt.")
            else:
                messages.error(request, "Ungültiger Modus.")
            return redirect("admin:microtech_orderrule_engine_verify")
        recent = list(RuleEngineShadowRun.objects.all()[:200])
        diffs = [r for r in recent if not r.is_equal]
        ctx = {
            **self.admin_site.each_context(request),
            "title": "Regel-Engine Verifikation",
            "mode": settings_obj.rule_engine_order_mode,
            "modes": MicrotechSettings.EngineMode.choices,
            "recent": recent[:50],
            "runs_total": RuleEngineShadowRun.objects.count(),
            "diff_count": len(diffs),
            "can_go_live": bool(recent) and not diffs,
            "overview_url": "../builder/",
        }
        return render(request, "admin/microtech/rule_engine_verify.html", ctx)
```

Template `rule_engine_verify.html` (erbt `admin/base_site.html`): aktuellen Modus + Formular (radio off/shadow/live, CSRF) anzeigen; `runs_total`, `diff_count`; „Auf Live schalten" nur bei `can_go_live`; Tabelle der `recent` (order_number, engine_rule_id, legacy_rule_id, is_equal, changed_json). Kurzer Hinweistext zum Rollback (Modus zurück auf off/shadow).

Verlinkung: in `rule_builder.html` Kopf einen Button „Engine-Verifikation & Cutover" auf `{% url 'admin:microtech_orderrule_engine_verify' %}`.

- [ ] **Step 4: Run — PASS.**

Run: `.venv/bin/python -m pytest microtech/test_rule_engine_activation.py -k verify -v`

- [ ] **Step 5: Commit**

```bash
git add microtech/admin.py microtech/templates/admin/microtech/rule_engine_verify.html microtech/templates/admin/microtech/rule_builder.html microtech/test_rule_engine_activation.py
git commit -m "Add rule-engine verification and cutover control in admin"
```

---

### Task 7: Bestehende Produktions-Regeln für die Engine aufbereiten (Backfill)

**Files:**
- Create: `microtech/management/commands/rule_engine_prepare.py`
- Test: `microtech/test_rule_engine_activation.py`

**Interfaces:**
- Produces: Management-Command `rule_engine_prepare` (Optionen `--dry-run`, `--enable`), das aktive Regeln ohne Trigger dem `order_create`-Trigger zuordnet, `execution_phase=BEFORE` sicherstellt und (nur mit `--enable`) `engine_enabled=True` setzt. Ohne `--enable`: nur Bericht (welche Regeln würden aktiviert). Zweck: damit `shadow`/`live` die gleichen Regeln wie der Legacy-Pfad auswertet.

- [ ] **Step 1: Failing test — dry-run ändert nichts, --enable aktiviert**

```python
def test_prepare_command_enable_sets_trigger_and_engine():
    from django.core.management import call_command
    from microtech.models import MicrotechOrderRule, RuleTrigger
    trg = _order_trigger()
    r = MicrotechOrderRule.objects.create(name="Legacy Regel", is_active=True, engine_enabled=False)
    call_command("rule_engine_prepare", "--dry-run")
    r.refresh_from_db(); assert r.engine_enabled is False and r.trigger_id is None
    call_command("rule_engine_prepare", "--enable")
    r.refresh_from_db()
    assert r.engine_enabled is True
    assert r.trigger_id == trg.id
    assert r.execution_phase == MicrotechOrderRule.ExecutionPhase.BEFORE
```

- [ ] **Step 2: Run — FAIL** (Command fehlt).

- [ ] **Step 3: Command implementieren**

```python
# microtech/management/commands/rule_engine_prepare.py
from django.core.management.base import BaseCommand
from microtech.models import MicrotechOrderRule, RuleTrigger
from microtech.rule_engine.order_resolver import ORDER_CREATE_TASK


class Command(BaseCommand):
    help = "Ordnet aktive Bestellregeln dem order_create-Trigger zu (Vorbereitung Engine-Cutover)."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument("--enable", action="store_true")

    def handle(self, *args, **opts):
        trigger = RuleTrigger.objects.filter(task_name=ORDER_CREATE_TASK, is_active=True).order_by("priority", "id").first()
        if trigger is None:
            self.stderr.write("Kein aktiver order_create-Trigger gefunden."); return
        qs = MicrotechOrderRule.objects.filter(is_active=True)
        touched = 0
        for rule in qs:
            needs = rule.trigger_id is None or rule.execution_phase != MicrotechOrderRule.ExecutionPhase.BEFORE or (opts["enable"] and not rule.engine_enabled)
            if not needs:
                continue
            touched += 1
            self.stdout.write(f"{'[dry-run] ' if opts['dry_run'] else ''}Regel {rule.pk} '{rule.name}' → trigger={trigger.code}, phase=before, enable={opts['enable']}")
            if opts["dry_run"]:
                continue
            rule.trigger = trigger
            rule.execution_phase = MicrotechOrderRule.ExecutionPhase.BEFORE
            if opts["enable"]:
                rule.engine_enabled = True
            rule.save(update_fields=["trigger", "execution_phase", "engine_enabled"])
        self.stdout.write(f"Fertig. Betroffen: {touched}.")
```

- [ ] **Step 4: Run — PASS.**

- [ ] **Step 5: Commit**

```bash
git add microtech/management/commands/rule_engine_prepare.py microtech/test_rule_engine_activation.py
git commit -m "Add management command to prepare rules for engine cutover"
```

---

### Task 8: Gesamtverifikation

**Files:** keine (nur Prüfen).

- [ ] **Step 1:** `.venv/bin/python manage.py check` → sauber.
- [ ] **Step 2:** `.venv/bin/python manage.py makemigrations --check --dry-run` → keine ausstehenden Migrationen.
- [ ] **Step 3:** `.venv/bin/python -m pytest microtech/ orders/ -q` → grün.
- [ ] **Step 4:** Browser-Verifikation (temp Superuser): Regelwerk-Übersicht → collapsible + Bearbeiten ok; „Engine-Verifikation & Cutover" öffnet, Modus off/shadow/live umschaltbar; Schatten-Läufe-Tabelle rendert. Danach temp Superuser + Test-Daten entfernen.
- [ ] **Step 5:** Ledger `.superpowers/sdd/2026-09-15-regelwerk-aktivierung/progress.md` abschließen.

---

## Cutover-Runbook (nach Deploy, manuell/kontrolliert)

1. Deploy mit `off` (Default) → nichts ändert sich live.
2. `rule_engine_prepare --dry-run` prüfen, dann `--enable` → aktive Regeln bekommen Trigger + `engine_enabled`.
3. Modus auf `shadow` → echte Bestellungen erzeugen Schatten-Läufe; Verifikations-Seite beobachten, bis `diff_count = 0` über repräsentative Bestellungen.
4. Bei sauberen Diffs Modus auf `live` (Verifikations-Seite bietet den Schalter erst dann an).
5. **Rollback jederzeit:** Modus zurück auf `shadow`/`off`.
6. Erst nach stabilem Live-Betrieb (eigener, späterer Schritt): Hardcoded-Mappings als Regeln migrieren, dann `OrderRuleResolverService` + Legacy-Felder entfernen.

## Self-Review

- **Spec-Abdeckung §7a (Paralleler Betrieb):** Default `off`, `shadow`-Modus + persistierte Diffs + Rollback → abgedeckt (Tasks 3/4/6).
- **Vertragstreue:** Engine liefert `ResolvedOrderRule` mit denselben Feldern, Downstream unverändert (Task 1/5).
- **Platzhalter:** keine — jeder Code-Step enthält realen Code.
- **Typkonsistenz:** `resolve_order_rule` (T1) ↔ `resolve_order_rule_with_mode` (T4) ↔ Aufrufstellen (T5); `EngineMode`/`RuleEngineShadowRun` (T3) konsistent in T4/T6 verwendet; `ORDER_CREATE_TASK` zentral in T1 definiert, in T4/T7 wiederverwendet.
