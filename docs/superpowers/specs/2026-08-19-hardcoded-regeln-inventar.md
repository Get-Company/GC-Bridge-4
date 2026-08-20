# Inventar: bestehende hart codierte Regeln & Mappings

**Datum:** 2026-08-19
**Zweck:** Vollständige Auflistung aller heute verteilt implementierten Regeln/Mappings,
um sie ins [zentrale Regelwerk](2026-08-19-zentrales-regelwerk-design.md) zu übernehmen.
**Anforderung:** Der alte Pfad bleibt maßgeblich, bis das neue Regelwerk verifiziert ist
(Parallelbetrieb, siehe Spec §7/§11).

## Logik-Klassen (Legende)

| Kürzel | Bedeutung | Regelwerk-Abbildung |
|---|---|---|
| DIREKT | Feld ← Feld, unverändert | `{{ Quelle.Feld }}` |
| STATIC | fester Wert | fester Wert |
| FALLBACK | `a or b` (erster nicht-leerer) | `{{ a \| b }}` |
| TRANSFORM | Funktion auf Wert | `{{ x \| funktion }}` (Whitelist) |
| RESOLVER | Mehrfach-Eingabe-Logik in Python | `{{ @resolver }}` (benannt) |
| BEDINGT | Feld nur unter Bedingung | Aktion mit Bedingung |
| BRANCHING | Modus-/Fallunterscheidung | mehrere Regeln oder Resolver |
| GLOBAL | Engine-weites Verhalten | Engine-Einstellung |

---

## A. Trigger „Kunde anlegen / aktualisieren"

Quelle: `customer/services/customer_upsert_microtech.py`,
`customer/services/webshop_mapping.py`

### A.1 Kundendaten `_build_customer_input` → GraphQL `customer`

| Microtech-Ziel | Quelle | Klasse |
|---|---|---|
| salutation | `translate_salutation_to_de(title \| name1)` | TRANSFORM `anrede_de` + FALLBACK |
| firstName | `address.first_name` | DIREKT |
| lastName | `address.last_name` | DIREKT |
| name1 | `address.name1 \| customer.name` | FALLBACK |
| name2 | `address.name2` | DIREKT |
| name3 | `address.name3` | DIREKT |
| street | `address.street` | DIREKT |
| zipCode | `address.postal_code` | DIREKT |
| city | `address.city` | DIREKT |
| email | `address.email \| customer.email` | FALLBACK |
| phone | `address.phone` | DIREKT |
| department | `address.department` | DIREKT |
| country | `address.country_code` | DIREKT |
| vatId | `customer.vat_id` | DIREKT |
| taxCategory | `resolve_tax_category(land, ustid, gruppe)` | RESOLVER (A.3) |
| webshopDefaults | `get_microtech_defaults(country)` | STATIC nach Land (A.2) |

### A.2 Webshop-Defaults (`customer/webshop.yaml`, `webshop_de.yaml`) — STATIC

Länder-Weiche: `webshop_de.yaml` bei `country == "DE"`, sonst `webshop.yaml`.

| Feld | webshop.yaml (nicht-DE) | webshop_de.yaml (DE) |
|---|---|---|
| Status | "Webshop-Kunde" | "Webshop-Kunde" |
| SuchBeg | "CL" | *(nicht gesetzt)* |
| VsdArt | 10 | 10 |
| VsdZWeise | 1 | 1 |
| ZahlHBk | 0 | 0 |
| ZahlBed | "14 Tage 2% - 30 Tage rein netto" | dito |
| SktoTg1 | 14 | 14 |
| SktoSz1 | 2,00 | 2,00 |
| NettoTg | 30 | 30 |
| VtrNr | 99 | 99 |
| GspKz | 0 | 0 |
| RabKz | 1 | 1 |
| ArtPrGrp | 0 | 0 |
| TextKz1 | 1 | 1 |
| TextKz2..5 | 0 | 0 |
| HistKz | 1 | 1 |

