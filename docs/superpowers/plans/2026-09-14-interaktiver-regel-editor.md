# Interaktiver Regel-Editor: Implementierungsplan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (backend tasks) — the frontend/JS tasks are browser-verified by the controller. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Eine eigene, grafische **Editor-Seite pro Regel** im Admin, auf der Trigger, verschachtelte UND/ODER-Bedingungen und Aktionen (fester Wert oder `{{ Variable }}`) interaktiv bearbeitet und transaktional gespeichert werden — ohne den bestehenden Django-Admin-Rule-Builder anzutasten.

**Architecture:** Neuer Backend-Vertrag: `serialize_rule_for_edit` (Regel → JSON mit IDs/Codes), `save_rule_from_payload` (JSON → transaktionale Persistenz von Regel + Bedingungsbaum + Aktionen), Meta-Endpoint um Trigger erweitert, zwei Admin-Views (Editor-Seite GET, Save-Endpoint POST) plus „Neue Regel". Frontend: Vanilla-JS (`rule_editor.js`) rendert das Block-Layout editierbar, nutzt den bestehenden `rule-builder-meta`-Endpoint + Operator-/Dataset-Feld-Autocomplete, sammelt den Payload und POSTet an den Save-Endpoint. Aus der bestehenden grafischen Übersicht führen „Bearbeiten"/„Neue Regel" hierhin.

**Tech Stack:** Django 5 Admin (django-unfold), Vanilla-JS (keine Build-Kette), pytest + pytest-django. Browser-Verifikation über die in-app Browser-Tools mit temporärem Superuser.

**Spec:** [docs/superpowers/specs/2026-08-19-zentrales-regelwerk-design.md](../specs/2026-08-19-zentrales-regelwerk-design.md) §6; baut auf der Nur-Lese-Übersicht (v1.17.2) auf.

## Global Constraints

- **Nicht-Regression (HART):** `MicrotechOrderRuleAdmin`-Änderungsmaske, der bestehende JS-Builder (`order_rule_builder.js`), `MicrotechOrderRuleConditionForm`/`ActionForm` bleiben unberührt. Der Editor ist eine SEPARATE Seite.
- **Engine bleibt abgeschaltet:** der Editor schreibt nur Daten; keine Engine-Verdrahtung in Produktionspfade. `engine_enabled`/`shadow_mode` bleiben editierbare Felder mit ihren Defaults.
- **Speichern ist transaktional & „tree-replace":** beim Save werden die Bedingungsgruppen (+ Bedingungen) und Aktionen der Regel ersetzt (in `transaction.atomic`). Bei Validierungsfehler wird NICHTS geändert.
- **Berechtigungen:** Editor-GET erfordert `has_view_permission`; Save-POST erfordert `has_change_permission` (bzw. `has_add_permission` bei neuer Regel). CSRF beachten.
- **Basisklassen/Muster:** wie bestehende Custom-Views in `microtech/admin.py` (`TemplateResponse`, `JsonResponse`, `get_custom_urls`-Tupel `(route, name, view)` → `reverse("admin:<name>")`).
- **Python:** `.venv/bin/python`. **Tests:** `.venv/bin/python -m pytest <file> -v` (Postgres `db`-Container muss laufen: `docker compose up -d db`; pytest ggf. via `uv pip install pytest pytest-django`).
- **Keine `Co-Authored-By`-Zeilen** in Commits (User-Regel hat Vorrang).

---

## Dateistruktur

Neu:
- `microtech/rule_engine/editor.py` — `serialize_rule_for_edit(rule)` + `save_rule_from_payload(payload, *, rule=None) -> MicrotechOrderRule` + `EditorValidationError`.
- `microtech/templates/admin/microtech/rule_editor.html` — Editor-Seiten-Gerüst (Container, die JS füllt) + Bootstrap-JSON (rule + save-URL + meta-URL).
- `microtech/static/microtech/js/rule_editor.js` — Editor-Logik.
- `microtech/static/microtech/css/rule_editor.css` — Editor-Styling.
- `microtech/test_rule_editor.py` — Serializer-, Save- und View-Tests.

