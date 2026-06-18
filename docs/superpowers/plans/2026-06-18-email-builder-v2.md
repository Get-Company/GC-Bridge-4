# Email Builder v2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a drag-and-drop MJML email editor as a new Django app `emails_v2`, mounted at `/email-builder/`, with auto-parsed variable fields so users never touch raw JSON.

**Architecture:** Greenfield Django app parallel to existing `emails` app. Django views + HTMX for server interactions + Alpine.js for UI state + SortableJS for drag/drop reordering. MJML blocks stored as a flat tree in the DB; rendered recursively to MJML string then compiled via existing `compile_mjml_to_html`.

**Tech Stack:** Django 4+, HTMX 1.9, Alpine.js 3, SortableJS 1.15, Tailwind CSS (CDN), pytest-django

## Global Constraints

- Use `BaseModel` from `core.models` for new models (adds `created_at`, `updated_at`)
- All views require `@staff_member_required` (from `django.contrib.admin.views.decorators`)
- Templates go in `emails_v2/templates/email_builder/`
- Reuse `compile_mjml_to_html` and `ProductEmailProxy` from `emails.mjml` — do not duplicate
- New fields on `MjmlComponent` go in an `emails` app migration (not emails_v2)
- Use `pytest-django` and `@pytest.mark.django_db` for all DB tests
- No JS build step — all JS/CSS from CDN

---

### Task 1: App scaffold + models + migrations

**Files:**
- Create: `emails_v2/__init__.py`
- Create: `emails_v2/apps.py`
- Create: `emails_v2/models.py`
- Create: `emails_v2/migrations/0001_initial.py` (auto-generated)
- Create: `emails/migrations/0XXX_mjmlcomponent_detected_variables.py` (auto-generated)
- Modify: `GC_Bridge_4/settings.py` — add app to INSTALLED_APPS
- Modify: `GC_Bridge_4/urls.py` — include emails_v2 urls

**Interfaces:**
- Produces: `EmailBuilderCampaign`, `EmailBlock` models; `MjmlComponent.detected_variables`, `MjmlComponent.variable_labels` fields

- [ ] **Step 1: Write the failing test**

```python
# tests/emails_v2/test_models.py
import pytest
from emails_v2.models import EmailBuilderCampaign, EmailBlock

@pytest.mark.django_db
def test_campaign_creation():
    c = EmailBuilderCampaign.objects.create(internal_title="Test")
    assert c.status == "draft"
    assert c.created_at is not None

@pytest.mark.django_db
def test_block_tree():
    c = EmailBuilderCampaign.objects.create(internal_title="Test")
    section = EmailBlock.objects.create(campaign=c, tag="mj-section", order=0)
    col = EmailBlock.objects.create(campaign=c, tag="mj-column", parent=section, order=0)
    assert col.parent_id == section.id
    assert list(section.children.all()) == [col]

@pytest.mark.django_db
def test_mjml_component_has_detected_variables(db):
    from emails.models import MjmlComponent
    comp = MjmlComponent.objects.create(name="Test", mjml_markup="<mj-text>{{ title }}</mj-text>")
    assert hasattr(comp, "detected_variables")
    assert hasattr(comp, "variable_labels")
```

- [ ] **Step 2: Run tests — expect ImportError/AttributeError**

```bash
cd /mnt/daten1tb/python/GC-Bridge-4
python -m pytest tests/emails_v2/test_models.py -v 2>&1 | head -20
```

- [ ] **Step 3: Create app files**

```python
# emails_v2/__init__.py
# (empty)
```

```python
# emails_v2/apps.py
from django.apps import AppConfig

class EmailsV2Config(AppConfig):
    name = "emails_v2"
    verbose_name = "Email Builder v2"

    def ready(self):
        import emails_v2.signals  # noqa
```

```python
# emails_v2/signals.py
# (placeholder — filled in Task 2)
```

```python
# emails_v2/models.py
from django.db import models
from core.models import BaseModel


class EmailBuilderCampaign(BaseModel):
    class Status(models.TextChoices):
        DRAFT = "draft", "Entwurf"
        READY = "ready", "Bereit"
        EXPORTED = "exported", "Exportiert"

    internal_title = models.CharField(max_length=255, verbose_name="Interner Titel")
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.DRAFT, db_index=True
    )

    class Meta:
        ordering = ("-created_at",)
        verbose_name = "Email Kampagne (v2)"

    def __str__(self):
        return self.internal_title


class EmailBlock(BaseModel):
    campaign = models.ForeignKey(
        EmailBuilderCampaign, on_delete=models.CASCADE, related_name="blocks"
    )
    parent = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.CASCADE, related_name="children"
    )
    tag = models.CharField(max_length=50)
    component = models.ForeignKey(
        "emails.MjmlComponent", null=True, blank=True, on_delete=models.PROTECT
    )
    attributes = models.JSONField(default=dict)
    variables = models.JSONField(default=dict)
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ("order", "id")

    def __str__(self):
        return f"{self.tag} (campaign={self.campaign_id})"
```

- [ ] **Step 4: Add `detected_variables` + `variable_labels` to `MjmlComponent`**

```python
# emails/models.py — add two fields to MjmlComponent after the `order` field:
    detected_variables = models.JSONField(
        default=list, blank=True, verbose_name="Erkannte Variablen"
    )
    variable_labels = models.JSONField(
        default=dict, blank=True, verbose_name="Variablen-Labels"
    )
```

- [ ] **Step 5: Register app + wire URLs**

In `GC_Bridge_4/settings.py`, add after `'emails.apps.EmailsConfig'`:
```python
    'emails_v2.apps.EmailsV2Config',
```

In `GC_Bridge_4/urls.py`, add import and path:
```python
from django.urls import path, include

urlpatterns = [
    path('', TemplateView.as_view(template_name='landing.html'), name='home'),
    path("docs/html/", RedirectView.as_view(url="/docs/html/index.html", permanent=False), name="docs-index"),
    path(
        "docs/html/<path:path>",
        static_serve,
        {"document_root": BASE_DIR / "docs" / "build" / "html"},
        name="docs-html",
    ),
    path('admin/', admin.site.urls),
    path('email-builder/', include('emails_v2.urls', namespace='email_builder')),
]
```

- [ ] **Step 6: Generate and apply migrations**

```bash
python manage.py makemigrations emails_v2
python manage.py makemigrations emails --name mjmlcomponent_detected_variables
python manage.py migrate
```

- [ ] **Step 7: Run tests — expect PASS**

```bash
python -m pytest tests/emails_v2/test_models.py -v
```
Expected: 3 passed

- [ ] **Step 8: Commit**

```bash
git add emails_v2/ emails/models.py emails/migrations/ GC_Bridge_4/settings.py GC_Bridge_4/urls.py
git commit -m "feat: scaffold emails_v2 app with EmailBuilderCampaign and EmailBlock models"
```

---

### Task 2: Variable parser + auto-update signal

**Files:**
- Create: `emails_v2/variable_parser.py`
- Modify: `emails_v2/signals.py` — wire `post_save` on `MjmlComponent`
- Create: `tests/emails_v2/test_variable_parser.py`

**Interfaces:**
- Consumes: `emails.models.MjmlComponent.mjml_markup`, `.detected_variables`
- Produces: `extract_variables(mjml_markup: str) -> list[str]`, `infer_field_type(name: str) -> str`

- [ ] **Step 1: Write failing tests**

