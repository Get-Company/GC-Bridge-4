# Product Admin Redis Cache — Implementierungsplan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Redis als Django-Cache-Backend einbinden und die Produktliste im Admin durch gecachte Bild-URLs und Filter-Choices entlasten (Ziel: von ~5 auf ~2 DB-Queries pro Pageload).

**Architecture:** `django-redis` wird auf DB 2 als `CACHES["default"]` konfiguriert. `products/cache.py` zentralisiert Cache-Keys, Hilfsfunktionen, `CachedRelatedDropdownFilter` und Signal-Receiver. `ProductAdmin.image_preview()` liest Bild-URLs aus Redis (Lazy Warm-up bei Miss via einzelner DB-Query). Filter-Dropdowns für Tax und Category lesen ihre Choices aus Redis (Invalidierung via Signals).

**Tech Stack:** `django-redis`, Django Cache Framework, `unfold.contrib.filters.admin.RelatedDropdownFilter`

## Global Constraints

- Package-Installation immer mit `uv pip install`, nicht mit `pip`
- Kein `Co-Authored-By` in Commits
- Redis DB 0 = Celery Broker, DB 1 = Celery Result, DB 2 = Django Cache (nicht überschreiben)
- Alle Cache-Operationen mit try/except absichern — Redis-Ausfall darf Admin nie blockieren
- `None` wird nie in den Cache geschrieben (dient als zuverlässiges Miss-Signal von `cache.get()`)

---

### Task 1: django-redis installieren und CACHES konfigurieren

**Files:**
- Modify: `GC_Bridge_4/settings.py:304` (nach `CELERY_RESULT_BACKEND`-Block)

**Interfaces:**
- Produces: `django.core.cache.cache` steht projektweit als Redis-Client (DB 2) zur Verfügung

- [ ] **Step 1: Paket installieren**

```bash
cd /mnt/daten1tb/python/GC-Bridge-4
uv pip install django-redis
```

Expected: `Successfully installed django-redis-x.x.x`

- [ ] **Step 2: CACHES-Block in settings.py einfügen**

In `GC_Bridge_4/settings.py` direkt nach Zeile 311 (`CELERY_BEAT_SCHEDULE = {}`):

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

- [ ] **Step 3: Konfiguration prüfen**

```bash
python manage.py shell -c "
from django.core.cache import cache
cache.set('smoke', 'ok', timeout=10)
assert cache.get('smoke') == 'ok', 'Cache nicht erreichbar'
cache.delete('smoke')
print('Cache OK')
"
```

Expected: `Cache OK`

- [ ] **Step 4: Committen**

```bash
git add GC_Bridge_4/settings.py
git commit -m "feat(cache): django-redis als CACHES-Backend konfigurieren (DB 2)"
```

---

### Task 2: products/cache.py anlegen

**Files:**
- Create: `products/cache.py`

**Interfaces:**
- Produces:
  - `get_cached_image_url(product_pk: int) -> str | None` — URL-String (auch `""`) oder `None` bei Miss; wirft nie
  - `set_cached_image_url(product_pk: int, url: str) -> None` — schreibt in Cache; wirft nie
  - `invalidate_image_url(product_pk: int) -> None` — löscht Key; wirft nie
  - `warm_image_url(product_pk: int) -> str` — DB-Query + Cache schreiben, gibt URL zurück
  - `CachedRelatedDropdownFilter` — Subklasse von `RelatedDropdownFilter` mit gecachten Choices
  - `register_cache_signals() -> None` — verbindet alle Signal-Receiver

- [ ] **Step 1: Failing-Test schreiben**

In `products/tests.py`, am Ende der Datei anhängen:

```python
# --- Cache-Tests ---

from django.test import TestCase, override_settings
from unittest.mock import patch, MagicMock

LOCMEM_CACHE = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
    }
}


@override_settings(CACHES=LOCMEM_CACHE)
class ProductImageUrlCacheTests(TestCase):
    def setUp(self):
        from django.core.cache import cache
        cache.clear()

    def test_get_returns_none_on_miss(self):
        from products.cache import get_cached_image_url
        self.assertIsNone(get_cached_image_url(99999))

    def test_set_and_get_roundtrip(self):
        from products.cache import get_cached_image_url, set_cached_image_url
        set_cached_image_url(42, "https://example.com/img.jpg")
        self.assertEqual(get_cached_image_url(42), "https://example.com/img.jpg")

    def test_set_empty_string_for_no_image(self):
        from products.cache import get_cached_image_url, set_cached_image_url
        set_cached_image_url(42, "")
        # "" ist ein gültiger Cache-Hit (kein Bild) — kein None
        self.assertEqual(get_cached_image_url(42), "")

    def test_invalidate_removes_key(self):
        from products.cache import get_cached_image_url, set_cached_image_url, invalidate_image_url
        set_cached_image_url(42, "https://example.com/img.jpg")
        invalidate_image_url(42)
        self.assertIsNone(get_cached_image_url(42))

    def test_redis_error_in_get_returns_none(self):
        from products.cache import get_cached_image_url
        with patch("products.cache.cache") as mock_cache:
            mock_cache.get.side_effect = Exception("Redis down")
            result = get_cached_image_url(42)
        self.assertIsNone(result)

    def test_redis_error_in_set_does_not_raise(self):
        from products.cache import set_cached_image_url
        with patch("products.cache.cache") as mock_cache:
            mock_cache.set.side_effect = Exception("Redis down")
            set_cached_image_url(42, "url")  # darf nicht werfen

    def test_redis_error_in_invalidate_does_not_raise(self):
        from products.cache import invalidate_image_url
        with patch("products.cache.cache") as mock_cache:
            mock_cache.delete.side_effect = Exception("Redis down")
            invalidate_image_url(42)  # darf nicht werfen
```

- [ ] **Step 2: Tests ausführen — müssen fehlschlagen**

```bash
python manage.py test products.tests.ProductImageUrlCacheTests -v 2
```

Expected: `ImportError: cannot import name 'get_cached_image_url' from 'products.cache'`

- [ ] **Step 3: products/cache.py implementieren**