Modifiziert:
- `microtech/admin.py` — Meta um `triggers` erweitern; drei URLs + Views (`rule_editor_view`, `rule_editor_save_view`); „Neue Regel" nutzt dieselbe View ohne `object_id`.
- `microtech/templates/admin/microtech/rule_builder.html` — „Bearbeiten"-Link je Regel + „Neue Regel"-Button.

---

## Task 1: `serialize_rule_for_edit` (Regel → editier-JSON)

**Files:** Create `microtech/rule_engine/editor.py`; Test `microtech/test_rule_editor.py`

**Interfaces:**
- Produces: `serialize_rule_for_edit(rule) -> dict` mit Struktur:
  ```
  {id, name, priority, is_active, execution_phase, engine_enabled, shadow_mode,
   trigger_id,
   root_group: {logic, children:[<group>...], conditions:[{field_path, operator_code, expected_value, expected_value_2}...]} | null,
   actions:[{action_type, dataset_field_id, target_value}...]}
  ```
  Gruppen rekursiv (`children`). Nur die (eine) Wurzelgruppe als `root_group`; leere Regel → `root_group=None`.

- [ ] **Step 1: Failing test**

```python
# microtech/test_rule_editor.py
from django.test import TestCase
from microtech.models import (
    MicrotechOrderRule, MicrotechOrderRuleConditionGroup,
    MicrotechOrderRuleCondition, RuleTrigger,
)
from microtech.rule_engine.editor import serialize_rule_for_edit


class SerializeForEditTest(TestCase):
    def test_serializes_tree_with_ids_and_codes(self):
        trig = RuleTrigger.objects.create(code="ed_o", label="Bestellung",
            task_name="orders.microtech_order_upsert", context_root="orders.Order")
        rule = MicrotechOrderRule.objects.create(name="R", trigger=trig)
        root = MicrotechOrderRuleConditionGroup.objects.create(
            rule=rule, logic=MicrotechOrderRule.ConditionLogic.ALL)
        MicrotechOrderRuleCondition.objects.create(
            rule=rule, group=root, django_field_path="total",
            operator_code="between", expected_value="5", expected_value_2="9")
        data = serialize_rule_for_edit(rule)
        self.assertEqual(data["trigger_id"], trig.id)
        self.assertEqual(data["root_group"]["logic"], "all")
        c = data["root_group"]["conditions"][0]
        self.assertEqual((c["field_path"], c["operator_code"], c["expected_value"], c["expected_value_2"]),
                         ("total", "between", "5", "9"))
```

- [ ] **Step 2: Run → RED** (`ModuleNotFoundError`).
Run: `.venv/bin/python -m pytest microtech/test_rule_editor.py::SerializeForEditTest -v`

- [ ] **Step 3: Implement** `serialize_rule_for_edit` in `microtech/rule_engine/editor.py` (recursive group serialisation over `condition_groups`/`children`/`conditions`, actions over `actions`; use `dataset_field_id`; root = active `parent_id is None` group, or the first root group).

- [ ] **Step 4: Run → GREEN.**

- [ ] **Step 5: Commit**
```bash
git add microtech/rule_engine/editor.py microtech/test_rule_editor.py
git commit -m "Add serialize_rule_for_edit for the interactive rule editor"
```

---

## Task 2: `save_rule_from_payload` (transaktionale Persistenz)

**Files:** Modify `microtech/rule_engine/editor.py`; Test `microtech/test_rule_editor.py`

**Interfaces:**
- Consumes: Task-1-Struktur (dasselbe JSON-Schema, in beide Richtungen).
- Produces:
  - `class EditorValidationError(Exception)` mit `.messages: list[str]`.
  - `save_rule_from_payload(payload: dict, *, rule=None) -> MicrotechOrderRule`. In `transaction.atomic`: setzt `name/priority/is_active/execution_phase/engine_enabled/shadow_mode/trigger_id/condition_logic`; **löscht** vorhandene `condition_groups` + `actions` der Regel und legt sie aus `payload` neu an (rekursiver Baum: Wurzelgruppe + `children`; Bedingungen mit `group`); validiert: gültiger `execution_phase`, `trigger_id` existiert (oder null), `operator_code` in aktivem Operator-Katalog, `action_type` gültig, `set_field`-Aktion braucht `dataset_field_id`. Fehler → `EditorValidationError` (Rollback, nichts geändert).
