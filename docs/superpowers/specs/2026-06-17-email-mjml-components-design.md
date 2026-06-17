# Email App: MJML Component Library & Campaign Overhaul

**Date:** 2026-06-17  
**Status:** Approved

---

## Overview

Refactor the email campaign system to use a managed MJML component library. Campaigns reference library components directly. Product special prices are written back to the database and synced to Microtech and Shopware on campaign save.

---

## 1. Models

### New: `MjmlComponent` (library)

| Field | Type | Notes |
|---|---|---|
| `name` | CharField(255) | Displayed as collapsed inline title |
| `description` | TextField | Optional, internal |
| `mjml_markup` | TextField | The MJML template; Django template variables allowed |
| `placement` | CharField choices: `head` / `body` | Determines `<mj-head>` vs `<mj-body>` |
| `is_default` | BooleanField | Auto-added to new campaigns |
| `order` | PositiveIntegerField | Default order when added to campaigns |

### Changed: `EmailCampaign`

**Removed fields:** `h1`, `h1_small`, `intro_text`, `product_template`  
These move into library components (e.g. a "Title & Intro" body component with `title`/`subtitle`/`body_html` data fields).

### Changed: `EmailCampaignComponent`

**Removed:** `component_key` (enum), `mjml_markup`  
**Added:** `library_component` FK → `MjmlComponent` (on_delete=PROTECT)  
**Kept:** `title`, `subtitle`, `body_html` (content data for text-bearing components), `order`, `enabled`

`__str__` returns: `"{order} – {library_component.name} ({placement})"` — visible in collapsed Unfold inline.

### Changed: `EmailCampaignProduct`

**Added:** `discount_pct` (DecimalField max_digits=5 decimal_places=2, null/blank) — percentage discount alternative to `special_price_override`  
**Added:** `prices_synced_at` (DateTimeField, null/blank, readonly) — timestamp of last write-back  
**Constraint:** Only one of `special_price_override` or `discount_pct` may be set (clean validation).

### Removed: `EmailCampaignSalesChannel`

Always use default sales channel (`ShopwareSettings.objects.get(is_default=True)`).

---

## 2. Admin

### `MjmlComponentAdmin` (standalone)

- `list_display`: name, placement, is_default, order
- `list_editable`: is_default, order
- `mjml_markup` rendered as monospace textarea

### `EmailCampaignAdmin`

**Inlines:**

**Components inline** (Unfold `BaseStackedInline`, sortable):
- `sortable = True`, `sortable_field_name = "order"`
- Fields: `library_component` (autocomplete), `title`, `subtitle`, `body_html`, `enabled`
- Collapsible; collapsed title shows `__str__` = `"10 – Logo (Body)"`

**Products inline** (Unfold `BaseTabularInline`, sortable):
- `sortable = True`, `sortable_field_name = "order"`
- Fields: `product` (autocomplete), `order`, `special_price_override`, `discount_pct`
- Readonly: `current_price_display`, `computed_special_price_display`, `prices_synced_at`

**No sales channel inline.**

### Automatic Price Write-Back on Save

`EmailCampaignAdmin.save_related()` calls `apply_campaign_special_prices(campaign)` after inlines are saved.  
Runs async via Celery to avoid blocking the save.

---

## 3. Price Write-Back Service (`emails/services.py`)

```
apply_campaign_special_prices(campaign: EmailCampaign) -> list[str]
```

For each `EmailCampaignProduct` where `special_price_override` or `discount_pct` is set:

1. Get default channel: `ShopwareSettings.objects.get(is_default=True)`
2. Get product's `Price` entry for default channel
3. Compute `special_price`:
   - If `special_price_override`: use directly (already absolute)
   - If `discount_pct`: `Price._round_up_5ct(base_price * (100 - pct) / 100)`
4. Save to default channel `Price` entry: set `special_price`, `special_start_date=now`, `special_end_date=end_of_next_month`
5. For each other active channel:
   - `other_special = _apply_factor(special_price, channel.price_factor)` (reuse from `products/signals.py`)
   - `Price.objects.update_or_create(product=..., sales_channel=channel, defaults={special_price: ..., dates: ...})`
6. Collect `erp_nr` of all affected products
7. Fire: `microtech_update_prices.delay(erp_nrs)` + `shopware_sync_products.delay(erp_nrs)`
8. Update `EmailCampaignProduct.prices_synced_at = now` for each synced row

**Rounding:** `Price._round_up_5ct()` always rounds **up** to nearest 5ct. `_apply_factor` in `products/signals.py` already applies this. Both are reused, not duplicated.

Only products where price fields actually changed trigger a sync (compare to existing DB value before writing).

---

## 4. MJML Rendering

`render_campaign_mjml(campaign)` is refactored:

```python
head_components = enabled_components.filter(library_component__placement="head").order_by("order")
body_components = enabled_components.filter(library_component__placement="body").order_by("order")
```

`newsletter_base.mjml`:
```mjml
<mjml>
  <mj-head>{{ head_mjml|safe }}</mj-head>
  <mj-body>{{ body_mjml|safe }}</mj-body>
</mjml>
```

Each component's `library_component.mjml_markup` is rendered as a Django template with context:
`component` (the `EmailCampaignComponent` instance, so `title`, `subtitle`, `body_html` are accessible), plus `products`, campaign fields, etc.

Components are sorted by `order` globally. Placement only determines which MJML section they land in — not their relative order within their section.

---

## 5. Default Components on New Campaign

When a new `EmailCampaign` is created, all `MjmlComponent` with `is_default=True` are added as `EmailCampaignComponent` instances, ordered by `MjmlComponent.order`.

---

## 6. Migrations

1. Add `MjmlComponent`
2. Add `library_component` FK to `EmailCampaignComponent`, drop `component_key` + `mjml_markup`
3. Add `discount_pct` + `prices_synced_at` to `EmailCampaignProduct`
4. Drop `EmailCampaignSalesChannel`
5. Drop `h1`, `h1_small`, `intro_text`, `product_template` from `EmailCampaign`

Data migration: create `MjmlComponent` library entries from legacy template files; migrate existing `EmailCampaignComponent` rows to reference them.

---

## 7. Out of Scope

- No per-campaign MJML override (Option B confirmed: library is authoritative)
- No manual "Sync Prices" button (auto on save)
- No separate CSS model (CSS = head-placement component)
