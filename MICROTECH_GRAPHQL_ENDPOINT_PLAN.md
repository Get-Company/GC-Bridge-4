# Microtech GraphQL Endpoint Plan

Ziel: Die direkte COM-Nutzung in GC-Bridge wird entfernt. Alle Microtech-Zugriffe laufen ueber den externen GraphQL-Wrapper unter `MICROTECH_GRAPHQL_URL`.

Die Wrapper-Regel bleibt: GC-Bridge spricht nur HTTP/GraphQL. COM bleibt ausschliesslich im separaten GraphQL-Wrapper-Worker.

## Arbeitsmodus

- Endpunkte werden stueckweise im GraphQL-Wrapper ergaenzt.
- GC-Bridge migriert erst dann eine COM-Call-Site, wenn der benoetigte Wrapper-Endpoint fachlich vollstaendig ist.
- Jede neue Mutation folgt dem vorhandenen Async-Muster: Mutation gibt `jobId` zurueck, GC-Bridge pollt den passenden `*Job`.
- Filter und Ranges werden zuerst als generische Dataset-Operationen im Wrapper eingefuehrt, danach werden fachliche Convenience-Endpunkte darauf aufgebaut.

## Tasklist

- [x] 1. Endpoint-Inventar und Contract fuer Filter/Range festlegen.
- [x] 2. Generische Dataset-Read-Operation im GraphQL-Wrapper planen: Dataset, Index, Range, Filter, Felder, Limit.
- [x] 3. Typed Job-Result fuer Dataset-Reads planen: Records, Field-Metadaten, Cursor/EOF/Count, Fehler.
- [ ] 4. Produkt-Read-Endpunkte aus Dataset-Read ableiten: Einzelartikel, Artikelliste, aktive Webshop-Artikel.
- [ ] 5. Lagerdaten-Endpunkt ergaenzen: Bestand und Lagerort pro Artikel.
- [ ] 6. Produkt-Sync in GC-Bridge auf GraphQL-Reads umstellen.
- [ ] 7. Customer-Read/Upsert-Endpunkte gegen bestehende Customer-Sync-Felder abgleichen.
- [ ] 8. Address- und Contact-Upsert-Endpunkte gegen `Anschriften` und `Ansprechpartner` abgleichen.
- [ ] 9. Vorgang-Suche nach `AuftrNr`/Bestellnummer ergaenzen.
- [ ] 10. Vorgang-Upsert so erweitern, dass Positionsersetzung, Versandposition, Zahlungsposition und Regel-Aktionen abbildbar sind.
- [ ] 11. Dataset-Feldkatalog/Metadaten-Endpunkt ergaenzen, damit Rulebuilder-Dataset-Felder ohne lokale COM-Inspektion aktualisiert werden koennen.
- [x] 12. GC-Bridge: `microtech_connection()`, lokalen Queue-Worker und COM-Service entfernen, sobald alle Call-Sites migriert sind.
- [x] 13. Betriebsdoku aktualisieren: keine lokale COM-Queue mehr, GraphQL-URL und Polling/Timeouts dokumentieren.

## Punkt 1: Endpoint-Inventar und Contract fuer Filter/Range

Status: abgeschlossen.

### Bereits in `README_GRAPHQL.md` vorhanden

- `health`
- `ping`
- `microtechVersion` mit Polling ueber `microtechJob`
- `requestProduct` und `updateProduct` mit Polling ueber `productJob`
- `requestCustomer`, `createCustomer`, `updateCustomer`, `deleteCustomer` mit Polling ueber `customerJob`
- `createPostalAddress`, `updatePostalAddress`, `deletePostalAddress`
- `createContactPerson`, `updateContactPerson`, `deleteContactPerson`
- `requestVorgang`, `createVorgang`, `updateVorgang` mit Polling ueber `vorgangJob`

### In GC-Bridge aktuell noch durch COM/Dataset-API benoetigt

Produkt-Sync:

- Dataset `Artikel`
- Range ueber Artikelnummern, aktuell z. B. `Nr` von `000000` bis `99999999ZZ`
- Filter `WShopKz = 1` fuer aktive Webshop-Artikel
- Einzelzugriff per `FindKey`
- Felder: `ArtNr`, `KuBez5`, `Bez5`, `Bez2`, `WShopKz`, `Sel6`, `Einh`, `Sel10`, `Sel11`, `Sel19`, `Vk0.Preis`, `Vk0.Rab0.Mge`, `Vk0.Rab0.Pr`, `Vk0.SPr`, `Vk0.SVonDat`, `Vk0.SBisDat`, `StSchl`, `StSchlSz`, `Bez3`, `Bild` bis `Bild5`
- Bild-Link-Auswertung: im Wrapper sollte idealerweise schon der Dateiname normalisiert geliefert werden

Lager:

- Bestand pro Artikel
- Lagerort pro Artikel
- benoetigtes Dataset/SpecialObject muss im Wrapper bestaetigt werden

Customer-Sync:

- Dataset `Adressen`
- Einzelzugriff per AdrNr
- Felder: `AdrNr`, `AdrId`, `Na1`, `EMail1`, `ReAnsNr`, `LiAnsNr`
- Dataset `Anschriften` per Range `[AdrNr, 0]` bis `[AdrNr, 999]`
- Felder: `ID`, `AnsNr`, `Na1`, `Na2`, `Na3`, `Str`, `PLZ`, `Ort`, `Land`, `EMail1`
- Dataset `Ansprechpartner` per Range `[AdrNr, AnsNr, 0]` bis `[AdrNr, AnsNr, 20]`
- Felder: `ID`, `AspNr`, `Anr`, `VNa`, `NNa`, `EMail1`, `Tel1`, `Abt`

Customer-Upsert:

- Adressen anlegen oder editieren
- neue AdrNr ueber Microtech-Nummernvergabe (`SetupNr`)
- Anschriften und Ansprechpartner anlegen/editieren
- Default-Liefer-/Rechnungsanschrift setzen
- Feldmapping muss im Wrapper exakt gegen die bestehende GC-Bridge-Logik validiert werden

Vorgang/Order-Upsert:

- Vorgang per `BelegNr` finden
- Vorgang per `AuftrNr` suchen, optional gegen Kunden-ERP-Nr absichern
- Vorgang anlegen/editieren
- alle Positionen ersetzen
- Positionen mit Menge, Einheit, Artikelnummer, Preis und Positionsbezeichnung schreiben
- Header-Felder setzen: `AuftrNr`, `Bez`, `ZahlArt`, `VsdArt`, optional `ZahlBed`
- Regel-Aktionen aus GC-Bridge koennen dynamisch Dataset-Felder setzen und Zusatzpositionen erzeugen

Dataset-Feldkatalog:

- Dataset-Liste
- Feldliste je Dataset
- Feldname, Label, Typ, schreibbar/lesbar, ggf. Sortierung
- benoetigt fuer den Rulebuilder, damit keine lokale COM-Inspektion mehr noetig ist

### Vorschlag fuer generischen Dataset-Read-Contract

Mutation:

```graphql
mutation {
  requestDatasetRecords(input: {
    dataset: "Artikel"
    indexField: "Nr"
    range: {
      from: ["000000"]
      to: ["99999999ZZ"]
    }
    filters: [
      { field: "WShopKz", op: EQ, value: "1" }
    ]
    fields: ["ArtNr", "KuBez5", "WShopKz"]
    limit: 100
  }) {
    accepted
    jobId
    status
    message
    retryAfterSeconds
  }
}
```

Polling:

```graphql
query {
  datasetJob(jobId: "<uuid>") {
    jobId
    status
    message
    errorMessage
    dataset
    recordCount
    records
  }
}
```

`records` kann fuer den ersten Schritt JSON bleiben. Typed Product/Customer/Vorgang-Endpunkte koennen spaeter stabilere Felder anbieten.

### Filter/Range-Regeln fuer den ersten Wrapper-Schnitt

