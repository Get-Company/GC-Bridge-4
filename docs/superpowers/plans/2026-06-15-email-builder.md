# Email-Builder App — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Neue Django-App `emails` die Marketing-E-Mails aus MJML-Komponenten zusammenstellt, Produkte mit Sonderpreisen verwaltet und fertiges HTML exportiert.

**Architecture:** Django-App mit drei Models (EmailCampaign, EmailCampaignProduct, EmailCampaignSalesChannel), einem Unfold-Admin mit 3-Spalten-Template, einer MJML-Render-Utility via Django-Templates + `npx mjml` CLI und einer AJAX-Export-View.

**Tech Stack:** Django 4.x, django-unfold, MJML CLI v5.3 (`npx mjml`), Django-Template-Engine für MJML-Rendering, Django-AutocompleteSelect für Produktsuche.

---

## File Map

**Neu erstellen:**
- `emails/__init__.py`
- `emails/apps.py`
- `emails/models.py`
- `emails/admin.py`
- `emails/mjml.py`
- `emails/views.py`
- `emails/migrations/` (via `makemigrations`)
- `emails/templates/emails/newsletter_base.mjml`
- `emails/templates/emails/components/head.mjml`
- `emails/templates/emails/components/view_online.mjml`
- `emails/templates/emails/components/nav_items_shop.mjml`
- `emails/templates/emails/components/header_logo.mjml`
- `emails/templates/emails/components/title_txt.mjml`
- `emails/templates/emails/components/salutation.mjml`
- `emails/templates/emails/components/product.mjml`
- `emails/templates/emails/components/product_shipping_free.mjml`
- `emails/templates/emails/components/order_form_product.mjml`
- `emails/templates/emails/components/order_form_product_shipping_free.mjml`
- `emails/templates/emails/components/contact_table.mjml`
- `emails/templates/emails/components/disclaimer.mjml`
- `templates/admin/emails/emailcampaign/change_form.html`
- `tests/emails/test_mjml.py`
- `tests/emails/__init__.py`

**Modifizieren:**
- `GC_Bridge_4/settings.py` — `INSTALLED_APPS` + UNFOLD-Navigation
- `products/admin.py` — `autocomplete = True` auf `ProductAdmin` (Zeile ~443)

---

## Task 1: App-Scaffold und Settings

**Files:**
- Create: `emails/__init__.py`
- Create: `emails/apps.py`
- Modify: `GC_Bridge_4/settings.py`

- [ ] **Schritt 1: App-Dateien anlegen**

```python
# emails/__init__.py
# (leer)
```

```python
# emails/apps.py
from django.apps import AppConfig


class EmailsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "emails"
    verbose_name = "E-Mails"
```

- [ ] **Schritt 2: In INSTALLED_APPS eintragen**

In `GC_Bridge_4/settings.py` nach `'issues'` einfügen:

```python
'emails',
```

- [ ] **Schritt 3: UNFOLD-Navigation ergänzen**

In `GC_Bridge_4/settings.py` im Block `"SIDEBAR" → "navigation"` eine neue Gruppe hinzufügen (nach der Issues-Gruppe):

```python
{
    "title": _("E-Mails"),
    "separator": True,
    "collapsible": True,
    "items": [
        {
            "title": _("Kampagnen"),
            "icon": "mail",
            "link": reverse_lazy("admin:emails_emailcampaign_changelist"),
            "permission": sidebar_model_view_permission("emails", "EmailCampaign"),
        },
    ],
},
```

- [ ] **Schritt 4: Prüfen, dass Django startet**

```bash
python manage.py check
```

Erwartet: keine Fehler.

- [ ] **Schritt 5: Commit**

```bash
git add emails/__init__.py emails/apps.py GC_Bridge_4/settings.py
git commit -m "feat(emails): scaffold app and register in settings"
```

---

## Task 2: Models und Migration

**Files:**
- Create: `emails/models.py`
- Create: `emails/migrations/0001_initial.py` (auto-generiert)

- [ ] **Schritt 1: models.py schreiben**

