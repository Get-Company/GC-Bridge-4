from __future__ import annotations

from io import BytesIO
from pathlib import Path

from django.conf import settings
from django.template.loader import render_to_string
from django.utils import timezone
from django.utils.text import slugify
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas as rl_canvas

from core.services import BaseService
from ppwr.models import KonformitaetsErklaerung, PackagingLabel

BLOCK_LABELS = {
    "producer_name": "Hersteller",
    "address": "Adresse",
    "email": "E-Mail",
    "phone": "Telefon",
    "unique_packaging_id": "Verpackungs-ID",
    "qr_code": "QR-Code",
}


def get_block_text(block: dict, label: PackagingLabel) -> str:
    company = label.company
    block_type = block.get("type", "")

    if block_type == "producer_name":
        return company.legal_name or company.name or ""
    if block_type == "address":
        parts = [company.street, f"{company.postal_code} {company.city}".strip(), company.country]
        return "\n".join(p for p in parts if p.strip())
    if block_type == "email":
        return company.email or ""
    if block_type == "phone":
        return company.phone or ""
    if block_type == "unique_packaging_id":
        return label.unique_packaging_id or ""
    return ""


class PackagingLabelPdfService(BaseService):
    model = PackagingLabel
    PX_PER_MM = 3.78

    def get_output_dir(self) -> Path:
        default = Path(settings.MEDIA_ROOT) / "ppwr"
        root = getattr(settings, "DOCUMENT_PDF_ROOT", None)
        return (Path(root) / "ppwr") if root else default

    def get_pdf_path(self, label: PackagingLabel) -> Path | None:
        if not label.pdf_filename:
            return None
        return self.get_output_dir() / label.pdf_filename

    def build_pdf_filename(self, label: PackagingLabel) -> str:
        base = slugify(label.slug or label.name) or f"etikett-{label.pk or 'neu'}"
        return f"{base}.pdf"

    def generate_pdf(self, label: PackagingLabel) -> Path:
        output_dir = self.get_output_dir()
        output_dir.mkdir(parents=True, exist_ok=True)

        filename = self.build_pdf_filename(label)
        output_path = output_dir / filename

        page_w = label.canvas_width_mm * mm
        page_h = label.canvas_height_mm * mm

        buffer = BytesIO()
        pdf = rl_canvas.Canvas(buffer, pagesize=(page_w, page_h))

        for block in label.layout_data:
            self._draw_block(pdf, block, label, page_h)

        pdf.showPage()
        pdf.save()

        output_path.write_bytes(buffer.getvalue())

        label.pdf_filename = filename
        label.pdf_generated_at = timezone.now()
        label.save(update_fields=["pdf_filename", "pdf_generated_at", "updated_at"])

        return output_path

    def get_pdf_bytes(self, label: PackagingLabel) -> bytes:
        page_w = label.canvas_width_mm * mm
        page_h = label.canvas_height_mm * mm

        buffer = BytesIO()
        pdf = rl_canvas.Canvas(buffer, pagesize=(page_w, page_h))
        for block in label.layout_data:
            self._draw_block(pdf, block, label, page_h)
        pdf.showPage()
        pdf.save()
        return buffer.getvalue()

    def _draw_block(self, pdf: rl_canvas.Canvas, block: dict, label: PackagingLabel, page_h: float) -> None:
        x_pt = block.get("x_mm", 0) * mm
        y_mm_from_top = block.get("y_mm", 0)
        h_mm = block.get("height_mm", 10)
        w_pt = block.get("width_mm", 40) * mm
        # ReportLab origin is bottom-left; editor origin is top-left
        y_pt = page_h - (y_mm_from_top + h_mm) * mm

        block_type = block.get("type", "")
        font_size = block.get("font_size", 8)
        bold = block.get("bold", False)

        if block_type == "qr_code" and label.qr_code:
            self._draw_qr(pdf, label, x_pt, y_pt, w_pt, h_mm * mm)
            return

        text = get_block_text(block, label)
        if not text:
            return

        font_name = "Helvetica-Bold" if bold else "Helvetica"
        pdf.setFont(font_name, font_size)

        lines = text.split("\n")
        line_height = font_size * 1.3
        current_y = y_pt + h_mm * mm - font_size
        for line in lines:
            if current_y < y_pt:
                break
            pdf.drawString(x_pt, current_y, line)
            current_y -= line_height

    def _draw_qr(self, pdf: rl_canvas.Canvas, label: PackagingLabel, x: float, y: float, w: float, h: float) -> None:
        from qrcodes.services.qr_code import QrCodeRenderService

        side = int(min(w, h) / mm * self.PX_PER_MM * 10)
        raster = QrCodeRenderService().render_raster(label.qr_code, "png", max(512, side))
        pdf.drawImage(ImageReader(BytesIO(raster)), x, y, width=w, height=h, mask="auto")


class KonformitaetsErklaerungPdfService(BaseService):
    model = None

    def get_output_dir(self) -> Path:
        default = Path(settings.MEDIA_ROOT) / "ppwr"
        root = getattr(settings, "DOCUMENT_PDF_ROOT", None)
        return (Path(root) / "ppwr") if root else default

    def get_pdf_path(self, erklaerung: KonformitaetsErklaerung) -> Path | None:
        if not erklaerung.pdf_filename:
            return None
        return self.get_output_dir() / erklaerung.pdf_filename

    def build_pdf_filename(self, erklaerung: KonformitaetsErklaerung) -> str:
        base = slugify(erklaerung.declaration_number) or f"erklaerung-{erklaerung.pk}"
        return f"konformitaet-{base}.pdf"

    def generate_pdf(self, erklaerung: KonformitaetsErklaerung) -> Path:
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