→ Übernahme: zwei Regeln (Trigger „Kunde anlegen"): eine mit Bedingung `Land = "DE"`
(höhere Priorität), eine als Fallback (nicht-DE, enthält zusätzlich `SuchBeg = "CL"`).
Einziger Unterschied ist `SuchBeg`.

### A.3 Steuerkategorie `resolve_tax_category` → `UStKat` — RESOLVER / BRANCHING

Reihenfolge (Rechnungsland hat Vorrang):
1. Land = `DE` → `1`
2. Land = `CH` **oder** Land ∉ EU → `2`
3. EU **und** Kundengruppe = italienische B2B-Gruppe **und** UStId vorhanden → `3`
4. sonst → `1`

→ Übernahme: benannter Resolver `@steuerkategorie` (Land/EU-Liste/Gruppe/UStId als
Eingabe) **oder** als Regelkette mit Bedingungen. Empfehlung: benannter Resolver,
weil EU-Länderliste und Gruppen-Konstante sonst in jede Bedingung wandern.

### A.4 Anschrift `_build_postal_address_input` → GraphQL `postalAddress`

| Microtech-Ziel | Quelle | Klasse |
|---|---|---|
| isDefaultShipping | `is_shipping` | DIREKT |
| isDefaultBilling | `is_invoice` | DIREKT |
| name1 | `_resolve_na1_for_anschrift(...) \| address.name1` | RESOLVER (A.5) + FALLBACK |
| name2 | `address.name2` | DIREKT |
| name3 | `address.name3` | DIREKT |
| street | `address.street` | DIREKT |
| zipCode | `address.postal_code` | DIREKT |
| city | `address.city` | DIREKT |
| email | `address.email` **nur wenn** `is_shipping` | BEDINGT |
| phone | `address.phone` | DIREKT |
| department | `address.department` | DIREKT |
| country | `address.country_code` | DIREKT |

### A.5 Na1-Auflösung `_resolve_na1_for_anschrift` — BRANCHING

`is_company` = (`name1` und `name2` gesetzt) **und** `name1` ist keine Anrede.
Modi:
- `static` → `static_value \| title \| name1`
- `salutation_only` → `anrede_de(title\|name1) \| title \| name1`
- `firma_or_salutation` → wenn Firma: `name1`; sonst `anrede_de(...) \| title \| name1`
- `auto` (Default) → wenn Firma: `name1`; sonst `anrede_de(...) \| title \| name1`

Der Na1-Modus kommt heute aus der aufgelösten Order-Regel (`ResolvedOrderRule.na1_mode`,
`na1_static_value`) — d. h. teilweise **schon regelgesteuert**.
→ Übernahme: benannter Resolver `@na1(modus, static)` mit den vier Modi.

### A.6 Ansprechpartner `_build_contact_person_input` → GraphQL `contactPerson`

| Microtech-Ziel | Quelle | Klasse |
|---|---|---|
| isDefault | `True` | STATIC |
| salutation | `get_contact_person_salutation` (Herr→"Herrn") | TRANSFORM `anrede_kontakt` |
| firstName | `first_name`, sonst `split(name2\|name1)[0]` | FALLBACK + STRING `split` |
| lastName | `last_name`, sonst `split(name2\|name1)[1]` | FALLBACK + STRING `split` |
| displayName | `"{first} {last}"` | TEMPLATE (Verkettung) |
| department | `address.department` | DIREKT |
| email | `address.email` | DIREKT |
| phone | `address.phone` | DIREKT |

### A.7 Global — GLOBAL

- `_drop_blank`: Felder mit Wert `None`/`""` werden nicht gesendet (überschreiben nicht).
  → Übernahme: Engine-Einstellung „leere Aktionswerte überschreiben nicht".

---

## B. Trigger „Bestellung schreiben" (Vorgang)

Quelle: `orders/services/order_upsert_microtech.py`,
`orders/services/order_rule_resolver.py`, `microtech/models.MicrotechSettings`

**Hinweis:** Bedingungen, Na1-Modus, Zusatz-/Versand-/Zahlungspositionen und Vorgangsart
laufen **bereits** über die DB-Engine (`MicrotechOrderRule` → `ResolvedOrderRule`).
Hier nur noch hart codierte Rest-Mappings/Defaults:

### B.1 Vorgang `_build_graphql...` create-input

| Microtech-Ziel | Quelle | Klasse |
|---|---|---|
| orderNumber | `order.order_number \| order.api_id` | FALLBACK |
| description | `order.description \| "Shopware Bestellung {order_number}"` | FALLBACK + TEMPLATE |
| currency | `"EUR"` | STATIC |
| vorgangArt | `resolved_rule.vorgangsart_id \| default_vorgangsart_id` | RESOLVER + DEFAULT |
| customerNumber | `order.customer.erp_nr` | DIREKT |

### B.2 Positionen `_build_graphql_positions`

| Microtech-Ziel | Quelle | Klasse |
|---|---|---|
| erpNumber | `detail.erp_nr` | DIREKT |
| quantity | `detail.quantity \| 1` | FALLBACK |
| unit | Produkt-Einheiten-Map bzw. `DEFAULT_UNIT` | RESOLVER |
| price | `detail.unit_price` (formatiert) | DIREKT |

### B.3 Versandposition (wenn Regel aktiv)

| Feld | Quelle | Klasse |
|---|---|---|
| erpNumber | Versandartikel aus Regel (V/F) | (Regel) |
| quantity | `1` | STATIC |
| unit | `DEFAULT_UNIT` | STATIC |
| price | `order.shipping_costs` | DIREKT |

### B.4 Vorgang-Defaults `MicrotechSettings` — STATIC/DEFAULT

| Feld | Default | Modellfeld |
|---|---|---|
| Vorgangsart | 111 | `default_vorgangsart_id` |
| Zahlungsart | 22 | `default_zahlungsart_id` |
| Versandart | 10 | `default_versandart_id` |

→ diese leben bereits in der DB (`MicrotechSettings`), sind aber kein „Regelwerk";
Übernahme optional als globale Konstanten/Fallback-Werte.

---

## C. Trigger „Kunde aus Microtech lesen" (Rückrichtung) — optional

Quelle: `customer/services/customer_sync.py`. Microtech → Django (Import).

| Django-Ziel | Microtech-Quelle | Klasse |
|---|---|---|
| customer.name | `Na1` | DIREKT |
| customer.email | `EMail1` | DIREKT |
| customer.erp_id | `AdrId` | DIREKT |
| address.name1/2/3 | `Na1`/`Na2`/`Na3` | DIREKT |
| address.street | `Str` | DIREKT |
| address.postal_code | `PLZ` | DIREKT |
| address.city | `Ort` | DIREKT |
| address.country_code | `Land` | DIREKT |
| address.email | `EMail1 \| contact.email` | FALLBACK |
| address.is_shipping | `ans_nr == LiAnsNr` | BEDINGT/Vergleich |
| address.is_invoice | `ans_nr == ReAnsNr` | BEDINGT/Vergleich |

→ Reine 1:1-Importzuordnung. Kandidat für eine spätere Ausbaustufe, nicht Pflicht für
den ersten Wurf.

---

## D. Nicht als Regelwerk (bewusst ausgeklammert)

- **Order-State-Transitions** (`shopware/services/order.py`): Zustandsautomat
  (process/ship/cancel …) — kein Feld-Mapping, bleibt Code.
- **Identitäts-Persistenz** (`_persist_*_identity`, erp_nr/ans_id-Rückschreiben):
  technische Verknüpfung, kein fachliches Mapping.
- **Kundennummer-Rückschreibung nach Shopware** (`_sync_new_customer_number_to_shopware`):
  Integrations-Seiteneffekt, kein Regelwerk.

---

## E. Abgeleiteter Bedarf an Engine-Erweiterungen

Aus dem Inventar ergeben sich genau die in der Spec vorgesehenen Erweiterungen:

1. **FALLBACK-Ketten** `{{ a | b | c }}` — für alle `a or b` (A.1, A.4, A.6, B.1, B.2, C).
2. **TRANSFORM-Whitelist** — `anrede_de`, `anrede_kontakt` (Herr→Herrn), `split:n`,
   Verkettung/Template (A.1, A.6).
3. **Benannte RESOLVER** `{{ @name }}` — `@steuerkategorie` (A.3), `@na1` (A.5),
   Produkt-Einheit (B.2).
4. **BEDINGTE Aktionen** — Feld nur unter Bedingung (A.4 email-nur-bei-Versand).
5. **GLOBAL** — „leere Werte überschreiben nicht" (`_drop_blank`, A.7).
6. **Konstanten** — EU-Länderliste, italienische B2B-Gruppe (für @steuerkategorie).

Damit ist jede Zeile dieses Inventars im Regelwerk darstellbar.