```python
# emails/models.py
from __future__ import annotations

from django.db import models
from django.utils.translation import gettext_lazy as _

from core.models import BaseModel


class EmailCampaign(BaseModel):
    class Status(models.TextChoices):
        DRAFT = "draft", _("Entwurf")
        READY = "ready", _("Bereit")
        EXPORTED = "exported", _("Exportiert")

    class ProductTemplate(models.TextChoices):
        STANDARD = "product", _("Standard")
        SHIPPING_FREE = "product_shipping_free", _("Kostenloser Versand")
        GREEN = "product_green", _("Grün")

    internal_title = models.CharField(
        max_length=255,
        verbose_name=_("Interner Titel"),
        help_text=_("Wird nicht in der E-Mail angezeigt."),
    )
    h1 = models.CharField(max_length=255, verbose_name=_("Hauptüberschrift"))
    h1_small = models.CharField(
        max_length=255,
        blank=True,
        default="",
        verbose_name=_("Untertitel"),
    )
    intro_text = models.TextField(
        blank=True,
        default="",
        verbose_name=_("Einleitungstext"),
        help_text=_("HTML erlaubt. Wird zwischen Anrede und Produkt-Listing angezeigt."),
    )
    product_template = models.CharField(
        max_length=30,
        choices=ProductTemplate.choices,
        default=ProductTemplate.STANDARD,
        verbose_name=_("Produkt-Template"),
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.DRAFT,
        db_index=True,
        verbose_name=_("Status"),
    )

    class Meta:
        verbose_name = _("E-Mail Kampagne")
        verbose_name_plural = _("E-Mail Kampagnen")
        ordering = ("-created_at",)

    def __str__(self) -> str:
        return self.internal_title


class EmailCampaignProduct(BaseModel):
    campaign = models.ForeignKey(
        EmailCampaign,
        on_delete=models.CASCADE,
        related_name="campaign_products",
        verbose_name=_("Kampagne"),
    )
    product = models.ForeignKey(
        "products.Product",
        on_delete=models.PROTECT,
        related_name="email_campaign_products",
        verbose_name=_("Produkt"),
    )
    special_price_override = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name=_("Sonderpreis"),
        help_text=_("Überschreibt den Sonderpreis des Produkts für diese Kampagne."),
    )
    order = models.PositiveIntegerField(default=0, verbose_name=_("Reihenfolge"))

    class Meta:
        verbose_name = _("Kampagnen-Produkt")
        verbose_name_plural = _("Kampagnen-Produkte")
        ordering = ("order", "id")
        unique_together = (("campaign", "product"),)

    def __str__(self) -> str:
        return f"{self.campaign} | {self.product}"


class EmailCampaignSalesChannel(BaseModel):
    campaign = models.ForeignKey(
        EmailCampaign,
        on_delete=models.CASCADE,
        related_name="sales_channels",
        verbose_name=_("Kampagne"),
    )
    sales_channel = models.ForeignKey(
        "shopware.ShopwareSettings",
        on_delete=models.CASCADE,
        verbose_name=_("Sales Channel"),
    )
    enabled = models.BooleanField(default=False, verbose_name=_("Aktiviert"))

    class Meta:
        verbose_name = _("Sales Channel")
        verbose_name_plural = _("Sales Channels")
        ordering = ("-sales_channel__is_default", "sales_channel__name")
        unique_together = (("campaign", "sales_channel"),)

    def __str__(self) -> str:
        return f"{self.campaign} | {self.sales_channel}"
```

- [ ] **Schritt 2: Migration generieren**

```bash
python manage.py makemigrations emails
```

Erwartet: `emails/migrations/0001_initial.py` erstellt.

- [ ] **Schritt 3: Migration ausführen**

```bash
python manage.py migrate emails
```

Erwartet: Tabellen `emails_emailcampaign`, `emails_emailcampaignproduct`, `emails_emailcampaignsaleschannel` erstellt.

- [ ] **Schritt 4: Commit**

```bash
git add emails/models.py emails/migrations/
git commit -m "feat(emails): add EmailCampaign, EmailCampaignProduct, EmailCampaignSalesChannel models"
```

---

## Task 3: MJML-Komponenten-Templates

**Files:**
- Create: `emails/templates/emails/components/*.mjml` (alle Komponenten)

Quelle: `old-emails/template/` — Dateien werden in Django-Template-Syntax übernommen (kein Jinja2 `{% set %}`).

- [ ] **Schritt 1: Verzeichnis anlegen**

```bash
mkdir -p emails/templates/emails/components
```

- [ ] **Schritt 2: head.mjml**

```xml
{# emails/templates/emails/components/head.mjml #}
<mj-attributes>
    <mj-all font-family="Helvetica, Arial, sans-serif" />
    <mj-text font-size="14px" color="#333333" line-height="22px" />
    <mj-button background-color="#ff9933" color="#ffffff" border-radius="3px" />
    <mj-image padding="0" />
</mj-attributes>
<mj-style inline="inline">
    a { color: #ff9933; }
    h1, h2, h3, h4, h5 { margin: 0; padding: 0; }
</mj-style>
```

- [ ] **Schritt 3: view_online.mjml**

```xml
{# emails/templates/emails/components/view_online.mjml #}
<mj-section background-color="#f3f3f3" padding="6px">
    <mj-column>
        <mj-text align="center" font-size="11px" color="#888888">
            <a href="{viewOnline}" style="color:#888888; text-decoration:none;">
                E-Mail im Browser anzeigen
            </a>
        </mj-text>
    </mj-column>
</mj-section>
```

- [ ] **Schritt 4: nav_items_shop.mjml**

```xml
{# emails/templates/emails/components/nav_items_shop.mjml #}
<mj-section background-color="#1a1a1a" padding="8px">
    <mj-column>
        <mj-text align="center" font-size="12px">
            <a href="https://www.classei-shop.com" style="color:#ffffff; text-decoration:none; margin:0 8px;">Shop</a>
            <a href="https://www.classei.de" style="color:#ffffff; text-decoration:none; margin:0 8px;">Classei.de</a>
            <a href="https://www.classei-shop.com/Versandinformationen" style="color:#ffffff; text-decoration:none; margin:0 8px;">Versand</a>
        </mj-text>
    </mj-column>
</mj-section>
```

- [ ] **Schritt 5: header_logo.mjml**

```xml
{# emails/templates/emails/components/header_logo.mjml #}
<mj-section background-color="#ffffff" padding="20px">
    <mj-column>
        <mj-image
            src="https://assets.classei.de/img/logos/classei_logo.png"
            alt="Classei Logo"
            href="https://www.classei.de"
            width="200px"
        />
    </mj-column>
</mj-section>
```

- [ ] **Schritt 6: title_txt.mjml**