```python
import logging

from django.core.cache import cache
from unfold.contrib.filters.admin import RelatedDropdownFilter

logger = logging.getLogger(__name__)

CACHE_TIMEOUT = 3600  # 1 Stunde

# --- Cache-Keys ---

def _image_url_key(product_pk: int) -> str:
    return f"product:image_url:{product_pk}"

_TAX_CHOICES_KEY = "filter:tax:all"
_CATEGORY_CHOICES_KEY = "filter:category:all"


# --- Bild-URL-Helpers ---

def get_cached_image_url(product_pk: int) -> str | None:
    """Gibt gecachte URL zurück (auch '' für kein Bild), None bei Miss. Wirft nie."""
    try:
        return cache.get(_image_url_key(product_pk))
    except Exception:
        logger.warning("Redis-Fehler in get_cached_image_url für pk=%s", product_pk, exc_info=True)
        return None


def set_cached_image_url(product_pk: int, url: str) -> None:
    """Schreibt URL in Cache. Wirft nie."""
    try:
        cache.set(_image_url_key(product_pk), url, timeout=CACHE_TIMEOUT)
    except Exception:
        logger.warning("Redis-Fehler in set_cached_image_url für pk=%s", product_pk, exc_info=True)


def invalidate_image_url(product_pk: int) -> None:
    """Löscht Cache-Key. Wirft nie."""
    try:
        cache.delete(_image_url_key(product_pk))
    except Exception:
        logger.warning("Redis-Fehler in invalidate_image_url für pk=%s", product_pk, exc_info=True)


def _fetch_first_image_url(product_pk: int) -> str:
    """Direkte DB-Query für erste Bild-URL, ohne Cache zu berühren."""
    from products.models import ProductImage
    pi = (
        ProductImage.objects
        .select_related("image")
        .filter(product_id=product_pk, image__isnull=False)
        .order_by("order", "id")
        .first()
    )
    return pi.image.url if pi and pi.image else ""


def warm_image_url(product_pk: int) -> str:
    """Holt URL aus DB, schreibt in Cache und gibt URL zurück."""
    url = _fetch_first_image_url(product_pk)
    set_cached_image_url(product_pk, url)
    return url


# --- Filter-Choices-Cache ---

class CachedRelatedDropdownFilter(RelatedDropdownFilter):
    """RelatedDropdownFilter mit Redis-gecachten Choices für Tax und Category."""

    _CACHE_KEY_MAP = {
        "products.tax": _TAX_CHOICES_KEY,
        "products.category": _CATEGORY_CHOICES_KEY,
    }

    def field_choices(self, field, request, model_admin):
        model_label = field.remote_field.model._meta.label.lower()
        cache_key = self._CACHE_KEY_MAP.get(model_label)
        if not cache_key:
            return super().field_choices(field, request, model_admin)
        try:
            choices = cache.get(cache_key)
            if choices is not None:
                return choices
            choices = list(super().field_choices(field, request, model_admin))
            cache.set(cache_key, choices, timeout=CACHE_TIMEOUT)
            return choices
        except Exception:
            logger.warning("Redis-Fehler in CachedRelatedDropdownFilter für %s", model_label, exc_info=True)
            return super().field_choices(field, request, model_admin)


# --- Signal-Receiver-Registrierung ---

def _on_product_image_save(sender, instance, **kwargs):
    invalidate_image_url(instance.product_id)
    warm_image_url(instance.product_id)


def _on_product_image_delete(sender, instance, **kwargs):
    invalidate_image_url(instance.product_id)


def _on_tax_change(sender, instance, **kwargs):
    try:
        cache.delete(_TAX_CHOICES_KEY)
    except Exception:
        logger.warning("Redis-Fehler beim Invalidieren von Tax-Filter-Choices", exc_info=True)


def _on_category_change(sender, instance, **kwargs):
    try:
        cache.delete(_CATEGORY_CHOICES_KEY)
    except Exception:
        logger.warning("Redis-Fehler beim Invalidieren von Category-Filter-Choices", exc_info=True)


def register_cache_signals():
    """Verbindet alle Cache-Invalidierungs-Receiver. Aufruf in ProductsConfig.ready()."""
    from django.db.models.signals import post_save, post_delete
    from products.models import ProductImage, Tax, Category

    post_save.connect(_on_product_image_save, sender=ProductImage,
                      dispatch_uid="cache_product_image_save")
    post_delete.connect(_on_product_image_delete, sender=ProductImage,
                        dispatch_uid="cache_product_image_delete")
    post_save.connect(_on_tax_change, sender=Tax,
                      dispatch_uid="cache_tax_save")
    post_delete.connect(_on_tax_change, sender=Tax,
                        dispatch_uid="cache_tax_delete")
    post_save.connect(_on_category_change, sender=Category,
                      dispatch_uid="cache_category_save")
    post_delete.connect(_on_category_change, sender=Category,
                        dispatch_uid="cache_category_delete")
```

- [ ] **Step 4: Tests ausführen — müssen grün sein**

```bash
python manage.py test products.tests.ProductImageUrlCacheTests -v 2
```

Expected: `OK` (7 Tests bestanden)

- [ ] **Step 5: Committen**

```bash
git add products/cache.py products/tests.py
git commit -m "feat(cache): products/cache.py mit Bild-URL-Helpers und CachedRelatedDropdownFilter"
```

---

### Task 3: Signal-Receiver registrieren und Invalidierung testen

