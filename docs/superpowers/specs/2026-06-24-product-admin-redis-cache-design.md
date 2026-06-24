# Product Admin Redis Cache — Design

**Datum:** 2026-06-24  
**Status:** Genehmigt

## Ziel

DB-Last reduzieren und Ladezeit der Produktliste im Django-Admin spürbar verbessern, indem Redis (bereits für Celery im Einsatz) auch als Django-Cache-Backend genutzt wird.

## Kontext

- Produktkatalog: <1.000 Produkte
- Änderungsfrequenz: gering (hauptsächlich via Microtech-Sync, selten manuelle Edits)
- Redis läuft bereits: DB 0 (Celery Broker), DB 1 (Celery Result Backend)
- Bisher kein `CACHES`-Backend konfiguriert — jeder Admin-Pageload trifft die DB ~5-6×

## Architektur

### Schicht 1 — Cache-Backend

`django-redis` wird als `CACHES["default"]` in `GC_Bridge_4/settings.py` eingetragen (Redis DB 2).

```python
CACHES = {
    "default": {
        "BACKEND": "django_redis.cache.RedisCache",
        "LOCATION": os.getenv("REDIS_CACHE_URL", "redis://localhost:6379/2"),
        "OPTIONS": {
            "CLIENT_CLASS": "django_redis.client.DefaultClient",
        },
    }
}
```

### Schicht 2 — Produkt-Bild-Cache

- Cache-Key pro Produkt: `product:image_url:{pk}` → URL-String (leer wenn kein Bild)
- TTL: 3.600 Sekunden (Fallback gegen verwaiste Keys)
- `ProductAdmin.image_preview()` liest aus Redis, fällt auf DB zurück (lazy warm-up), schreibt dabei in Cache
- `ProductAdmin.get_queryset()` entfernt den `Prefetch` für `product_images` — eine DB-Query weniger pro Pageload
- Signal `post_save`/`post_delete` auf `ProductImage` invalidiert und re-wärmt den Cache-Key für das betroffene Produkt synchron

### Schicht 3 — Filter-Choices-Cache

- Neue Klasse `CachedRelatedDropdownFilter(RelatedDropdownFilter)` in `products/cache.py`
- Cached Queryset-Ergebnisse für die Sidebar-Filter Tax und Category
- Cache-Keys: `filter:tax:all`, `filter:category:all` — TTL: 3.600 Sekunden
- Signal-Invalidierung bei `Tax`/`Category` post_save/post_delete

## Datenfluss

### Admin-Listenseite (nach Warm-up)

```
Browser → ProductAdmin.changelist_view
  → get_queryset()           # 1 DB-Query (kein Prefetch)
  → Pagination Count         # 1 DB-Query (ORM)
  → image_preview(obj)       # Redis Hit → 0 DB-Queries
  → Tax-Filter-Sidebar       # Redis Hit
  → Category-Filter-Sidebar  # Redis Hit
Gesamt: 2 DB-Queries (vorher: ~5-6)
```

### Lazy Warm-up (Cache-Miss)

`image_preview` führt eine direkte DB-Query durch, schreibt das Ergebnis in Redis und gibt die URL zurück. Tax/Category-Filter analog.

## Invalidierungslogik

| Ereignis | Cache-Aktion |
|---|---|
| `ProductImage` post_save | delete + re-wärmen für `product_id` |
| `ProductImage` post_delete | delete für `product_id` |
| `Tax` post_save / post_delete | delete `filter:tax:all` |
| `Category` post_save / post_delete | delete `filter:category:all` |

Re-wärmen bei `ProductImage`-Änderungen ist synchron im Signal (eine DB-Query, kein Celery-Task).

## Fehlerbehandlung

Redis-Ausfall darf den Admin nie blockieren. Alle Cache-Calls werden mit Try/Except abgesichert:

- `cache.get` wirft Exception → DB-Fallback, Admin funktioniert wie ohne Cache
- `cache.delete` in Signal-Receiver wirft Exception → wird geloggt, Signal läuft weiter, kein Save-Abbruch

## Dateien

| Datei | Änderung |
|---|---|
| `GC_Bridge_4/settings.py` | `CACHES`-Block ergänzen |
| `products/cache.py` | Neu: Cache-Keys, Hilfsfunktionen, Signal-Receiver, `CachedRelatedDropdownFilter` |
| `products/admin.py` | `image_preview` und `get_queryset` anpassen, Filter-Klasse nutzen |
| `products/apps.py` | Neue Signal-Receiver in `ready()` registrieren |
| `products/tests.py` | Tests für Warm-up, Invalidierung, Redis-Ausfall-Fallback |

## Testing

Tests in `products/tests.py` mit `override_settings(CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}})`:

1. **Warm-up:** Nach `ProductImage`-Save ist Cache-Key gesetzt und liefert korrekte URL
2. **Invalidierung:** Nach `ProductImage`-Delete ist Key weg; nächster Aufruf trifft DB
3. **Redis-Ausfall-Fallback:** Cache gemockt auf Exception → `image_preview` gibt korrektes Ergebnis zurück, kein 500-Fehler

## Abhängigkeiten

- `django-redis` via `uv pip install django-redis`
- Umgebungsvariable `REDIS_CACHE_URL` in `.env` / Docker Compose ergänzen (optional, Default: `redis://localhost:6379/2`)