- **Round-trip-Eigenschaft:** `serialize_rule_for_edit(save_rule_from_payload(p))` ist strukturgleich zu `p`.

- [ ] **Step 1: Failing tests**

```python
from microtech.rule_engine.editor import save_rule_from_payload, EditorValidationError, serialize_rule_for_edit
from microtech.models import MicrotechOrderRuleOperator

class SaveFromPayloadTest(TestCase):
    def setUp(self):
        MicrotechOrderRuleOperator.objects.get_or_create(code="eq", defaults={"name":"==","engine_operator":"eq"})
        MicrotechOrderRuleOperator.objects.get_or_create(code="between", defaults={"name":"between","engine_operator":"between"})

    def _payload(self):
        return {
            "name": "Neu", "priority": 30, "is_active": True,
            "execution_phase": "before", "engine_enabled": False, "shadow_mode": True,
            "trigger_id": None,
            "root_group": {"logic": "all", "children": [
                {"logic": "any", "children": [], "conditions": [
                    {"field_path": "total", "operator_code": "between", "expected_value": "5", "expected_value_2": "9"}]}],
                "conditions": [{"field_path": "billing_address__country_code", "operator_code": "eq",
                                "expected_value": "CH", "expected_value_2": ""}]},
            "actions": [{"action_type": "create_shipping_position", "dataset_field_id": None, "target_value": "V"}],
        }

    def test_round_trip(self):
        rule = save_rule_from_payload(self._payload())
        data = serialize_rule_for_edit(rule)
        self.assertEqual(data["name"], "Neu")
        self.assertEqual(len(data["root_group"]["children"]), 1)
        self.assertEqual(data["root_group"]["children"][0]["conditions"][0]["operator_code"], "between")
        self.assertEqual(data["actions"][0]["target_value"], "V")

    def test_resave_replaces_tree(self):
        rule = save_rule_from_payload(self._payload())
        p2 = self._payload(); p2["root_group"]["children"] = []; p2["actions"] = []
        save_rule_from_payload(p2, rule=rule)
        data = serialize_rule_for_edit(rule)
        self.assertEqual(data["root_group"]["children"], [])
        self.assertEqual(data["actions"], [])

    def test_invalid_operator_rolls_back(self):
        p = self._payload(); p["root_group"]["conditions"][0]["operator_code"] = "nope"
        with self.assertRaises(EditorValidationError):
            save_rule_from_payload(p)
```

- [ ] **Step 2: Run → RED.**
- [ ] **Step 3: Implement** `save_rule_from_payload` + `EditorValidationError` (transaction.atomic, delete+recreate, validation as above).
- [ ] **Step 4: Run → GREEN.**
- [ ] **Step 5: Commit**
```bash
git add microtech/rule_engine/editor.py microtech/test_rule_editor.py
git commit -m "Add transactional save_rule_from_payload for the rule editor"
```

---

## Task 3: Meta-Endpoint um Trigger erweitern

**Files:** Modify `microtech/admin.py` (`rule_builder_meta_view`); Test `microtech/test_rule_editor.py`

**Interfaces:** Der bestehende `rule-builder-meta`-JSON bekommt zusätzlich `"triggers": [{id, code, label, task_name, context_root}...]` (aktive, nach priority). Alles andere unverändert.

- [ ] **Step 1: Failing test** — GET `reverse("admin:microtech_orderrule_builder_meta")` als Superuser → JSON enthält `triggers` mit dem angelegten Trigger. (Nutze `RuleTrigger.objects.get_or_create` mit nicht-geseedetem Code, um Seed-Kollision zu vermeiden.)
- [ ] **Step 2: Run → RED.**
- [ ] **Step 3: Implement** — Trigger-Liste additiv in den `payload` von `rule_builder_meta_view`.
- [ ] **Step 4: Run → GREEN** (+ `manage.py check`).
- [ ] **Step 5: Commit**
```bash
git add microtech/admin.py microtech/test_rule_editor.py
git commit -m "Expose rule triggers in rule-builder meta endpoint"
```

