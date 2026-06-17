# Email MJML Component Library Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the hardcoded email component system with a managed MJML component library; add per-channel special price write-back with Microtech + Shopware sync.

**Architecture:** New `MjmlComponent` model acts as the library; `EmailCampaignComponent` references it via FK. Components carry a `placement` field (head/body) that drives MJML section routing at render time. Price write-back runs as a Celery task triggered automatically on campaign save.

**Tech Stack:** Django, django-unfold, Celery, MJML CLI, pytest

**Spec:** `docs/superpowers/specs/2026-06-17-email-mjml-components-design.md`

---

## File Map

| Action | Path | Responsibility |
|--------|------|----------------|
| Modify | `emails/models.py` | Add `MjmlComponent`; update `EmailCampaignComponent`, `EmailCampaignProduct`; remove legacy fields/models |
| Create | `emails/services.py` | `apply_campaign_special_prices()` — price write-back logic |
| Create | `emails/tasks.py` | `apply_campaign_prices_async` Celery task |
| Modify | `emails/mjml.py` | Head/body split rendering; remove h1/product_template refs |
| Modify | `emails/admin.py` | `MjmlComponentAdmin`; sortable inlines; `save_related` price trigger; remove `SalesChannelInline` |
| Modify | `emails/templates/emails/newsletter_base.mjml` | Add `head_mjml` variable |
| Create | `emails/migrations/0008_mjml_component.py` | auto-generated |
| Create | `emails/migrations/0009_add_library_fk_and_new_fields.py` | auto-generated |
| Create | `emails/migrations/0010_data_migration_library_components.py` | hand-written data migration |
| Create | `emails/migrations/0011_remove_legacy_fields.py` | auto-generated |
| Modify | `tests/emails/test_mjml.py` | Update for new model shape |
| Modify | `tests/emails/test_admin.py` | Remove SalesChannelInline; add MjmlComponent tests |
| Create | `tests/emails/test_services.py` | Price write-back service tests |

---

## Task 1: Add `MjmlComponent` model

**Files:**
- Modify: `emails/models.py`
- Create: `emails/migrations/0008_mjml_component.py` (auto-generated)
- Test: `tests/emails/test_mjml.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/emails/test_mjml.py`:

```python
@pytest.mark.django_db
class TestMjmlComponent:
    def test_str_returns_name(self):
        from emails.models import MjmlComponent
        component = MjmlComponent(name="Logo", placement="body", mjml_markup="<mj-section/>", order=10)
        assert str(component) == "Logo"

    def test_default_placement_is_body(self):
        from emails.models import MjmlComponent
        component = MjmlComponent(name="Test")
        assert component.placement == "body"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /mnt/daten1tb/python/GC-Bridge-4
.venv/bin/pytest tests/emails/test_mjml.py::TestMjmlComponent -v
```

Expected: `ImportError` or `AttributeError` — MjmlComponent does not exist yet.

- [ ] **Step 3: Add `MjmlComponent` to `emails/models.py`**

Add after the existing imports, before `EmailCampaign`:

```python
class MjmlComponent(BaseModel):
    class Placement(models.TextChoices):
        HEAD = "head", _("Head")
        BODY = "body", _("Body")

    name = models.CharField(max_length=255, verbose_name=_("Name"))
    description = models.TextField(blank=True, default="", verbose_name=_("Beschreibung"))
    mjml_markup = models.TextField(blank=True, default="", verbose_name=_("MJML Markup"))
    placement = models.CharField(
        max_length=10,
        choices=Placement.choices,
        default=Placement.BODY,
        verbose_name=_("Platzierung"),
    )
    is_default = models.BooleanField(default=False, verbose_name=_("Standard"))
    order = models.PositiveIntegerField(default=0, verbose_name=_("Reihenfolge"))

    class Meta:
        verbose_name = _("MJML Komponente")
        verbose_name_plural = _("MJML Komponenten")
        ordering = ("order", "name")

    def __str__(self) -> str:
        return self.name
```

- [ ] **Step 4: Generate migration**

```bash
cd /mnt/daten1tb/python/GC-Bridge-4
.venv/bin/python manage.py makemigrations emails --name mjml_component
```

Expected: `emails/migrations/0008_mjml_component.py` created.

- [ ] **Step 5: Run migration**

```bash
.venv/bin/python manage.py migrate emails
```

- [ ] **Step 6: Run tests to verify they pass**

```bash
.venv/bin/pytest tests/emails/test_mjml.py::TestMjmlComponent -v
```

Expected: 2 PASSED.

- [ ] **Step 7: Commit**

```bash
git add emails/models.py emails/migrations/0008_mjml_component.py tests/emails/test_mjml.py
git commit -m "feat(emails): add MjmlComponent library model"
```

---

## Task 2: Update `EmailCampaignComponent` — add library FK

**Files:**
- Modify: `emails/models.py`
- Create: `emails/migrations/0009_add_library_fk_and_new_fields.py` (auto-generated)

> The FK is nullable for now so existing rows don't break. Task 4 (data migration) fills it in. Task 5 removes the old fields.

- [ ] **Step 1: Write the failing test**

Add to `tests/emails/test_mjml.py`:

```python
@pytest.mark.django_db
class TestEmailCampaignComponentStr:
    def test_str_shows_order_name_and_placement(self):
        from emails.models import EmailCampaign, EmailCampaignComponent, MjmlComponent
        lib = MjmlComponent.objects.create(name="Logo", placement="body", order=10)
        campaign = EmailCampaign.objects.create(internal_title="T", status="draft")
        comp = EmailCampaignComponent(
            campaign=campaign,
            library_component=lib,
            order=10,
        )
        assert str(comp) == "10 – Logo (Body)"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
.venv/bin/pytest tests/emails/test_mjml.py::TestEmailCampaignComponentStr -v
```

Expected: FAIL — `library_component` field does not exist.

- [ ] **Step 3: Update `EmailCampaignComponent` in `emails/models.py`**

Add `library_component` FK and update `__str__`. Keep `component_key` and `mjml_markup` for now (removed in Task 5 after data migration):

```python
class EmailCampaignComponent(BaseModel):
    # ... existing fields unchanged above ...
    library_component = models.ForeignKey(
        "MjmlComponent",
        on_delete=models.PROTECT,
        related_name="campaign_usages",
        null=True,
        blank=True,
        verbose_name=_("Bibliotheks-Komponente"),
    )
    # component_key, title, subtitle, body_html, mjml_markup, order, enabled — all kept for now

    def __str__(self) -> str:
        if self.library_component_id:
            placement = self.library_component.get_placement_display()
            return f"{self.order} – {self.library_component.name} ({placement})"
        return self.title or self.get_component_key_display()
```

- [ ] **Step 4: Generate and run migration**

```bash
.venv/bin/python manage.py makemigrations emails --name add_library_fk_and_new_fields
.venv/bin/python manage.py migrate emails
```

- [ ] **Step 5: Run tests**

```bash
.venv/bin/pytest tests/emails/test_mjml.py::TestEmailCampaignComponentStr -v
```

Expected: PASSED.

- [ ] **Step 6: Commit**

```bash
git add emails/models.py emails/migrations/0009_add_library_fk_and_new_fields.py tests/emails/test_mjml.py
git commit -m "feat(emails): add library_component FK to EmailCampaignComponent"
```

---

## Task 3: Update `EmailCampaignProduct` — add `discount_pct` and `prices_synced_at`

**Files:**
- Modify: `emails/models.py`
- Migration: auto-generated (included in 0009 or separate)

- [ ] **Step 1: Write the failing test**

Add to `tests/emails/test_mjml.py`:

```python
@pytest.mark.django_db
class TestEmailCampaignProductFields:
    def test_discount_pct_and_prices_synced_at_exist(self):
        from emails.models import EmailCampaign, EmailCampaignProduct
        from products.models import Product
        campaign = EmailCampaign.objects.create(internal_title="X", status="draft")
        product = Product.objects.filter(is_active=True).first()
        if product is None:
            pytest.skip("No products in test DB")
        cp = EmailCampaignProduct(campaign=campaign, product=product, order=0)
        assert hasattr(cp, "discount_pct")
        assert hasattr(cp, "prices_synced_at")
        assert cp.discount_pct is None
        assert cp.prices_synced_at is None
```

- [ ] **Step 2: Run to verify it fails**

```bash
.venv/bin/pytest tests/emails/test_mjml.py::TestEmailCampaignProductFields -v
```

Expected: FAIL — fields don't exist.

- [ ] **Step 3: Add fields to `EmailCampaignProduct` in `emails/models.py`**

```python
class EmailCampaignProduct(BaseModel):
    # ... existing fields ...
    discount_pct = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name=_("Rabatt (%)"),
        help_text=_("Alternativ zum absoluten Sonderpreis. Wird auf den Standardkanalpreis angewendet."),
    )
    prices_synced_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name=_("Preise synchronisiert am"),
    )

    def clean(self):
        from django.core.exceptions import ValidationError
        if self.special_price_override and self.discount_pct:
            raise ValidationError(_("Nur Sonderpreis ODER Rabatt (%) angeben, nicht beides."))
```

- [ ] **Step 4: Generate and run migration**

```bash
.venv/bin/python manage.py makemigrations emails --name emailcampaignproduct_discount_pct
.venv/bin/python manage.py migrate emails
```

- [ ] **Step 5: Run tests**

```bash
.venv/bin/pytest tests/emails/test_mjml.py::TestEmailCampaignProductFields -v
```

Expected: PASSED (or SKIPPED if no products in test DB — acceptable).

- [ ] **Step 6: Commit**

```bash
git add emails/models.py emails/migrations/ tests/emails/test_mjml.py
git commit -m "feat(emails): add discount_pct and prices_synced_at to EmailCampaignProduct"
```

---

## Task 4: Data migration — populate library from legacy templates

**Files:**
- Create: `emails/migrations/0011_data_migration_library_components.py`

This migration:
1. Creates `MjmlComponent` entries from legacy template files
2. Sets `library_component` FK on all existing `EmailCampaignComponent` rows
3. Migrates `h1`/`h1_small`/`intro_text` from `EmailCampaign` into the matching TITLE_INTRO component
4. Maps `campaign.product_template` to the correct product `MjmlComponent`

- [ ] **Step 1: Create the data migration file**

```bash
.venv/bin/python manage.py makemigrations emails --empty --name data_migration_library_components
```

- [ ] **Step 2: Write the migration**

Open the generated file and replace its `operations` list with:

```python
import os
from django.db import migrations


LEGACY_COMPONENT_KEYS = [
    ("header_nav", "Onlineansicht & Navigation", "body", True, 10),
    ("logo", "Logo", "body", True, 20),
    ("title_intro", "Überschrift & Einleitung", "body", True, 30),
    ("products", "Produkte Standard", "body", True, 40),
    ("product_shipping_free", "Produkte Kostenloser Versand", "body", False, 41),
    ("product_green", "Produkte Grün", "body", False, 42),
    ("content_text", "Textblock", "body", False, 50),
    ("blog_acymailing", "Blog Auto-Content", "body", False, 60),
    ("certs_logo_green", "Zertifikate grün", "body", False, 70),
    ("4r", "4R Nachhaltigkeit", "body", False, 80),
    ("weihnachten", "Weihnachten", "body", False, 90),
    ("contact_table", "Kontaktformular", "body", True, 100),
    ("disclaimer", "Disclaimer", "body", True, 110),
    ("head", "Head (CSS & Meta)", "head", True, 5),
]

LEGACY_TEMPLATE_MAP = {
    "header_nav": "legacy/header_nav.mjml",
    "logo": "legacy/logo.mjml",
    "title_intro": "legacy/title_intro.mjml",
    "products": "legacy/products.mjml",
    "product_shipping_free": "legacy/products.mjml",
    "product_green": "legacy/products.mjml",
    "content_text": "legacy/content_text.mjml",
    "blog_acymailing": "legacy/blog_acymailing.mjml",
    "certs_logo_green": "legacy/certs_logo_green.mjml",
    "4r": "legacy/4r.mjml",
    "weihnachten": "legacy/weihnachten.mjml",
    "contact_table": "legacy/contact_table.mjml",
    "disclaimer": "legacy/disclaimer.mjml",
    "head": "head.mjml",
}

PRODUCT_TEMPLATE_KEY_MAP = {
    "product": "products",
    "product_shipping_free": "product_shipping_free",
    "product_green": "product_green",
}


def _read_template(key: str) -> str:
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    rel = LEGACY_TEMPLATE_MAP.get(key, "")
    if not rel:
        return ""
    path = os.path.join(base, "templates", "emails", "components", rel)
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return f.read()
    return ""


def forwards(apps, schema_editor):
    MjmlComponent = apps.get_model("emails", "MjmlComponent")
    EmailCampaignComponent = apps.get_model("emails", "EmailCampaignComponent")
    EmailCampaign = apps.get_model("emails", "EmailCampaign")

    # 1. Create library entries
    lib_by_key = {}
    for key, name, placement, is_default, order in LEGACY_COMPONENT_KEYS:
        obj, _ = MjmlComponent.objects.get_or_create(
            name=name,
            defaults={
                "mjml_markup": _read_template(key),
                "placement": placement,
                "is_default": is_default,
                "order": order,
            },
        )
        lib_by_key[key] = obj

    # 2. Map existing EmailCampaignComponent rows
    for comp in EmailCampaignComponent.objects.select_related("campaign").all():
        component_key = comp.component_key
        if component_key == "products":
            # Use product_template from parent campaign
            pt = comp.campaign.product_template if hasattr(comp.campaign, "product_template") else "product"
            mapped_key = PRODUCT_TEMPLATE_KEY_MAP.get(pt, "products")
        else:
            mapped_key = component_key
        lib = lib_by_key.get(mapped_key)
        if lib:
            comp.library_component = lib
            comp.save(update_fields=["library_component"])

    # 3. Move h1/h1_small/intro_text into TITLE_INTRO components
    title_lib = lib_by_key.get("title_intro")
    if title_lib:
        for campaign in EmailCampaign.objects.all():
            h1 = getattr(campaign, "h1", "")
            h1_small = getattr(campaign, "h1_small", "")
            intro_text = getattr(campaign, "intro_text", "")
            if not (h1 or h1_small or intro_text):
                continue
            try:
                title_comp = EmailCampaignComponent.objects.get(
                    campaign=campaign,
                    library_component=title_lib,
                )
                if not title_comp.title:
                    title_comp.title = h1
                if not title_comp.subtitle:
                    title_comp.subtitle = h1_small
                if not title_comp.body_html:
                    title_comp.body_html = intro_text
                title_comp.save(update_fields=["title", "subtitle", "body_html"])
            except EmailCampaignComponent.DoesNotExist:
                pass


def backwards(apps, schema_editor):
    pass  # Non-destructive — library components can remain


class Migration(migrations.Migration):
    dependencies = [
        ("emails", "0010_emailcampaignproduct_discount_pct"),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
```

> **Note:** Adjust the `dependencies` entry to match the actual last migration number before running.

- [ ] **Step 3: Run the data migration**

```bash
.venv/bin/python manage.py migrate emails
```

Expected: runs without error.

- [ ] **Step 4: Verify in shell**

```bash
.venv/bin/python manage.py shell -c "
from emails.models import MjmlComponent, EmailCampaignComponent
print('Library entries:', MjmlComponent.objects.count())
linked = EmailCampaignComponent.objects.filter(library_component__isnull=False).count()
total = EmailCampaignComponent.objects.count()
print(f'Linked: {linked}/{total}')
"
```

Expected: library entries ≥ 14; all campaign components linked.

- [ ] **Step 5: Commit**

