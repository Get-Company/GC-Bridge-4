# Na1-Regelwerk Implementation Plan

> **For agentic workers:** Umsetzung task-by-task (TDD). Steps als Checkbox.

**Goal:** Die Na1-Auflösung einer Anschrift regelgesteuert machen (Trigger „Anschrift schreiben"), abgesichert per `off/shadow/live`, Code bleibt Fallback.

**Architecture:** Kleine Engine-Erweiterung (Listen-Operatoren + Anrede-Konstante/Resolver), neuer Adress-Trigger + kontextabhängiger Feldkatalog, Adress-Resolver + Modus-Fassade, Verdrahtung in `_build_postal_address_input`.

**Tech Stack:** Django 5, Postgres (Docker `db`), pytest, django-unfold, Vanilla-JS-Editor.

**Spec:** `docs/superpowers/specs/2026-09-15-na1-regelwerk-design.md`

## Global Constraints

- Default `off` → byte-identisches heutiges Verhalten; Code bleibt Fallback bei jedem Fehler.
- `uv pip install`; Tests gegen Postgres, ohne Microtech-COM/GraphQL.
- Kein `Co-Authored-By`.
- `RuleConstant` (`microtech/models.py:709`), `EngineMode` (`MicrotechSettings`), `RuleEngineShadowRun` wiederverwenden.
- Adressmodell: `customer.Address` (`customer/models.py:50`). Anrede-Sets: `_SALUTATION_FEMALE_VALUES`/`_SALUTATION_MALE_VALUES` (`customer/services/webshop_mapping.py`).

---

### Task 1: Listen-Operatoren `in_list` / `not_in_list`

**Files:** Modify `microtech/rule_engine/operators.py`; Test `microtech/test_na1_regelwerk.py`.
**Produces:** `evaluate_operator("in_list"|"not_in_list", actual, expected, _, _)`; Helfer `parse_list(expected) -> list[str]`.

- [ ] Test: `in_list("herr","herr,frau")` True; `not_in_list("ACME","herr,frau")` True; `in_list("HERR","herr\nfrau")` True (case-insensitiv, Zeilentrenner); `in_list("","a,b")` False.
- [ ] Run → FAIL.
- [ ] Implementieren: `parse_list` splittet an `,` und `\n`, trimmt, entfernt Leere; Vergleich casefold.
- [ ] Run → PASS. Commit.

### Task 2: Anrede-Konstante + Resolver `@anreden` / `@anrede`

**Files:** Migration (Seed `RuleConstant` `anreden`); Modify `microtech/rule_engine/resolvers.py`; Test.
**Consumes:** `RuleConstant.get_list`, `CustomerWebshopMappingService.translate_salutation_to_de`.
**Produces:** resolver `anreden` (Komma-String der Liste), `anrede` (Privat-Anrede aus Kontext-Adresse).

- [ ] Test: Seed vorhanden → `resolve_named("anreden", ctx)` enthält "herr"/"frau"; für Adresse mit title="mr" → `resolve_named("anrede", ctx)` == "Herr"; ohne Anrede → title-Fallback.
- [ ] Run → FAIL.
- [ ] Migration `RuleConstant(key="anreden", kind=LIST, value=…)` (get_or_create); resolvers `anreden`/`anrede` ergänzen.
- [ ] Run → PASS. Commit.

### Task 3: Trigger „Anschrift schreiben" + kontextabhängiger Feldkatalog

**Files:** Migration (Seed `RuleTrigger address_write`); Modify `microtech/rule_builder.py`; Test.
**Produces:** `get_django_field_defs(context_root="customer.Address")` liefert Adressfelder (`name1,…`); Order-Katalog unverändert; jede DjangoFieldDef trägt `context_root`.

- [ ] Test: Katalog für `customer.Address` enthält `name1`,`title`,`first_name`,`last_name`; Order-Katalog enthält weiterhin `billing_address__country_code`; Trigger `address_write` existiert.
- [ ] Run → FAIL.
- [ ] Katalog context-aware machen (Order-Zweig unverändert, Address-Zweig neu); Trigger-Seed-Migration.
- [ ] Run → PASS. Commit.

### Task 4: Modus-Setting `rule_engine_address_mode`

**Files:** Modify `microtech/models.py` + Migration; Test.
**Produces:** `MicrotechSettings.rule_engine_address_mode` (EngineMode, default OFF).

- [ ] Test: Default OFF; Choices {off,shadow,live}.
- [ ] Run → FAIL. Feld + Migration. Run → PASS. Commit.

### Task 5: Adress-Resolver `resolve_address_fields`

**Files:** Create `microtech/rule_engine/address_resolver.py`; Test.
**Consumes:** `MicrotechOrderRule` (trigger address_write, engine_enabled, phase before), `EvaluationContext`, `rule_matches`, `render_template`.
**Produces:** `resolve_address_fields(address) -> dict[str,str]` (erste passende Regel → `{dataset_field_name: value}`); `ADDRESS_WRITE_TASK="customer.microtech_postal_address"`.

- [ ] Test: Firma-Adresse + Regel (Bedingungen wie Spec D.1, Aktion Na1="Firma") → `{"Na1":"Firma"}`; Privat-Adresse + Fallback-Regel (Na1="{{@anrede}}") → `{"Na1":"Herr"}`; keine aktive Regel → `{}`.
- [ ] Run → FAIL. Implementieren (analog `order_resolver.resolve_order_rule`, Ziel = dataset_field.field_name). Run → PASS. Commit.

### Task 6: Fassade `resolve_address_na1_with_mode`

**Files:** Modify `microtech/rule_engine/dispatch.py`; Test.
**Consumes:** Task 5, `MicrotechSettings.rule_engine_address_mode`, `RuleEngineShadowRun`, `CustomerWebshopMappingService.resolve_na1`.
**Produces:** `resolve_address_na1_with_mode(address) -> str | None`.

- [ ] Test: off→None (kein Resolver-Aufruf); shadow→None + ShadowRun geschrieben (changed_json enthält "Na1"); live→Engine-Na1; Engine-Fehler→None.
- [ ] Run → FAIL. Implementieren (Code-Na1 via `resolve_na1` für Vergleich; try/except → None). Run → PASS. Commit.

### Task 7: Verdrahtung in `_build_postal_address_input`

**Files:** Modify `customer/services/customer_upsert_microtech.py`; Test.
**Produces:** `name1` = Engine-Na1 (nur live-Erfolg) sonst bisheriger Code.

- [ ] Test: Fassade→"X" → postal-address name1=="X"; Fassade→None → name1 == bisheriger `_resolve_na1_for_anschrift`-Wert (off-Verhalten unverändert). Ohne COM (Fassade monkeypatchen; `_build_postal_address_input` isoliert testen).
- [ ] Run → FAIL. Einbauen (`engine_na1 = resolve_address_na1_with_mode(address); name1 = engine_na1 if engine_na1 is not None else <code>`). Run → PASS + bestehende customer-Tests grün. Commit.

### Task 8: Editor — Adressfelder im richtigen Kontext

**Files:** Modify `microtech/admin.py` (rule_builder_meta_view), `microtech/static/microtech/js/rule_editor.js`; Test.
**Produces:** Meta liefert `django_fields` mit `context_root`; Editor filtert Feld-Dropdown nach `context_root` des gewählten Triggers.

- [ ] Test (view): Meta-Payload enthält Adressfelder mit `context_root="customer.Address"` und Order-Felder mit `context_root="orders.Order"`.
- [ ] Run → FAIL. Meta erweitern; JS: Feldliste nach Trigger-Kontext filtern (Trigger→context_root aus META.triggers). Run → PASS.
- [ ] Browser-Verifikation: Trigger „Anschrift schreiben" wählen → nur Adressfelder; Regel „Firma → Na1" bauen (inkl. `nicht in Liste {{@anreden}}`, `≠ {{title}}`) → speichern → Round-trip. Temp-Superuser/Testdaten aufräumen. Commit.

### Task 9: Gesamtverifikation

- [ ] `manage.py check`; `makemigrations --check`; `pytest microtech/ customer/ -q` grün.
- [ ] Ledger `.superpowers/sdd/2026-09-15-na1-regelwerk/progress.md`.

## Self-Review

- Spec-Abdeckung A–D → Tasks 1/2, 5/6/7, 3/8, 4. ✅
- Fallback-/Modus-Semantik in Task 6/7 explizit. ✅
- Keine Platzhalter; Namen konsistent (`resolve_address_fields`, `resolve_address_na1_with_mode`, `ADDRESS_WRITE_TASK`, `rule_engine_address_mode`, `address_write`). ✅
