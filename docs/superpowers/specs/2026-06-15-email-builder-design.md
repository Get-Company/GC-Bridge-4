# Email-Builder App — Design Spec

**Datum:** 2026-06-15  
**Status:** Approved  
**Scope:** Phase 1 — Builder + HTML-Export, kein Versand

---

## Kontext

Classei verschickt regelmäßig Marketing-E-Mails an ~2.000 Empfänger. Bisher wurden diese manuell als MJML-Dateien zusammengebaut (Vorlagen in `old-emails/`). AcyMailing wird abgelöst. Ziel ist eine Django-Admin-Oberfläche, mit der neue E-Mails aus bestehenden MJML-Komponenten zusammengestellt, Produkte mit Sonderpreisen hinzugefügt und fertiges HTML exportiert werden kann — ohne Kenntnisse von MJML oder Jinja.

---

## Neue Django-App: `emails`

Untergebracht in `/mnt/daten1tb/python/GC-Bridge-4/emails/`.

---

## Datenmodell

### `EmailCampaign`

| Feld | Typ | Beschreibung |
|---|---|---|
| `internal_title` | CharField | Interner Name, z.B. "Archivierung 2025-01" |
| `h1` | CharField | Haupt-Überschrift (→ `title_txt.mjml`) |
| `h1_small` | CharField | Untertitel (→ `title_txt.mjml`) |
| `intro_text` | TextField | Einleitungstext als HTML-Fragment |
| `product_template` | CharField choices | `product` / `product_shipping_free` / `product_green` |
| `status` | CharField choices | `draft` / `ready` / `exported` |
| `created_at` | DateTimeField | auto_now_add |
| `updated_at` | DateTimeField | auto_now |

### `EmailCampaignProduct`

| Feld | Typ | Beschreibung |
|---|---|---|
| `campaign` | FK → EmailCampaign | on_delete=CASCADE |
| `product` | FK → `products.Product` | on_delete=PROTECT |
| `special_price_override` | DecimalField (nullable) | Überschreibt `Product.special_price` für diese E-Mail |
| `order` | PositiveIntegerField | Reihenfolge in der E-Mail |

**Meta:** `unique_together = ('campaign', 'product')`, `ordering = ('order',)`

### `EmailCampaignSalesChannel`

| Feld | Typ | Beschreibung |
|---|---|---|
| `campaign` | FK → EmailCampaign | on_delete=CASCADE |
| `sales_channel` | FK → `shopware.ShopwareSettings` | on_delete=CASCADE |
| `enabled` | BooleanField | Default: True für Standard-Channel, False für weitere |

Der Standard-Channel (`ShopwareSettings.is_default=True`) wird bei Campaign-Erstellung automatisch als aktiviert angelegt und ist im UI nicht deaktivierbar.

---

## Admin UI

### 3-Spalten-Layout (Unfold Admin, custom `change_form.html`)

**Linke Sidebar (240px)**

Zwei Gruppen:

*Fest (immer enthalten, keine Konfiguration):*
- View Online (`view_online.mjml`)
- Navigation (`nav_items_shop.mjml`)
- Header Logo (`header_logo.mjml`)
- Kontaktformular (`contact_table.mjml`)
- Blog Content (`blog_acymailing.mjml`)
- Disclaimer (`disclaimer.mjml`)

*Konfigurierbar (klickbar, öffnet Formular in Mitte):*
- Titel → Felder `h1`, `h1_small`
- Anrede → statischer Block (AcyMailing-Tags bleiben vorerst unverändert)
- Einleitung → Feld `intro_text` (Textarea mit HTML)
- Produkte → Produkttabelle
- *(Phase 2: Schrank-Block — Slot bereits im Template vorbereitet)*

**Mittlerer Bereich (flex)**

Zeigt Formular des aktiv gewählten Blocks. Umschaltung per einfachem JS (Tab-Switching, kein Full-Page-Reload). Für den Produkte-Block:
- Tabelle: ERP-Nr., Bezeichnung, Listenpreis, Sonderpreis-Eingabefeld, Reihenfolge-Griff
- Suchfeld oben: Live-Autocomplete (AJAX-View filtert `Product` nach Name oder `erp_nr`)
- Ergebnis wird als neue Zeile in die Tabelle eingefügt

**Rechte Sidebar (280px)**