```python
# tests/emails_v2/test_variable_parser.py
import pytest
from emails_v2.variable_parser import extract_variables, infer_field_type


def test_extract_single_variable():
    assert extract_variables("<mj-text>{{ title }}</mj-text>") == ["title"]


def test_extract_multiple_variables():
    assert extract_variables("{{ description }} {{ price }}") == ["description", "price"]


def test_extract_variable_in_if_block():
    assert extract_variables("{% if show %}{{ label }}{% endif %}") == ["label", "show"]


def test_extract_empty():
    assert extract_variables("no variables here") == []


def test_extract_empty_string():
    assert extract_variables("") == []


def test_infer_textarea():
    assert infer_field_type("description_html") == "textarea"
    assert infer_field_type("body") == "textarea"
    assert infer_field_type("intro_text") == "textarea"


def test_infer_number():
    assert infer_field_type("price") == "number"
    assert infer_field_type("discount_amount") == "number"


def test_infer_url():
    assert infer_field_type("link_url") == "url"
    assert infer_field_type("product_href") == "url"


def test_infer_text_fallback():
    assert infer_field_type("title") == "text"
    assert infer_field_type("subtitle") == "text"


@pytest.mark.django_db
def test_signal_updates_detected_variables():
    from emails.models import MjmlComponent
    comp = MjmlComponent.objects.create(
        name="Sig Test",
        mjml_markup="<mj-text>{{ headline }}</mj-text>",
    )
    comp.refresh_from_db()
    assert comp.detected_variables == ["headline"]


@pytest.mark.django_db
def test_signal_updates_on_markup_change():
    from emails.models import MjmlComponent
    comp = MjmlComponent.objects.create(name="Change Test", mjml_markup="{{ old_var }}")
    comp.mjml_markup = "{{ new_var }}"
    comp.save()
    comp.refresh_from_db()
    assert comp.detected_variables == ["new_var"]
```

- [ ] **Step 2: Run — expect ImportError**

```bash
python -m pytest tests/emails_v2/test_variable_parser.py -v 2>&1 | head -20
```

- [ ] **Step 3: Implement variable_parser.py**

```python
# emails_v2/variable_parser.py
from jinja2 import Environment, meta

_HTML_PATTERNS = ("_html", "description", "body", "text", "content", "intro")
_NUMBER_PATTERNS = ("price", "discount", "amount", "qty", "quantity", "count")
_URL_PATTERNS = ("url", "href", "link", "src")


def extract_variables(mjml_markup: str) -> list[str]:
    if not mjml_markup:
        return []
    env = Environment()
    ast = env.parse(mjml_markup)
    return sorted(meta.find_undeclared_variables(ast))


def infer_field_type(name: str) -> str:
    lower = name.lower()
    if any(p in lower for p in _HTML_PATTERNS):
        return "textarea"
    if any(p in lower for p in _NUMBER_PATTERNS):
        return "number"
    if any(p in lower for p in _URL_PATTERNS):
        return "url"
    return "text"
```

- [ ] **Step 4: Implement signal**

```python
# emails_v2/signals.py
from django.db.models.signals import post_save
from django.dispatch import receiver


@receiver(post_save, sender="emails.MjmlComponent")
def update_detected_variables(sender, instance, **kwargs):
    from emails_v2.variable_parser import extract_variables
    new_vars = extract_variables(instance.mjml_markup)
    if new_vars != instance.detected_variables:
        sender.objects.filter(pk=instance.pk).update(detected_variables=new_vars)
```

- [ ] **Step 5: Run — expect all PASS**

```bash
python -m pytest tests/emails_v2/test_variable_parser.py -v
```
Expected: 10 passed

- [ ] **Step 6: Commit**

```bash
git add emails_v2/variable_parser.py emails_v2/signals.py emails_v2/apps.py
git commit -m "feat: add Jinja2 variable auto-parser and MjmlComponent post_save signal"
```

---

### Task 3: MJML tag catalog

**Files:**
- Create: `emails_v2/catalog.py`
- Create: `tests/emails_v2/test_catalog.py`

**Interfaces:**
- Produces: `MJML_TAGS: list[MjmlTag]`, `MJML_TAG_MAP: dict[str, MjmlTag]`
- Each `MjmlTag` has: `.name`, `.category`, `.icon`, `.description`, `.default_attributes`, `.droppable_in`

- [ ] **Step 1: Write failing tests**

```python
# tests/emails_v2/test_catalog.py
from emails_v2.catalog import MJML_TAGS, MJML_TAG_MAP, MjmlTag


def test_all_layout_tags_present():
    names = [t.name for t in MJML_TAGS]
    for tag in ["mj-section", "mj-column", "mj-wrapper", "mj-group"]:
        assert tag in names, f"{tag} missing from catalog"


def test_all_content_tags_present():
    names = [t.name for t in MJML_TAGS]
    for tag in ["mj-text", "mj-image", "mj-button", "mj-divider", "mj-spacer", "mj-table", "mj-raw"]:
        assert tag in names


def test_all_advanced_tags_present():
    names = [t.name for t in MJML_TAGS]
    for tag in ["mj-hero", "mj-navbar", "mj-social", "mj-carousel", "mj-accordion"]:
        assert tag in names


def test_tag_has_required_fields():
    for tag in MJML_TAGS:
        assert tag.name, f"tag missing name"
        assert tag.category in ("layout", "content", "advanced"), f"{tag.name} bad category"
        assert tag.icon, f"{tag.name} missing icon"
        assert isinstance(tag.default_attributes, dict)
        assert isinstance(tag.droppable_in, list)


def test_tag_map_lookup():
    assert MJML_TAG_MAP["mj-text"].category == "content"
    assert MJML_TAG_MAP["mj-section"].category == "layout"
```

- [ ] **Step 2: Run — expect ImportError**

```bash
python -m pytest tests/emails_v2/test_catalog.py -v 2>&1 | head -10
```

- [ ] **Step 3: Implement catalog.py**

```python
# emails_v2/catalog.py
from dataclasses import dataclass, field


@dataclass
class MjmlTag:
    name: str
    category: str
    icon: str
    description: str
    default_attributes: dict = field(default_factory=dict)
    droppable_in: list = field(default_factory=list)


MJML_TAGS = [
    # Layout
    MjmlTag("mj-section",   "layout",   "rows",          "Container-Zeile",             {"padding": "10px 0"},                  ["body"]),
    MjmlTag("mj-column",    "layout",   "columns",        "Spalte innerhalb einer Section", {"padding": "0 10px"},              ["mj-section", "mj-group"]),
    MjmlTag("mj-wrapper",   "layout",   "box",            "Umschließt mehrere Sections",  {},                                    ["body"]),
    MjmlTag("mj-group",     "layout",   "object-group",   "Gruppe von Spalten",           {},                                    ["mj-section"]),
    # Content
    MjmlTag("mj-text",      "content",  "type",           "Textblock",                   {"padding": "10px", "font-size": "14px"}, ["mj-column"]),
    MjmlTag("mj-image",     "content",  "image",          "Bild",                        {"padding": "10px", "width": "100%"},    ["mj-column"]),
    MjmlTag("mj-button",    "content",  "cursor-pointer", "Call-to-Action Button",        {"padding": "10px", "background-color": "#333333"}, ["mj-column"]),
    MjmlTag("mj-divider",   "content",  "minus",          "Horizontale Trennlinie",       {"border-width": "1px", "border-color": "#cccccc"}, ["mj-column"]),
    MjmlTag("mj-spacer",    "content",  "space",          "Vertikaler Abstand",           {"height": "20px"},                    ["mj-column"]),
    MjmlTag("mj-table",     "content",  "table",          "HTML-Tabelle",                {"padding": "10px"},                    ["mj-column"]),
    MjmlTag("mj-raw",       "content",  "code",           "Reines HTML",                 {},                                     ["mj-column", "mj-head"]),
    # Advanced
    MjmlTag("mj-hero",      "advanced", "layout-template","Hero-Bild-Section",           {},                                     ["body"]),
    MjmlTag("mj-navbar",    "advanced", "navigation",     "Navigationsleiste",            {},                                    ["mj-section"]),
    MjmlTag("mj-social",    "advanced", "share-2",        "Social-Media-Icons",           {},                                    ["mj-column"]),
    MjmlTag("mj-carousel",  "advanced", "images",         "Bild-Karussell",              {},                                     ["mj-section"]),
    MjmlTag("mj-accordion", "advanced", "chevrons-down",  "Akkordeon-Element",           {},                                     ["mj-column"]),
]

MJML_TAG_MAP: dict[str, MjmlTag] = {t.name: t for t in MJML_TAGS}
```

