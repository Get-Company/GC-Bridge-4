import pytest
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from ppwr.models import KonformitaetsErklaerung, PackagingLabel


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def packaging_label_fixture(db):
    from organization.models import CompanyProfile
    company, _ = CompanyProfile.objects.get_or_create(
        id=1,
        defaults={
            "name": "Test GmbH",
            "legal_name": "Test GmbH",
            "street": "Teststr. 1",
            "postal_code": "12345",
            "city": "Teststadt",
            "country": "Deutschland",
        },
    )
    return PackagingLabel.objects.create(
        name="Test-Etikett",
        slug="test-etikett",
        company=company,
        unique_packaging_id="PKG-2026-001",
    )


def _make_erklaerung(packaging_label, number="EU-KE-2026-001"):
    return KonformitaetsErklaerung.objects.create(
        packaging_label=packaging_label,
        declaration_number=number,
        erzeuger_name_anschrift="Test GmbH\nTeststr. 1\n12345 Teststadt",
        gegenstand_beschreibung="Faltschachtel 200x150x50mm, Wellpappe",
        harmonisierung="PPWR (EU) 2025/...",
        normen_spezifikationen="EN 13431",
        ausstellungsort="Teststadt",
        ausstellungsdatum=timezone.now().date(),
        unterzeichner_name="Max Mustermann",
        unterzeichner_funktion="Geschäftsführer",
    )


# ---------------------------------------------------------------------------
# Task 1: Modell
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_konformitaet_erstellen(packaging_label_fixture):
    erklaerung = _make_erklaerung(packaging_label_fixture)
    assert erklaerung.pk is not None
    assert erklaerung.packaging_label == packaging_label_fixture
    assert str(erklaerung) == "EU-KE-2026-001"


@pytest.mark.django_db
def test_konformitaet_one_to_one(packaging_label_fixture):
    _make_erklaerung(packaging_label_fixture)
    from django.db import IntegrityError
    with pytest.raises(IntegrityError):
        _make_erklaerung(packaging_label_fixture, number="EU-KE-2026-002")


# ---------------------------------------------------------------------------
# Task 2: PDF-Service
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_pdf_service_generate(packaging_label_fixture, tmp_path, settings):
    from ppwr.services import KonformitaetsErklaerungPdfService
    settings.DOCUMENT_PDF_ROOT = str(tmp_path)

    erklaerung = _make_erklaerung(packaging_label_fixture)
    service = KonformitaetsErklaerungPdfService()
    pdf_path = service.generate_pdf(erklaerung)

    assert pdf_path.exists()
    assert pdf_path.suffix == ".pdf"
    erklaerung.refresh_from_db()
    assert erklaerung.pdf_filename != ""
    assert erklaerung.pdf_generated_at is not None


# ---------------------------------------------------------------------------
# Task 3: Öffentliche Views
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_oeffentliche_html_view(packaging_label_fixture):
    _make_erklaerung(packaging_label_fixture)
    client = Client()
    url = reverse("ppwr:erklaerung-html", kwargs={"slug": packaging_label_fixture.slug})
    response = client.get(url)
    assert response.status_code == 200
    assert "EU-KE-2026-001".encode() in response.content


@pytest.mark.django_db
def test_oeffentliche_html_view_404_ohne_erklaerung(packaging_label_fixture):
    client = Client()
    url = reverse("ppwr:erklaerung-html", kwargs={"slug": packaging_label_fixture.slug})
    response = client.get(url)
    assert response.status_code == 404


@pytest.mark.django_db
def test_pdf_download_view(packaging_label_fixture, tmp_path, settings):
    from ppwr.services import KonformitaetsErklaerungPdfService
    settings.DOCUMENT_PDF_ROOT = str(tmp_path)

    erklaerung = _make_erklaerung(packaging_label_fixture)
    KonformitaetsErklaerungPdfService().generate_pdf(erklaerung)
    erklaerung.refresh_from_db()

    client = Client()
    url = reverse("ppwr:erklaerung-pdf", kwargs={"slug": packaging_label_fixture.slug})
    response = client.get(url)
    assert response.status_code == 200
    assert response["Content-Type"] == "application/pdf"