```bash
git add emails/migrations/
git commit -m "feat(emails): data migration — populate MjmlComponent library from legacy templates"
```

---

## Task 5: Remove legacy fields

**Files:**
- Modify: `emails/models.py` — remove `component_key`, `mjml_markup` from `EmailCampaignComponent`; remove `h1`, `h1_small`, `intro_text`, `product_template` from `EmailCampaign`; remove `EmailCampaignSalesChannel`
- Create: migration (auto-generated)

> Before this task: verify all `EmailCampaignComponent` rows have `library_component` set (Task 4). If any are NULL, the migration will fail on the NOT NULL constraint.

- [ ] **Step 1: Update `emails/models.py`**

In `EmailCampaignComponent`, remove these fields entirely:
- `component_key`
- `mjml_markup`
- `DEFAULT_COMPONENTS` class attribute
- `ComponentKey` inner class

Make `library_component` non-nullable:

```python
library_component = models.ForeignKey(
    "MjmlComponent",
    on_delete=models.PROTECT,
    related_name="campaign_usages",
    verbose_name=_("Bibliotheks-Komponente"),
)
```

Update `__str__` (remove the old fallback):

```python
def __str__(self) -> str:
    placement = self.library_component.get_placement_display()
    return f"{self.order} – {self.library_component.name} ({placement})"

def get_inline_title(self) -> str:
    return str(self)
```

In `EmailCampaign`, remove: `h1`, `h1_small`, `intro_text`, `product_template`, `ProductTemplate` inner class, `products_with_special_price_count` method.

Delete the entire `EmailCampaignSalesChannel` class.

- [ ] **Step 2: Generate migration**

```bash
.venv/bin/python manage.py makemigrations emails --name remove_legacy_fields
```

- [ ] **Step 3: Run migration**

```bash
.venv/bin/python manage.py migrate emails
```

- [ ] **Step 4: Check that the app loads**

```bash
.venv/bin/python manage.py check
```

Expected: `System check identified no issues`.

- [ ] **Step 5: Commit**

```bash
git add emails/models.py emails/migrations/
git commit -m "feat(emails): remove legacy component_key, mjml_markup, h1 and SalesChannel fields"
```

---

## Task 6: Price write-back service

**Files:**
- Create: `emails/services.py`
- Create: `tests/emails/test_services.py`

- [ ] **Step 1: Write failing tests**

Create `tests/emails/test_services.py`:

```python
from decimal import Decimal
import pytest
from unittest.mock import MagicMock, patch, call
from types import SimpleNamespace


class TestApplyCampaignSpecialPrices:
    def _make_campaign(self, products):
        campaign = MagicMock()
        campaign.campaign_products.select_related.return_value.all.return_value = products
        return campaign

    def _make_cp(self, erp_nr, base_price, special_price_override=None, discount_pct=None):
        product = SimpleNamespace(erp_nr=erp_nr)
        cp = MagicMock()
        cp.product = product
        cp.special_price_override = special_price_override
        cp.discount_pct = discount_pct
        return cp, product

    @patch("emails.services.ShopwareSettings")
    @patch("emails.services.Price")
    def test_returns_empty_when_no_default_channel(self, MockPrice, MockSettings):
        from emails.services import apply_campaign_special_prices
        MockSettings.objects.filter.return_value.first.return_value = None
        campaign = MagicMock()
        result = apply_campaign_special_prices(campaign)
        assert result == []

    @patch("emails.services.ShopwareSettings")
    @patch("emails.services.Price")
    def test_skips_products_without_price_override_or_discount(self, MockPrice, MockSettings):
        from emails.services import apply_campaign_special_prices
        default_ch = SimpleNamespace(pk=1, price_factor=Decimal("1.0"), is_active=True)
        MockSettings.objects.filter.return_value.first.return_value = default_ch
        MockSettings.objects.filter.return_value.exclude.return_value = []

        cp = MagicMock()
        cp.special_price_override = None
        cp.discount_pct = None
        campaign = MagicMock()
        campaign.campaign_products.select_related.return_value.all.return_value = [cp]

        result = apply_campaign_special_prices(campaign)
        assert result == []
        MockPrice.objects.filter.assert_not_called()

    def test_round_up_5ct_helper(self):
        from emails.services import _round_up_5ct
        assert _round_up_5ct(Decimal("9.91")) == Decimal("9.95")
        assert _round_up_5ct(Decimal("9.95")) == Decimal("9.95")
        assert _round_up_5ct(Decimal("9.96")) == Decimal("10.00")
        assert _round_up_5ct(Decimal("10.00")) == Decimal("10.00")
        assert _round_up_5ct(Decimal("10.01")) == Decimal("10.05")

    def test_apply_factor_helper(self):
        from emails.services import _apply_channel_factor
        assert _apply_channel_factor(Decimal("10.00"), Decimal("1.1")) == Decimal("11.00")
        assert _apply_channel_factor(Decimal("9.10"), Decimal("1.1")) == Decimal("10.05")
        assert _apply_channel_factor(None, Decimal("1.1")) is None
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
.venv/bin/pytest tests/emails/test_services.py -v
```

Expected: `ImportError` — `emails.services` does not exist.

- [ ] **Step 3: Create `emails/services.py`**