- [ ] **Step 4: Run — expect all PASS**

```bash
python -m pytest tests/emails_v2/test_catalog.py -v
```
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add emails_v2/catalog.py tests/emails_v2/test_catalog.py
git commit -m "feat: add static MJML tag catalog with 16 components"
```

---

### Task 4: MJML tree renderer

**Files:**
- Create: `emails_v2/mjml.py`
- Create: `tests/emails_v2/test_mjml_renderer.py`

**Interfaces:**
- Consumes: `EmailBuilderCampaign`, `EmailBlock`, `emails.mjml.compile_mjml_to_html`
- Produces: `build_mjml_from_blocks(campaign) -> str`, `render_campaign_preview(campaign) -> str`

- [ ] **Step 1: Write failing tests**

```python
# tests/emails_v2/test_mjml_renderer.py
import pytest
from emails_v2.models import EmailBuilderCampaign, EmailBlock
from emails_v2.mjml import build_mjml_from_blocks


@pytest.mark.django_db
def test_empty_campaign_produces_valid_mjml():
    campaign = EmailBuilderCampaign.objects.create(internal_title="Empty")
    result = build_mjml_from_blocks(campaign)
    assert "<mjml>" in result
    assert "<mj-body>" in result
    assert "</mj-body>" in result


@pytest.mark.django_db
def test_section_rendered():
    campaign = EmailBuilderCampaign.objects.create(internal_title="S")
    EmailBlock.objects.create(campaign=campaign, tag="mj-section", order=0)
    result = build_mjml_from_blocks(campaign)
    assert "<mj-section>" in result
    assert "</mj-section>" in result


@pytest.mark.django_db
def test_section_with_column_and_text():
    campaign = EmailBuilderCampaign.objects.create(internal_title="Nested")
    section = EmailBlock.objects.create(campaign=campaign, tag="mj-section", order=0)
    col = EmailBlock.objects.create(campaign=campaign, tag="mj-column", parent=section, order=0)
    EmailBlock.objects.create(
        campaign=campaign, tag="mj-text", parent=col, order=0,
        variables={"content": "Hello World"}
    )
    result = build_mjml_from_blocks(campaign)
    assert "<mj-text>" in result
    assert "Hello World" in result


@pytest.mark.django_db
def test_attributes_rendered():
    campaign = EmailBuilderCampaign.objects.create(internal_title="Attrs")
    EmailBlock.objects.create(
        campaign=campaign, tag="mj-section", order=0,
        attributes={"padding": "20px", "background-color": "#fff"}
    )
    result = build_mjml_from_blocks(campaign)
    assert 'padding="20px"' in result
    assert 'background-color="#fff"' in result


@pytest.mark.django_db
def test_custom_component_rendered_via_jinja(db):
    from emails.models import MjmlComponent
    comp = MjmlComponent.objects.create(
        name="Greet", mjml_markup="<mj-text>{{ greeting }}</mj-text>"
    )
    campaign = EmailBuilderCampaign.objects.create(internal_title="Custom")
    section = EmailBlock.objects.create(campaign=campaign, tag="mj-section", order=0)
    col = EmailBlock.objects.create(campaign=campaign, tag="mj-column", parent=section, order=0)
    EmailBlock.objects.create(
        campaign=campaign, tag="mj-section", parent=col, order=0,
        component=comp, variables={"greeting": "Hallo!"}
    )
    result = build_mjml_from_blocks(campaign)
    assert "Hallo!" in result


@pytest.mark.django_db
def test_ordering_respected():
    campaign = EmailBuilderCampaign.objects.create(internal_title="Order")
    EmailBlock.objects.create(campaign=campaign, tag="mj-section", order=1, attributes={"css-class": "second"})
    EmailBlock.objects.create(campaign=campaign, tag="mj-section", order=0, attributes={"css-class": "first"})
    result = build_mjml_from_blocks(campaign)
    assert result.index('css-class="first"') < result.index('css-class="second"')
```

- [ ] **Step 2: Run — expect ImportError**

```bash
python -m pytest tests/emails_v2/test_mjml_renderer.py -v 2>&1 | head -10
```

- [ ] **Step 3: Implement mjml.py**

```python
# emails_v2/mjml.py
from __future__ import annotations
import jinja2
from emails.mjml import compile_mjml_to_html  # reuse existing CLI wrapper
from emails_v2.models import EmailBuilderCampaign, EmailBlock

_jinja_env = jinja2.Environment(autoescape=False, undefined=jinja2.Undefined)


def _attrs_str(attributes: dict) -> str:
    if not attributes:
        return ""
    return " " + " ".join(f'{k}="{v}"' for k, v in attributes.items())


def _render_block(block: EmailBlock, child_map: dict[int | None, list[EmailBlock]]) -> str:
    if block.component_id and block.component:
        markup = block.component.mjml_markup
        try:
            return _jinja_env.from_string(markup).render(block.variables)
        except Exception:
            return ""

    children = sorted(child_map.get(block.id, []), key=lambda b: (b.order, b.id))
    inner = block.variables.get("content", "")
    for child in children:
        inner += _render_block(child, child_map)

    attrs = _attrs_str(block.attributes)
    return f"<{block.tag}{attrs}>{inner}</{block.tag}>"


def build_mjml_from_blocks(campaign: EmailBuilderCampaign) -> str:
    blocks = list(campaign.blocks.select_related("component").all())

    child_map: dict[int | None, list[EmailBlock]] = {}
    for block in blocks:
        child_map.setdefault(block.parent_id, []).append(block)

    top_blocks = sorted(child_map.get(None, []), key=lambda b: (b.order, b.id))
    body_inner = "".join(_render_block(b, child_map) for b in top_blocks)

    return f"<mjml><mj-head></mj-head><mj-body>{body_inner}</mj-body></mjml>"


def render_campaign_preview(campaign: EmailBuilderCampaign) -> str:
    return compile_mjml_to_html(build_mjml_from_blocks(campaign))
