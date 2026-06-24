# EU-Konformitätserklärung (Anhang VIII) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** EU-Konformitätserklärung nach PPWR Anhang VIII — verknüpft mit PackagingLabel, speicherbar, editierbar, mit PDF-Export und öffentlicher URL für QR-Code-Scan.

**Architecture:** Neues Modell `KonformitaetsErklaerung` (OneToOne auf `PackagingLabel`) in der `ppwr`-App. Admin-UI über Unfold mit Fieldset-Tabs und PDF-Aktion. WeasyPrint erzeugt das A4-PDF aus einem Django-Template. Zwei öffentliche Views (HTML + PDF-Download) ohne Login-Pflicht unter `/ppwr/erklaerung/<slug>/`.

**Tech Stack:** Django 4.x, django-unfold, WeasyPrint, PostgreSQL, Tailwind CSS (via Unfold)

## Global Constraints

- Python-Importe nach isort-Standard (stdlib → third-party → local)
- Alle user-facing Strings in `_()` / `gettext_lazy` eingewickelt
- Modelle erben von `core.models.BaseModel` (liefert `created_at`, `updated_at`, `pk`)
- Admin-Klassen erben von `core.admin.BaseAdmin`
- PDF-Ausgabepfad: `settings.DOCUMENT_PDF_ROOT / "ppwr"` (bereits genutzt von `PackagingLabelPdfService`)
- Keine neuen Python-Pakete — WeasyPrint ist bereits in `requirements.txt`
- Kein Login für öffentliche Views (QR-Code-Scan muss ohne Account funktionieren)
- `ppwr`-App hat aktuell kein `views.py` und kein `urls.py` — beide werden neu angelegt

---

## File Map

| Datei | Aktion | Verantwortung |
|-------|--------|---------------|
| `ppwr/models.py` | Modify | `KonformitaetsErklaerung`-Modell hinzufügen |
| `ppwr/migrations/XXXX_add_konformitaetserklaerung.py` | Create | Datenbankschema |
| `ppwr/services.py` | Modify | `KonformitaetsErklaerungPdfService` hinzufügen |
| `ppwr/views.py` | Create | Öffentliche HTML- und PDF-Views |
| `ppwr/urls.py` | Create | URL-Routen für die ppwr-App |
| `GC_Bridge_4/urls.py` | Modify | `ppwr.urls` einbinden |
| `ppwr/admin.py` | Modify | `KonformitaetsErklaerungAdmin` + Inline registrieren |
| `ppwr/templates/ppwr/konformitaetserklaerung.html` | Create | Öffentliche A4-Ansicht (HTML + WeasyPrint-Basis) |
| `ppwr/templates/admin/ppwr/konformitaet_pdf_button.html` | Create | Admin-Button "PDF erzeugen" |
| `tests/ppwr/test_konformitaet.py` | Create | Modell- und View-Tests |

---

### Task 1: Modell `KonformitaetsErklaerung`

**Files:**
- Modify: `ppwr/models.py`
- Create: `tests/ppwr/test_konformitaet.py`

**Interfaces:**
- Produces: `KonformitaetsErklaerung` mit Feldern `packaging_label`, `declaration_number`, `erzeuger_name_anschrift`, `gegenstand_beschreibung`, `harmonisierung`, `normen_spezifikationen`, `notifizierte_stelle`, `zusaetzliche_angaben`, `ausstellungsort`, `ausstellungsdatum`, `unterzeichner_name`, `unterzeichner_funktion`, `pdf_filename`, `pdf_generated_at`

- [ ] **Step 1: Test schreiben (schlägt fehl)**

