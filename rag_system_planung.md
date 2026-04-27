# RAG-System Planung für GC-Bridge-4

> Status: Geplant — noch nicht implementiert  
> Erstellt: 2026-04-23

---

## Was ist RAG?

RAG (Retrieval-Augmented Generation) ist kein klassisches Training, sondern ein **zweistufiges Abfragesystem**:

1. **Indexierung** — Projektdaten werden in Textstücke (Chunks) zerlegt, mit einem Embedding-Modell in Zahlenvektoren umgewandelt und in der Datenbank gespeichert.
2. **Abfrage** — Bei einer Nutzerfrage wird die Frage ebenfalls als Vektor codiert, die ähnlichsten Chunks per Datenbanksuche gefunden, und dann einem LLM (z.B. Claude/GPT) als Kontext übergeben, das eine präzise Antwort formuliert.

**Kein Modell-Training nötig.** Die KI lernt nichts dauerhaft — sie bekommt die relevanten Informationen bei jeder Abfrage frisch als Kontext. Der "Lernprozess" ist das regelmäßige Neu-Indexieren der Datenbank.

---

## Anwendungsgebiete

| Frage | Datenquelle |
|-------|-------------|
| „Welche roten Produkte haben wir?" | Produkteigenschaften (PropertyValue) |
| „Was kostet Artikel 091300 bei Mappei vs. intern?" | Mappei-Preisvergleich |
| „Welche Produkte wurden im März 2025 am meisten bestellt?" | Bestellauswertung |
| „Zeig alle Produkte mit Staffelpreis unter 5 EUR" | Preismodell |
| „Wie lege ich einen neuen Shopware-Kanal an?" | Dokumentation |
| „Welche Produkte sind in der Kategorie Archivierung?" | Kategoriepfade (MPTT) |
| „Wie hat sich der Preis von Artikel X entwickelt?" | PriceHistory |

---

## Architektur

```
┌──────────────────────────────────────────────────────────────────┐
│  Django Admin (Unfold)                                           │
│  └─ RAGQueryAdminView: Freitext-Eingabe → Antwort + Quellen      │
└──────────────────────┬───────────────────────────────────────────┘
                       │ Anfrage
                       ▼
          ┌────────────────────────┐
          │   RAGQueryService      │
          │  1. Frage embedden     │
          │  2. Vektorsuche        │──► RAGChunk-Tabelle (pgvector)
          │  3. Kontext aufbauen   │
          │  4. LLM aufrufen       │◄── AIProviderConfig (existing)
          │  5. Antwort + Quellen  │
          └────────────────────────┘
                       ▲
          index_rag (Management-Command, nightly / manuell)
                       │
    ┌──────────────────┼──────────────────────────┐
    │                  │                          │
ProductIndexer  MappeiComparisonIndexer  OrderSummaryIndexer
    │                  │                          │
Produkt-DB       Mappei-Snapshots          Bestellpositionen
```

---

## Datenquellen und Chunk-Strategie

### 1. Produkte (`ProductIndexer`)

Je aktivem Produkt werden **5 Chunks** erstellt:

| Chunk | Inhalt |
|-------|--------|
| Stammdaten | `Produkt 091300: Ordnermappe A4. SKU: XY. Einheit: Stk. Gewicht: 250g.` |
| Beschreibung | Volltext aus `description` + `description_short` |
| Kategorien | `Kategorien: Büro > Archivierung > Mappen` (vollständiger MPTT-Pfad) |
| Eigenschaften/Farben | `Eigenschaften: Farbe: Rot, Grün. Größe: A4.` ← ermöglicht Farb-Queries |
| Preise | `Preise (Standard): 4,45 EUR. Staffel ab 5 Stk: 3,90 EUR.` |

### 2. Mappei-Vergleich (`MappeiComparisonIndexer`)

Je gemapptem Produkt 1 Chunk:
```
Mappei-Vergleich Ordnermappe A4 (Art. 091300):
Interner Preis: 4,45 EUR
Mappei-Preis: 3,80 EUR (Staffel ab 10: 3,40 EUR)
Differenz: -14,6% (Mappei günstiger)
Zuletzt geprüft: 2025-03-15
```