```

- [ ] **Step 4: Run — expect all PASS**

```bash
python -m pytest tests/emails_v2/test_mjml_renderer.py -v
```
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add emails_v2/mjml.py tests/emails_v2/test_mjml_renderer.py
git commit -m "feat: add MJML tree renderer with recursive block-to-MJML conversion"
```

---

### Task 5: Views + URLs

**Files:**
- Create: `emails_v2/views.py`
- Create: `emails_v2/urls.py`

**Interfaces:**
- Consumes: `EmailBuilderCampaign`, `EmailBlock`, `MjmlComponent`, `MJML_TAGS`, `render_campaign_preview`, `infer_field_type`
- Produces: URL namespace `email_builder` with named URLs: `list`, `create`, `editor`, `htmx_block_create`, `htmx_block_reorder`, `htmx_block_delete`, `htmx_variable_panel`, `htmx_variable_save`, `htmx_preview`

- [ ] **Step 1: Write failing test**

```python
# tests/emails_v2/test_views.py
import pytest
from django.test import Client
from django.contrib.auth.models import User
from emails_v2.models import EmailBuilderCampaign


@pytest.fixture
def staff_client(db):
    user = User.objects.create_user("staff", password="pw", is_staff=True)
    client = Client()
    client.login(username="staff", password="pw")
    return client


@pytest.mark.django_db
def test_campaign_list_requires_staff(client):
    response = client.get("/email-builder/")
    assert response.status_code == 302  # redirects to login


@pytest.mark.django_db
def test_campaign_list_accessible_for_staff(staff_client):
    response = staff_client.get("/email-builder/")
    assert response.status_code == 200


@pytest.mark.django_db
def test_campaign_create_post(staff_client):
    response = staff_client.post("/email-builder/campaign/create/", {"internal_title": "My Campaign"})
    assert response.status_code == 302
    assert EmailBuilderCampaign.objects.filter(internal_title="My Campaign").exists()


@pytest.mark.django_db
def test_editor_view(staff_client):
    c = EmailBuilderCampaign.objects.create(internal_title="Ed")
    response = staff_client.get(f"/email-builder/campaign/{c.pk}/")
    assert response.status_code == 200


@pytest.mark.django_db
def test_htmx_block_create(staff_client):
    c = EmailBuilderCampaign.objects.create(internal_title="Htmx")
    response = staff_client.post(
        "/email-builder/htmx/block/create/",
        {"campaign_id": c.pk, "tag": "mj-section"},
    )
    assert response.status_code == 200
    from emails_v2.models import EmailBlock
    assert EmailBlock.objects.filter(campaign=c, tag="mj-section").exists()
```

- [ ] **Step 2: Run — expect 404/ImportError**

```bash
python -m pytest tests/emails_v2/test_views.py -v 2>&1 | head -15
```

- [ ] **Step 3: Implement urls.py**

```python
# emails_v2/urls.py
from django.urls import path
from emails_v2 import views

app_name = "email_builder"

urlpatterns = [
    path("", views.campaign_list, name="list"),
    path("campaign/create/", views.campaign_create, name="create"),
    path("campaign/<int:campaign_id>/", views.campaign_editor, name="editor"),
    path("htmx/block/create/", views.htmx_block_create, name="htmx_block_create"),
    path("htmx/block/<int:block_id>/reorder/", views.htmx_block_reorder, name="htmx_block_reorder"),
    path("htmx/block/<int:block_id>/delete/", views.htmx_block_delete, name="htmx_block_delete"),
    path("htmx/block/<int:block_id>/vars/", views.htmx_variable_panel, name="htmx_variable_panel"),
    path("htmx/block/<int:block_id>/vars/save/", views.htmx_variable_save, name="htmx_variable_save"),
    path("htmx/campaign/<int:campaign_id>/preview/", views.htmx_preview, name="htmx_preview"),
]
```

- [ ] **Step 4: Implement views.py**

```python
# emails_v2/views.py
from __future__ import annotations
from django.contrib.admin.views.decorators import staff_member_required
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, render, redirect
from django.views.decorators.http import require_http_methods

from emails.models import MjmlComponent
from emails_v2.catalog import MJML_TAGS
from emails_v2.models import EmailBuilderCampaign, EmailBlock
from emails_v2.mjml import render_campaign_preview
from emails_v2.variable_parser import infer_field_type


def _child_map(campaign: EmailBuilderCampaign) -> dict:
    blocks = list(campaign.blocks.select_related("component").all())
    result: dict = {}
    for b in blocks:
        result.setdefault(b.parent_id, []).append(b)
    return result


@staff_member_required
def campaign_list(request):
    campaigns = EmailBuilderCampaign.objects.all()
    return render(request, "email_builder/campaign_list.html", {"campaigns": campaigns})


@staff_member_required
def campaign_create(request):
    if request.method == "POST":
        title = request.POST.get("internal_title", "Neue Kampagne")
        campaign = EmailBuilderCampaign.objects.create(internal_title=title)
        return redirect("email_builder:editor", campaign_id=campaign.pk)
    return render(request, "email_builder/campaign_create.html")


@staff_member_required
def campaign_editor(request, campaign_id):
    campaign = get_object_or_404(EmailBuilderCampaign, pk=campaign_id)
    return render(request, "email_builder/editor.html", {
        "campaign": campaign,
        "mjml_tags": MJML_TAGS,
        "custom_components": MjmlComponent.objects.order_by("name"),
        "top_blocks": sorted((_child_map(campaign)).get(None, []), key=lambda b: (b.order, b.id)),
        "child_map": _child_map(campaign),
    })


@staff_member_required
@require_http_methods(["POST"])
def htmx_block_create(request):
    campaign = get_object_or_404(EmailBuilderCampaign, pk=request.POST.get("campaign_id"))
    parent_id = request.POST.get("parent_id") or None
    component_id = request.POST.get("component_id") or None
    tag = request.POST.get("tag", "mj-section")

    last_order = EmailBlock.objects.filter(campaign=campaign, parent_id=parent_id).count()
    EmailBlock.objects.create(
        campaign=campaign, tag=tag, parent_id=parent_id,
        component_id=component_id, order=last_order,
    )
    cm = _child_map(campaign)
    return render(request, "email_builder/_canvas.html", {
        "campaign": campaign,
        "top_blocks": sorted(cm.get(None, []), key=lambda b: (b.order, b.id)),
        "child_map": cm,
    })


@staff_member_required
@require_http_methods(["POST"])
def htmx_block_reorder(request, block_id):
    block = get_object_or_404(EmailBlock, pk=block_id)
    block.order = int(request.POST.get("order", 0))
    block.save(update_fields=["order"])
    return HttpResponse(status=204)


@staff_member_required
@require_http_methods(["POST"])
def htmx_block_delete(request, block_id):
    block = get_object_or_404(EmailBlock, pk=block_id)
    campaign = block.campaign
    block.delete()
    cm = _child_map(campaign)
    return render(request, "email_builder/_canvas.html", {
        "campaign": campaign,
        "top_blocks": sorted(cm.get(None, []), key=lambda b: (b.order, b.id)),
        "child_map": cm,
    })


@staff_member_required
def htmx_variable_panel(request, block_id):
    block = get_object_or_404(EmailBlock.objects.select_related("component"), pk=block_id)
    variable_fields = []
    if block.component_id and block.component:
        for var_name in block.component.detected_variables:
            variable_fields.append({
                "name": var_name,
                "field_type": infer_field_type(var_name),
                "value": block.variables.get(var_name, ""),
                "label": block.component.variable_labels.get(var_name, var_name.replace("_", " ").title()),
            })
    return render(request, "email_builder/_variable_panel.html", {
        "block": block,
        "variable_fields": variable_fields,
    })


@staff_member_required
@require_http_methods(["POST"])
def htmx_variable_save(request, block_id):
    block = get_object_or_404(EmailBlock.objects.select_related("component"), pk=block_id)
    if block.component_id and block.component:
        for var_name in block.component.detected_variables:
            if var_name in request.POST:
                block.variables[var_name] = request.POST[var_name]
    for key, value in request.POST.items():
        if key.startswith("attr_"):
            block.attributes[key[5:]] = value
    block.save(update_fields=["variables", "attributes"])
    return HttpResponse(status=204)


@staff_member_required
@require_http_methods(["POST"])
def htmx_preview(request, campaign_id):
    campaign = get_object_or_404(EmailBuilderCampaign, pk=campaign_id)
    try:
        html = render_campaign_preview(campaign)
    except Exception as e:
        html = f"<html><body><p style='color:red'>Preview-Fehler: {e}</p></body></html>"
    return HttpResponse(html)
```