```python
# tests/ppwr/test_konformitaet.py
import pytest
from django.utils import timezone
from ppwr.models import KonformitaetsErklaerung, PackagingLabel
from organization.models import CompanyProfile


@pytest.mark.django_db
def test_konformitaet_erstellen(packaging_label_fixture):
    erklaerung = KonformitaetsErklaerung.objects.create(
        packaging_label=packaging_label_fixture,
        declaration_number="EU-KE-2026-001",
        erzeuger_name_anschrift="Musterfirma GmbH\nMusterstraße 1\n12345 Musterstadt",
        gegenstand_beschreibung="Faltschachtel 200x150x50mm, Wellpappe",
        harmonisierung="PPWR (EU) 2025/...",
        normen_spezifikationen="EN 13431",
        ausstellungsort="Musterstadt",
        ausstellungsdatum=timezone.now().date(),
        unterzeichner_name="Max Mustermann",
        unterzeichner_funktion="Geschäftsführer",
    )
    assert erklaerung.pk is not None
    assert erklaerung.packaging_label == packaging_label_fixture
    assert str(erklaerung) == "EU-KE-2026-001"


@pytest.mark.django_db
def test_konformitaet_one_to_one(packaging_label_fixture):
    KonformitaetsErklaerung.objects.create(
        packaging_label=packaging_label_fixture,
        declaration_number="EU-KE-2026-001",
        erzeuger_name_anschrift="Test GmbH",
        gegenstand_beschreibung="Test-Verpackung",
        harmonisierung="PPWR",
        normen_spezifikationen="EN 13431",
        ausstellungsort="Teststadt",
        ausstellungsdatum=timezone.now().date(),
        unterzeichner_name="Test Person",
        unterzeichner_funktion="Manager",
    )
    from django.db import IntegrityError
    with pytest.raises(IntegrityError):
        KonformitaetsErklaerung.objects.create(
            packaging_label=packaging_label_fixture,
            declaration_number="EU-KE-2026-002",
            erzeuger_name_anschrift="Test GmbH",
            gegenstand_beschreibung="Test-Verpackung 2",
            harmonisierung="PPWR",
            normen_spezifikationen="EN 13431",
            ausstellungsort="Teststadt",
            ausstellungsdatum=timezone.now().date(),
            unterzeichner_name="Test Person",
            unterzeichner_funktion="Manager",
        )
```

Fixture in `conftest.py` anlegen falls nicht vorhanden:
```python
# tests/conftest.py (ergänzen)
import pytest
from organization.models import CompanyProfile
from ppwr.models import PackagingLabel


@pytest.fixture
def packaging_label_fixture(db):
    company, _ = CompanyProfile.objects.get_or_create(
        id=1,
        defaults={"name": "Test GmbH", "legal_name": "Test GmbH", "street": "Teststr. 1",
                  "postal_code": "12345", "city": "Teststadt", "country": "Deutschland"}
    )
    return PackagingLabel.objects.create(
        name="Test-Etikett",
        slug="test-etikett",
        company=company,
        unique_packaging_id="PKG-2026-001",
    )
```

- [ ] **Step 2: Test ausführen — erwarte FAIL**

```bash
cd /mnt/daten1tb/python/GC-Bridge-4
python -m pytest tests/ppwr/test_konformitaet.py -v 2>&1 | tail -20
```

Erwartete Ausgabe: `ImportError: cannot import name 'KonformitaetsErklaerung'`

- [ ] **Step 3: Modell in `ppwr/models.py` hinzufügen**

Am Ende der Datei (nach der `PackagingLabel`-Klasse) einfügen:

```python
class KonformitaetsErklaerung(BaseModel):
    packaging_label = models.OneToOneField(
        PackagingLabel,
        on_delete=models.CASCADE,
        related_name="konformitaetserklaerung",
        verbose_name=_("Verpackungsetikett"),
    )
    declaration_number = models.CharField(
        max_length=100,
        verbose_name=_("Erklärungsnummer"),
        help_text=_("Anhang VIII, Kopf: Eindeutige Kennnummer der Erklärung."),
    )
    erzeuger_name_anschrift = models.TextField(
        verbose_name=_("Name und Anschrift des Erzeugers"),
        help_text=_("Anhang VIII, Nr. 2: Name, Anschrift und ggf. Bevollmächtigter des Erzeugers."),
    )
    gegenstand_beschreibung = models.TextField(
        verbose_name=_("Beschreibung der Verpackung"),
        help_text=_("Anhang VIII, Nr. 4: Kennung der Verpackung zwecks Rückverfolgbarkeit."),
    )
    harmonisierung = models.TextField(
        verbose_name=_("Harmonisierung"),
        help_text=_("Anhang VIII, Nr. 5: Verweis auf die angewandten Rechtsakte der Union, z. B. PPWR (EU) 2025/..."),
    )
    normen_spezifikationen = models.TextField(
        verbose_name=_("Normen / Spezifikationen"),
        help_text=_("Anhang VIII, Nr. 6: Harmonisierte Normen oder gemeinsame Spezifikationen."),
    )
    notifizierte_stelle = models.TextField(
        blank=True,
        default="",
        verbose_name=_("Notifizierte Stelle"),
        help_text=_("Anhang VIII, Nr. 7: Name, Anschrift, Kennnummer der notifizierten Stelle (falls anwendbar)."),
    )
    zusaetzliche_angaben = models.TextField(
        blank=True,
        default="",
        verbose_name=_("Zusätzliche Angaben"),
        help_text=_("Anhang VIII, Nr. 8: Optionale weitere Angaben."),
    )
    ausstellungsort = models.CharField(
        max_length=255,
        verbose_name=_("Ausstellungsort"),
    )
    ausstellungsdatum = models.DateField(
        verbose_name=_("Ausstellungsdatum"),
    )
    unterzeichner_name = models.CharField(
        max_length=255,
        verbose_name=_("Name des Unterzeichners"),
    )
    unterzeichner_funktion = models.CharField(
        max_length=255,
        verbose_name=_("Funktion des Unterzeichners"),
    )
    pdf_filename = models.CharField(
        max_length=255,
        blank=True,
        default="",
        editable=False,
        verbose_name=_("PDF-Dateiname"),
    )
    pdf_generated_at = models.DateTimeField(
        null=True,
        blank=True,
        editable=False,
        verbose_name=_("PDF erstellt am"),
    )

    class Meta:
        verbose_name = _("EU-Konformitätserklärung")
        verbose_name_plural = _("EU-Konformitätserklärungen")
        ordering = ("-ausstellungsdatum",)

    def __str__(self) -> str:
        return self.declaration_number
```

