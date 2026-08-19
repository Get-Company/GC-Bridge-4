# Zentrales Regelwerk — Design

**Datum:** 2026-08-19
**Status:** Entwurf zur Review
**Betrifft:** `microtech/` (Modelle, Admin, Rule-Builder), Ablösung von `customer/webshop*.yaml`, perspektivisch Shopware→Bridge-Mapping
**Begleitdokument:** [Inventar der hart codierten Regeln & Mappings](2026-08-19-hardcoded-regeln-inventar.md) — vollständige Übernahme-Checkliste

## 1. Ziel und Motivation

Heute existieren drei getrennte, teils inkonsistente Wege, um Feldwerte beim
Datenaustausch zu bestimmen:

1. **`MicrotechOrderRule`** — reife Wenn-Dann-Engine mit Bedingungen und Aktionen,
   grafischer JS-Builder im Unfold-Admin. Implizit nur an den Order-Upsert gebunden,
   Bedingungen sind *flach* (ein UND/ODER für alle).
2. **`customer/webshop.yaml` / `webshop_de.yaml`** — feste Default-Werte für
   Microtech-Kundenfelder, als Datei auf Platte, nicht im Admin editierbar, nur
   zwei Varianten per Länder-Weiche. `Na1`-Logik zusätzlich hart in Python.
3. **Shopware → Bridge** — Feldzuordnung hart in Python (`customer_sync.py`,
   `shopware/services/order.py`).

**Ziel:** Ein **zentrales, trigger-gesteuertes Regelwerk**, das alle drei Fälle als
Spezialfälle desselben Modells abbildet und über einen grafischen Block-Builder im
Admin gepflegt wird.

Eine Regel ist stets: **Trigger → Bedingungsbaum → Aktionen.**