- Range-Werte immer als Liste serialisieren, auch bei einfachem Key: `["000000"]`.
- Filter-Operatoren klein halten: `EQ`, `NE`, `LT`, `LTE`, `GT`, `GTE`, `CONTAINS`, `STARTS_WITH`.
- Keine freien Filter-Ausdruecke von GC-Bridge an COM durchreichen.
- `fields` ist Pflicht, damit der Wrapper keine kompletten Datasets exportiert.
- `limit` ist Pflicht und hat serverseitig einen Maximalwert.
- Ergebniswerte werden als JSON-safe Scalars serialisiert: String, Int, Float, Boolean, ISO-Date/Datetime oder null.
- COM-Fehler werden im Job als `FAILED` plus `errorMessage` geliefert.

### Offene Entscheidungen fuer Punkt 1

- Soll `requestDatasetRecords` langfristig oeffentlich bleiben oder nur als interne Migrationshilfe dienen?
- Wie gross darf `limit` fuer Produkt-Vollsync sein?
- Brauchen wir Pagination/Cursor sofort oder reicht fuer den Start `limit` plus wiederholte Range-Schnitte?
- Soll der Wrapper FieldType/Schema-Informationen zusammen mit jedem Dataset-Read liefern oder nur ueber einen separaten Metadaten-Endpunkt?

## Punkt 2: Generische Dataset-Read-Operation

Status: abgeschlossen.

### Entscheidung fuer den ersten Schnitt

`requestDatasetRecords` wird als interne Wrapper-Operation eingefuehrt. Sie ist kein finaler Fach-Endpoint fuer GC-Bridge-Features, sondern die technische Grundlage fuer:

- Produktlisten und Produkt-Vollsync
- Lagerabfragen
- Kunden-/Anschriften-/Ansprechpartner-Reads
- Vorgang-Suche nach `AuftrNr`
- Validierung von Filter- und Range-Verhalten vor den typed Endpoints

Der Endpoint bleibt serverseitig stark eingeschraenkt:

- nur erlaubte Datasets
- nur erlaubte Felder
- nur erlaubte Filteroperatoren
- Pflicht-`limit`
- serverseitiger Maximalwert
- kein freier COM-Filterstring aus GC-Bridge

### Erlaubte Datasets fuer den Start

Diese Datasets decken die aktuell bekannten GC-Bridge-Reads ab:

| Dataset | Standard-Index | Zweck |
| --- | --- | --- |
| `Artikel` | `Nr` | Produkt-Sync, Einzelprodukt |
| `Lager` | `ArtNrLagNr` | Bestand und Lagerort pro Artikel |
| `Adressen` | `Nr` | Kundenkopf |
| `Anschriften` | noch im Wrapper bestaetigen | Kundenanschriften per zusammengesetztem Range |
| `Ansprechpartner` | noch im Wrapper bestaetigen | Kontakte per zusammengesetztem Range |
| `Vorgang` | `BelegNr` | Vorgang per Belegnummer, spaeter Suche per `AuftrNr` |

`Anschriften` und `Ansprechpartner` muessen im Wrapper ueber Dataset-Metadaten bestaetigt werden, weil GC-Bridge aktuell nur die Range-Werte kennt, nicht den Indexnamen.

### GraphQL Input-Contract

Vorschlag:

```graphql
input DatasetRangeInput {
  fromValues: [JSON!]!
  toValues: [JSON!]!
}

enum DatasetFilterOperator {
  EQ
  NE
  LT
  LTE
  GT
  GTE
  CONTAINS
  STARTS_WITH
}

input DatasetFilterInput {
  field: String!
  op: DatasetFilterOperator!
  value: JSON!
}

input DatasetReadInput {
  dataset: String!
  indexField: String
  findKey: [JSON!]
  range: DatasetRangeInput
  after: [JSON!]
  filters: [DatasetFilterInput!]
  fields: [String!]!
  limit: Int!
  includeFieldMeta: Boolean = false
}
```

Regeln:

- Entweder `findKey` oder `range` ist gesetzt, nicht beides.
- Ohne `findKey` und ohne `range` wird der Request abgelehnt.
- `after` ist nur mit `range` erlaubt und dient als Cursor fuer Pagination.
- `fields` ist Pflicht und darf nur erlaubte Feldnamen enthalten.
- `limit` ist Pflicht. Startwert fuer Tests: `100`; serverseitiges Maximum fuer den ersten Schnitt: `500`.
- `indexField` ist optional, wenn der Wrapper fuer das Dataset einen Default kennt.

### Mutation

```graphql
mutation {
  requestDatasetRecords(input: {
    dataset: "Artikel"
    indexField: "Nr"
    range: {
      fromValues: ["000000"]
      toValues: ["99999999ZZ"]
    }
    filters: [
      { field: "WShopKz", op: EQ, value: 1 }
    ]
    fields: ["Nr", "ArtNr", "KuBez5", "WShopKz"]
    limit: 100
  }) {
    accepted
    jobId
    status
    message
    retryAfterSeconds
  }
}
```

### Polling-Query

```graphql
query {
  datasetJob(jobId: "<uuid>") {
    jobId
    status
    message
    errorMessage
    dataset
    indexField
    recordCount
    returnedCount
    hasMore
    nextCursor
    records
    fieldMeta
  }
}
```

`records` bleibt fuer den ersten Schnitt JSON. Ein Record soll so aussehen:

```json
{
  "_key": ["000123"],
  "Nr": "000123",
  "ArtNr": "A-123",
  "KuBez5": "Artikelname",
  "WShopKz": true
}
```

`nextCursor` ist die `_key` des letzten gelieferten Records. Fuer die naechste Page sendet GC-Bridge denselben Range plus `after: nextCursor`.

### Pagination-Regel

Der Wrapper iteriert nach `SetRange` in stabiler Index-Reihenfolge.

- Wenn `after` gesetzt ist, werden Records bis inklusive `after` uebersprungen.
- Danach werden maximal `limit` Records gelesen.
- Wenn nach `limit` noch ein weiterer Record existiert, ist `hasMore = true`.
- `nextCursor` wird nur gesetzt, wenn mindestens ein Record geliefert wurde.

Damit kann GC-Bridge Produkt-Vollsyncs ohne riesige Job-Payloads laufen lassen.

### COM-Abbildung im Wrapper

FindKey:

```text
dataset.FindKey(indexField, findKey[0] oder findKey)
```

Range:

```text
dataset.SetRange(indexField, fromValues[0] oder fromValues, toValues[0] oder toValues)
dataset.ApplyRange()
dataset.First()
```

Filter:

- Der Wrapper baut den COM-Filterstring selbst aus validierten `DatasetFilterInput`-Objekten.
- Stringwerte werden escaped.
- Nicht unterstuetzte Operatoren oder Felder fuehren zu `FAILED`.

Feldlesen:

- Feldwerte werden mit einer zentralen Serializer-Funktion JSON-sicher gemacht.
- Datumswerte werden ISO-8601 Strings.
- Nicht lesbare Felder erzeugen keinen Teil-Erfolg mit falschem Inhalt, sondern Job-Fehler, solange das Feld explizit angefordert wurde.

### GC-Bridge Beispielaufrufe

Einzelartikel:

```graphql
mutation {
  requestDatasetRecords(input: {
    dataset: "Artikel"
    indexField: "Nr"
    findKey: ["10005"]
    fields: ["ArtNr", "KuBez5", "Bez5", "WShopKz"]
    limit: 1
  }) { accepted jobId status message retryAfterSeconds }
}
```

Aktive Webshop-Artikel, erste Seite:

```graphql
mutation {
  requestDatasetRecords(input: {
    dataset: "Artikel"
    indexField: "Nr"
    range: { fromValues: ["000000"], toValues: ["99999999ZZ"] }
    filters: [{ field: "WShopKz", op: EQ, value: 1 }]
    fields: ["Nr", "ArtNr", "KuBez5", "Vk0.Preis", "StSchl", "Bild"]
    limit: 500
  }) { accepted jobId status message retryAfterSeconds }
}
```

