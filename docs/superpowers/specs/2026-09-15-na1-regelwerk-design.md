# Na1-Auflösung als Regelwerk — Design

**Datum:** 2026-09-15
**Status:** freigegeben (Brainstorming), bereit für Implementierungsplan
**Zweck:** Die heute hart codierte Na1-Auflösung (`resolve_na1` / `_resolve_na1_for_anschrift`)
aus dem Code in ein **Regelwerk** überführen, sodass sie ohne Code-Änderung steuerbar ist —
mit der bewährten `off/shadow/live`-Absicherung. Erster Baustein, um den Adress-/Kunden-Pfad
schrittweise regelgesteuert zu machen.

## Kontext & Ausgangslage

Heute berechnet `CustomerWebshopMappingService.resolve_na1` (`customer/services/webshop_mapping.py:94`)
den Microtech-Wert `Na1` einer Anschrift:

- **Firma** → `Na1 = "Firma"` (der Firmenname landet über `resolve_na2` in `Na2`)
- **Privat** → `Na1 = Anrede` (`translate_salutation_to_de(title) → (name1) → title`)

„Firma" ist definiert durch `is_company_address` (`webshop_mapping.py:125`):
`name1` gefüllt **und** keine Anrede **und** ≠ Titel **und** ≠ „Vorname Nachname".

Der neue Engine-Pfad rendert erwartete Bedingungswerte bereits als Template
(`evaluation.py:20` → `render_template(condition.expected_value, context)`), daher sind
**Feld-gegen-Feld-Vergleiche** (`{{ title }}`) und **Verkettung** (`{{ first_name }} {{ last_name }}`)
ohne weitere Arbeit möglich. Vergleiche sind case-insensitiv (`operators.py` → Legacy-`_evaluate_condition`).

## Entscheidungen (aus dem Brainstorming)

1. Na1-Logik wird **regelgesteuert**; der Code bleibt vorerst als `off`-Pfad + Fallback.
2. Firma-Erkennung **komplett als Bedingungen** (keine code-gestützte `is_company`-Variable).
3. Auswertung auf **Anschrifts-Ebene** über einen **neuen Trigger „Anschrift schreiben"**
   (Kontext = `customer.Address`).
4. Absicherung über **eigenen Modus** `rule_engine_address_mode` (off/shadow/live), unabhängig
   vom Order-Modus. Default `off` → heutiges Verhalten unverändert.
5. **YAGNI:** Umfang nur **Na1**. Trigger/Katalog/Anbindung werden wiederverwendbar gebaut
   (Na2 u. a. später ohne neuen Unterbau).

## Architektur

### A. Engine-Erweiterung (klein)

**A.1 Operatoren `in_list` / `not_in_list`** in `microtech/rule_engine/operators.py`
(`evaluate_operator`): der erwartete Wert wird als Liste geparst (Trenner Komma **und**
Zeilenumbruch), Elemente getrimmt und casefold-verglichen.

```
in_list(actual, expected)      = casefold(actual) ∈ {casefold(x) for x in parse_list(expected)}
not_in_list(actual, expected)  = not in_list(...)
```

Leere/None-`actual` → `in_list=False`, `not_in_list=True`.
Registrierung als `MicrotechOrderRuleOperator` (Seed-Migration) mit
`engine_operator="in_list"`/`"not_in_list"`, Labels „ist in Liste" / „ist nicht in Liste".

**A.2 Anrede-Konstante + Resolver** — `RuleConstant` (`microtech/models.py:709`, `kind=LIST`)
mit `key="anreden"`, Werte = `_SALUTATION_FEMALE_VALUES ∪ _SALUTATION_MALE_VALUES`
(aus `webshop_mapping.py`) via Seed-Migration. Zwei benannte Resolver in
`microtech/rule_engine/resolvers.py`:

- `@anreden` → gibt die Anrede-Liste als Komma-String zurück (`RuleConstant.get_list("anreden")`),
  damit sie als erwarteter Wert `{{ @anreden }}` in einer `not_in_list`-Bedingung nutzbar ist.
- `@anrede` → liefert die Privat-Anrede des Kontext-Adressobjekts:
  `translate_salutation_to_de(title) → translate_salutation_to_de(name1) → title`
  (Wiederverwendung `CustomerWebshopMappingService.translate_salutation_to_de`).

### B. Neuer Trigger + kontextabhängiger Feldkatalog

**B.1 Trigger** — `RuleTrigger` (Seed-Migration): `code="address_write"`,
`label="Anschrift schreiben"`, `task_name="customer.microtech_postal_address"`,
`context_root="customer.Address"`, `priority=30`.

**B.2 Kontextabhängiger Feldkatalog** — heute ist `get_django_field_defs`
(`microtech/rule_builder.py`) fest auf `Order` verwurzelt (`_ALLOWED_RELATIONS`,
`Order._meta`). Neu: eine Katalog-Funktion, die pro `context_root` die passenden Felder liefert.

- Für `customer.Address`: direkte Felder `name1, name2, name3, title, first_name, last_name,
  street, postal_code, city, country_code, department, email, phone` (Pfade ohne Relation-Prefix,
  z. B. `name1`), Wertetyp über `_field_value_kind`.
- Der Order-Katalog bleibt unverändert (`context_root="orders.Order"`).
- Die Meta-Antwort (`rule_builder_meta_view`) liefert `django_fields` künftig **mit
  `context_root`**; der Editor zeigt nur Felder, deren `context_root` zum gewählten Trigger passt
  (JS-Filter analog zur bestehenden Operator-Filterung).

Für die **Engine-Auswertung** genügt, dass `EvaluationContext(address).get("name1")` das
Adressfeld liest (bestehende Pfad-Traversierung). Fehlt ein Pfad im Feldmap, ist `value_kind`
= `string` — für Na1-Bedingungen ausreichend.