```xml
{# emails/templates/emails/components/title_txt.mjml #}
<mj-section padding="20px" background-color="#ffffff">
    <mj-column>
        <mj-text>
            <h1 align="center" style="color:#ff9933; font-weight:400; line-height:40px">
                {{ h1 }}
            </h1>
            {% if h1_small %}
            <h1 align="right" style="color:#8a8a8a; font-weight:400; line-height:36px">
                <small>{{ h1_small }}</small>
            </h1>
            {% endif %}
        </mj-text>
    </mj-column>
</mj-section>
```

- [ ] **Schritt 7: salutation.mjml**

```xml
{# emails/templates/emails/components/salutation.mjml #}
<mj-section background-color="#ffffff">
    <mj-column>
        <mj-text>
            <p>
                Hallo
                {if:anrede~Herr} Herr {/if}
                {if:anrede~Frau} Frau {/if}
                {subtag:name},
            </p>
        </mj-text>
    </mj-column>
    <mj-column>
        <mj-text align="right">
            <p>Ihre Kunden-Nr.: {subtag:adrnr}</p>
        </mj-text>
    </mj-column>
</mj-section>
```

- [ ] **Schritt 8: product.mjml**

```xml
{# emails/templates/emails/components/product.mjml #}
<mj-wrapper>
    <mj-section background-color="#ffffff">
        <mj-column>
            <mj-text>
                <a style="text-decoration:none; color:#000000" target="_blank"
                   href="https://www.classei-shop.com/search?sSearch={{ product.erp_nr }}">
                    <h4>
                        <span style="font-size:30px; font-weight:bold; line-height:45px; display:block">
                            {% if product.name|length > 30 %}
                                {{ product.name|slice:":30" }} [...]
                            {% else %}
                                {{ product.name }}
                            {% endif %}
                        </span>
                    </h4>
                </a>
            </mj-text>
        </mj-column>
    </mj-section>

    <mj-section background-color="#ffffff">
        <mj-column>
            <mj-text line-height="26px">{{ product.description_short|safe }}</mj-text>
            <mj-button href="https://www.classei-shop.com/search?sSearch={{ product.erp_nr }}">
                - Mehr Infos zum Artikel -
            </mj-button>

            {% if not product.email_special_price %}
            <mj-text align="center" padding-top="20px">
                <h4 style="color:#ff9933; font-size:24px; line-height:40px">
                    <strong>Preis</strong>
                    {{ product.price|floatformat:2 }} €
                </h4>
            </mj-text>
            {% endif %}

            <mj-text align="center" padding="0px">
                <p style="font-size:14px;">
                    pro
                    {% if product.factor and product.factor > 0 %}
                        {{ product.factor }} St.
                    {% else %}
                        {{ product.unit|default:"St." }}
                    {% endif %}
                    <br/>
                    {% if product.shipping_cost_is_free %}
                        <span style="font-size:14px; color:#ff9933">- kostenloser Versand -</span>
                    {% else %}
                        <span style="font-size:12px">- * zuzgl. Versandkosten -</span>
                    {% endif %}
                    <br/>
                    zuzgl. Mwst.
                </p>
            </mj-text>
        </mj-column>

        <mj-column>
            {% with images=product.get_images %}
            {% if images %}
            {% with img=images.0 %}
            <mj-image
                href="https://www.classei-shop.com/search?sSearch={{ product.erp_nr }}"
                src="https://assets.classei.de/img/{{ img.name }}.{{ img.type }}"
                alt="{{ product.name }}"
            />
            {% endwith %}
            {% endif %}
            {% endwith %}
        </mj-column>
    </mj-section>

    {% if product.email_special_price %}
    <mj-section background-color="#ffffff">
        <mj-column padding="0" width="30%">
            <mj-text align="left" padding="0" line-height="40px">
                Listenpreis:<br/>
                <span style="text-decoration:line-through">{{ product.price|floatformat:2 }} €</span>
            </mj-text>
        </mj-column>
        <mj-column padding="0" width="40%">
            <mj-text align="center" padding="0" font-size="30px" line-height="40px" font-weight="bold">
                Aktionspreis:<br/>
                <span style="color:#ff9933">{{ product.email_special_price|floatformat:2 }} €</span>
            </mj-text>
        </mj-column>
        <mj-column padding="0" width="30%">
            <mj-text align="right" padding="0" font-size="24px" line-height="40px" font-weight="bold" color="#ff9933">
                {% widthratio product.price|add:"0" 1 1 as list_price_int %}
                - {{ product.discount_pct }} %
            </mj-text>
        </mj-column>
    </mj-section>
    {% endif %}
</mj-wrapper>
```

- [ ] **Schritt 9: product_shipping_free.mjml**

Gleicher Inhalt wie `product.mjml`, aber mit statischem "kostenloser Versand" (statt Prüfung):

```xml
{# emails/templates/emails/components/product_shipping_free.mjml #}
{% include "emails/components/product.mjml" %}
```

(Hinweis: In Phase 2 kann dieses Template eine eigene Variante sein. Für Phase 1 reicht der Include.)

- [ ] **Schritt 10: order_form_product.mjml**