- [ ] **Step 4: Migration erstellen**

```bash
python manage.py makemigrations ppwr --name add_konformitaetserklaerung
```

Erwartete Ausgabe: `Migrations for 'ppwr': ppwr/migrations/XXXX_add_konformitaetserklaerung.py`

- [ ] **Step 5: Migration anwenden**

```bash
python manage.py migrate ppwr
```

Erwartete Ausgabe: `Applying ppwr.XXXX_add_konformitaetserklaerung... OK`

- [ ] **Step 6: Tests ausführen — erwarte PASS**

```bash
python -m pytest tests/ppwr/test_konformitaet.py -v
```

Erwartete Ausgabe: `2 passed`

- [ ] **Step 7: Commit**

```bash
git add ppwr/models.py ppwr/migrations/ tests/ppwr/test_konformitaet.py
git commit -m "feat(ppwr): KonformitaetsErklaerung-Modell nach Anhang VIII"
```

---

### Task 2: PDF-Service mit WeasyPrint

**Files:**
- Modify: `ppwr/services.py`
- Create: `ppwr/templates/ppwr/konformitaetserklaerung.html`

**Interfaces:**
- Consumes: `KonformitaetsErklaerung` (aus Task 1)
- Produces: `KonformitaetsErklaerungPdfService` mit Methoden `generate_pdf(erklaerung) -> Path` und `get_pdf_path(erklaerung) -> Path | None`

- [ ] **Step 1: Test schreiben**

```python
# in tests/ppwr/test_konformitaet.py ergänzen:

@pytest.mark.django_db
def test_pdf_service_generate(packaging_label_fixture, tmp_path, settings):
    from ppwr.services import KonformitaetsErklaerungPdfService
    settings.DOCUMENT_PDF_ROOT = str(tmp_path)

    erklaerung = KonformitaetsErklaerung.objects.create(
        packaging_label=packaging_label_fixture,
        declaration_number="EU-KE-2026-001",
        erzeuger_name_anschrift="Test GmbH\nTeststr. 1\n12345 Teststadt",
        gegenstand_beschreibung="Faltschachtel",
        harmonisierung="PPWR (EU) 2025/...",
        normen_spezifikationen="EN 13431",
        ausstellungsort="Teststadt",
        ausstellungsdatum=timezone.now().date(),
        unterzeichner_name="Max Mustermann",
        unterzeichner_funktion="Geschäftsführer",
    )

    service = KonformitaetsErklaerungPdfService()
    pdf_path = service.generate_pdf(erklaerung)

    assert pdf_path.exists()
    assert pdf_path.suffix == ".pdf"
    erklaerung.refresh_from_db()
    assert erklaerung.pdf_filename != ""
    assert erklaerung.pdf_generated_at is not None
```

- [ ] **Step 2: Test ausführen — erwarte FAIL**

```bash
python -m pytest tests/ppwr/test_konformitaet.py::test_pdf_service_generate -v
```

Erwartete Ausgabe: `ImportError: cannot import name 'KonformitaetsErklaerungPdfService'`