---

## Task 4: Editor-Views + URLs (GET-Seite, POST-Save, Neue Regel)

**Files:** Modify `microtech/admin.py`; Test `microtech/test_rule_editor.py`

**Interfaces:**
- URLs in `get_custom_urls` (Namen → `admin:<name>`):
  - `"builder/new/"` → `microtech_orderrule_editor_new` → `rule_editor_view` (ohne object_id)
  - `"builder/<path:object_id>/edit/"` → `microtech_orderrule_editor` → `rule_editor_view`
  - `"builder/save/"` → `microtech_orderrule_editor_save` → `rule_editor_save_view` (POST)
- `rule_editor_view(request, object_id=None)`: `has_view_permission` sonst redirect; lädt Regel (oder None), rendert `admin/microtech/rule_editor.html` mit Kontext: `rule_json` (Task-1-Serialisierung oder leeres Skelett), `save_url`, `meta_url`, `overview_url`, `opts`, admin each_context.
- `rule_editor_save_view(request)`: nur POST; CSRF; `has_change_permission` (bzw. add bei neuer); parst `json.loads(request.body)`; `save_rule_from_payload`; bei `EditorValidationError` → `JsonResponse({"ok":False,"errors":[...]}, status=400)`; sonst `JsonResponse({"ok":True,"id":rule.id,"redirect":<overview_url>})`.

- [ ] **Step 1: Failing tests** — (a) GET editor page for a rule → 200 + enthält das Bootstrap-JSON/Container-IDs; (b) GET new → 200; (c) POST save with a valid payload (JSON body, `content_type="application/json"`) → 200 `{"ok":true}` und die Regel existiert mit den Aktionen; (d) POST invalid → 400 `{"ok":false}`.
- [ ] **Step 2: Run → RED.**
- [ ] **Step 3: Implement** views + URLs.
- [ ] **Step 4: Run → GREEN** (+ `manage.py check`).
- [ ] **Step 5: Commit**
```bash
git add microtech/admin.py microtech/test_rule_editor.py
git commit -m "Add rule editor GET page and transactional save endpoint"
```

---

## Task 5: Editor-Template + CSS-Gerüst

**Files:** Create `microtech/templates/admin/microtech/rule_editor.html`, `microtech/static/microtech/css/rule_editor.css`

**Interfaces:** Template extends `admin/base_site.html`; lädt CSS + `rule_editor.js`; enthält: JSON-Bootstrap (`{{ rule_json|json_script:"rule-data" }}`), `data-…`-Attribute für `save_url`/`meta_url`/`overview_url`, und leere Container mit stabilen IDs, die das JS füllt (`#re-trigger`, `#re-conditions`, `#re-actions`, `#re-summary`, `#re-save`, Flags-Inputs). CSS baut auf dem Overview-Look auf.

- [ ] **Step 1:** Template + CSS anlegen (statisches Gerüst; kein JS-Verhalten hier).
- [ ] **Step 2:** `manage.py check` clean; die Editor-GET-Seite aus Task 4 rendert das Gerüst (Test aus Task 4 deckt 200 + Container-IDs ab; ggf. Assertion auf eine Container-ID ergänzen).
- [ ] **Step 3: Commit**
```bash
git add microtech/templates/admin/microtech/rule_editor.html microtech/static/microtech/css/rule_editor.css
git commit -m "Add rule editor page skeleton template and CSS"
```

---

## Task 6: Editor-JS — Rendern + Bearbeiten + Speichern (Controller-gebaut, browser-verifiziert)

**Files:** Create `microtech/static/microtech/js/rule_editor.js`

**Note:** Kein JS-Unit-Framework im Projekt — diese Aufgabe wird vom Controller gebaut und **im Browser** gegen einen laufenden Dev-Server verifiziert (temporärer Superuser), plus der Save-Round-trip über den (getesteten) Endpoint aus Task 4.