**Files:**
- Modify: `products/apps.py`
- Modify: `products/tests.py` (neue Testklasse)

**Interfaces:**
- Consumes: `register_cache_signals()` aus Task 2
- Produces: Alle Signal-Receiver aktiv wenn App bereit ist

- [ ] **Step 1: Failing-Test schreiben**

In `products/tests.py` nach `ProductImageUrlCacheTests` anhängen:

```python
@override_settings(CACHES=LOCMEM_CACHE)
class CacheInvalidationSignalTests(TestCase):
    def setUp(self):
        from django.core.cache import cache
        cache.clear()

    def _make_product(self):
        from products.models import Product, Tax
        tax, _ = Tax.objects.get_or_create(name="19%", rate=19)
        return Product.objects.create(erp_nr=f"TEST-{Tax.objects.count()}", tax=tax)

    def _make_image(self):
        from products.models import Image
        return Image.objects.create(path="test/img.jpg")

    def test_product_image_save_warms_cache(self):
        from products.cache import get_cached_image_url, set_cached_image_url
        from products.models import ProductImage
        product = self._make_product()
        image = self._make_image()
        # Vor dem Save: Cache leer
        self.assertIsNone(get_cached_image_url(product.pk))
        # ProductImage anlegen → Signal → Cache wärmt
        ProductImage.objects.create(product=product, image=image, order=1)
        # Nach dem Save: Cache gesetzt
        cached = get_cached_image_url(product.pk)
        self.assertIsNotNone(cached)

    def test_product_image_delete_invalidates_cache(self):
        from products.cache import get_cached_image_url, set_cached_image_url
        from products.models import ProductImage
        product = self._make_product()
        image = self._make_image()
        pi = ProductImage.objects.create(product=product, image=image, order=1)
        # Cache ist nach Save gesetzt
        self.assertIsNotNone(get_cached_image_url(product.pk))
        # Löschen → Signal → Cache weg
        pi.delete()
        self.assertIsNone(get_cached_image_url(product.pk))

    def test_tax_save_invalidates_filter_cache(self):
        from django.core.cache import cache
        from products.models import Tax
        cache.set("filter:tax:all", [("1", "19%")], timeout=3600)
        tax, _ = Tax.objects.get_or_create(name="7%", rate=7)
        tax.save()
        self.assertIsNone(cache.get("filter:tax:all"))

    def test_category_save_invalidates_filter_cache(self):
        from django.core.cache import cache
        from products.models import Category
        cache.set("filter:category:all", [("1", "Test")], timeout=3600)
        cat, _ = Category.objects.get_or_create(name="TestCat", slug="test-cat")
        cat.save()
        self.assertIsNone(cache.get("filter:category:all"))
```

- [ ] **Step 2: Tests ausführen — müssen fehlschlagen (Signale noch nicht registriert)**

```bash
python manage.py test products.tests.CacheInvalidationSignalTests -v 2
```

Expected: Tests schlagen fehl, weil `register_cache_signals()` noch nicht in `apps.py` aufgerufen wird.

- [ ] **Step 3: apps.py anpassen**

`products/apps.py` — `register_cache_signals()` in `ready()` ergänzen:

```python
from django.apps import AppConfig


class ProductsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "products"

    def ready(self) -> None:
        import products.signals  # noqa: F401
        from products.cache import register_cache_signals
        register_cache_signals()
```

- [ ] **Step 4: Tests ausführen — müssen grün sein**

```bash
python manage.py test products.tests.CacheInvalidationSignalTests -v 2
```

Expected: `OK` (4 Tests bestanden)

- [ ] **Step 5: Committen**

```bash
git add products/apps.py products/tests.py
git commit -m "feat(cache): Cache-Signal-Receiver in ProductsConfig.ready() registrieren"
```

---

### Task 4: ProductAdmin anpassen

**Files:**
- Modify: `products/admin.py`
- Modify: `products/tests.py` (neue Testklasse für image_preview)