- [ ] **Step 3: HTML-Template erstellen**

`ppwr/templates/ppwr/konformitaetserklaerung.html` anlegen:

```html
<!DOCTYPE html>
<html lang="de">
<head>
  <meta charset="UTF-8">
  <title>EU-Konformitätserklärung {{ erklaerung.declaration_number }}</title>
  <style>
    @page {
      size: A4;
      margin: 20mm 20mm 25mm 20mm;
    }
    * { box-sizing: border-box; }
    body {
      font-family: Arial, Helvetica, sans-serif;
      font-size: 10pt;
      color: #111;
      line-height: 1.5;
    }
    h1 {
      font-size: 12pt;
      font-weight: bold;
      text-align: center;
      margin-bottom: 4pt;
    }
    h2 {
      font-size: 11pt;
      font-weight: bold;
      text-align: center;
      margin-bottom: 16pt;
    }
    .item {
      margin-bottom: 10pt;
    }
    .item-number {
      font-weight: bold;
      display: inline;
    }
    .item-text {
      display: inline;
    }
    .item-value {
      margin-top: 3pt;
      margin-left: 16pt;
      white-space: pre-wrap;
      border-bottom: 1px solid #999;
      min-height: 14pt;
      padding-bottom: 2pt;
    }
    .static-text {
      font-style: italic;
    }
    .signature-block {
      margin-top: 20pt;
      border-top: 1px solid #333;
      padding-top: 10pt;
    }
    .signature-row {
      margin-bottom: 8pt;
    }
    .signature-label {
      font-size: 9pt;
      color: #555;
    }
    .signature-value {
      border-bottom: 1px solid #999;
      min-height: 14pt;
      padding-bottom: 2pt;
    }
    .footnote {
      margin-top: 16pt;
      font-size: 8pt;
      color: #666;
      border-top: 1px solid #ddd;
      padding-top: 6pt;
    }
  </style>
</head>
<body>
  <h1>ANHANG VIII</h1>
  <h2>EU-Konformitätserklärung Nr. (¹) {{ erklaerung.declaration_number }}</h2>

  <div class="item">
    <span class="item-number">1.</span>
    <span class="item-text">Nr. … (eindeutige Kennung der Verpackung):</span>
    <div class="item-value">{{ erklaerung.packaging_label.unique_packaging_id }}</div>
  </div>

  <div class="item">
    <span class="item-number">2.</span>
    <span class="item-text">Name und Anschrift des Erzeugers und gegebenenfalls des Bevollmächtigten des Erzeugers:</span>
    <div class="item-value">{{ erklaerung.erzeuger_name_anschrift }}</div>
  </div>

  <div class="item">
    <span class="item-number">3.</span>
    <span class="item-text static-text">Die alleinige Verantwortung für die Ausstellung dieser Konformitätserklärung trägt der Erzeuger.</span>
  </div>

  <div class="item">
    <span class="item-number">4.</span>
    <span class="item-text">Gegenstand der Erklärung (Kennung der Verpackung zwecks Rückverfolgbarkeit): Beschreibung der Verpackung:</span>
    <div class="item-value">{{ erklaerung.gegenstand_beschreibung }}</div>
  </div>

  <div class="item">
    <span class="item-number">5.</span>
    <span class="item-text">Der unter Nummer 4 genannte Gegenstand der Erklärung erfüllt die einschlägigen Rechtsvorschriften der Union in Bezug auf die Harmonisierung: … (Verweis auf die anderen angewandten Rechtsakte der Union).</span>
    <div class="item-value">{{ erklaerung.harmonisierung }}</div>
  </div>

  <div class="item">
    <span class="item-number">6.</span>
    <span class="item-text">Angabe der einschlägigen harmonisierten Normen oder gemeinsamen Spezifikationen, die zugrunde gelegt wurden, oder Angabe anderer technischer Spezifikationen, für die die Konformität erklärt wird:</span>
    <div class="item-value">{{ erklaerung.normen_spezifikationen }}</div>
  </div>

  <div class="item">
    <span class="item-number">7.</span>
    <span class="item-text">Die notifizierte Stelle … (Name, Anschrift, Kennnummer) … hat, falls anwendbar, … (Beschreibung ihrer Maßnahme) durchgeführt und die folgende(n) Bescheinigung(en) ausgestellt:</span>
    <div class="item-value">{% if erklaerung.notifizierte_stelle %}{{ erklaerung.notifizierte_stelle }}{% else %}Entfällt.{% endif %}</div>
  </div>

  <div class="item">
    <span class="item-number">8.</span>
    <span class="item-text">Zusätzliche Angaben:</span>
    <div class="item-value">{% if erklaerung.zusaetzliche_angaben %}{{ erklaerung.zusaetzliche_angaben }}{% endif %}</div>
  </div>

  <div class="signature-block">
    <p>Unterzeichnet für und im Namen von:</p>
    <div class="signature-row">
      <div class="signature-label">(Ort und Datum der Ausstellung)</div>
      <div class="signature-value">{{ erklaerung.ausstellungsort }}, {{ erklaerung.ausstellungsdatum|date:"d.m.Y" }}</div>
    </div>
    <div class="signature-row">
      <div class="signature-label">(Name, Funktion) (Unterschrift)</div>
      <div class="signature-value">{{ erklaerung.unterzeichner_name }}, {{ erklaerung.unterzeichner_funktion }}</div>
    </div>
  </div>

  <div class="footnote">
    (¹) Kennnummer der Erklärung: {{ erklaerung.declaration_number }}
  </div>
</body>
</html>
```