- Webshop-Defaults = Regel(Trigger „Kunde anlegen", keine Bedingung, feste Werte).
- Shopware-Mapping = Aktionen mit `{{ Quelle.Feld }}`-Variablen.

## 2. Entscheidungen (aus dem Brainstorming)

| Thema | Entscheidung |
|---|---|
| Umfang | Eine gemeinsame Engine für alle drei Bereiche |
| Builder-Bedienung | Vertikaler Block-Builder (Trigger → Wenn → Dann, eingerückte Gruppen) — **kein** freier Knoten-Canvas |
| Trigger-Quelle | Kuratierter Katalog von Geschäfts-Events, zeigt auf Celery-Tasks |
| Bedingungen | Verschachtelte Gruppen (Baum), je Gruppe UND/ODER |
| Operatoren | Bestehende + `between`, `before`, `after`, `is_true`, `is_false` |
| Aktionswert | Fester Wert **oder** Variable `{{ Wurzel.Feld }}` (Template) |
| Variablen-Umfang | Kontext-Wurzel des Triggers (erreichbare Feldpfade) |
| Ausführungspunkt | Pro Regel wählbar: **vor** oder **nach** dem Trigger-Task |
| Migrationsweg | Bestehendes `MicrotechOrderRule`-Modell direkt ausbauen |
| Absicherung | Schatten-/Dry-Run-Modus pro Regel, um gefahrlos scharf zu schalten |

## 3. Frontend-Rahmenbedingung

Das Projekt hat **keine Frontend-Build-Kette** (kein `package.json`, node_modules,
Webpack/Vite). Der bestehende Builder ist reines Vanilla-JS (IIFE), geladen über die
Django-`Media`-Klasse, mit `fetch` gegen Django-JSON-Endpoints. Der neue Builder
bleibt in diesem Muster: **Vanilla-JS, keine neue Toolchain, keine React-Abhängigkeit.**

## 4. Datenmodell

Erweiterung der Modelle in `microtech/models.py`. Rückwärtskompatibel: bestehende
Felder bleiben, neue Struktur wird additiv eingeführt und per Datenmigration befüllt.

### 4.1 Trigger-Katalog — neu: `RuleTrigger`

```
code           CharField unique      z. B. "order_create", "customer_create"
label          CharField             "Bestellung anlegen"
task_name      CharField             "orders.microtech_order_upsert" (Celery-Task-Name)
context_root   CharField             "orders.Order" (app_label.Model) — Variablen-Namensraum
is_active      Bool
priority       PositiveInt
```

- Der Trigger-Katalog ist bewusst **kuratiert**: nur Geschäfts-Events, nicht jede rohe
  Task (Poll/Cleanup/Watchdog bleiben außen vor).
- `context_root` legt fest, welche Modell-Wurzel die Variablen- und Bedingungsfelder
  aufspannt (z. B. `Order` → `Order.Kunde.Firma`, `Order.Positionen.*`).

### 4.2 Regel — Erweiterung `MicrotechOrderRule`

Neue Felder:

```
trigger           FK(RuleTrigger, null=True)   — welches Event
execution_phase   Choices("before", "after")   — vor/nach dem Task, Default "before"
shadow_mode       Bool default False           — Dry-Run: evaluieren + protokollieren, nicht anwenden
```

`condition_logic` (flach) bleibt vorerst erhalten für die Migration, wird aber von der
Wurzelgruppe (4.3) abgelöst und nach vollständiger Migration entfernt.

### 4.3 Verschachtelte Bedingungen — neu: `MicrotechOrderRuleConditionGroup`

```
rule       FK(MicrotechOrderRule, related_name="condition_groups")
parent     FK("self", null=True, related_name="children")   — Baumstruktur
logic      Choices("all"=UND, "any"=ODER)  default "all"
priority   PositiveInt
is_active  Bool
```

`MicrotechOrderRuleCondition` bekommt zusätzlich:

```
group             FK(MicrotechOrderRuleConditionGroup, null=True, related_name="conditions")
expected_value_2  CharField blank                — zweiter Wert für "between"/Bereiche
```

- Jede Regel hat genau eine Wurzelgruppe (`parent=None`). Bedingungen hängen künftig an
  einer Gruppe statt direkt an der Regel.
- Beliebige Verschachtelungstiefe; jede Gruppe trägt ihr eigenes UND/ODER.
- Das `rule`-FK auf der Condition bleibt für die Migration bestehen (redundant zur
  Gruppe), wird nach der Migration entfernt oder auf `group.rule` abgeleitet.

### 4.4 Operatoren — Erweiterung `EngineOperator`

Vorhanden: `eq, ne, contains, gt, lt, is_empty, is_not_empty`.
Neu:

```
between    — nutzt expected_value + expected_value_2
before     — Datum/Zeit vor Wert (Wert kann Literal, "heute" o. Variable sein)
after      — Datum/Zeit nach Wert
is_true    — boolescher Wert wahr
is_false   — boolescher Wert falsch
```

Operatoren bleiben DB-Katalog (`MicrotechOrderRuleOperator`) — neue Zeilen via
Datenmigration, plus je ein Handler in der Ausführungs-Engine. Erlaubte Operatoren
pro Feld werden weiterhin über `MicrotechOrderRuleDjangoFieldPolicy` gesteuert
(z. B. `between/before/after` nur für Datums-/Zahlfelder).

### 4.5 Aktionswert: fester Wert oder Variable — Template-Ansatz

`MicrotechOrderRuleAction.target_value` wird als **Template-String** interpretiert:

```
"Webshop-Kunde"            → fester Wert (kein {{ }})
"{{ Kunde.Firma }}"        → reine Variable aus Trigger-Kontext
"Auftrag {{ Order.Nr }}"   → Mischung Literal + Variable
```

- Aufgelöst gegen die Trigger-Wurzel (`context_root`) über Feldpfade.
- Feldpfad-Katalog: bestehendes `MicrotechOrderRuleDjangoField`, erweitert um eine
  **Trigger-/Wurzel-Zuordnung**, damit der Variablen-Picker im Builder nur die zum
  aktuellen Trigger erreichbaren Pfade anbietet.
- Ein optionales Flag `value_is_template` (Bool) darf die Auflösung explizit steuern,
  falls Literale mit `{{` gewünscht sind (Kantenfall; Default: automatisch erkennen).

### 4.6 Bedingungs-Vergleichswert als Variable

`expected_value` (und `expected_value_2`) unterstützen dieselbe `{{ }}`-Syntax, damit
Bedingungen Feld-gegen-Feld vergleichen können (z. B. `Order.Lieferdatum` nach
`{{ Order.Bestelldatum }}`) und Sonderwerte wie `heute` erlaubt sind.

### 4.7 Ausdrucks-Erweiterungen (aus dem Hardcode-Inventar)

Das Inventar der Altlogik (Begleitdokument) verlangt fünf gezielte Erweiterungen —
bewusst **keine** freie Ausdruckssprache (YAGNI):

1. **Fallback-Ketten:** `{{ a | b | c }}` → erster nicht-leerer Wert. Deckt alle `a or b`.
2. **Transform-Whitelist:** fest registrierte Funktionen, z. B. `{{ x | anrede_de }}`,
   `| anrede_kontakt` (Herr→Herrn), `| upper`, `| split:n`. Keine freie Code-Ausführung.
3. **Benannte Resolver:** komplexe Mehrfach-Eingabe-Logik bleibt in Python, referenzierbar
   als `{{ @steuerkategorie }}`, `{{ @na1 }}`. Neuer Resolver = Python-Funktion + Katalogeintrag.
4. **Bedingte Aktion:** eine Aktion darf eine eigene Kurzbedingung tragen (z. B. „email nur
   bei Versandadresse"), ohne dafür eine ganze Regel zu brauchen.
5. **Konstanten-Katalog:** benannte Konstanten (EU-Länderliste, italienische B2B-Gruppe),
   von Resolvern und Bedingungen nutzbar.

### 4.8 Global — leere Werte

Engine-weite Einstellung „leere Aktionswerte überschreiben Zielfelder nicht"
(entspricht dem heutigen `_drop_blank`). Default: an.

## 5. Ausführungs-Engine

Zentraler Resolver (Ausbau von `orders/services/order_rule_resolver.py`):

1. **Trigger-Bindung:** Beim Ausführen eines Tasks, der einem `RuleTrigger.task_name`
   entspricht, werden vor bzw. nach der Task-Logik alle aktiven Regeln dieses Triggers
   nach `priority` evaluiert (`execution_phase` entscheidet vor/nach).
2. **Kontext:** Die Trigger-Wurzel-Instanz (z. B. das `Order`-Objekt) bildet den
   Auflösungskontext für Variablen und Bedingungsfelder.
3. **Bedingungsbaum:** Rekursive Auswertung — Gruppe `all` = UND über Kinder,
   `any` = ODER. Blätter sind Conditions (Feld, Operator, Wert(e)).
4. **Aktionen:** Bei Treffer werden Aktionen angewandt. `target_value` wird als Template
   gegen den Kontext aufgelöst. `before`-Regeln verändern den Payload/das Objekt vor
   dem Schreiben; `after`-Regeln stoßen Folgeaktionen an.
5. **Schatten-Modus:** `shadow_mode=True` → Regel wird evaluiert und das Ergebnis
   (Treffer/Nicht-Treffer, geplante Aktionen) protokolliert, aber **nicht** angewandt.
   Ermöglicht Parallelbetrieb neu/alt und Diff-Vergleich vor dem Scharfschalten.

**Erste-passende-Regel vs. alle:** Priorität steuert die Reihenfolge; das bestehende
Verhalten (erste passende aktive Regel gewinnt) bleibt zunächst erhalten und wird bei
Bedarf pro Trigger konfigurierbar gemacht (Ausbaustufe, nicht Teil dieser Spec).

## 6. Grafischer Block-Builder (Admin)

Vertikaler Aufbau (siehe Mockup), reines Vanilla-JS im Unfold-Admin, JSON über
Django-Endpoints wie beim bestehenden `rule-builder-meta/`.

```
[Trigger ▾]   Event-Auswahl aus RuleTrigger-Katalog; zeigt task_name + Kontext-Wurzel
   │          Umschalter execution_phase (vor/nach), Schalter shadow_mode
WENN          Wurzelgruppe mit UND/ODER-Umschalter
   ├─ Bedingung: [Feld ▾] [Operator ▾] [Wert] (+ 2. Wert bei "between")
   ├─ [+ Untergruppe] → eingerückter Block mit eigenem UND/ODER
   └─ [+ Bedingung]
DANN          Aktionsliste
   ├─ setze [Feld ▾] = ( fester Wert | {{ Variable ▾ }} )
   ├─ Zusatz-/Versandposition anlegen
   └─ [+ Aktion]
Klartext-Vorschau (Live), wie heute
```

- **Feld-/Operator-/Variablen-Auswahl** über Autocomplete-Endpoints, gefiltert nach der
  Trigger-Wurzel und `MicrotechOrderRuleDjangoFieldPolicy`.
- **Wert-Umschalter** „fester Wert / Variable" pro Aktions- und Bedingungswert; im
  Variablen-Modus ein Picker über die erreichbaren Feldpfade, der `{{ … }}` einsetzt.
- **Drag-&-Drop** nur für Reihenfolge (Priorität) und Verschachtelung von Gruppen —
  kein freies Positionieren auf einer Canvas.
- Bestehende Live-Klartext-Zusammenfassung wird auf den Bedingungsbaum erweitert.

Speicherung erfolgt weiter über Django-Formsets/Inlines bzw. einen JSON-Submit, der die
Baumstruktur (Gruppen + Conditions + Actions) transaktional persistiert.

## 7. Migration der Altfälle

1. **Webshop-YAML-Defaults** (`customer/webshop.yaml`, `webshop_de.yaml`)
   → Datenmigration erzeugt je eine Regel mit Trigger „Kunde anlegen":
   - `webshop.yaml` → Regel ohne Länder-Bedingung (Fallback) oder Bedingung Land ≠ DE.
   - `webshop_de.yaml` → Regel mit Bedingung Land = DE, höhere Priorität.
   - Felder (`Status`, `VsdArt`, `ZahlBed`, …) werden zu „setze Feld = fester Wert".
   - `Na1`-Logik: als dedizierte Aktion/Resolver abbilden (Firma vs. Anrede) oder als
     Variable `{{ Kunde.Na1 }}`, sobald die Wurzel diese berechnet bereitstellt.
   `webshop_mapping.py` liest danach aus der Engine statt aus der Datei; die YAML-Dateien
   werden nach verifiziertem Parallelbetrieb entfernt.
2. **Microtech-Regeln:** Bestehende flache Conditions werden per Datenmigration in eine
   Wurzelgruppe (mit dem bisherigen `condition_logic`) verschoben; `trigger` auf
   „Bestellung anlegen", `execution_phase="before"`.
3. **Shopware → Bridge:** Hart codierte Feldzuordnungen werden als Regel(n) mit Trigger
   „Kunde/Bestellung importieren" und `{{ Quelle.Feld }}`-Aktionen nachgebildet.
   Eigene Ausbaustufe nach bewährtem Parallelbetrieb der ersten beiden.

Jede Migrationsstufe läuft zuerst im **Schatten-Modus** parallel zum bestehenden Pfad;
erst nach Diff-Abgleich wird scharf geschaltet.

## 7a. Parallelbetrieb & Nicht-Regression (HARTE ANFORDERUNG)

Verbindliche Bedingung, keine Option:

- **Der bestehende Pfad bleibt maßgeblich und unverändert aktiv**, bis das neue Regelwerk
  für einen Bereich ausdrücklich freigegeben wird. Kein bestehendes Verhalten
  (Kunden-Upsert, Order-Upsert, Webshop-Defaults, Steuerkategorie, Na1) darf vor der
  Freigabe ausfallen oder abweichen.
- **Umschaltung pro Bereich über ein Feature-Flag** (z. B. `RuleTrigger.engine_enabled`
  oder projektweite Settings): solange „aus", liefert weiterhin die alte Logik.
- **Schatten-Modus als Standard bei Einführung:** neue Regeln laufen zunächst
  `shadow_mode=True` — sie werden evaluiert und ihr Ergebnis wird gegen das alte Ergebnis
  geloggt (Diff), aber **nicht angewandt**.
- **Diff-Abgleich als Freigabekriterium:** ein Bereich wird erst scharf geschaltet, wenn
  der Schatten-Diff über repräsentative Fälle leer ist (Golden-Test, siehe §8).
- **Rückschaltbar:** Flag zurückstellen stellt sofort das alte Verhalten wieder her; die
  alten Code-Pfade (YAML-Loader, Resolver) werden erst nach dauerhaft verifizierter
  Freigabe entfernt.

## 8. Testing

- **Modell/Engine (pytest):**
  - Bedingungsbaum: UND/ODER, Verschachtelung, alle Operatoren inkl. `between/before/after/is_true/is_false`.
  - Template-Auflösung: fester Wert, reine Variable, gemischt, unbekannter Pfad → definierter Fallback.
  - `execution_phase` vor/nach; `shadow_mode` wendet nichts an, protokolliert aber.
  - Erste-passende-Regel-Reihenfolge nach Priorität.
- **Migration:** Datenmigrationen erzeugen aus YAML/Alt-Regeln äquivalente Regeln;
  Golden-Test vergleicht altes vs. neues Ergebnis für repräsentative Kunden/Bestellungen.
- **Builder (JS):** bestehende `test_admin_rulebuilder.py` / `test_rule_forms.py`
  erweitern um Trigger-Auswahl, Gruppen, Variablen-Picker.
- **Regression:** Der produktive Order-Upsert bleibt über den Schatten-Modus messbar
  unverändert, bis bewusst umgeschaltet wird.

## 9. Nicht in dieser Spec (bewusst ausgeklammert, YAGNI)

- Freier Knoten-Canvas / n8n-Stil.
- Pro-Trigger konfigurierbares „alle Regeln statt erste passende".
- Versionierung/Audit-Historie von Regeln über das bestehende `BaseModel` hinaus.
- Vollständige Shopware-Mapping-Migration (eigene Ausbaustufe nach Pilot).

## 10. Umsetzungsreihenfolge (grob)

1. Datenmodell + Migrationen (Trigger, Gruppen, neue Felder, Operatoren).
2. Ausführungs-Engine (Baum-Eval, Template-Auflösung, phase/shadow).
3. Datenmigration Alt-Microtech-Regeln in Baumstruktur.
4. Block-Builder-UI (Trigger, Gruppen, Variablen-Picker, erweiterte Klartext-Vorschau).
5. Webshop-Defaults-Pilot im Schatten-Modus → verifizieren → scharf schalten → YAML entfernen.
6. (Ausbaustufe) Shopware-Mapping-Migration.