```python
from __future__ import annotations

import calendar
from decimal import Decimal, ROUND_UP

from django.utils import timezone

from products.models import Price
from shopware.models import ShopwareSettings


def _round_up_5ct(value: Decimal) -> Decimal:
    step = Decimal("0.05")
    return (Decimal(value) / step).to_integral_value(rounding=ROUND_UP) * step


def _apply_channel_factor(value: Decimal | None, factor: Decimal) -> Decimal | None:
    if value is None:
        return None
    return _round_up_5ct(Decimal(value) * factor).quantize(Decimal("0.01"))


def _end_of_next_month(now) -> object:
    next_month = (now.month % 12) + 1
    year = now.year + (1 if next_month == 1 else 0)
    last_day = calendar.monthrange(year, next_month)[1]
    return now.replace(year=year, month=next_month, day=last_day, hour=23, minute=59, second=59, microsecond=0)


def apply_campaign_special_prices(campaign) -> list[str]:
    """Writes special_price back to all ProductPrice entries for each campaign product.

    Uses the default sales channel as base; applies price_factor for all other
    active channels. Rounds up to nearest 5 ct at every step.

    Returns list of erp_nrs that were updated (for Celery sync tasks).
    """
    default_channel = ShopwareSettings.objects.filter(is_default=True, is_active=True).first()
    if not default_channel:
        return []

    other_channels = list(
        ShopwareSettings.objects.filter(is_active=True).exclude(pk=default_channel.pk)
    )

    now = timezone.now()
    special_end = _end_of_next_month(now)
    affected_erp_nrs: list[str] = []

    for cp in campaign.campaign_products.select_related("product").all():
        if not cp.special_price_override and not cp.discount_pct:
            continue

        product = cp.product
        default_price = Price.objects.filter(
            product=product, sales_channel=default_channel
        ).first()
        if not default_price:
            continue

        if cp.special_price_override:
            special_price = Decimal(str(cp.special_price_override))
        else:
            base = Decimal(str(default_price.price))
            special_price = _round_up_5ct(
                base * (Decimal("100") - Decimal(str(cp.discount_pct))) / Decimal("100")
            )

        default_price.special_price = special_price
        if not default_price.special_start_date:
            default_price.special_start_date = now
        default_price.special_end_date = special_end
        default_price.save(
            history_tracked_fields=["special_price", "special_start_date", "special_end_date"]
        )

        for channel in other_channels:
            factor_val = channel.price_factor
            factor = Decimal(str(factor_val)) if factor_val else Decimal("1.0")
            channel_price = Price.objects.filter(product=product, sales_channel=channel).first()
            if channel_price:
                channel_price.special_price = _apply_channel_factor(special_price, factor)
                if not channel_price.special_start_date:
                    channel_price.special_start_date = now
                channel_price.special_end_date = special_end
                channel_price.save(
                    history_tracked_fields=["special_price", "special_start_date", "special_end_date"]
                )

        cp.prices_synced_at = now
        cp.save(update_fields=["prices_synced_at"])
        affected_erp_nrs.append(product.erp_nr)

    return affected_erp_nrs
```

- [ ] **Step 4: Run tests**

```bash
.venv/bin/pytest tests/emails/test_services.py -v
```

Expected: all PASSED.

- [ ] **Step 5: Commit**

```bash
git add emails/services.py tests/emails/test_services.py
git commit -m "feat(emails): add apply_campaign_special_prices service with per-channel write-back"
```

---

## Task 7: Celery task for async price sync

**Files:**
- Create: `emails/tasks.py`

- [ ] **Step 1: Create `emails/tasks.py`**

```python
from __future__ import annotations

from celery import shared_task


@shared_task(name="emails.apply_campaign_prices_async")
def apply_campaign_prices_async(campaign_pk: int) -> None:
    from emails.models import EmailCampaign
    from emails.services import apply_campaign_special_prices
    from products.tasks import microtech_update_prices, shopware_sync_products

    try:
        campaign = EmailCampaign.objects.get(pk=campaign_pk)
    except EmailCampaign.DoesNotExist:
        return

    erp_nrs = apply_campaign_special_prices(campaign)
    if erp_nrs:
        microtech_update_prices.delay(erp_nrs)
        shopware_sync_products.delay(erp_nrs)
```

- [ ] **Step 2: Verify app loads**

```bash
.venv/bin/python manage.py check
```

Expected: no issues.

- [ ] **Step 3: Commit**

```bash
git add emails/tasks.py
git commit -m "feat(emails): add Celery task for async campaign price sync"
```

---

## Task 8: Update MJML rendering — head/body split

**Files:**
- Modify: `emails/mjml.py`
- Modify: `emails/templates/emails/newsletter_base.mjml`
- Modify: `tests/emails/test_mjml.py`

- [ ] **Step 1: Write failing test**

Add to `tests/emails/test_mjml.py`:

```python
class TestHeadBodySplit:
    def test_head_components_land_in_head_mjml(self, monkeypatch):
        from types import SimpleNamespace
        from emails.mjml import render_campaign_mjml

        def fake_render_to_string(template_name, context):
            if template_name == "emails/newsletter_base.mjml":
                return f"HEAD:{context['head_mjml']}|BODY:{context['body_mjml']}"
            return ""

        monkeypatch.setattr("emails.mjml.render_to_string", fake_render_to_string)

        head_lib = SimpleNamespace(placement="head", name="CSS", mjml_markup="<mj-style>body{}</mj-style>")
        body_lib = SimpleNamespace(placement="body", name="Logo", mjml_markup="<mj-section/>")

        campaign = SimpleNamespace(
            sales_channels=FakeQuerySet(),
            campaign_products=FakeQuerySet(),
            components=FakeQuerySet([
                SimpleNamespace(library_component=head_lib, title="", subtitle="", body_html="", mjml_markup="", order=5, enabled=True),
                SimpleNamespace(library_component=body_lib, title="", subtitle="", body_html="", mjml_markup="", order=10, enabled=True),
            ]),
        )

        result = render_campaign_mjml(campaign)
        assert "<mj-style>body{}</mj-style>" in result.split("|")[0]
        assert "<mj-section/>" in result.split("|")[1]
```

- [ ] **Step 2: Run test to verify it fails**

```bash
.venv/bin/pytest tests/emails/test_mjml.py::TestHeadBodySplit -v
```

Expected: FAIL — `head_mjml` key not in context.

- [ ] **Step 3: Update `emails/mjml.py`**

Replace `render_campaign_mjml` with this implementation. Remove the `LEGACY_COMPONENT_TEMPLATES` dict and `default_component_markup` function (no longer needed after migration):

```python
def _campaign_components(campaign):
    return list(
        campaign.components.filter(enabled=True)
        .select_related("library_component")
        .order_by("order", "id")
    )


def _render_component_mjml(component, context: dict) -> str:
    markup = component.library_component.mjml_markup if component.library_component_id else ""
    if not markup:
        return ""
    component_context = {**context, "component": component}
    try:
        return Template(markup).render(Context(component_context))
    except Exception:
        return ""


def render_campaign_mjml(campaign) -> str:
    sales_channel_ids = _campaign_sales_channel_ids(campaign)

    products = [
        ProductEmailProxy(cp.product, cp.special_price_override, sales_channel_ids=sales_channel_ids)
        for cp in campaign.campaign_products.select_related("product").order_by("order", "id")
    ]

    base_context = {
        "products": products,
    }

    components = _campaign_components(campaign)

    head_mjml = "\n".join(
        rendered
        for comp in components
        if getattr(getattr(comp, "library_component", None), "placement", "body") == "head"
        for rendered in [_render_component_mjml(comp, base_context)]
        if rendered.strip()
    )
    body_mjml = "\n".join(
        rendered
        for comp in components
        if getattr(getattr(comp, "library_component", None), "placement", "body") == "body"
        for rendered in [_render_component_mjml(comp, base_context)]
        if rendered.strip()
    )

    context = {
        **base_context,
        "head_mjml": head_mjml,
        "body_mjml": body_mjml,
    }
    return render_to_string("emails/newsletter_base.mjml", context)
```

Also remove `_campaign_sales_channel_ids` — replace with a simple default-channel lookup:

```python
def _campaign_sales_channel_ids(campaign) -> tuple[int, ...]:
    from shopware.models import ShopwareSettings
    default = ShopwareSettings.objects.filter(is_default=True, is_active=True).first()
    if default:
        return (default.pk,)
    return ()
```

- [ ] **Step 4: Update `newsletter_base.mjml`**

```mjml
{# emails/templates/emails/newsletter_base.mjml #}
<mjml>
    <mj-head>
        {{ head_mjml|safe }}
    </mj-head>
    <mj-body>
        {{ body_mjml|safe }}
    </mj-body>
</mjml>
```

- [ ] **Step 5: Run tests**

```bash
.venv/bin/pytest tests/emails/test_mjml.py -v
```

Some existing tests reference removed fields (`h1`, `product_template`, `component_key`). They will fail — fix them in the next step.

- [ ] **Step 6: Update broken tests in `tests/emails/test_mjml.py`**

Replace `TestCampaignComponentRendering.test_render_campaign_uses_enabled_component_order`:

```python
class TestCampaignComponentRendering:
    def test_render_campaign_uses_enabled_component_order(self, monkeypatch):
        def fake_render_to_string(template_name, context):
            if template_name == "emails/newsletter_base.mjml":
                return context["body_mjml"]
            return ""

        monkeypatch.setattr("emails.mjml.render_to_string", fake_render_to_string)

        def make_comp(name, markup, order, enabled=True):
            lib = SimpleNamespace(placement="body", name=name, mjml_markup=markup)
            return SimpleNamespace(
                library_component=lib,
                title="", body_html="",
                mjml_markup="",
                order=order,
                enabled=enabled,
            )

        campaign = SimpleNamespace(
            sales_channels=FakeQuerySet(),
            campaign_products=FakeQuerySet(),
            components=FakeQuerySet([
                make_comp("Content", "content_text", order=20),
                make_comp("Logo", "logo", order=10, enabled=False),
                make_comp("Header", "header_nav", order=5),
            ]),
        )

        mjml = render_campaign_mjml(campaign)
        assert mjml == "header_nav\ncontent_text"
```

Replace `TestRenderCampaignMjml` (uses DB — needs real MjmlComponent now):