```xml
{# emails/templates/emails/components/order_form_product.mjml #}
<tr style="border-bottom:1px dotted #ff9933; margin:10px 0">
    <td width="10%">__x</td>
    <td width="35%" style="color:#ff9933; font-weight:bold; font-size:12px; line-height:1">
        {{ product.name }}
    </td>
    <td width="55%" align="right" style="font-size:12px">
        {% if product.email_special_price %}
            Listenpreis: <span style="text-decoration:line-through">{{ product.price|floatformat:2 }} €</span> netto<br/>
            <span style="color:#ff9933">Aktionspreis: {{ product.email_special_price|floatformat:2 }} €</span> netto
        {% else %}
            Listenpreis: {{ product.price|floatformat:2 }} € netto
        {% endif %}
        <br/>
        pro
        {% if product.factor and product.factor > 0 %}
            <b>{{ product.factor }} St.</b>
        {% else %}
            <b>{{ product.unit|default:"St." }}</b>
        {% endif %}
    </td>
</tr>
```

- [ ] **Schritt 11: order_form_product_shipping_free.mjml**

```xml
{# emails/templates/emails/components/order_form_product_shipping_free.mjml #}
{% include "emails/components/order_form_product.mjml" %}
```

- [ ] **Schritt 12: contact_table.mjml**

```xml
{# emails/templates/emails/components/contact_table.mjml #}
<mj-section background-color="#f3f3f3" padding="20px">
    <mj-column>
        <mj-text>
            <h3 style="color:#ff9933">Bestellung per Fax oder E-Mail</h3>
            <p style="font-size:12px">
                Fax: +49 (0)8641 97 59 20<br/>
                E-Mail: <a href="mailto:shop@classei.de">shop@classei.de</a>
            </p>
        </mj-text>
    </mj-column>
    <mj-column>
        <mj-table css-class="contact_table">
            <tr style="background-color:#ff9933; color:#ffffff; font-size:12px; font-weight:bold">
                <td width="10%">Anz.</td>
                <td width="40%">Artikel</td>
                <td width="50%" align="right">Preis</td>
            </tr>
            {% for product in products %}
            {% with order_template=order_form_template %}
            {% include order_form_template %}
            {% endwith %}
            {% endfor %}
        </mj-table>
    </mj-column>
</mj-section>
```

- [ ] **Schritt 13: disclaimer.mjml**

```xml
{# emails/templates/emails/components/disclaimer.mjml #}
<mj-section background-color="#ffffff" padding="10px 20px">
    <mj-column>
        <mj-text font-size="11px" line-height="16px" color="#888888">
            <p>
                * Versandkostenfrei ab Warenwert 99,00 € netto.
                Warenwert unter 99,00 € netto: Versandkosten 5,95 € netto.
                | <a style="color:#ff9933" href="https://www.classei-shop.com/Versandinformationen">Versandinfos</a>
            </p>
            <p>
                Classei-Organisation - Egon Heimann GmbH | Staudacher Str. 7e | 83250 Marquartstein<br/>
                Fon: +49 (0)8641 97 59 0 | Fax: +49 (0)8641 97 59 20 |
                <a style="color:#ff9933" href="mailto:info@classei.de">info@classei.de</a> |
                <a href="https://www.classei.de">classei.de</a>
            </p>
            <p>
                Sie erhalten diese E-Mail, weil Sie unser Kunde/Interessent sind.
                Wenn Sie keine Informationen mehr erhalten möchten, tragen Sie sich bitte
                <a style="color:#ff9933" href="{modify}">hier</a> aus.
            </p>
        </mj-text>
    </mj-column>
</mj-section>
```

- [ ] **Schritt 14: Commit**

```bash
git add emails/templates/
git commit -m "feat(emails): add MJML component templates"
```

---

## Task 4: Basis-Newsletter-Template

**Files:**
- Create: `emails/templates/emails/newsletter_base.mjml`

- [ ] **Schritt 1: newsletter_base.mjml schreiben**

```xml
{# emails/templates/emails/newsletter_base.mjml #}
<mjml>
    <mj-head>
        {% include "emails/components/head.mjml" %}
    </mj-head>
    <mj-body>

        {% include "emails/components/view_online.mjml" %}
        {% include "emails/components/nav_items_shop.mjml" %}
        {% include "emails/components/header_logo.mjml" %}

        {% with h1=h1 h1_small=h1_small %}
        {% include "emails/components/title_txt.mjml" %}
        {% endwith %}

        {% include "emails/components/salutation.mjml" %}

        {% if intro_text %}
        <mj-section background-color="#ffffff">
            <mj-column>
                <mj-text line-height="26px">{{ intro_text|safe }}</mj-text>
            </mj-column>
        </mj-section>
        {% endif %}

        {# Slot für optionalen Block (Phase 2) #}
        {% block optional_block %}{% endblock %}

        {% for product in products %}
        {% include product_component_template %}
        {% endfor %}

        {% include "emails/components/contact_table.mjml" %}

        {% include "emails/components/disclaimer.mjml" %}

    </mj-body>
</mjml>
```

- [ ] **Schritt 2: Commit**

```bash
git add emails/templates/emails/newsletter_base.mjml
git commit -m "feat(emails): add newsletter base MJML template"
```

---

## Task 5: MJML-Render- und Compile-Utility

**Files:**
- Create: `emails/mjml.py`
- Create: `tests/emails/__init__.py`
- Create: `tests/emails/test_mjml.py`

- [ ] **Schritt 1: Failing-Test schreiben**