- [ ] **Step 4: PDF-Service in `ppwr/services.py` hinzufügen**

Importe am Anfang der Datei ergänzen (nach den bestehenden Importen):

```python
from django.template.loader import render_to_string
```

Am Ende der Datei anfügen:

```python
class KonformitaetsErklaerungPdfService(BaseService):
    model = None  # kein direkter Modell-Bezug nötig

    def get_output_dir(self) -> Path:
        default = Path(settings.MEDIA_ROOT) / "ppwr"
        root = getattr(settings, "DOCUMENT_PDF_ROOT", None)
        return (Path(root) / "ppwr") if root else default

    def get_pdf_path(self, erklaerung) -> Path | None:
        if not erklaerung.pdf_filename:
            return None
        return self.get_output_dir() / erklaerung.pdf_filename

    def build_pdf_filename(self, erklaerung) -> str:
        from django.utils.text import slugify
        base = slugify(erklaerung.declaration_number) or f"erklaerung-{erklaerung.pk}"
        return f"konformitaet-{base}.pdf"

    def generate_pdf(self, erklaerung) -> Path:
        from weasyprint import HTML

        output_dir = self.get_output_dir()
        output_dir.mkdir(parents=True, exist_ok=True)

        html_string = render_to_string(
            "ppwr/konformitaetserklaerung.html",
            {"erklaerung": erklaerung},
        )
        filename = self.build_pdf_filename(erklaerung)
        output_path = output_dir / filename

        HTML(string=html_string, base_url="/").write_pdf(str(output_path))

        erklaerung.pdf_filename = filename
        erklaerung.pdf_generated_at = timezone.now()
        erklaerung.save(update_fields=["pdf_filename", "pdf_generated_at", "updated_at"])

        return output_path
```

- [ ] **Step 5: Tests ausführen — erwarte PASS**

```bash
python -m pytest tests/ppwr/test_konformitaet.py -v
```

Erwartete Ausgabe: `3 passed`

- [ ] **Step 6: Commit**

```bash
git add ppwr/services.py ppwr/templates/ppwr/konformitaetserklaerung.html tests/ppwr/test_konformitaet.py
git commit -m "feat(ppwr): WeasyPrint PDF-Service für Konformitätserklärung"
```

---

### Task 3: Öffentliche Views und URLs

**Files:**
- Create: `ppwr/views.py`
- Create: `ppwr/urls.py`
- Modify: `GC_Bridge_4/urls.py`

**Interfaces:**
- Consumes: `KonformitaetsErklaerung` (Task 1), `KonformitaetsErklaerungPdfService` (Task 2)
- Produces: URL `ppwr:erklaerung-html` → `/ppwr/erklaerung/<slug>/`, URL `ppwr:erklaerung-pdf` → `/ppwr/erklaerung/<slug>/pdf/`

- [ ] **Step 1: Tests schreiben**