Lager zu Artikel und Lager 1:

```graphql
mutation {
  requestDatasetRecords(input: {
    dataset: "Lager"
    indexField: "ArtNrLagNr"
    findKey: ["10005", 1]
    fields: ["ArtNr", "LagNr", "Mge", "Pos"]
    limit: 1
  }) { accepted jobId status message retryAfterSeconds }
}
```

Anschriften eines Kunden:

```graphql
mutation {
  requestDatasetRecords(input: {
    dataset: "Anschriften"
    range: { fromValues: ["1234", 0], toValues: ["1234", 999] }
    fields: ["ID", "AnsNr", "Na1", "Na2", "Na3", "Str", "PLZ", "Ort", "Land", "EMail1"]
    limit: 100
  }) { accepted jobId status message retryAfterSeconds }
}
```

### Offene Entscheidungen fuer Punkt 2

- Exakter Indexname fuer `Anschriften` und `Ansprechpartner`.
- Ob `JSON` im Wrapper als Strawberry `JSON` Scalar genutzt wird oder ob Werte als Strings transportiert und serverseitig typisiert werden.
- Ob `fieldMeta` direkt in `datasetJob` enthalten sein soll oder nur ueber Punkt 11 separat kommt.
- Ob `requestDatasetRecords` per Auth/Token nur intern fuer GC-Bridge freigegeben wird.

## Punkt 3: Typed Job-Result fuer Dataset-Reads

Status: abgeschlossen.

Ziel: GC-Bridge soll Dataset-Read-Jobs stabil pollen koennen, ohne Wrapper-interne Jobdaten oder COM-Details kennen zu muessen.

### Result-Type

Vorschlag fuer Strawberry:

```python
@strawberry.type
class DatasetFieldMetaType:
    field_name: str
    label: str | None
    field_type: str | None
    is_calc_field: bool | None
    can_access: bool | None


@strawberry.type
class DatasetJobType:
    job_id: strawberry.ID
    status: str
    message: str
    error_message: str | None
    dataset: str | None
    index_field: str | None
    record_count: int | None
    returned_count: int
    has_more: bool
    next_cursor: strawberry.scalars.JSON | None
    records: strawberry.scalars.JSON
    field_meta: list[DatasetFieldMetaType]
```

GraphQL-Query:

```graphql
query {
  datasetJob(jobId: "<uuid>") {
    jobId
    status
    message
    errorMessage
    dataset
    indexField
    recordCount
    returnedCount
    hasMore
    nextCursor
    records
    fieldMeta {
      fieldName
      label
      fieldType
      isCalcField
      canAccess
    }
  }
}
```

### Status-Semantik

Der Wrapper bleibt bei den vorhandenen Statuswerten:

- `QUEUED`
- `RUNNING`
- `DONE`
- `FAILED`

GC-Bridge behandelt nur `DONE` als Erfolg. `FAILED` ist terminal und muss `errorMessage` enthalten. Unbekannte Statuswerte gelten in GC-Bridge als nicht-terminal, bis der lokale Polling-Timeout greift.

### Records-Format

`records` ist eine JSON-Liste aus Objekten:

```json
[
  {
    "_key": ["000123"],
    "_row": 1,
    "ArtNr": "A-123",
    "KuBez5": "Artikelname",
    "WShopKz": true
  }
]
```

Pflichtfelder im Wrapper-Record:

- `_key`: Cursor-faehiger Key des Records als Liste. Bei zusammengesetzten Indexen enthaelt die Liste mehrere Werte.
- `_row`: 1-basierter Zaehler innerhalb des aktuellen Job-Results.

Fachfelder:

- Nur explizit angeforderte `fields` werden geliefert.
- Feldnamen bleiben exakt Microtech-Feldnamen, z. B. `Vk0.Preis`.
- Nicht vorhandene Feldwerte sind `null`.