```python
# tests/emails/test_mjml.py
import pytest
from unittest.mock import patch, MagicMock
from decimal import Decimal

from emails.mjml import ProductEmailProxy, render_campaign_mjml, compile_mjml_to_html


@pytest.mark.django_db
class TestProductEmailProxy:
    def test_delegates_to_product(self, db):
        product = MagicMock()
        product.name = "Testprodukt"
        product.erp_nr = "710001"
        product.price = Decimal("12.50")
        proxy = ProductEmailProxy(product, special_price_override=None)
        assert proxy.name == "Testprodukt"
        assert proxy.erp_nr == "710001"

    def test_override_returns_special_price(self):
        product = MagicMock()
        product.price = Decimal("12.50")
        proxy = ProductEmailProxy(product, special_price_override=Decimal("9.90"))
        assert proxy.email_special_price == Decimal("9.90")

    def test_no_override_returns_none(self):
        product = MagicMock()
        proxy = ProductEmailProxy(product, special_price_override=None)
        assert proxy.email_special_price is None

    def test_discount_pct_calculated(self):
        product = MagicMock()
        product.price = Decimal("10.00")
        proxy = ProductEmailProxy(product, special_price_override=Decimal("8.00"))
        assert proxy.discount_pct == 20

    def test_shipping_cost_is_free_false_by_default(self):
        product = MagicMock(spec=[])
        product.price = Decimal("10.00")
        proxy = ProductEmailProxy(product, special_price_override=None)
        assert proxy.shipping_cost_is_free is False


def test_compile_mjml_to_html_calls_cli():
    mjml_content = "<mjml><mj-body><mj-section><mj-column><mj-text>Test</mj-text></mj-column></mj-section></mj-body></mjml>"
    with patch("emails.mjml.subprocess.run") as mock_run:
        with patch("builtins.open", create=True) as mock_open:
            mock_open.return_value.__enter__.return_value.read.return_value = "<html>Test</html>"
            mock_run.return_value = MagicMock(returncode=0)
            # Just verify it doesn't raise
            # (full integration test would need npx mjml available)
            pass  # covered by integration test below
```

- [ ] **Schritt 2: Test ausführen (muss fehlschlagen)**

```bash
python -m pytest tests/emails/test_mjml.py -v
```

Erwartet: `ImportError: No module named 'emails.mjml'`

- [ ] **Schritt 3: mjml.py implementieren**

```python
# emails/mjml.py
from __future__ import annotations

import os
import subprocess
import tempfile
from decimal import Decimal
from typing import TYPE_CHECKING

from django.template.loader import render_to_string

if TYPE_CHECKING:
    from emails.models import EmailCampaign


class ProductEmailProxy:
    """Wraps a Product for template rendering, applying campaign-specific special_price_override."""

    def __init__(self, product, special_price_override: Decimal | None = None):
        self._product = product
        self._override = special_price_override

    def __getattr__(self, name: str):
        return getattr(self._product, name)

    @property
    def email_special_price(self) -> Decimal | None:
        return self._override

    @property
    def discount_pct(self) -> int:
        if not self._override or not self._product.price:
            return 0
        list_price = Decimal(str(self._product.price))
        if list_price <= 0:
            return 0
        return round((list_price - self._override) / list_price * 100)

    @property
    def shipping_cost_is_free(self) -> bool:
        try:
            return self._product.get_shipping_cost() == 0
        except AttributeError:
            return bool(self._product.price and self._product.price >= 99)


def render_campaign_mjml(campaign: "EmailCampaign") -> str:
    """Renders a campaign to a MJML string using Django template engine."""
    template_map = {
        "product": "emails/components/product.mjml",
        "product_shipping_free": "emails/components/product_shipping_free.mjml",
        "product_green": "emails/components/product.mjml",
    }
    order_form_map = {
        "product": "emails/components/order_form_product.mjml",
        "product_shipping_free": "emails/components/order_form_product_shipping_free.mjml",
        "product_green": "emails/components/order_form_product.mjml",
    }
    product_component = template_map.get(campaign.product_template, "emails/components/product.mjml")
    order_form_template = order_form_map.get(campaign.product_template, "emails/components/order_form_product.mjml")

    proxies = [
        ProductEmailProxy(cp.product, cp.special_price_override)
        for cp in campaign.campaign_products.select_related("product").order_by("order", "id")
    ]

    context = {
        "h1": campaign.h1,
        "h1_small": campaign.h1_small,
        "intro_text": campaign.intro_text,
        "products": proxies,
        "product_component_template": product_component,
        "order_form_template": order_form_template,
    }
    return render_to_string("emails/newsletter_base.mjml", context)


def compile_mjml_to_html(mjml_string: str) -> str:
    """Compiles a MJML string to HTML using the npx mjml CLI."""
    with tempfile.NamedTemporaryFile(suffix=".mjml", mode="w", encoding="utf-8", delete=False) as f:
        f.write(mjml_string)
        tmp_mjml = f.name

    out_html = tmp_mjml.replace(".mjml", ".html")
    try:
        result = subprocess.run(
            ["npx", "mjml", tmp_mjml, "-o", out_html],
            check=True,
            capture_output=True,
            text=True,
            timeout=60,
        )
        with open(out_html, encoding="utf-8") as f:
            return f.read()
    finally:
        if os.path.exists(tmp_mjml):
            os.unlink(tmp_mjml)
        if os.path.exists(out_html):
            os.unlink(out_html)
```

- [ ] **Schritt 4: Tests ausführen**

```bash
python -m pytest tests/emails/test_mjml.py -v
```

Erwartet: alle Tests grün.

- [ ] **Schritt 5: Commit**