```python
# in tests/ppwr/test_konformitaet.py ergänzen:

from django.test import Client
from django.urls import reverse
from django.utils import timezone


@pytest.mark.django_db
def test_oeffentliche_html_view(packaging_label_fixture):
    erklaerung = KonformitaetsErklaerung.objects.create(
        packaging_label=packaging_label_fixture,
        declaration_number="EU-KE-2026-001",
        erzeuger_name_anschrift="Test GmbH",
        gegenstand_beschreibung="Faltschachtel",
        harmonisierung="PPWR",
        normen_spezifikationen="EN 13431",
        ausstellungsort="Teststadt",
        ausstellungsdatum=timezone.now().date(),
        unterzeichner_name="Max Mustermann",
        unterzeichner_funktion="Geschäftsführer",
    )
    client = Client()
    url = reverse("ppwr:erklaerung-html", kwargs={"slug": packaging_label_fixture.slug})
    response = client.get(url)
    assert response.status_code == 200
    assert b"EU-Konformitätserkl" in response.content
    assert b"EU-KE-2026-001" in response.content


@pytest.mark.django_db
def test_oeffentliche_html_view_404_ohne_erklaerung(packaging_label_fixture):
    client = Client()
    url = reverse("ppwr:erklaerung-html", kwargs={"slug": packaging_label_fixture.slug})
    response = client.get(url)
    assert response.status_code == 404


@pytest.mark.django_db
def test_pdf_download_view(packaging_label_fixture, tmp_path, settings):
    settings.DOCUMENT_PDF_ROOT = str(tmp_path)
    from ppwr.services import KonformitaetsErklaerungPdfService

    erklaerung = KonformitaetsErklaerung.objects.create(
        packaging_label=packaging_label_fixture,
        declaration_number="EU-KE-2026-001",
        erzeuger_name_anschrift="Test GmbH",
        gegenstand_beschreibung="Faltschachtel",
        harmonisierung="PPWR",
        normen_spezifikationen="EN 13431",
        ausstellungsort="Teststadt",
        ausstellungsdatum=timezone.now().date(),
        unterzeichner_name="Max Mustermann",
        unterzeichner_funktion="Geschäftsführer",
    )
    KonformitaetsErklaerungPdfService().generate_pdf(erklaerung)
    erklaerung.refresh_from_db()

    client = Client()
    url = reverse("ppwr:erklaerung-pdf", kwargs={"slug": packaging_label_fixture.slug})
    response = client.get(url)
    assert response.status_code == 200
    assert response["Content-Type"] == "application/pdf"
```

- [ ] **Step 2: Tests ausführen — erwarte FAIL**

```bash
python -m pytest tests/ppwr/test_konformitaet.py::test_oeffentliche_html_view -v
```

Erwartete Ausgabe: `NoReverseMatch` oder `ModuleNotFoundError`

- [ ] **Step 3: `ppwr/views.py` anlegen**

```python
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, render

from ppwr.models import KonformitaetsErklaerung, PackagingLabel
from ppwr.services import KonformitaetsErklaerungPdfService


def erklaerung_html(request, slug: str):
    label = get_object_or_404(PackagingLabel, slug=slug)
    erklaerung = getattr(label, "konformitaetserklaerung", None)
    if erklaerung is None:
        raise Http404("Keine Konformitätserklärung für dieses Etikett vorhanden.")
    return render(request, "ppwr/konformitaetserklaerung.html", {"erklaerung": erklaerung})


def erklaerung_pdf(request, slug: str):
    label = get_object_or_404(PackagingLabel, slug=slug)
    erklaerung = getattr(label, "konformitaetserklaerung", None)
    if erklaerung is None:
        raise Http404("Keine Konformitätserklärung für dieses Etikett vorhanden.")
    service = KonformitaetsErklaerungPdfService()
    pdf_path = service.get_pdf_path(erklaerung)
    if not pdf_path or not pdf_path.exists():
        pdf_path = service.generate_pdf(erklaerung)
    return FileResponse(
        pdf_path.open("rb"),
        as_attachment=True,
        filename=pdf_path.name,
        content_type="application/pdf",
    )
```

- [ ] **Step 4: `ppwr/urls.py` anlegen**

```python
from django.urls import path

from ppwr import views

app_name = "ppwr"

urlpatterns = [
    path("erklaerung/<slug:slug>/", views.erklaerung_html, name="erklaerung-html"),
    path("erklaerung/<slug:slug>/pdf/", views.erklaerung_pdf, name="erklaerung-pdf"),
]
```

- [ ] **Step 5: In `GC_Bridge_4/urls.py` einbinden**

Nach der Zeile mit `path('qr-codes/', ...)` einfügen:

```python
path('ppwr/', include('ppwr.urls', namespace='ppwr')),
```