- [ ] **Step 5: Run — expect all PASS**

```bash
python -m pytest tests/emails_v2/test_views.py -v
```
Expected: 5 passed

- [ ] **Step 6: Commit**

```bash
git add emails_v2/views.py emails_v2/urls.py tests/emails_v2/test_views.py
git commit -m "feat: add emails_v2 views and URL routing for editor and HTMX endpoints"
```

---

### Task 6: Template tags + editor shell + campaign list

**Files:**
- Create: `emails_v2/templatetags/__init__.py`
- Create: `emails_v2/templatetags/email_builder_tags.py`
- Create: `emails_v2/templates/email_builder/campaign_list.html`
- Create: `emails_v2/templates/email_builder/campaign_create.html`
- Create: `emails_v2/templates/email_builder/editor.html`

**Interfaces:**
- Produces: `{% load email_builder_tags %}`, `{{ dict|get_item:key }}` filter (used in canvas template)

- [ ] **Step 1: Write failing test**

```python
# tests/emails_v2/test_template_tags.py
from django.template import Context, Template


def test_get_item_filter_returns_value():
    t = Template("{% load email_builder_tags %}{{ mydict|get_item:key }}")
    c = Context({"mydict": {"hello": "world"}, "key": "hello"})
    assert t.render(c) == "world"


def test_get_item_filter_returns_empty_list_for_missing():
    t = Template("{% load email_builder_tags %}{% for x in mydict|get_item:key %}{{ x }}{% endfor %}")
    c = Context({"mydict": {}, "key": "missing"})
    assert t.render(c) == ""
```

- [ ] **Step 2: Run — expect ImportError**

```bash
python -m pytest tests/emails_v2/test_template_tags.py -v 2>&1 | head -10
```

- [ ] **Step 3: Implement template tags**

```python
# emails_v2/templatetags/__init__.py
# (empty)
```

```python
# emails_v2/templatetags/email_builder_tags.py
from django import template

register = template.Library()

@register.filter
def get_item(dictionary, key):
    return dictionary.get(key, [])
```

- [ ] **Step 4: Run template tag tests — expect PASS**

```bash
python -m pytest tests/emails_v2/test_template_tags.py -v
```

- [ ] **Step 5: Create campaign_list.html**

```html
<!-- emails_v2/templates/email_builder/campaign_list.html -->
<!DOCTYPE html>
<html lang="de">
<head>
  <meta charset="UTF-8">
  <title>Email Builder</title>
  <script src="https://cdn.tailwindcss.com"></script>
</head>
<body class="bg-gray-50 min-h-screen p-8">
  <div class="max-w-3xl mx-auto">
    <div class="flex items-center justify-between mb-6">
      <h1 class="text-2xl font-bold text-gray-800">Email Kampagnen</h1>
      <a href="{% url 'email_builder:create' %}"
         class="px-4 py-2 bg-indigo-600 text-white rounded-lg text-sm hover:bg-indigo-700">
        + Neue Kampagne
      </a>
    </div>
    {% for campaign in campaigns %}
    <div class="bg-white rounded-lg border p-4 mb-3 flex items-center justify-between hover:border-indigo-300">
      <div>
        <p class="font-medium text-gray-800">{{ campaign.internal_title }}</p>
        <p class="text-xs text-gray-400 mt-0.5">{{ campaign.get_status_display }} · {{ campaign.created_at|date:"d.m.Y" }}</p>
      </div>
      <a href="{% url 'email_builder:editor' campaign.pk %}"
         class="px-3 py-1.5 bg-indigo-50 text-indigo-600 rounded text-sm hover:bg-indigo-100">
        Bearbeiten →
      </a>
    </div>
    {% empty %}
    <p class="text-gray-400 text-center py-12">Noch keine Kampagnen. Erstelle die erste!</p>
    {% endfor %}
  </div>
</body>
</html>
```

- [ ] **Step 6: Create campaign_create.html**

```html
<!-- emails_v2/templates/email_builder/campaign_create.html -->
<!DOCTYPE html>
<html lang="de">
<head>
  <meta charset="UTF-8">
  <title>Neue Kampagne</title>
  <script src="https://cdn.tailwindcss.com"></script>
</head>
<body class="bg-gray-50 min-h-screen flex items-center justify-center">
  <div class="bg-white rounded-xl border p-8 w-full max-w-md shadow-sm">
    <h1 class="text-xl font-bold text-gray-800 mb-6">Neue Email-Kampagne</h1>
    <form method="post">
      {% csrf_token %}
      <label class="block text-sm text-gray-600 mb-1">Interner Titel</label>
      <input type="text" name="internal_title" autofocus required
        class="w-full border rounded-lg px-3 py-2 text-sm mb-4 focus:outline-none focus:border-indigo-500"
        placeholder="z.B. Sommer-Aktion 2026">
      <div class="flex gap-3">
        <button type="submit"
          class="flex-1 py-2 bg-indigo-600 text-white rounded-lg text-sm hover:bg-indigo-700">
          Erstellen
        </button>
        <a href="{% url 'email_builder:list' %}"
          class="flex-1 py-2 text-center border rounded-lg text-sm text-gray-600 hover:bg-gray-50">
          Abbrechen
        </a>
      </div>
    </form>
  </div>
</body>
</html>
```

- [ ] **Step 7: Create editor.html**