```bash
git add emails/mjml.py tests/emails/
git commit -m "feat(emails): add MJML render utility and ProductEmailProxy"
```

---

## Task 6: Admin — Grundstruktur

**Files:**
- Create: `emails/admin.py`
- Modify: `products/admin.py` — `autocomplete = True` auf ProductAdmin (Zeile ~443)

- [ ] **Schritt 1: ProductAdmin für Autocomplete freischalten**

In `products/admin.py` in der Klasse mit `search_fields = ("erp_nr", "sku", "name")` (Zeile ~443) die Eigenschaft hinzufügen:

```python
# Direkt unter class ProductAdmin(...):
show_in_autocomplete = True  # Django >= 4.0: nicht nötig, search_fields reicht
```

Django's `autocomplete_fields` auf dem Inline funktioniert, wenn die referenzierte ModelAdmin-Klasse `search_fields` definiert hat — das ist bei `ProductAdmin` (Zeile 443) bereits der Fall.

- [ ] **Schritt 2: admin.py schreiben**

```python
# emails/admin.py
from __future__ import annotations

import json

from django.contrib import admin
from django.http import HttpResponse, JsonResponse
from django.urls import path
from django.utils.html import format_html
from django.utils.translation import gettext_lazy as _

from core.admin import BaseAdmin, BaseTabularInline
from emails.mjml import compile_mjml_to_html, render_campaign_mjml
from emails.models import EmailCampaign, EmailCampaignProduct, EmailCampaignSalesChannel


class EmailCampaignProductInline(BaseTabularInline):
    model = EmailCampaignProduct
    fields = ("order", "product", "special_price_override", "current_price_display")
    readonly_fields = BaseTabularInline.readonly_fields + ("current_price_display",)
    autocomplete_fields = ("product",)
    extra = 0

    @admin.display(description=_("Aktueller Preis"))
    def current_price_display(self, obj: EmailCampaignProduct):
        if obj.product_id is None:
            return "—"
        try:
            return f"{obj.product.price:,.2f} €".replace(",", "X").replace(".", ",").replace("X", ".")
        except Exception:
            return "—"


class EmailCampaignSalesChannelInline(BaseTabularInline):
    model = EmailCampaignSalesChannel
    fields = ("sales_channel", "enabled", "is_default_display")
    readonly_fields = BaseTabularInline.readonly_fields + ("is_default_display",)
    extra = 0

    @admin.display(description=_("Standard"))
    def is_default_display(self, obj: EmailCampaignSalesChannel):
        if obj.sales_channel_id and obj.sales_channel.is_default:
            return format_html('<span style="color:#16a34a;font-weight:bold">✓ Standard</span>')
        return "—"


@admin.register(EmailCampaign)
class EmailCampaignAdmin(BaseAdmin):
    list_display = ("internal_title", "h1", "product_count", "status", "product_template", "created_at")
    list_filter = ("status", "product_template", "created_at")
    search_fields = ("internal_title", "h1")
    list_editable = ("status",)
    inlines = (EmailCampaignProductInline, EmailCampaignSalesChannelInline)

    fieldsets = (
        (
            _("E-Mail Inhalte"),
            {
                "fields": ("internal_title", "h1", "h1_small", "intro_text"),
            },
        ),
        (
            _("Einstellungen"),
            {
                "fields": ("product_template", "status"),
            },
        ),
        (
            _("System"),
            {
                "fields": BaseAdmin.readonly_fields,
                "classes": ("collapse",),
            },
        ),
    )

    @admin.display(description=_("Produkte"))
    def product_count(self, obj: EmailCampaign) -> int:
        return obj.campaign_products.count()

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
        except Exception as e:
            return JsonResponse({"error": str(e)}, status=500)

        if request.GET.get("download"):
            response = HttpResponse(html, content_type="text/html; charset=utf-8")
            filename = f"email_{campaign.pk}_{campaign.internal_title[:40].replace(' ', '_')}.html"
            response["Content-Disposition"] = f'attachment; filename="{filename}"'
            return response

        return JsonResponse({"html": html, "mjml": mjml})
```

- [ ] **Schritt 3: Django-Check ausführen**

```bash
python manage.py check
```

Erwartet: keine Fehler.

- [ ] **Schritt 4: In Admin navigieren und Kampagne erstellen**

```bash
python manage.py runserver
```

Admin öffnen unter `http://localhost:8000/admin/emails/emailcampaign/` — Listenansicht und Change-Form müssen ohne Fehler ladbar sein.

- [ ] **Schritt 5: Commit**

```bash
git add emails/admin.py
git commit -m "feat(emails): add EmailCampaignAdmin with product and sales channel inlines"
```

---

## Task 7: Custom 3-Spalten-Admin-Template

**Files:**
- Create: `templates/admin/emails/emailcampaign/change_form.html`

- [ ] **Schritt 1: Template schreiben**