### C. Anbindung des Adress-Pfads an die Engine (Kern)

**C.1 Modus-Setting** — `MicrotechSettings.rule_engine_address_mode`
(`EngineMode`-Choices off/shadow/live wiederverwenden, Default `off`) + Migration.

**C.2 Adress-Resolver** — `microtech/rule_engine/address_resolver.py`:
`resolve_address_fields(address) -> dict[str, str]` wertet aktive
`address_write`-Regeln (engine_enabled, phase=before, `trigger__task_name="customer.microtech_postal_address"`)
in Prioritätsreihenfolge aus; die **erste passende** Regel liefert ihre `set_field`-Aktionen als
`{dataset_field_name: render_template(target_value)}`. Zielfeld ist das **Adressen-Dataset-Feld
`Na1`** (bestehendes Aktionsmodell, `dataset_field` → `MicrotechDatasetField`).

**C.3 Fassade + Verdrahtung** — `resolve_address_na1_with_mode(address) -> str | None`
(in `microtech/rule_engine/dispatch.py`, analog `resolve_order_rule_with_mode`):

- `off`: `None` zurück (kein Engine-Aufruf) → Code entscheidet.
- `shadow`: Engine berechnen, `_persist_shadow_run` (Code-Na1 vs. Engine-Na1), **`None`** zurück
  (Code bleibt maßgeblich).
- `live`: Engine-Na1 zurück; bei leerem/keinem Ergebnis oder Fehler → `None` (Fallback Code).
- Jeder Engine-Fehler → `None` (Code-Fallback); der Adress-Pfad bricht nie.

In `_build_postal_address_input` (`customer/services/customer_upsert_microtech.py:351`) wird
`name1` so bestimmt:

```python
engine_na1 = resolve_address_na1_with_mode(address)     # None außer im live-Erfolgsfall
name1 = engine_na1 if engine_na1 is not None else self._resolve_na1_for_anschrift(...)  # heutiger Code
```

Der Code-Zweig (`resolve_na1`) für den Shadow-Vergleich wird ohnehin berechnet.

**C.4 Schatten-Log** — Wiederverwendung `RuleEngineShadowRun`; `order_number` trägt eine
Adress-Kennung (`address.pk`), `task_name="customer.microtech_postal_address"`,
`changed_json` enthält `{"Na1": {"code": …, "engine": …}}`.

### D. Die Regeln (durch den Anwender im grafischen Editor)

Keine Code-Aufgabe — nur nach dem Bau anzulegen (Trigger „Anschrift schreiben"):

1. **„Firma → Na1"** (Prio 10), UND-Gruppe:
   `name1` **ist nicht leer**; `name1` **ist nicht in Liste** `{{ @anreden }}`;
   `name1` **ist nicht identisch** `{{ title }}`; `name1` **ist nicht identisch**
   `{{ first_name }} {{ last_name }}` → Aktion `Na1` setzen = `Firma`.
2. **„Privat → Na1"** (Prio 100, ohne Bedingung) → Aktion `Na1` setzen = `{{ @anrede }}`.

## Datenfluss

```
customer upsert → _build_postal_address_input(address)
  → resolve_address_na1_with_mode(address)
       off    → None
       shadow → resolve_address_fields(address)["Na1"] vs resolve_na1 → ShadowRun; None
       live   → resolve_address_fields(address)["Na1"]  (sonst None)
  → name1 = engine-Na1 ?? resolve_na1(address)    (Fallback Code)
```

## Fehlerbehandlung

- Engine-Ausnahme, fehlende Regel/Aktion, leeres Ergebnis → `None` → Code-Fallback.
- Modus nicht ladbar → `off`.
- Kein `Na1`-Dataset-Feld gepflegt → Aktion greift nicht → `None` → Code-Fallback.

## Nicht im Umfang (bewusst)

- Na2 und weitere Adressfelder (später, gleicher Unterbau).
- Entfernen der alten `resolve_na1`/`_resolve_na1_for_anschrift` — erst nach verifiziertem
  Live-Betrieb (eigener Aufräum-Schritt).
- Kunden-Ebene (customer-Input-Felder wie taxCategory/salutation) — nicht Teil dieses Wurfs.

## Test-Strategie

Alle Tests DB-basiert (Postgres), **ohne** Microtech-COM/GraphQL:

- Operatoren `in_list`/`not_in_list` (Einheiten, inkl. Liste aus `{{ @anreden }}`).
- Resolver `@anreden`/`@anrede` (mit Adress-Kontext).
- `resolve_address_fields`: Firma-Adresse → `{"Na1":"Firma"}`; Privat-Adresse (Fallback-Regel)
  → `{"Na1":"<Anrede>"}`; keine Regel → `{}`.
- Fassade: off→None (kein Engine-Aufruf); shadow→None + ShadowRun geschrieben; live→Engine-Wert;
  Engine-Fehler→None.
- Verdrahtung: `_build_postal_address_input` nimmt Engine-Na1 nur im live-Erfolgsfall, sonst Code
  (byte-identisch zu heute im `off`-Modus) — ohne COM, durch Injektion/Monkeypatch der Fassade.
- Feldkatalog: `customer.Address`-Kontext liefert `name1` u. a.; Order-Katalog unverändert.
```
```

## Selbst-Review

- **Platzhalter:** keine.
- **Konsistenz:** Fassaden-/Resolver-Namen und Modus-Setting durchgängig; ShadowRun wiederverwendet.
- **Scope:** genau ein Feld (Na1), ein Trigger, ein Modus — für einen Implementierungsplan geeignet.
- **Ambiguität:** „erste passende Regel" (nicht Merge mehrerer) explizit; Fallback-Semantik
  (`None` = Code) explizit.