### 3. Bestellauswertung (`OrderSummaryIndexer`)

1 Chunk pro Monat (Top-20 Produkte nach Umsatz):
```
Bestellauswertung 2025-03: 
Top-Produkte nach Umsatz:
1. Ordnermappe A4 (091300): 148 Stk, 658,60 EUR
2. Hängeregister DIN A4 (204450): 96 Stk, 432,00 EUR
...
```

Zusätzlich 1 Chunk je Produkt mit Gesamtbestellhistorie.

### 4. Dokumentation (`DocumentationIndexer`)

Markdown-/RST-Dateien aus `docs/` werden nach Überschriften in Chunks à ~600 Wörter aufgeteilt.

---

## Technische Umsetzung

### Neue Abhängigkeiten

```
# requirements.txt
pgvector>=0.3.0          # pgvector Python-Client für Django
```

```yaml
# docker-compose.yml
# Änderung: postgres:16-alpine → pgvector/pgvector:pg16
# (pgvector-Extension ist in postgres:16-alpine nicht enthalten)
services:
  db:
    image: pgvector/pgvector:pg16
```

### Neues Django-App `rag/`

```
rag/
├── __init__.py
├── apps.py
├── models.py              ← RAGEmbeddingProvider, RAGChunk, RAGQueryLog
├── admin.py               ← Query-Interface + Read-Only-Listen
├── services/
│   ├── embedding.py       ← Embedding-Calls via AIProviderConfig
│   ├── indexers.py        ← ProductIndexer, MappeiIndexer, OrderIndexer, DocIndexer
│   └── query.py           ← RAGQueryService (Suche + LLM-Aufruf)
└── management/commands/
    ├── index_rag.py        ← Indexierungs-Command
    └── rag_query.py        ← CLI-Abfrage zum Testen
```

In `settings.py` hinzufügen: `'rag.apps.RagConfig'`

---

### Modelle

#### `RAGEmbeddingProvider`
Referenziert einen bestehenden `AIProviderConfig` (base_url + api_key) und gibt an welches Embedding-Modell genutzt wird (z.B. `text-embedding-3-small` von OpenAI, 1536 Dimensionen).

#### `RAGChunk` (Kerntabelle)
| Feld | Beschreibung |
|------|-------------|
| `source_type` | `product`, `order_summary`, `mappei_comparison`, `documentation` |
| `source_id` | ERP-Nummer, Monat (`2025-03`), Mappei-Artikelnummer |
| `source_label` | Lesbarer Name für Quellenangabe in der Antwort |
| `content` | Der eingebettete Textinhalt |
| `content_hash` | SHA-256 des Inhalts — bei unverändertem Hash wird Chunk übersprungen |
| `embedding` | `VectorField(1536)` — pgvector |

HNSW-Index auf `embedding` mit Cosine-Similarity für schnelle Abfragen.

#### `RAGQueryLog`
Protokolliert alle Abfragen: Frage, Antwort, genutzte Chunks, Latenz, Nutzer.

---

### Settings (`settings.py`)

```python
RAG_SYSTEM_PROMPT = os.getenv("RAG_SYSTEM_PROMPT",
    "Du bist ein interner Assistent für das GC-Bridge ERP-Shopware-System. "
    "Beantworte Fragen präzise auf Basis des bereitgestellten Kontexts. "
    "Wenn der Kontext keine Antwort enthält, sage das klar. Antworte auf Deutsch.")
RAG_DEFAULT_TOP_K = int(os.getenv("RAG_DEFAULT_TOP_K", "5"))
RAG_SIMILARITY_THRESHOLD = float(os.getenv("RAG_SIMILARITY_THRESHOLD", "0.40"))
```

---

## Einrichtung (Schritt für Schritt)