- **Sales Channels:** Checkboxen/Toggles für alle aktiven `ShopwareSettings`; Standard-Channel als Badge (nicht abwählbar)
- **Template:** Dropdown für `product_template`
- **Zusammenfassung:** Anzahl Produkte, davon mit Sonderpreis
- **Export-Buttons:**
  - *Vorschau MJML* — öffnet Modal mit MJML-Code (read-only)
  - *HTML Export* — kompiliert via `mjml` CLI, öffnet Modal mit HTML + Download-Button

---

## MJML-Generierung

### Template-Datei

Neue Basis-Vorlage: `templates/emails/newsletter_base.mjml`

Orientiert an `old-emails/2025/08_moebel/newsletter.mjml`, verwendet Django-Template-Syntax (`{% include %}`, `{% with %}`, `{% for %}`). Enthält einen optionalen `{% block optional_block %}{% endblock %}` Slot vor dem Produkt-Listing (für Phase-2 Schrank-Block).

### Render-Ablauf (Python)

```python
# emails/mjml.py
def render_campaign_mjml(campaign: EmailCampaign) -> str:
    context = {
        "h1": campaign.h1,
        "h1_small": campaign.h1_small,
        "intro_text": campaign.intro_text,
        "products": [cp.product for cp in campaign.emailcampaignproduct_set.select_related("product")],
        # special_price_override wird per Proxy/Wrapper auf das Product-Objekt gesetzt
    }
    return render_to_string("emails/newsletter_base.mjml", context)

def compile_mjml_to_html(mjml_string: str) -> str:
    with tempfile.NamedTemporaryFile(suffix=".mjml", mode="w", delete=False) as f:
        f.write(mjml_string)
        tmp_path = f.name
    out_path = tmp_path.replace(".mjml", ".html")
    subprocess.run(["mjml", tmp_path, "-o", out_path], check=True, timeout=30)
    with open(out_path) as f:
        html = f.read()
    os.unlink(tmp_path)
    os.unlink(out_path)
    return html
```

**Product-Wrapper:** Da `special_price_override` pro Campaign-Produkt gespeichert wird, wird beim Rendern ein leichtgewichtiger Proxy verwendet, der `get_special_price()` / `get_list_price()` auf den Override umleitet, ohne das `Product`-Modell zu ändern.

---

## Sonderpreise & Sales Channels (Export)

Beim HTML-Export erscheint ein optionaler Schritt: *"Sonderpreise jetzt in Shopware setzen?"*

- Für jeden `EmailCampaignProduct` mit `special_price_override`: Shopware-API-Call setzt `special_price` auf dem Standard-Channel (nutzt existierende Shopware-Sync-Logik aus `shopware/`)
- Für jeden aktivierten weiteren Sales Channel: gleicher Preis auf dem jeweiligen Channel

Dieser Schritt ist **on-demand**, nicht automatisch beim Speichern — verhindert versehentliche Preisänderungen.

---

## Bestehende Templates (Wiederverwendung)

Alle Komponenten unter `templates/classei/email/template/*.mjml` bleiben unverändert. Die neue App referenziert sie via `{% include %}` — kein Copy-Paste, kein Doppeln.

Relevante Komponenten:
- `title_txt.mjml` — nimmt `h1`, `h1_small` via `{% with %}`
- `product.mjml` / `product_shipping_free.mjml` / `product_green.mjml` — nehmen `product`-Objekt
- `order_form_product.mjml` / `order_form_product_shipping_free.mjml` — gleiche `product`-Objekte
- `salutation.mjml` — statisch, keine Variablen von der App

---

## Navigation im Unfold Admin

Eintrag in `UNFOLD["SIDEBAR"]["navigation"]` unter einer neuen Gruppe "E-Mails":
- E-Mail-Kampagnen (Liste + Neu)

---

## Außerhalb des Scope (Phase 1)

- Schrank-Block UI (Architektur-Slot vorbereitet, Felder kommen Phase 2)
- ESP-Integration / direkter Versand
- Empfänger-Verwaltung / Unsubscribe
- Vorschau im Browser (Inline-Rendering in der App)

---

## Verifikation

1. Migration läuft durch: `manage.py migrate`
2. `EmailCampaign` ist im Admin sichtbar, 3-Spalten-Layout korrekt
3. Produkt-Suche: Eingabe "710" → Autocomplete zeigt Treffer aus `Product`
4. MJML-Render: Campaign mit 2 Produkten → valides MJML-Output
5. HTML-Export: `mjml` CLI kompiliert ohne Fehler, HTML enthält Produktnamen und Sonderpreise
6. Sales Channel Toggle: Aktivierter Channel erscheint im Export-Dialog