```python
@pytest.mark.django_db
class TestRenderCampaignMjml:
    def test_renders_without_products(self):
        from emails.models import EmailCampaign, EmailCampaignComponent, MjmlComponent
        lib = MjmlComponent.objects.create(
            name="Titel",
            placement="body",
            mjml_markup="<mj-section><mj-column><mj-text>{{ component.title }}</mj-text></mj-column></mj-section>",
        )
        campaign = EmailCampaign.objects.create(internal_title="Test", status="draft")
        EmailCampaignComponent.objects.create(
            campaign=campaign,
            library_component=lib,
            title="Testtitel",
            order=10,
            enabled=True,
        )
        mjml = render_campaign_mjml(campaign)
        assert "<mjml>" in mjml
        assert "Testtitel" in mjml

    def test_head_component_lands_in_mj_head(self):
        from emails.models import EmailCampaign, EmailCampaignComponent, MjmlComponent
        lib = MjmlComponent.objects.create(
            name="CSS",
            placement="head",
            mjml_markup="<mj-style>.custom{}</mj-style>",
        )
        campaign = EmailCampaign.objects.create(internal_title="HeadTest", status="draft")
        EmailCampaignComponent.objects.create(
            campaign=campaign,
            library_component=lib,
            order=5,
            enabled=True,
        )
        mjml = render_campaign_mjml(campaign)
        assert "<mj-head>" in mjml
        assert ".custom{}" in mjml
```

Remove `test_product_template_selection_shipping_free` (product_template is gone).

- [ ] **Step 7: Run full test suite**

```bash
.venv/bin/pytest tests/emails/ -v
```

Expected: all PASSED.

- [ ] **Step 8: Commit**

```bash
git add emails/mjml.py emails/templates/emails/newsletter_base.mjml tests/emails/test_mjml.py
git commit -m "feat(emails): split MJML rendering into head/body by component placement"
```

---

## Task 9: Update Django admin

**Files:**
- Modify: `emails/admin.py`
- Modify: `tests/emails/test_admin.py`

- [ ] **Step 1: Update `emails/admin.py`**

Full replacement — key changes only described here. Write the complete file:

```python
# emails/admin.py
from __future__ import annotations

import logging

from django import forms
from django.contrib import admin
from django.contrib.admin.widgets import AdminTextareaWidget
from django.http import HttpResponse, JsonResponse
from django.urls import path
from django.utils.translation import gettext_lazy as _

logger = logging.getLogger(__name__)

from core.admin import BaseAdmin, BaseStackedInline, BaseTabularInline
from emails.mjml import compile_mjml_to_html, render_campaign_mjml
from emails.models import EmailCampaign, EmailCampaignComponent, EmailCampaignProduct, MjmlComponent


class MjmlComponentForm(forms.ModelForm):
    class Meta:
        model = MjmlComponent
        fields = "__all__"
        widgets = {
            "mjml_markup": AdminTextareaWidget(
                attrs={
                    "rows": 16,
                    "style": "font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;",
                }
            ),
        }


@admin.register(MjmlComponent)
class MjmlComponentAdmin(BaseAdmin):
    form = MjmlComponentForm
    list_display = ("name", "placement", "is_default", "order")
    list_filter = ("placement", "is_default")
    list_editable = ("is_default", "order")
    search_fields = ("name",)
    ordering = ("order", "name")

    fieldsets = (
        (
            _("Komponente"),
            {"fields": ("name", "description", "placement", "is_default", "order")},
        ),
        (
            _("MJML Markup"),
            {"fields": ("mjml_markup",)},
        ),
        (
            _("System"),
            {"fields": BaseAdmin.readonly_fields, "classes": ("collapse",)},
        ),
    )


class EmailCampaignComponentInline(BaseStackedInline):
    model = EmailCampaignComponent
    fields = ("order", "enabled", "library_component", "title", "subtitle", "body_html")
    autocomplete_fields = ("library_component",)
    extra = 0
    ordering = ("order", "id")
    collapsible = True
    sortable = True
    sortable_field_name = "order"


class EmailCampaignProductInline(BaseTabularInline):
    model = EmailCampaignProduct
    fields = ("order", "product", "special_price_override", "discount_pct", "current_price_display", "prices_synced_at")
    readonly_fields = BaseTabularInline.readonly_fields + ("current_price_display", "prices_synced_at")
    autocomplete_fields = ("product",)
    extra = 0
    sortable = True
    sortable_field_name = "order"

    @admin.display(description=_("Aktueller Preis"))
    def current_price_display(self, obj: EmailCampaignProduct):
        if obj.product_id is None:
            return "—"
        try:
            price = obj.product.price
            return f"{price:,.2f} €".replace(",", "X").replace(".", ",").replace("X", ".")
        except Exception:
            return "—"


@admin.register(EmailCampaign)
class EmailCampaignAdmin(BaseAdmin):
    list_display = ("internal_title", "component_count", "product_count", "status", "created_at")
    list_filter = ("status", "created_at")
    search_fields = ("internal_title",)
    list_editable = ("status",)
    inlines = (EmailCampaignComponentInline, EmailCampaignProductInline)

    fieldsets = (
        (
            _("Kampagne"),
            {"fields": ("internal_title", "status")},
        ),
        (
            _("System"),
            {"fields": BaseAdmin.readonly_fields, "classes": ("collapse",)},
        ),
    )

    @admin.display(description=_("Produkte"))
    def product_count(self, obj: EmailCampaign) -> int:
        return obj.campaign_products.count()

    @admin.display(description=_("Komponenten"))
    def component_count(self, obj: EmailCampaign) -> int:
        return obj.components.count()

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        if not change:
            self._ensure_default_components(obj)

    def save_related(self, request, form, formsets, change):
        super().save_related(request, form, formsets, change)
        from emails.tasks import apply_campaign_prices_async
        apply_campaign_prices_async.delay(form.instance.pk)

    def _ensure_default_components(self, campaign: EmailCampaign) -> None:
        if campaign.components.exists():
            return
        defaults = MjmlComponent.objects.filter(is_default=True).order_by("order")
        EmailCampaignComponent.objects.bulk_create([
            EmailCampaignComponent(
                campaign=campaign,
                library_component=lib,
                title=lib.name,
                order=(i + 1) * 10,
                enabled=True,
            )
            for i, lib in enumerate(defaults)
        ])

    def get_urls(self):
        urls = super().get_urls()
        custom = [
            path(
                "<int:campaign_id>/export-html/",
                self.admin_site.admin_view(self.export_html_view),
                name="emails_emailcampaign_export_html",
            ),
        ]
        return custom + urls

    def export_html_view(self, request, campaign_id: int):
        try:
            campaign = EmailCampaign.objects.get(pk=campaign_id)
        except EmailCampaign.DoesNotExist:
            return JsonResponse({"error": "Kampagne nicht gefunden."}, status=404)

        try:
            mjml = render_campaign_mjml(campaign)
            html = compile_mjml_to_html(mjml)
        except Exception:
            logger.exception("MJML export failed for campaign %s", campaign_id)
            return JsonResponse({"error": "Fehler beim Rendern der Kampagne."}, status=500)

        if request.GET.get("download"):
            response = HttpResponse(html, content_type="text/html; charset=utf-8")
            safe_title = campaign.internal_title[:40].replace(" ", "_")
            filename = f"email_{campaign.pk}_{safe_title}.html"
            response["Content-Disposition"] = f'attachment; filename="{filename}"'
            return response

        return JsonResponse({"html": html, "mjml": mjml})
```