**Interfaces:**
- Consumes:
  - `get_cached_image_url(product_pk)` → `str | None`
  - `warm_image_url(product_pk)` → `str`
  - `CachedRelatedDropdownFilter`
  - alle aus Task 2
- Produces: Admin-Produktliste ohne Prefetch, image_preview aus Redis

**Hinweis:** Ohne Prefetch macht `image_preview()` auf Cache-Miss eine einzelne DB-Query pro Produkt-Zeile. Bei <1.000 Produkten ist der Cache nach der ersten Seitenladung vollständig warm — danach 0 Bild-Queries.

- [ ] **Step 1: Failing-Test für image_preview schreiben**

In `products/tests.py` nach `CacheInvalidationSignalTests` anhängen:

```python
@override_settings(CACHES=LOCMEM_CACHE)
class ProductAdminImagePreviewCacheTests(TestCase):
    def setUp(self):
        from django.core.cache import cache
        cache.clear()

    def _make_product_with_image(self):
        from products.models import Product, Tax, Image, ProductImage
        tax, _ = Tax.objects.get_or_create(name="19%", rate=19)
        product = Product.objects.create(erp_nr="IMGTEST-1", tax=tax)
        image = Image.objects.create(path="test/preview.jpg")
        ProductImage.objects.create(product=product, image=image, order=1)
        return product

    def _call_image_preview(self, product):
        from django.contrib.admin.sites import AdminSite
        from django.test import RequestFactory
        from products.admin import ProductAdmin
        admin = ProductAdmin(model=product.__class__, admin_site=AdminSite())
        return admin.image_preview(product)

    def test_image_preview_serves_from_cache_on_hit(self):
        from products.cache import set_cached_image_url
        from products.models import Product, Tax
        tax, _ = Tax.objects.get_or_create(name="19%", rate=19)
        product = Product.objects.create(erp_nr="IMGTEST-2", tax=tax)
        set_cached_image_url(product.pk, "https://cdn.example.com/img.jpg")
        result = self._call_image_preview(product)
        self.assertIn("cdn.example.com/img.jpg", str(result))

    def test_image_preview_warms_cache_on_miss(self):
        from products.cache import get_cached_image_url
        product = self._make_product_with_image()
        # Cache ist leer
        self.assertIsNone(get_cached_image_url(product.pk))
        # image_preview aufrufen → Cache-Miss → DB-Fallback → Cache wärmt
        self._call_image_preview(product)
        # Cache ist jetzt gesetzt
        self.assertIsNotNone(get_cached_image_url(product.pk))

    def test_image_preview_returns_empty_for_no_image(self):
        from products.models import Product, Tax
        tax, _ = Tax.objects.get_or_create(name="19%", rate=19)
        product = Product.objects.create(erp_nr="IMGTEST-3", tax=tax)
        result = self._call_image_preview(product)
        self.assertEqual(result, "")

    def test_image_preview_works_when_redis_down(self):
        product = self._make_product_with_image()
        with patch("products.cache.cache") as mock_cache:
            mock_cache.get.side_effect = Exception("Redis down")
            mock_cache.set.side_effect = Exception("Redis down")
            result = self._call_image_preview(product)
        # Fällt auf DB zurück — kein 500-Fehler, gibt HTML zurück
        self.assertIn("<img", str(result))
```

- [ ] **Step 2: Tests ausführen — müssen fehlschlagen**

```bash
python manage.py test products.tests.ProductAdminImagePreviewCacheTests -v 2
```

Expected: Tests schlagen fehl (image_preview nutzt noch kein Cache)

- [ ] **Step 3: ProductAdmin.get_queryset anpassen — Prefetch entfernen**

In `products/admin.py`, die Methode `get_queryset` in `ProductAdmin` (aktuell Zeilen 477–485) ersetzen:

```python
def get_queryset(self, request):
    return super().get_queryset(request)
```