```html
<!-- emails_v2/templates/email_builder/editor.html -->
{% load email_builder_tags %}
<!DOCTYPE html>
<html lang="de">
<head>
  <meta charset="UTF-8">
  <title>{{ campaign.internal_title }} — Email Builder</title>
  <script src="https://cdn.tailwindcss.com"></script>
  <script src="https://unpkg.com/htmx.org@1.9.12"></script>
  <script defer src="https://unpkg.com/alpinejs@3.13.5/dist/cdn.min.js"></script>
  <script src="https://cdn.jsdelivr.net/npm/sortablejs@1.15.2/Sortable.min.js"></script>
</head>
<body class="bg-gray-100 h-screen flex flex-col overflow-hidden" x-data="emailEditor()" @select-block.window="selectBlock($event.detail.id)">

  <!-- Topbar -->
  <header class="bg-white border-b px-4 py-2 flex items-center gap-4 shadow-sm z-10 flex-shrink-0">
    <a href="{% url 'email_builder:list' %}" class="text-sm text-gray-500 hover:text-gray-800">← Kampagnen</a>
    <h1 class="font-semibold text-gray-800 truncate">{{ campaign.internal_title }}</h1>
    <span class="px-2 py-0.5 rounded-full text-xs font-medium
      {% if campaign.status == 'draft' %}bg-yellow-100 text-yellow-700
      {% elif campaign.status == 'ready' %}bg-green-100 text-green-700
      {% else %}bg-gray-100 text-gray-500{% endif %}">
      {{ campaign.get_status_display }}
    </span>
    <div class="ml-auto flex gap-2">
      <button
        hx-post="{% url 'email_builder:htmx_preview' campaign.id %}"
        hx-target="#preview-pane"
        hx-indicator="#preview-spinner"
        class="px-4 py-1.5 bg-indigo-600 text-white rounded-lg text-sm hover:bg-indigo-700 flex items-center gap-1">
        <span id="preview-spinner" class="htmx-indicator text-xs">⏳</span>
        Preview
      </button>
    </div>
  </header>

  <!-- 3-panel layout -->
  <div class="flex flex-1 overflow-hidden">
    {% include "email_builder/_sidebar.html" %}

    <main class="flex-1 overflow-y-auto bg-gray-50" id="canvas-wrapper">
      {% include "email_builder/_canvas.html" %}
    </main>

    <!-- Right panel -->
    <aside class="w-72 bg-white border-l overflow-y-auto flex-shrink-0" id="variable-panel">
      <div class="p-4 text-sm text-gray-400">Element auswählen...</div>
    </aside>
  </div>

  <!-- Preview pane (hidden until preview clicked) -->
  <div id="preview-pane" class="hidden fixed inset-0 z-50 bg-black/60 flex items-center justify-center p-8"
       @click.self="$el.classList.add('hidden')">
  </div>

  <script>
    function emailEditor() {
      return {
        selectedBlockId: null,
        selectBlock(id) {
          this.selectedBlockId = id;
          htmx.ajax('GET', `/email-builder/htmx/block/${id}/vars/`, { target: '#variable-panel' });
        }
      }
    }

    // Re-init SortableJS after HTMX canvas swap
    document.addEventListener('htmx:afterSwap', (e) => {
      if (e.detail.target.id === 'canvas-wrapper' || e.detail.target.closest?.('#canvas-wrapper')) {
        initSortables();
      }
    });
    document.addEventListener('DOMContentLoaded', initSortables);

    function initSortables() {
      document.querySelectorAll('[data-sortable]').forEach(el => {
        if (el._sortable) return;
        el._sortable = Sortable.create(el, {
          group: el.dataset.sortable,
          handle: '.drag-handle',
          animation: 150,
          onEnd(evt) {
            const blockId = evt.item.dataset.blockId;
            if (!blockId) return;
            htmx.ajax('POST', `/email-builder/htmx/block/${blockId}/reorder/`, {
              values: { order: evt.newIndex, csrfmiddlewaretoken: getCsrf() }
            });
          }
        });
      });
    }

    function getCsrf() {
      return document.cookie.match(/csrftoken=([^;]+)/)?.[1] ?? '';
    }
  </script>
</body>
</html>
```

- [ ] **Step 8: Smoke-test in browser**

```bash
python manage.py runserver
# Visit http://localhost:8000/email-builder/ — expect campaign list page
# Click "+ Neue Kampagne" — expect create form
# Submit form — expect redirect to editor with 3-panel layout
```

- [ ] **Step 9: Commit**

```bash
git add emails_v2/templatetags/ emails_v2/templates/email_builder/campaign_list.html emails_v2/templates/email_builder/campaign_create.html emails_v2/templates/email_builder/editor.html tests/emails_v2/test_template_tags.py
git commit -m "feat: add editor shell, campaign list/create templates and get_item template tag"
```

---

### Task 7: Sidebar template

**Files:**
- Create: `emails_v2/templates/email_builder/_sidebar.html`

- [ ] **Step 1: Create _sidebar.html**

```html
<!-- emails_v2/templates/email_builder/_sidebar.html -->
{% load email_builder_tags %}
<aside class="w-56 bg-white border-r overflow-y-auto flex-shrink-0 flex flex-col" x-data="{ tab: 'standard' }">

  <!-- Tab switcher -->
  <div class="flex border-b flex-shrink-0">
    <button @click="tab='standard'"
      :class="tab==='standard' ? 'border-b-2 border-indigo-600 text-indigo-600 font-medium' : 'text-gray-500 hover:text-gray-700'"
      class="flex-1 py-2.5 text-xs transition-colors">
      Standard
    </button>
    <button @click="tab='custom'"
      :class="tab==='custom' ? 'border-b-2 border-indigo-600 text-indigo-600 font-medium' : 'text-gray-500 hover:text-gray-700'"
      class="flex-1 py-2.5 text-xs transition-colors">
      Eigene
    </button>
  </div>

  <!-- Standard MJML tags -->
  <div x-show="tab==='standard'" class="p-2 overflow-y-auto">
    {% regroup mjml_tags by category as tag_groups %}
    {% for group in tag_groups %}
    <p class="text-xs font-semibold text-gray-400 uppercase tracking-wide mt-3 mb-1 px-1">{{ group.grouper }}</p>
    {% for tag in group.list %}
    <div
      draggable="true"
      data-tag="{{ tag.name }}"
      class="flex items-center gap-2 px-2 py-1.5 rounded-md cursor-grab active:cursor-grabbing hover:bg-indigo-50 hover:text-indigo-700 text-sm text-gray-700 select-none transition-colors"
      title="{{ tag.description }}"
      @dragstart="
        $event.dataTransfer.setData('tag', '{{ tag.name }}');
        $event.dataTransfer.setData('component_id', '');
        $event.dataTransfer.effectAllowed = 'copy';
      ">
      <span class="text-gray-300 text-xs font-mono w-3">⬛</span>
      <span class="font-mono text-xs">{{ tag.name }}</span>
    </div>
    {% endfor %}
    {% endfor %}
  </div>

  <!-- Custom components -->
  <div x-show="tab==='custom'" class="p-2 overflow-y-auto">
    {% for comp in custom_components %}
    <div
      draggable="true"
      data-component-id="{{ comp.id }}"
      class="flex items-center gap-2 px-2 py-1.5 rounded-md cursor-grab active:cursor-grabbing hover:bg-purple-50 hover:text-purple-700 text-sm text-gray-700 select-none transition-colors"
      title="{{ comp.description }}"
      @dragstart="
        $event.dataTransfer.setData('component_id', '{{ comp.id }}');
        $event.dataTransfer.setData('tag', 'mj-section');
        $event.dataTransfer.effectAllowed = 'copy';
      ">
      <span class="text-purple-300 text-xs">📦</span>
      <span class="text-xs truncate">{{ comp.name }}</span>
    </div>
    {% empty %}
    <p class="text-xs text-gray-400 p-3 text-center">Keine eigenen Komponenten.<br>Im Admin unter Emails → MJML Komponenten erstellen.</p>
    {% endfor %}
  </div>
</aside>
```

- [ ] **Step 2: Smoke-test sidebar**

```bash
python manage.py runserver
# Open editor — expect two-tab sidebar with draggable tags
# Verify Standard tab shows layout/content/advanced groups
# Verify Eigene tab shows MjmlComponent entries from DB (or empty state)
```