### 1. Docker-Image wechseln
```yaml
# docker-compose.yml
image: pgvector/pgvector:pg16
```
```bash
docker-compose down && docker-compose up -d
```
> **Achtung:** Nur bei Neuinstallation oder wenn die DB sowieso neu aufgesetzt wird. Bestehende Daten bleiben erhalten, wenn dasselbe Volume genutzt wird — aber Image-Wechsel erfordert Test.

### 2. Abhängigkeit installieren
```bash
uv pip install pgvector>=0.3.0
```

### 3. Migration anwenden
```bash
python manage.py migrate rag
```
Die Migration aktiviert automatisch die pgvector-Extension: `CREATE EXTENSION IF NOT EXISTS vector;`

### 4. Embedding Provider anlegen
Im Django-Admin unter **RAG → Embedding Providers** einen neuen Eintrag anlegen:
- Name: `OpenAI Embeddings`
- AI Provider: *(einen bestehenden AIProviderConfig mit OpenAI-Key wählen)*
- Embedding Model: `text-embedding-3-small`
- Dimensionen: `1536`

### 5. Ersten Index bauen
```bash
# Testlauf (kein Schreiben)
python manage.py index_rag --source product --dry-run

# Echte Indexierung
python manage.py index_rag --source all
```

### 6. Abfrage testen
```bash
python manage.py rag_query "Welche roten Produkte haben wir?" --show-sources
python manage.py rag_query "Was kostet Artikel 091300 bei Mappei?"
```

### 7. Admin-Interface
Unter `/admin/rag/query/` steht eine Freitext-Eingabe zur Verfügung.

---

## Regelmäßige Re-Indexierung

Da sich Produktdaten, Preise und Bestellungen laufend ändern, sollte `index_rag` regelmäßig laufen. Möglichkeiten:

- **Nightly via Scheduled Task** (Windows Server):
  ```batch
  schtasks /Create /TN "GC-Bridge-RAG-Index" /SC DAILY /ST 02:00 /TR "python manage.py index_rag --source all"
  ```
- **Nach ERP-Sync**: Management-Command am Ende von `scheduled_product_sync.py` aufrufen
- **Manuell**: Nach Bulk-Importen wie `preisimport_preiserhoehung_2025.csv`

Der Hash-Mechanismus sorgt dafür, dass unveränderte Chunks übersprungen werden — ein täglicher Lauf ist effizient.

---

## Kritische Referenz-Dateien (für Implementierung)

| Datei | Relevanz |
|-------|----------|
| `ai/models.py` | `AIProviderConfig` (base_url, api_key, model_name) — für Embedding-Calls wiederverwenden |
| `ai/admin.py` | Pattern für `RAGQueryAdminView` (UnfoldModelAdminViewMixin + `get_urls()`) |
| `products/models.py` | `Product`, `PropertyValue`, `Price`, `Category` — Quell-Modelle für ProductIndexer |
| `mappei/models.py` | `MappeiProductMapping`, `MappeiPriceSnapshot` — für MappeiComparisonIndexer |
| `orders/models.py` | `Order`, `OrderDetail` — für OrderSummaryIndexer |
| `core/models/base.py` | `BaseModel` — alle neuen Modelle erben davon |
| `docker-compose.yml` | Image-Wechsel auf `pgvector/pgvector:pg16` |

---

## Embedding-Modell Optionen

| Option | Modell | Kosten | Qualität Deutsch |
|--------|--------|--------|-----------------|
| **OpenAI (empfohlen)** | `text-embedding-3-small` | ~$0.02/1M Tokens | Sehr gut |
| OpenAI (besser) | `text-embedding-3-large` | ~$0.13/1M Tokens | Exzellent |
| Lokal (kostenlos) | `paraphrase-multilingual-MiniLM-L12-v2` | $0 | Gut |
| Lokal (besser) | `intfloat/multilingual-e5-large` | $0 | Sehr gut |

Für Phase 1 empfiehlt sich `text-embedding-3-small` da `AIProviderConfig` bereits OpenAI-Keys verwaltet. Lokale Modelle können später via `sentence-transformers` nachgerüstet werden.