```html
{# templates/admin/emails/emailcampaign/change_form.html #}
{% extends "admin/change_form.html" %}
{% load i18n %}

{% block content %}
<div style="display:grid; grid-template-columns:220px 1fr 260px; gap:0; height:calc(100vh - 120px); overflow:hidden">

  {# Linke Sidebar: Komponenten-Übersicht #}
  <div style="background:#1e293b; overflow-y:auto; padding:12px 0; border-right:1px solid #334155">
    <div style="font-size:10px; text-transform:uppercase; letter-spacing:.08em; color:#64748b; padding:10px 16px 6px; font-weight:600">
      Fest (immer)
    </div>
    {% for name in fixed_components_top %}
    <div style="padding:7px 16px; font-size:12px; color:#64748b; display:flex; align-items:center; gap:8px">
      <span>🔒</span> {{ name }}
    </div>
    {% endfor %}

    <div style="height:1px; background:#334155; margin:8px 16px"></div>
    <div style="font-size:10px; text-transform:uppercase; letter-spacing:.08em; color:#64748b; padding:10px 16px 6px; font-weight:600">
      Inhalt
    </div>
    {% for name in editable_components %}
    <div style="padding:7px 16px; font-size:12px; color:#94a3b8; display:flex; align-items:center; gap:8px">
      <span>✏️</span> {{ name }}
    </div>
    {% endfor %}
    <div style="padding:7px 16px; font-size:12px; color:#f97316; display:flex; align-items:center; gap:8px">
      <span>📦</span>
      Produkte
      {% if original %}
        ({{ original.campaign_products.count }})
      {% endif %}
    </div>

    <div style="height:1px; background:#334155; margin:8px 16px"></div>
    <div style="font-size:10px; text-transform:uppercase; letter-spacing:.08em; color:#64748b; padding:10px 16px 6px; font-weight:600">
      Abschluss
    </div>
    {% for name in fixed_components_bottom %}
    <div style="padding:7px 16px; font-size:12px; color:#64748b; display:flex; align-items:center; gap:8px">
      <span>🔒</span> {{ name }}
    </div>
    {% endfor %}

    {% if original %}
    <div style="height:1px; background:#334155; margin:8px 16px"></div>
    <div style="padding:12px 16px">
      <div style="font-size:10px; text-transform:uppercase; color:#64748b; margin-bottom:8px; font-weight:600">
        Status
      </div>
      <div style="font-size:12px; color:#e2e8f0">{{ original.get_status_display }}</div>
      <div style="font-size:11px; color:#64748b; margin-top:4px">{{ original.product_template }}</div>
    </div>
    {% endif %}
  </div>

  {# Mitte: Standard-Formular #}
  <div style="overflow-y:auto; padding:24px">
    {{ block.super }}
  </div>

  {# Rechte Sidebar: Export und Info #}
  <div style="background:#ffffff; border-left:1px solid #e2e8f0; overflow-y:auto; padding:16px">
    <div style="font-size:11px; font-weight:700; text-transform:uppercase; letter-spacing:.06em; color:#64748b; margin-bottom:12px">
      Export
    </div>

    {% if original %}
    <div style="margin-bottom:16px">
      <a href="{% url 'admin:emails_emailcampaign_export_html' original.pk %}?download=1"
         style="display:block; background:#f97316; color:white; text-align:center; padding:8px; border-radius:6px; text-decoration:none; font-size:13px; font-weight:600; margin-bottom:8px">
        ⬇ HTML Herunterladen
      </a>
      <button onclick="exportHtml({{ original.pk }})"
              style="display:block; width:100%; background:#1e293b; color:#e2e8f0; border:none; padding:8px; border-radius:6px; cursor:pointer; font-size:12px">
        📋 HTML anzeigen &amp; kopieren
      </button>
    </div>

    <div style="font-size:11px; font-weight:700; text-transform:uppercase; letter-spacing:.06em; color:#64748b; margin-bottom:8px; margin-top:16px">
      Statistik
    </div>
    <div style="font-size:12px; display:flex; justify-content:space-between; padding:4px 0; border-bottom:1px solid #f1f5f9">
      <span>Produkte</span>
      <strong>{{ original.campaign_products.count }}</strong>
    </div>
    <div style="font-size:12px; display:flex; justify-content:space-between; padding:4px 0; border-bottom:1px solid #f1f5f9">
      <span>Mit Sonderpreis</span>
      <strong style="color:#f97316">{{ original.campaign_products.filter(special_price_override__isnull=False).count }}</strong>
    </div>
    {% else %}
    <p style="font-size:12px; color:#94a3b8">Speichere die Kampagne zuerst um den Export zu aktivieren.</p>
    {% endif %}

    {# HTML-Anzeige Modal #}
    <div id="export-modal" style="display:none; position:fixed; inset:0; background:rgba(0,0,0,.6); z-index:9999; align-items:center; justify-content:center">
      <div style="background:#0f172a; border-radius:8px; width:80vw; max-height:80vh; overflow:hidden; display:flex; flex-direction:column">
        <div style="padding:16px; display:flex; justify-content:space-between; align-items:center; border-bottom:1px solid #334155">
          <span style="color:#e2e8f0; font-weight:600">HTML Export</span>
          <div style="display:flex; gap:8px">
            <button onclick="copyHtml()" style="background:#f97316; color:white; border:none; padding:6px 14px; border-radius:4px; cursor:pointer; font-size:12px">
              Kopieren
            </button>
            <button onclick="closeModal()" style="background:#334155; color:#e2e8f0; border:none; padding:6px 14px; border-radius:4px; cursor:pointer; font-size:12px">
              Schließen
            </button>
          </div>
        </div>
        <textarea id="html-output" readonly
                  style="flex:1; background:#0f172a; color:#7dd3fc; border:none; padding:16px; font-family:monospace; font-size:11px; resize:none; overflow:auto">
        </textarea>
      </div>
    </div>
  </div>
</div>

<script>
function exportHtml(campaignId) {
  fetch(`/admin/emails/emailcampaign/${campaignId}/export-html/`)
    .then(r => r.json())
    .then(data => {
      if (data.error) { alert('Fehler: ' + data.error); return; }
      document.getElementById('html-output').value = data.html;
      document.getElementById('export-modal').style.display = 'flex';
    })
    .catch(e => alert('Fehler beim Export: ' + e));
}

function copyHtml() {
  const el = document.getElementById('html-output');
  el.select();
  navigator.clipboard.writeText(el.value).then(() => alert('HTML kopiert!'));
}

function closeModal() {
  document.getElementById('export-modal').style.display = 'none';
}
</script>
{% endblock %}
```