- [ ] **Step 3: Commit**

```bash
git add emails_v2/templates/email_builder/_sidebar.html
git commit -m "feat: add sidebar template with standard MJML tags and custom components"
```

---

### Task 8: Canvas template + drag/drop

**Files:**
- Create: `emails_v2/templates/email_builder/_canvas.html`

- [ ] **Step 1: Create _canvas.html**

```html
<!-- emails_v2/templates/email_builder/_canvas.html -->
{% load email_builder_tags %}
<div id="canvas" class="p-6">
  <div class="max-w-2xl mx-auto">

    <!-- Sections list (SortableJS target) -->
    <div
      id="sections-list"
      data-sortable="sections"
      data-campaign-id="{{ campaign.id }}"
      class="space-y-3 min-h-16"
      @dragover.prevent="$el.classList.add('ring-2','ring-indigo-300')"
      @dragleave="$el.classList.remove('ring-2','ring-indigo-300')"
      @drop.prevent="
        $el.classList.remove('ring-2','ring-indigo-300');
        const tag = $event.dataTransfer.getData('tag');
        const cid = $event.dataTransfer.getData('component_id');
        if (!tag && !cid) return;
        htmx.ajax('POST', '{% url "email_builder:htmx_block_create" %}', {
          target: '#canvas',
          swap: 'outerHTML',
          values: {
            campaign_id: '{{ campaign.id }}',
            tag: tag || 'mj-section',
            component_id: cid,
            parent_id: '',
            csrfmiddlewaretoken: document.cookie.match(/csrftoken=([^;]+)/)?.[1] ?? ''
          }
        });
      ">

      {% for section in top_blocks %}
      {% with col_blocks=child_map|get_item:section.id %}
      <div
        class="bg-white rounded-xl border-2 border-gray-200 hover:border-indigo-200 transition-colors shadow-sm"
        data-block-id="{{ section.id }}"
        @click.stop="$dispatch('select-block', { id: {{ section.id }} })">

        <!-- Section header -->
        <div class="flex items-center px-3 py-2 border-b bg-gray-50 rounded-t-xl gap-2">
          <span class="drag-handle cursor-move text-gray-300 hover:text-gray-500 select-none text-lg leading-none">⠿</span>
          <span class="text-xs font-mono text-indigo-400">{{ section.tag }}</span>
          {% if section.component %}
          <span class="text-xs text-purple-500 font-medium">{{ section.component.name }}</span>
          {% endif %}
          <div class="ml-auto flex gap-1">
            <button
              class="text-red-300 hover:text-red-500 text-sm px-1 transition-colors"
              title="Abschnitt löschen"
              hx-post="{% url 'email_builder:htmx_block_delete' section.id %}"
              hx-target="#canvas"
              hx-swap="outerHTML"
              hx-confirm="Diesen Abschnitt mit allen Inhalten löschen?">
              ✕
            </button>
          </div>
        </div>

        <!-- Columns -->
        <div class="flex p-2 gap-2 min-h-20 items-stretch"
             data-sortable="columns-{{ section.id }}"
             @dragover.prevent
             @drop.prevent="
               const tag = $event.dataTransfer.getData('tag');
               if (tag !== 'mj-column' && tag !== 'mj-group') return;
               htmx.ajax('POST', '{% url "email_builder:htmx_block_create" %}', {
                 target: '#canvas', swap: 'outerHTML',
                 values: { campaign_id: '{{ campaign.id }}', tag: tag, parent_id: '{{ section.id }}', component_id: '', csrfmiddlewaretoken: document.cookie.match(/csrftoken=([^;]+)/)?.[1] ?? '' }
               });
             ">
          {% for col in col_blocks %}
          {% with content_blocks=child_map|get_item:col.id %}
          <div
            class="flex-1 min-w-0 border rounded-lg p-2 bg-gray-50 hover:border-indigo-200 transition-colors"
            data-block-id="{{ col.id }}"
            data-sortable="content-{{ col.id }}"
            @click.stop="$dispatch('select-block', { id: {{ col.id }} })"
            @dragover.prevent="$el.classList.add('bg-indigo-50')"
            @dragleave="$el.classList.remove('bg-indigo-50')"
            @drop.prevent="
              $el.classList.remove('bg-indigo-50');
              const tag = $event.dataTransfer.getData('tag');
              const cid = $event.dataTransfer.getData('component_id');
              const isLayout = ['mj-section','mj-column','mj-wrapper','mj-group'].includes(tag);
              if (!cid && isLayout) return;
              htmx.ajax('POST', '{% url "email_builder:htmx_block_create" %}', {
                target: '#canvas', swap: 'outerHTML',
                values: { campaign_id: '{{ campaign.id }}', tag: tag || 'mj-text', component_id: cid, parent_id: '{{ col.id }}', csrfmiddlewaretoken: document.cookie.match(/csrftoken=([^;]+)/)?.[1] ?? '' }
              });
            ">
            <!-- Column label -->
            <div class="text-xs text-gray-400 mb-1.5 flex items-center gap-1">
              <span class="drag-handle cursor-move text-gray-300 hover:text-gray-400">⠿</span>
              <span class="font-mono">{{ col.tag }}</span>
              {% if col.attributes.width %}<span class="text-gray-300">({{ col.attributes.width }})</span>{% endif %}
              <button
                class="ml-auto text-red-300 hover:text-red-400 text-xs"
                hx-post="{% url 'email_builder:htmx_block_delete' col.id %}"
                hx-target="#canvas" hx-swap="outerHTML">✕</button>
            </div>

            <!-- Content blocks -->
            {% for content in content_blocks %}
            <div
              class="bg-white border rounded-lg p-2 mb-1.5 text-xs cursor-pointer hover:border-indigo-400 hover:shadow-sm transition-all flex items-start gap-1"
              data-block-id="{{ content.id }}"
              @click.stop="$dispatch('select-block', { id: {{ content.id }} })">
              <span class="drag-handle cursor-move text-gray-300 hover:text-gray-400 mt-0.5">⠿</span>
              <div class="flex-1 min-w-0">
                <span class="font-mono text-indigo-400">{{ content.tag }}</span>
                {% if content.component %}
                <span class="text-purple-500 ml-1">{{ content.component.name }}</span>
                {% endif %}
                {% if content.variables.content %}
                <p class="text-gray-400 truncate mt-0.5">{{ content.variables.content|truncatechars:40 }}</p>
                {% endif %}
              </div>
              <button
                class="text-red-300 hover:text-red-400 flex-shrink-0"
                hx-post="{% url 'email_builder:htmx_block_delete' content.id %}"
                hx-target="#canvas" hx-swap="outerHTML">✕</button>
            </div>
            {% endfor %}

            <!-- Empty drop hint -->
            {% if not content_blocks %}
            <div class="border-2 border-dashed border-gray-200 rounded-lg p-3 text-center text-xs text-gray-300">
              Inhalt hierher ziehen
            </div>
            {% endif %}
          </div>
          {% endwith %}
          {% endfor %}

          <!-- Add column button -->
          <button
            class="self-center flex-shrink-0 text-xs text-indigo-400 hover:text-indigo-600 px-2 py-1 rounded hover:bg-indigo-50 transition-colors whitespace-nowrap"
            hx-post="{% url 'email_builder:htmx_block_create' %}"
            hx-vals='{"campaign_id": "{{ campaign.id }}", "tag": "mj-column", "parent_id": "{{ section.id }}"}'
            hx-headers='{"X-CSRFToken": "{{ csrf_token }}"}'
            hx-target="#canvas"
            hx-swap="outerHTML">
            + Spalte
          </button>
        </div>
      </div>
      {% endwith %}
      {% endfor %}

      <!-- Bottom drop zone -->
      {% if not top_blocks %}
      <div class="border-2 border-dashed border-gray-300 rounded-xl p-8 text-center text-sm text-gray-400">
        MJML-Tag aus der linken Sidebar hierher ziehen
      </div>
      {% endif %}
    </div>
  </div>
</div>
```