Und `include` ist bereits importiert (prüfen, sonst `from django.urls import include, path`).

- [ ] **Step 6: Tests ausführen — erwarte PASS**

```bash
python -m pytest tests/ppwr/test_konformitaet.py -v
```

Erwartete Ausgabe: `6 passed`

- [ ] **Step 7: Commit**

```bash
git add ppwr/views.py ppwr/urls.py GC_Bridge_4/urls.py tests/ppwr/test_konformitaet.py
git commit -m "feat(ppwr): öffentliche Views und URLs für Konformitätserklärung"
```

---

### Task 4: Admin-Integration

**Files:**
- Modify: `ppwr/admin.py`

**Interfaces:**
- Consumes: `KonformitaetsErklaerung` (Task 1), `KonformitaetsErklaerungPdfService` (Task 2), URL `ppwr:erklaerung-html` (Task 3)

- [ ] **Step 1: Imports in `ppwr/admin.py` ergänzen**

Am Anfang der Datei nach den bestehenden Importen hinzufügen:

```python
from django.utils import timezone

from ppwr.models import KonformitaetsErklaerung
from ppwr.services import KonformitaetsErklaerungPdfService
```

- [ ] **Step 2: `KonformitaetsErklaerungAdmin` registrieren**

Am Ende von `ppwr/admin.py` anfügen:

```python
@admin.register(KonformitaetsErklaerung)
class KonformitaetsErklaerungAdmin(BaseAdmin):
    list_display = (
        "declaration_number",
        "packaging_label",
        "ausstellungsdatum",
        "unterzeichner_name",
        "pdf_status",
        "oeffentliche_url_link",
        "updated_at",
    )
    search_fields = ("declaration_number", "packaging_label__name", "unterzeichner_name")
    autocomplete_fields = ("packaging_label",)
    readonly_fields = BaseAdmin.readonly_fields + (
        "pdf_filename",
        "pdf_generated_at",
        "pdf_download_link",
        "oeffentliche_url_display",
    )
    actions_detail = ("generate_pdf_action",)

    fieldsets = (
        (
            "Erklärung",
            {
                "fields": (
                    "packaging_label",
                    "declaration_number",
                    "erzeuger_name_anschrift",
                    "gegenstand_beschreibung",
                    "harmonisierung",
                    "normen_spezifikationen",
                    "notifizierte_stelle",
                    "zusaetzliche_angaben",
                ),
                "classes": ("tab",),
            },
        ),
        (
            "Unterzeichnung",
            {
                "fields": (
                    "ausstellungsort",
                    "ausstellungsdatum",
                    "unterzeichner_name",
                    "unterzeichner_funktion",
                ),
                "classes": ("tab",),
            },
        ),
        (
            "PDF & URL",
            {
                "fields": (
                    "pdf_generated_at",
                    "pdf_filename",
                    "pdf_download_link",
                    "oeffentliche_url_display",
                ),
                "classes": ("tab",),
            },
        ),
        (
            "System",
            {
                "fields": ("created_at", "updated_at"),
                "classes": ("tab",),
            },
        ),
    )

    def get_urls(self):
        return [
            path(
                "<path:object_id>/generate-pdf/",
                self.admin_site.admin_view(self.generate_pdf_view),
                name="ppwr_konformitaetserklaerung_generate_pdf",
            ),
            path(
                "<path:object_id>/download-pdf/",
                self.admin_site.admin_view(self.download_pdf_view),
                name="ppwr_konformitaetserklaerung_download_pdf",
            ),
        ] + super().get_urls()

    @admin.display(description=_("PDF"))
    def pdf_status(self, obj: KonformitaetsErklaerung) -> str:
        if obj.pdf_generated_at:
            return f"✓ {obj.pdf_generated_at.strftime('%d.%m.%Y')}"
        return "–"

    @admin.display(description=_("PDF herunterladen"))
    def pdf_download_link(self, obj: KonformitaetsErklaerung | None = None) -> str:
        if not obj or not obj.pk or not obj.pdf_filename:
            return "Noch kein PDF generiert."
        pdf_path = KonformitaetsErklaerungPdfService().get_pdf_path(obj)
        if not pdf_path or not pdf_path.exists():
            return format_html("{} (Datei fehlt)", obj.pdf_filename)
        return format_html(
            '<a href="{}" class="text-primary-600 dark:text-primary-500">PDF herunterladen</a>',
            reverse("admin:ppwr_konformitaetserklaerung_download_pdf", args=(obj.pk,)),
        )

    @admin.display(description=_("Öffentliche URL"))
    def oeffentliche_url_display(self, obj: KonformitaetsErklaerung | None = None) -> str:
        if not obj or not obj.pk:
            return "Nach dem Speichern verfügbar."
        try:
            url = reverse("ppwr:erklaerung-html", kwargs={"slug": obj.packaging_label.slug})
        except Exception:
            return "URL nicht verfügbar."
        return format_html(
            '<a href="{url}" target="_blank" class="text-primary-600 dark:text-primary-500">{url}</a>'
            '<br><small class="text-gray-400">QR-Code Ziel-URL auf diesen Pfad setzen.</small>',
            url=url,
        )

    @admin.display(description=_("URL"))
    def oeffentliche_url_link(self, obj: KonformitaetsErklaerung) -> str:
        try:
            url = reverse("ppwr:erklaerung-html", kwargs={"slug": obj.packaging_label.slug})
        except Exception:
            return "–"
        return format_html(
            '<a href="{}" target="_blank" class="text-primary-600 dark:text-primary-500 text-xs">↗ öffnen</a>',
            url,
        )

    @action(description=_("PDF generieren"), icon="picture_as_pdf", variant=ActionVariant.INFO)
    def generate_pdf_action(self, request, object_id: str):
        from django.http import HttpResponseRedirect

        erklaerung = self.get_object(request, object_id)
        if not erklaerung:
            self.message_user(request, "Erklärung nicht gefunden.", level=messages.ERROR)
            return HttpResponseRedirect(reverse("admin:ppwr_konformitaetserklaerung_changelist"))
        KonformitaetsErklaerungPdfService().generate_pdf(erklaerung)
        self.message_user(request, "PDF erfolgreich generiert.")
        return HttpResponseRedirect(reverse("admin:ppwr_konformitaetserklaerung_change", args=(object_id,)))

    def generate_pdf_view(self, request, object_id: str):
        erklaerung = get_object_or_404(KonformitaetsErklaerung, pk=object_id)
        try:
            pdf_path = KonformitaetsErklaerungPdfService().generate_pdf(erklaerung)
        except Exception as exc:
            return JsonResponse({"error": str(exc)}, status=500)
        return FileResponse(
            pdf_path.open("rb"),
            as_attachment=True,
            filename=pdf_path.name,
            content_type="application/pdf",
        )

    def download_pdf_view(self, request, object_id: str):
        erklaerung = get_object_or_404(KonformitaetsErklaerung, pk=object_id)
        pdf_path = KonformitaetsErklaerungPdfService().get_pdf_path(erklaerung)
        if not pdf_path or not pdf_path.exists():
            raise Http404("PDF nicht gefunden.")
        return FileResponse(pdf_path.open("rb"), as_attachment=True, filename=pdf_path.name)
```