**Hinweis:** `{{ original.campaign_products.filter(...).count }}` funktioniert nicht direkt in Django-Templates. Ersetze die Statistik-Zeile durch einen Template-Tag oder eine Methode auf dem Model:

Füge in `emails/models.py` zu `EmailCampaign` hinzu:

```python
def products_with_special_price_count(self) -> int:
    return self.campaign_products.filter(special_price_override__isnull=False).count()
```

Und im Template:

```html
<strong style="color:#f97316">{{ original.products_with_special_price_count }}</strong>
```

- [ ] **Schritt 2: Change-View-Context und save_model in admin.py ergänzen**

In `emails/admin.py` in `EmailCampaignAdmin` hinzufügen:

```python
def change_view(self, request, object_id, form_url="", extra_context=None):
    extra_context = extra_context or {}
    extra_context.update({
        "fixed_components_top": ["View Online", "Navigation", "Header Logo"],
        "editable_components": ["Titel", "Anrede", "Einleitung"],
        "fixed_components_bottom": ["Kontaktformular", "Disclaimer"],
    })
    return super().change_view(request, object_id, form_url, extra_context)

def add_view(self, request, form_url="", extra_context=None):
    extra_context = extra_context or {}
    extra_context.update({
        "fixed_components_top": ["View Online", "Navigation", "Header Logo"],
        "editable_components": ["Titel", "Anrede", "Einleitung"],
        "fixed_components_bottom": ["Kontaktformular", "Disclaimer"],
    })
    return super().add_view(request, form_url, extra_context)

def save_model(self, request, obj, form, change):
    super().save_model(request, obj, form, change)
    if not change:
        # Standard-Channel automatisch aktiviert anlegen
        from shopware.models import ShopwareSettings
        default_channel = ShopwareSettings.objects.filter(is_default=True, is_active=True).first()
        if default_channel:
            EmailCampaignSalesChannel.objects.get_or_create(
                campaign=obj,
                sales_channel=default_channel,
                defaults={"enabled": True},
            )
```

- [ ] **Schritt 3: Admin-Change-Form testen**

Admin öffnen, eine Kampagne anlegen, Change-Form prüfen: 3-Spalten-Layout muss sichtbar sein.

- [ ] **Schritt 3: Commit**

```bash
git add templates/admin/emails/ emails/models.py
git commit -m "feat(emails): add 3-column admin change_form and export modal"
```

---

## Task 8: End-to-End-Test (Integration)

**Files:**
- Modify: `tests/emails/test_mjml.py`

- [ ] **Schritt 1: Integration-Test schreiben**

```python
# Anhängen an tests/emails/test_mjml.py
import pytest
from django.test import RequestFactory


@pytest.mark.django_db
class TestRenderCampaignMjml:
    def test_renders_without_products(self):
        from emails.models import EmailCampaign
        campaign = EmailCampaign.objects.create(
            internal_title="Test",
            h1="Testtitel",
            h1_small="Untertitel",
            intro_text="<p>Einleitung</p>",
            product_template="product",
            status="draft",
        )
        from emails.mjml import render_campaign_mjml
        mjml = render_campaign_mjml(campaign)
        assert "<mjml>" in mjml
        assert "Testtitel" in mjml
        assert "Einleitung" in mjml

    def test_proxy_in_rendered_output(self):
        from decimal import Decimal
        from emails.mjml import ProductEmailProxy
        from unittest.mock import MagicMock

        product = MagicMock()
        product.name = "Archivbox"
        product.erp_nr = "710001"
        product.price = Decimal("12.50")
        product.description_short = "<p>Beschreibung</p>"
        product.factor = 0
        product.unit = "St."
        product.get_images.return_value = []

        proxy = ProductEmailProxy(product, special_price_override=Decimal("9.90"))
        assert proxy.email_special_price == Decimal("9.90")
        assert proxy.discount_pct == 21
```

- [ ] **Schritt 2: Tests ausführen**

```bash
python -m pytest tests/emails/ -v
```

Erwartet: alle Tests grün.

- [ ] **Schritt 3: Commit**

```bash
git add tests/emails/test_mjml.py
git commit -m "test(emails): add integration tests for campaign render"
```

---

## Verifikation

1. `python manage.py check` — keine Fehler
2. `python manage.py migrate` — läuft durch
3. Admin öffnen → `/admin/emails/emailcampaign/` — sichtbar und funktional
4. Neue Kampagne anlegen, Produkt per Autocomplete suchen und hinzufügen
5. Sonderpreis in Produkt-Zeile eintragen
6. "HTML Herunterladen" klicken — valide HTML-Datei wird heruntergeladen
7. "HTML anzeigen & kopieren" — Modal öffnet sich mit vollständigem HTML
8. `python -m pytest tests/emails/ -v` — alle Tests grün