- [ ] **Step 2: Smoke-test drag/drop**

```bash
python manage.py runserver
# 1. Drag mj-section from sidebar onto canvas → section block appears
# 2. Drag mj-column into section → column appears
# 3. Drag mj-text into column → text block appears
# 4. Click "+ Spalte" → second column added
# 5. Drag section drag handle → sections reorder
# 6. Click ✕ on a block → block removed, canvas refreshes
```

- [ ] **Step 3: Commit**

```bash
git add emails_v2/templates/email_builder/_canvas.html
git commit -m "feat: add canvas template with drag/drop zones, SortableJS reordering, HTMX block CRUD"
```

---

### Task 9: Variable panel + preview

**Files:**
- Create: `emails_v2/templates/email_builder/_variable_panel.html`

- [ ] **Step 1: Create _variable_panel.html**

```html
<!-- emails_v2/templates/email_builder/_variable_panel.html -->
<div class="p-4" x-data="{ saved: false }">
  <!-- Block info -->
  <div class="mb-4 pb-3 border-b">
    <p class="text-xs text-gray-400 uppercase tracking-wide mb-1">Ausgewählt</p>
    <p class="font-mono text-sm text-indigo-600 font-semibold">{{ block.tag }}</p>
    {% if block.component %}
    <p class="text-xs text-purple-600 mt-0.5">📦 {{ block.component.name }}</p>
    {% endif %}
  </div>

  {% if variable_fields %}
  <!-- Variables -->
  <div class="mb-4">
    <p class="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2">Variablen</p>
    <form
      hx-post="{% url 'email_builder:htmx_variable_save' block.id %}"
      hx-trigger="change delay:600ms"
      hx-swap="none"
      hx-on::after-request="saved = true; setTimeout(() => saved = false, 2000)"
      @submit.prevent>
      {% csrf_token %}
      {% for field in variable_fields %}
      <div class="mb-3">
        <label class="block text-xs text-gray-500 mb-1 font-medium">{{ field.label }}</label>
        {% if field.field_type == "textarea" %}
        <textarea
          name="{{ field.name }}"
          rows="4"
          class="w-full border border-gray-200 rounded-lg px-2.5 py-1.5 text-sm focus:outline-none focus:border-indigo-400 resize-y">{{ field.value }}</textarea>
        {% elif field.field_type == "number" %}
        <input type="number" step="0.01" name="{{ field.name }}" value="{{ field.value }}"
          class="w-full border border-gray-200 rounded-lg px-2.5 py-1.5 text-sm focus:outline-none focus:border-indigo-400">
        {% elif field.field_type == "url" %}
        <input type="url" name="{{ field.name }}" value="{{ field.value }}"
          class="w-full border border-gray-200 rounded-lg px-2.5 py-1.5 text-sm focus:outline-none focus:border-indigo-400"
          placeholder="https://">
        {% else %}
        <input type="text" name="{{ field.name }}" value="{{ field.value }}"
          class="w-full border border-gray-200 rounded-lg px-2.5 py-1.5 text-sm focus:outline-none focus:border-indigo-400">
        {% endif %}
      </div>
      {% endfor %}
      <p class="text-xs text-green-600 transition-opacity" :class="saved ? 'opacity-100' : 'opacity-0'">✓ Gespeichert</p>
    </form>
  </div>
  {% else %}
  <p class="text-xs text-gray-400 mb-4">Keine Variablen für dieses Element.</p>
  {% endif %}

  <!-- Attributes -->
  {% if block.attributes %}
  <div class="pt-3 border-t">
    <p class="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2">Attribute</p>
    <form
      hx-post="{% url 'email_builder:htmx_variable_save' block.id %}"
      hx-trigger="change delay:600ms"
      hx-swap="none"
      @submit.prevent>
      {% csrf_token %}
      {% for key, val in block.attributes.items %}
      <div class="mb-2">
        <label class="block text-xs text-gray-400 mb-0.5">{{ key }}</label>
        <input type="text" name="attr_{{ key }}" value="{{ val }}"
          class="w-full border border-gray-200 rounded px-2 py-1 text-xs focus:outline-none focus:border-indigo-400">
      </div>
      {% endfor %}
    </form>
  </div>
  {% endif %}
</div>
```

- [ ] **Step 2: Wire preview response**

The `htmx_preview` view already returns HTML. Update `editor.html` so clicking Preview opens the result in the fullscreen overlay. The `#preview-pane` div in editor.html receives the raw HTML — wrap it in an iframe via JS:

In `editor.html`, add this htmx event listener in the `<script>` block:

```javascript
document.body.addEventListener('htmx:afterSwap', (e) => {
  if (e.detail.target.id === 'preview-pane') {
    const pane = e.detail.target;
    const html = pane.innerHTML;
    pane.innerHTML = `
      <div class="bg-white rounded-xl w-full max-w-4xl max-h-full overflow-hidden flex flex-col shadow-2xl" @click.stop>
        <div class="flex items-center justify-between px-4 py-2 border-b bg-gray-50">
          <span class="font-medium text-sm text-gray-700">Email Preview</span>
          <button @click="$el.closest('#preview-pane').classList.add('hidden')" class="text-gray-400 hover:text-gray-600">✕ Schließen</button>
        </div>
        <iframe class="flex-1 w-full" style="height:600px" srcdoc="${html.replace(/"/g, '&quot;')}"></iframe>
      </div>`;
    pane.classList.remove('hidden');
  }
});
```

- [ ] **Step 3: End-to-end verification**

```bash
python manage.py runserver
```

Run the verification checklist from the spec:
1. Visit `/email-builder/` — campaign list loads
2. Create campaign → redirects to editor
3. Drag `mj-section` → section block appears
4. Drag `mj-column` into section → column appears
5. Drag `mj-text` into column → text block appears, click it → right panel shows `content` textarea
6. In Django admin, create a `MjmlComponent` with markup `<mj-text>{{ title }}</mj-text><mj-image src="{{ image_url }}"/>` — auto-saves `detected_variables = ["image_url", "title"]`
7. Drag that custom component onto canvas → click it → right panel shows `title` (text) and `image_url` (url) fields
8. Change component markup to add `{{ price }}` → save → right panel shows 3 fields, old values preserved
9. Click Preview button → iframe opens with compiled email HTML

- [ ] **Step 4: Commit**

```bash
git add emails_v2/templates/email_builder/_variable_panel.html emails_v2/templates/email_builder/editor.html
git commit -m "feat: add variable panel with auto-fields and fullscreen preview modal"
```

---

## Full test suite

```bash
python -m pytest tests/emails_v2/ -v
```

Expected: all tests pass across test_models, test_variable_parser, test_catalog, test_mjml_renderer, test_views, test_template_tags.