- [ ] **Step 3: Admin manuell prüfen**

```bash
python manage.py check
```

Erwartete Ausgabe: `System check identified no issues (0 silenced).`

- [ ] **Step 4: Commit**

```bash
git add ppwr/admin.py
git commit -m "feat(ppwr): Admin-Interface für Konformitätserklärung"
```

---

### Task 5: End-to-End-Smoke-Test

**Files:**
- Modify: `tests/ppwr/test_konformitaet.py`

- [ ] **Step 1: Vollständigen Test-Lauf ausführen**

```bash
python -m pytest tests/ppwr/test_konformitaet.py -v
```

Erwartete Ausgabe: `6 passed` (oder mehr, falls weitere Tests hinzugefügt wurden)

- [ ] **Step 2: Django System-Check**

```bash
python manage.py check --deploy 2>&1 | grep -v "WARNINGS\|security"
```

Erwartete Ausgabe: `System check identified no issues (0 silenced).`

- [ ] **Step 3: Dev-Server starten und manuell prüfen**

```bash
python manage.py runserver
```

Im Browser prüfen:
- `/admin/ppwr/konformitaetserklaerung/add/` → Formular öffnet sich mit allen 8 Feldern
- Nach Anlegen einer Erklärung: `/ppwr/erklaerung/<slug>/` → öffentliche A4-Ansicht
- PDF-Aktion in Admin → PDF wird heruntergeladen

- [ ] **Step 4: Finaler Commit**

```bash
git add -p
git commit -m "feat(ppwr): EU-Konformitätserklärung nach Anhang VIII vollständig"
```