- [ ] **Step 2: Update `tests/emails/test_admin.py`**

Replace the file with:

```python
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from django.test import SimpleTestCase


class TestMjmlComponentAdminRegistered(SimpleTestCase):
    def test_mjml_component_admin_is_registered(self):
        from django.contrib import admin
        from emails.models import MjmlComponent
        assert admin.site.is_registered(MjmlComponent)


@pytest.mark.django_db
class TestEmailCampaignAdminDefaultComponents:
    def test_default_components_created_on_new_campaign(self):
        from emails.models import EmailCampaign, EmailCampaignComponent, MjmlComponent
        MjmlComponent.objects.create(name="Logo", placement="body", is_default=True, order=10)
        MjmlComponent.objects.create(name="Footer", placement="body", is_default=True, order=20)

        from emails.admin import EmailCampaignAdmin
        from django.contrib.admin.sites import AdminSite
        admin_instance = EmailCampaignAdmin(EmailCampaign, AdminSite())

        campaign = EmailCampaign.objects.create(internal_title="Test", status="draft")
        admin_instance._ensure_default_components(campaign)

        assert EmailCampaignComponent.objects.filter(campaign=campaign).count() == 2
        names = list(
            EmailCampaignComponent.objects.filter(campaign=campaign)
            .select_related("library_component")
            .values_list("library_component__name", flat=True)
            .order_by("order")
        )
        assert names == ["Logo", "Footer"]

    def test_default_components_not_duplicated_on_second_call(self):
        from emails.models import EmailCampaign, EmailCampaignComponent, MjmlComponent
        MjmlComponent.objects.create(name="Logo", placement="body", is_default=True, order=10)

        from emails.admin import EmailCampaignAdmin
        from django.contrib.admin.sites import AdminSite
        admin_instance = EmailCampaignAdmin(EmailCampaign, AdminSite())

        campaign = EmailCampaign.objects.create(internal_title="Test2", status="draft")
        admin_instance._ensure_default_components(campaign)
        admin_instance._ensure_default_components(campaign)

        assert EmailCampaignComponent.objects.filter(campaign=campaign).count() == 1
```

- [ ] **Step 3: Run tests**

```bash
.venv/bin/pytest tests/emails/ -v
```

Expected: all PASSED.

- [ ] **Step 4: Check system**

```bash
.venv/bin/python manage.py check
```

- [ ] **Step 5: Commit**

```bash
git add emails/admin.py tests/emails/test_admin.py
git commit -m "feat(emails): MjmlComponentAdmin, sortable inlines, auto price sync on save"
```

---

## Task 10: Full test run and cleanup

- [ ] **Step 1: Run full test suite**

```bash
.venv/bin/pytest tests/ -v --tb=short 2>&1 | tail -40
```

- [ ] **Step 2: Fix any remaining failures**

Common failures to expect:
- Any test that imported `EmailCampaignSalesChannel` → remove import
- Any test using `campaign.h1` or `campaign.product_template` → update accordingly
- Any test using `component.component_key` → update to `component.library_component.name`

- [ ] **Step 3: Final system check**

```bash
.venv/bin/python manage.py check --deploy 2>&1 | grep -v "WARNINGS:"
```

- [ ] **Step 4: Final commit**

```bash
git add -p
git commit -m "test(emails): update test suite for MJML component library refactor"
```