### Value-Serialisierung

Der Wrapper serialisiert COM-Feldwerte nach JSON:

| COM/Python-Wert | JSON-Wert |
| --- | --- |
| Leerwert | `null` |
| String/WideString/Blob/Info | String |
| Integer/Byte/AutoInc | Integer |
| Boolean | Boolean |
| Float/Double/Currency | String, wenn Dezimalpraezision relevant ist; sonst Number |
| Date | ISO-Date `YYYY-MM-DD` |
| DateTime | ISO-DateTime |
| unbekannt | String-Repr |

Fuer Geld-, Preis- und Mengenwerte ist String zu bevorzugen, damit GC-Bridge `Decimal` daraus baut und keine Float-Rundungsfehler uebernimmt.

### Field-Metadaten

`fieldMeta` wird nur gefuellt, wenn `includeFieldMeta: true` gesetzt ist. Fuer normale Sync-Laeufe bleibt es leer, damit Payloads klein bleiben.

Minimaldaten:

- `fieldName`
- `label`
- `fieldType`
- `isCalcField`
- `canAccess`

Diese Daten duerfen aus `DataSetInfos` kommen. Wenn ein Feldwert gelesen werden kann, aber keine Metadaten verfuegbar sind, darf `fieldMeta` leer bleiben; der Job soll deshalb nicht fehlschlagen.

### Count-Semantik

- `returnedCount`: Anzahl gelieferter Records in dieser Page.
- `recordCount`: Gesamtzahl im aktuell gesetzten Range, falls Microtech sie billig und verlaesslich liefert. Sonst `null`.
- `hasMore`: `true`, wenn nach der aktuellen Page mindestens ein weiterer Record existiert.
- `nextCursor`: `_key` des letzten gelieferten Records oder `null`.

GC-Bridge darf sich fuer Pagination nicht auf `recordCount` verlassen. Entscheidend sind `hasMore` und `nextCursor`.

### Fehlerformat

Bei `FAILED`:

```json
{
  "status": "FAILED",
  "message": "Dataset read failed",
  "errorMessage": "Unknown field 'Foo' for dataset 'Artikel'",
  "records": [],
  "returnedCount": 0,
  "hasMore": false,
  "nextCursor": null
}
```

Fehler, die terminal sein muessen:

- unbekanntes Dataset
- nicht erlaubtes Dataset
- unbekanntes oder nicht erlaubtes Feld
- nicht erlaubter Filteroperator
- fehlendes `findKey`/`range`
- `findKey` und `range` gleichzeitig gesetzt
- `limit` fehlt oder liegt ueber Maximum
- COM-Fehler beim Erstellen des Datasets
- COM-Fehler beim Lesen eines explizit angeforderten Felds

### Polling-Verhalten in GC-Bridge

GC-Bridge-Client:

- startet nach `retryAfterSeconds`
- pollt standardmaessig alle `retryAfterSeconds`, mindestens aber alle `2s`
- Timeout fuer Einzelreads: `60s`
- Timeout fuer Page-Reads im Sync: `180s`
- bei `FAILED`: `GraphQLMicrotechError` mit `errorMessage`
- bei Timeout: `GraphQLMicrotechTimeout`

Das Polling gehoert in einen zentralen Client-Service, nicht in Admin-Actions oder Management-Commands.

### Akzeptanzkriterien fuer den Wrapper

- Ein `Artikel`-`findKey` liefert genau einen Record oder leere `records`.
- Ein `Artikel`-Range mit `limit: 2` liefert `hasMore = true`, wenn mehr als zwei Records im Range liegen.
- Ein Folgeaufruf mit `after: nextCursor` liefert keine Dublette des Cursor-Records.
- Ein `Lager`-`findKey` mit zusammengesetztem Key `["ARTNR", 1]` funktioniert.
- Ein unbekanntes Feld erzeugt `FAILED`, nicht stillschweigend `null`.
- `records` ist immer eine Liste, auch bei Einzelrecords.