- [ ] **Step 4: ProductAdmin.image_preview anpassen — Cache nutzen**

Import am Anfang von `products/admin.py` ergänzen (nach dem bestehenden Block `from .models import ...`):

```python
from .cache import CachedRelatedDropdownFilter, get_cached_image_url, warm_image_url
```

Die Methode `image_preview` in `ProductAdmin` (aktuell Zeilen 520–528) ersetzen:

```python
@admin.display(description="Bild")
def image_preview(self, obj: Product):
    try:
        url = get_cached_image_url(obj.pk)
    except Exception:
        url = None

    if url is None:
        # Cache-Miss oder Redis-Fehler → DB-Fallback + Cache wärmen
        try:
            url = warm_image_url(obj.pk)
        except Exception:
            from products.models import ProductImage
            pi = (
                ProductImage.objects
                .select_related("image")
                .filter(product_id=obj.pk, image__isnull=False)
                .order_by("order", "id")
                .first()
            )
            url = pi.image.url if pi and pi.image else ""

    if not url:
        return ""
    return format_html(
        '<img src="{}" loading="lazy" style="width:50px;height:50px;object-fit:cover;border-radius:4px;" />',
        url,
    )
```

- [ ] **Step 5: list_filter in ProductAdmin anpassen — CachedRelatedDropdownFilter nutzen**

In `ProductAdmin`, `list_filter` (aktuell Zeilen 445–450) anpassen:

```python
list_filter = [
    ("is_active", BooleanRadioFilter),
    ("tax", CachedRelatedDropdownFilter),
    ("categories", CachedRelatedDropdownFilter),
    ("created_at", RangeDateTimeFilter),
]
```

- [ ] **Step 6: Tests ausführen — müssen grün sein**

```bash
python manage.py test products.tests.ProductAdminImagePreviewCacheTests -v 2
```

Expected: `OK` (4 Tests bestanden)

- [ ] **Step 7: Alle Produkt-Tests ausführen**

```bash
python manage.py test products -v 2
```

Expected: Keine Regressionen, alle Tests `OK`

- [ ] **Step 8: Committen**

```bash
git add products/admin.py products/tests.py
git commit -m "feat(cache): ProductAdmin nutzt Redis-Cache für Bild-URLs und Filter-Choices"
```

---

## Self-Review

**Spec-Coverage-Check:**

| Spec-Anforderung | Umgesetzt in |
|---|---|
| `django-redis` als `CACHES["default"]` (DB 2) | Task 1 |
| Cache-Key `product:image_url:{pk}` | Task 2 |
| `image_preview` liest aus Cache, DB-Fallback bei Miss | Task 4 |
| Prefetch aus `get_queryset` entfernt | Task 4 |
| `post_save`/`post_delete` auf `ProductImage` → invalidate + re-warm | Task 2 + Task 3 |
| `CachedRelatedDropdownFilter` für Tax + Category | Task 2 |
| `filter:tax:all` / `filter:category:all` gecacht | Task 2 |
| Tax/Category Signals → Filter-Cache invalidieren | Task 2 + Task 3 |
| Signal-Receiver in `apps.py` registriert | Task 3 |
| Redis-Ausfall → DB-Fallback, kein 500 | Task 2 (Helpers) + Task 4 (image_preview) |
| Tests: Warm-up, Invalidierung, Redis-Ausfall | Task 2 + Task 3 + Task 4 |

**Placeholder-Scan:** Keine TBDs, TODOs oder vagen Schritte gefunden. Alle Code-Blöcke vollständig.

**Type-Konsistenz:** `get_cached_image_url`, `set_cached_image_url`, `invalidate_image_url`, `warm_image_url` — in Task 2 definiert und in Task 4 exakt so verwendet. `CachedRelatedDropdownFilter` in Task 2 definiert, in Task 4 importiert und in `list_filter` genutzt. Konsistent.
