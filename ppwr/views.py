from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, render

from ppwr.models import PackagingLabel
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