**Umfang:**
- Beim Laden: `#rule-data` JSON + Meta (`meta_url`) holen; Trigger-Select, Flags (execution_phase, engine_enabled, shadow_mode, name, priority, is_active) füllen.
- Bedingungsbaum rendern (rekursiv): je Gruppe UND/ODER-Umschalter, „+ Bedingung", „+ Untergruppe", „Gruppe entfernen"; je Bedingung Feld-Select (aus meta `django_fields`), Operator-Select (gefiltert per `allowed_operator_codes`), Wert-Eingabe (+ zweiter Wert bei `between`, ausgeblendet bei wertlosen Operatoren), „entfernen".
- Aktionen rendern: Typ-Select (set_field / create_extra_position / create_shipping_position), bei set_field Ziel-Feld (Dataset-Feld-Autocomplete/Select), Wert-Eingabe mit Umschalter **fester Wert / Variable**; Variable-Picker setzt `{{ Pfad }}` aus meta `django_fields`.
- Live-Klartext-Vorschau (wie Overview-Semantik).
- „Speichern": Payload im Task-1/2-Schema sammeln, `POST save_url` (JSON + CSRF-Header); bei `ok` → redirect zur Übersicht; bei `400` Fehler anzeigen.

- [ ] **Step 1:** `rule_editor.js` implementieren.
- [ ] **Step 2 (Verifikation, Controller):** Dev-Server starten, temporären Superuser anlegen, im Browser Editor öffnen, eine Regel bauen/ändern, speichern → prüfen dass die Übersicht sie zeigt und `serialize_rule_for_edit` in der DB passt; Screenshot für den User; temp. Superuser wieder löschen.
- [ ] **Step 3: Commit**
```bash
git add microtech/static/microtech/js/rule_editor.js
git commit -m "Add interactive rule editor JavaScript"
```

---

## Task 7: Übersicht → Editor verlinken

**Files:** Modify `microtech/templates/admin/microtech/rule_builder.html`

**Interfaces:** Je Regelkarte ein „Bearbeiten"-Link → `admin:microtech_orderrule_editor` (mit `rule.id`); oben ein „Neue Regel"-Button → `admin:microtech_orderrule_editor_new`. (Reverse im Template via `{% url %}`.)

- [ ] **Step 1:** Links ergänzen.
- [ ] **Step 2:** `manage.py check` clean; Overview-Test (falls vorhanden) grün; ein Test, dass die Übersichtsseite den Editor-Link enthält.
- [ ] **Step 3: Commit**
```bash
git add microtech/templates/admin/microtech/rule_builder.html microtech/test_rule_builder_overview.py
git commit -m "Link rule overview cards to the interactive editor"
```

---

## Task 8: Gesamt-Verifikation

- [ ] `.venv/bin/python manage.py check` clean; `makemigrations --check` „No changes" (keine Modelländerung erwartet — nur neue Views/JS).
- [ ] `.venv/bin/python -m pytest microtech/test_rule_editor.py microtech/test_rule_builder_overview.py microtech/test_admin_rulebuilder.py microtech/test_rule_forms.py microtech/test_rule_engine_admin.py -q` → alle grün (inkl. Nicht-Regression des alten Builders).
- [ ] Browser-Smoke (Controller): Editor neu → Regel bauen → speichern → Übersicht zeigt sie → Editor erneut öffnen zeigt dieselben Werte. Screenshot an den User.

## Self-Review (gegen Spec/Constraints)
- Trigger/Bedingungsbaum (verschachtelt, UND/ODER)/Aktionen (fest/Variable) interaktiv editierbar → Tasks 1–6. ✅
- Transaktionaler, validierter Save; Round-trip → Task 2. ✅
- Separate Seite, alter Builder unberührt (Nicht-Regression) → Constraints + Task 8. ✅
- Engine bleibt abgeschaltet (nur Datenpflege) → Constraints. ✅

## Bewusst NICHT in diesem Plan (später)
- Drag-&-Drop-Umsortierung von Prioritäten (erstmal Auf/Ab oder Zahlenfeld).
- Kontext-spezifische Variablenkataloge pro Trigger (MVP nutzt den vorhandenen `django_fields`-Katalog).
- Ablösen der Django-Admin-Änderungsmaske (bleibt als Fallback bestehen).
