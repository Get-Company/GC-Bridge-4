# Email Builder v2 — Design Spec

**Date:** 2026-06-18
**Status:** Approved

## Context

The existing `emails` app requires users to enter raw JSON to supply template variables to MJML components. This is error-prone and not viable for non-technical users. Additionally, there is no visual overview of which variables a component expects.

This spec describes a new `emails_v2` Django app: a drag-and-drop MJML email editor with auto-parsed variable fields. It runs in parallel to the existing `emails` app (greenfield, no migration).

## Architecture

**Tech stack:** Django + HTMX + Alpine.js + SortableJS

**New app:** `emails_v2/`

```
emails_v2/
├── models.py
├── views.py
├── urls.py              # mounted at /email-builder/
├── catalog.py           # static MJML tag definitions
├── variable_parser.py   # Jinja2 AST variable extraction
├── mjml.py              # rendering (reuses ProductEmailProxy from emails/)
└── templates/email_builder/
    ├── editor.html          # 3-panel shell
    ├── _sidebar.html
    ├── _canvas.html
    └── _variable_panel.html # HTMX partial
```

**Auth:** `@staff_member_required` on all views — no custom auth.

**URLs:**
```
/email-builder/                               # campaign list
/email-builder/campaign/<id>/                 # editor
/email-builder/htmx/block/create/            # POST: add block
/email-builder/htmx/block/<id>/order/        # PATCH: reorder
/email-builder/htmx/block/<id>/vars/         # GET: variable panel
/email-builder/htmx/campaign/<id>/preview/   # POST: render preview
```

## Data Models

```python
class EmailBuilderCampaign(models.Model):
    internal_title = CharField()
    status         = CharField(choices=["draft", "ready", "exported"])
    created_at     = DateTimeField(auto_now_add=True)

class EmailBlock(models.Model):
    campaign   = ForeignKey(EmailBuilderCampaign, CASCADE)
    parent     = ForeignKey('self', null=True, blank=True, CASCADE)
    tag        = CharField()                        # "mj-section", "mj-text", ...
    component  = ForeignKey(MjmlComponent, null=True, blank=True, PROTECT)
    attributes = JSONField(default=dict)            # padding, color, width, etc.
    variables  = JSONField(default=dict)            # Jinja2 variable values
    order      = PositiveIntegerField(default=0)
```

`MjmlComponent` (from `emails` app) gains two new fields:
```python
detected_variables = JSONField(default=list)   # auto-populated on save
variable_labels    = JSONField(default=dict)   # optional human-readable labels
```

## MJML Tag Catalog

`emails_v2/catalog.py` defines all standard MJML tags as a static Python dataclass list. The sidebar renders from this — no runtime fetching.

Categories and tags:

| Category | Tags |
|---|---|
| Layout | `mj-section`, `mj-column`, `mj-wrapper`, `mj-group` |
| Content | `mj-text`, `mj-image`, `mj-button`, `mj-divider`, `mj-spacer`, `mj-table`, `mj-raw` |
| Advanced | `mj-hero`, `mj-navbar`, `mj-social`, `mj-carousel`, `mj-accordion` |

Each tag entry includes: `name`, `category`, `icon`, `description`, `default_attributes`.

Custom components (from `MjmlComponent` DB table) appear in a separate sidebar tab.

## Variable Auto-Parse

When a `MjmlComponent` is saved, its MJML markup is parsed with Jinja2's AST:

```python
# emails_v2/variable_parser.py
from jinja2 import Environment, meta

def extract_variables(mjml_markup: str) -> list[str]:
    env = Environment()
    ast = env.parse(mjml_markup)
    return sorted(meta.find_undeclared_variables(ast))
```

Detected variable names are stored in `MjmlComponent.detected_variables`.

**Field type inference** (from variable name):

| Name pattern | Rendered as |
|---|---|
| `_html`, `description`, `body` | Textarea (WYSIWYG) |
| `price`, `discount`, `amount` | Number input |
| `url`, `href`, `link` | URL input |
| anything else | Text input |

**On template change:** New variables appear as empty fields. Removed variables leave orphaned JSON keys that are silently ignored during rendering. No migration required.

## UI Layout

```
┌──────────────┬─────────────────────────────┬───────────────┐
│   Sidebar    │          Canvas             │  Right Panel  │
│              │                             │               │
│ [Standard]   │ ┌─────────────────────────┐ │ Selected:     │
│ [Eigene]     │ │ mj-section          ≡   │ │ mj-text       │
│              │ │ ┌────────┐ ┌────────┐   │ │               │
│ mj-section   │ │ │col 33% │ │col 67% │   │ │ title         │
│ mj-text      │ │ │[mj-img]│ │[mj-txt]│   │ │ [____________]│
│ mj-image     │ │ └────────┘ └────────┘   │ │               │
│ mj-button    │ └─────────────────────────┘ │ description   │
│ ...          │                             │ [____________]│
│              │ ┌─ Drop here ─────────────┐ │               │
│ [Eigene]     │ └─────────────────────────┘ │ [Attribute]   │
│ Produkt-Box  │                             │ padding: 10px │
│ Slider       │   [Preview]                 │               │
└──────────────┴─────────────────────────────┴───────────────┘
```

**Sidebar:** Two tabs — Standard MJML tags + custom `MjmlComponent` entries. Drag source via HTML5 drag API.

**Canvas:**
- Sections sortable via SortableJS
- Columns within a section: variable count (add/remove), width adjustable via right panel
- Content within columns: sortable via SortableJS
- Drop zones highlight on `dragover` (Alpine.js)
- Blocks added/reordered via HTMX (server re-renders canvas fragment)

**Right Panel:** Loaded via HTMX on block click. Shows:
- Auto-generated variable fields (from `detected_variables`)
- MJML attribute overrides (padding, color, width, etc.)
- For `mj-column`: width input + column count controls

## Preview Flow

1. User clicks "Preview" → HTMX POST to preview endpoint
2. Server: loads all `EmailBlock` tree for campaign
3. Recursively builds MJML string (section → columns → content)
4. Renders Jinja2 with product context (reuses `ProductEmailProxy` from `emails/mjml.py`)
5. Compiles via `mjml` CLI → HTML

**Two modes:**
- **Live preview:** Small iframe in canvas, debounced 800ms after any change
- **Full preview:** New tab, Desktop/Mobile toggle

## Reused Code

- `emails.mjml.ProductEmailProxy` — product context wrapper, imported directly
- `emails.mjml.compile_mjml_to_html` — MJML CLI wrapper, imported directly
- `emails.models.MjmlComponent` — extended with `detected_variables` field

## Verification

1. Create a new campaign in `/email-builder/`
2. Drag `mj-section` onto canvas → section block appears
3. Drag `mj-column` into section → column appears
4. Drag `mj-text` into column → text block appears, right panel shows `content` textarea
5. Add a custom component with `{{ title }}` and `{{ description }}` in markup → right panel shows two fields
6. Change component markup to add `{{ price }}` → right panel shows three fields without data loss
7. Click Preview → iframe renders email HTML
