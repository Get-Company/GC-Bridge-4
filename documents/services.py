import re
from io import BytesIO
from pathlib import Path

from django.apps import apps
from django.conf import settings
from django.utils import timezone
from django.utils.html import escape
from django.utils.text import slugify
from pypdf import PdfWriter, PdfReader
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas as pdf_canvas
from weasyprint import HTML as WeasyHTML

from core.services import BaseService
from documents.models import Document


class DocumentPdfService(BaseService):
    model = Document
    default_price_list_css_path = Path("templates/admin/products/includes/price_list_document_template.css")
    default_price_list_template_path = Path("documents/templates/preisliste.html")
    default_price_list_cover_pdf_path = Path("templates/admin/products/includes/cover_pricelist.pdf")
    price_list_cover_date_x = 16 * mm
    price_list_cover_date_y_from_top = 9.4 * mm
    price_list_cover_date_font_size = 5 * mm
    price_list_cover_month_map = {
        "jan": 1,
        "januar": 1,
        "feb": 2,
        "februar": 2,
        "mar": 3,
        "maerz": 3,
        "märz": 3,
        "mrz": 3,
        "april": 4,
        "apr": 4,
        "mai": 5,
        "jun": 6,
        "juni": 6,
        "jul": 7,
        "juli": 7,
        "aug": 8,
        "august": 8,
        "sep": 9,
        "sept": 9,
        "september": 9,
        "okt": 10,
        "oktober": 10,
        "nov": 11,
        "november": 11,
        "dez": 12,
        "dezember": 12,
    }

    def get_output_dir(self) -> Path:
        default = Path(settings.MEDIA_ROOT) / "documents"
        return Path(getattr(settings, "DOCUMENT_PDF_ROOT", default))

    def get_pdf_path(self, document: Document) -> Path | None:
        if not document.pdf_filename:
            return None
        return self.get_output_dir() / document.pdf_filename

    def build_pdf_filename(self, document: Document) -> str:
        filename = slugify(document.slug or document.title) or f"dokument-{document.pk or 'neu'}"
        return f"{filename}.pdf"

    def get_css_content(self, document: Document) -> str:
        if document.css_content:
            return document.css_content
        if document.document_type == Document.DocumentType.PRICE_LIST:
            css_path = settings.BASE_DIR / self.default_price_list_css_path
            if css_path.exists():
                return css_path.read_text(encoding="utf-8")
        return ""

    def get_default_price_list_template_source(self) -> str:
        template_path = settings.BASE_DIR / self.default_price_list_template_path
        return template_path.read_text(encoding="utf-8") if template_path.exists() else ""

    def should_use_default_price_list_template(self, document: Document) -> bool:
        """Keep old price-increase templates from producing placeholder pages.

        The former price-list template expects a ``PriceIncrease`` context.  A
        document-based price list has no such context, so its cover and closing
        page only render empty labels.  Existing customer-specific templates
        continue to be used; only an empty or recognisably legacy template is
        replaced with the bundled customer price-list template.
        """
        if document.document_type != Document.DocumentType.PRICE_LIST:
            return False
        template_source = document.get_template_source()
        legacy_markers = (
            "price_increase.",
            'data-pdf-section="cover"',
            'data-pdf-section="closing"',
        )
        return not template_source.strip() or any(marker in template_source for marker in legacy_markers)

    def render_document_html(self, document: Document, context: dict | None = None) -> str:
        css_content = self.get_css_content(document)
        render_context = {"document": document, "css": css_content, **(context or {})}
        if self.should_use_default_price_list_template(document):
            from documents.jinja2_env import build_env

            template_source = self.get_default_price_list_template_source()
            if template_source:
                return build_env().from_string(template_source).render(**render_context)
        return document.render(render_context)

    def get_cover_pdf_path(self, document: Document) -> Path | None:
        if document.cover_pdf and document.cover_pdf.name:
            return Path(document.cover_pdf.path)
        if document.document_type == Document.DocumentType.PRICE_LIST:
            default_cover_path = settings.BASE_DIR / self.default_price_list_cover_pdf_path
            if default_cover_path.exists():
                return default_cover_path
        return None

    @classmethod
    def get_price_list_effective_date_text(cls, document: Document) -> str:
        title = (document.title or "").strip().lower()
        numeric_match = re.search(r"(?<!\d)(0?[1-9]|1[0-2])[./\-\s]+(20\d{2})(?!\d)", title)
        if numeric_match:
            return f"ab {int(numeric_match.group(1)):02d}/{numeric_match.group(2)}"
        for month_name, month_number in cls.price_list_cover_month_map.items():
            month_match = re.search(rf"(?<![a-zäöü]){month_name}(?![a-zäöü])[^0-9]*(20\d{{2}})", title)
            if month_match:
                return f"ab {month_number:02d}/{month_match.group(1)}"
        return f"ab {timezone.localdate():%m/%Y}"

    def add_default_price_list_cover_date(self, pdf_path: Path, document: Document) -> None:
        reader = PdfReader(str(pdf_path))
        if not reader.pages:
            return
        writer = PdfWriter()
        date_text = self.get_price_list_effective_date_text(document)
        for page_index, page in enumerate(reader.pages):
            if page_index == 0:
                page_width = float(page.mediabox.width)
                page_height = float(page.mediabox.height)
                overlay_buffer = BytesIO()
                overlay_canvas = pdf_canvas.Canvas(
                    overlay_buffer,
                    pagesize=(page_width, page_height),
                )
                overlay_canvas.setFont("Helvetica", self.price_list_cover_date_font_size)
                overlay_canvas.drawString(
                    self.price_list_cover_date_x,
                    page_height - self.price_list_cover_date_y_from_top - self.price_list_cover_date_font_size,
                    date_text,
                )
                overlay_canvas.save()
                page.merge_page(PdfReader(overlay_buffer).pages[0])
            writer.add_page(page)
        dated_path = pdf_path.with_suffix(".dated.pdf")
        with dated_path.open("wb") as output_file:
            writer.write(output_file)
        dated_path.replace(pdf_path)

    @staticmethod
    def add_price_list_page_numbers(pdf_path: Path) -> None:
        """Number the complete merged document, including the cover page."""
        reader = PdfReader(str(pdf_path))
        page_count = len(reader.pages)
        writer = PdfWriter()
        for page_number, page in enumerate(reader.pages, start=1):
            page_width = float(page.mediabox.width)
            page_height = float(page.mediabox.height)
            overlay_buffer = BytesIO()
            overlay_canvas = pdf_canvas.Canvas(
                overlay_buffer,
                pagesize=(page_width, page_height),
            )
            overlay_canvas.setFillColorRGB(1, 1, 1)
            overlay_canvas.rect(
                (page_width - (44 * mm)) / 2,
                4 * mm,
                44 * mm,
                10 * mm,
                fill=1,
                stroke=0,
            )
            overlay_canvas.setFillColorRGB(0.45, 0.45, 0.45)
            overlay_canvas.setFont("Helvetica", 8)
            overlay_canvas.drawCentredString(page_width / 2, 7 * mm, f"{page_number}/{page_count}")
            overlay_canvas.save()
            overlay_page = PdfReader(overlay_buffer).pages[0]
            page.merge_page(overlay_page)
            writer.add_page(page)

        numbered_path = pdf_path.with_suffix(".numbered.pdf")
        with numbered_path.open("wb") as output_file:
            writer.write(output_file)
        numbered_path.replace(pdf_path)

    def build_pdf_html(self, document: Document, context: dict | None = None) -> str:
        css_content = self.get_css_content(document)
        rendered_html = self.render_document_html(document, context)
        if "<html" in rendered_html.lower():
            return rendered_html
        return (
            "<!doctype html>"
            "<html lang=\"de\">"
            "<head>"
            "<meta charset=\"utf-8\">"
            f"<title>{escape(document.title)}</title>"
            f"<style>{css_content}</style>"
            "</head>"
            "<body>"
            f"{rendered_html}"
            "</body>"
            "</html>"
        )

    def generate_pdf(self, document: Document, context: dict | None = None) -> Path:
        output_dir = self.get_output_dir()
        output_dir.mkdir(parents=True, exist_ok=True)
        pdf_path = output_dir / self.build_pdf_filename(document)
        html = self.build_pdf_html(document, context)

        parts: list[Path] = []
        cover_pdf_path = self.get_cover_pdf_path(document)
        uses_default_price_list_cover = (
            document.document_type == Document.DocumentType.PRICE_LIST
            and not (document.cover_pdf and document.cover_pdf.name)
            and cover_pdf_path == settings.BASE_DIR / self.default_price_list_cover_pdf_path
        )
        if cover_pdf_path:
            parts.append(cover_pdf_path)

        main_tmp = pdf_path.with_suffix(".main.pdf")
        WeasyHTML(string=html, base_url=str(settings.BASE_DIR)).write_pdf(target=str(main_tmp))
        parts.append(main_tmp)

        if document.end_pdf and document.end_pdf.name:
            parts.append(Path(document.end_pdf.path))

        if len(parts) > 1:
            writer = PdfWriter()
            for part in parts:
                reader = PdfReader(str(part))
                for page in reader.pages:
                    writer.add_page(page)
            with open(pdf_path, "wb") as fh:
                writer.write(fh)
            main_tmp.unlink(missing_ok=True)
        else:
            main_tmp.rename(pdf_path)

        if document.document_type == Document.DocumentType.PRICE_LIST:
            if uses_default_price_list_cover:
                self.add_default_price_list_cover_date(pdf_path, document)
            self.add_price_list_page_numbers(pdf_path)

        document.pdf_filename = pdf_path.name
        document.pdf_generated_at = timezone.now()
        document.save(update_fields=("pdf_filename", "pdf_generated_at", "updated_at"))
        return pdf_path


class DocumentTemplateContextService(BaseService):
    model = Document

    def _product_to_row(self, product) -> dict:
        price_obj = product.prices.filter(sales_channel__is_default=True).first()
        price = price_obj.price if price_obj else None
        rebate_price = price_obj.rebate_price if price_obj else None
        factor = product.factor or 1
        unit = product.unit or "Stk"
        cat2 = next(iter(product.categories.all()), None)
        cat1 = cat2.parent if cat2 and hasattr(cat2, "parent") and cat2.parent else cat2

        def fmt(val):
            return f"{val:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".") + " EUR" if val else "-"

        return {
            "erp_nr": product.erp_nr,
            "product_name": product.name,
            "attributes": "",
            "price": float(price) if price else None,
            "price_display": fmt(price),
            "price_source": "Standardpreis",
            "rebate_quantity": None,
            "rebate_quantity_display": "-",
            "rebate_price": float(rebate_price) if rebate_price else None,
            "rebate_price_display": fmt(rebate_price),
            "vpe_display": f"{factor} {unit}",
            "unit": unit,
            "factor": factor,
            "min_purchase": product.min_purchase or 1,
            "purchase_unit": product.purchase_unit or 1,
            "category_level1_name": cat1.name if cat1 else "",
            "category_level1_id": cat1.pk if cat1 else None,
            "category_level2_name": cat2.name if cat2 else "",
            "category_level2_id": cat2.pk if cat2 else None,
        }

    def build_preview_context(self, document: Document) -> dict:
        from collections import defaultdict
        from products.models import Product

        created_at = timezone.now()
        products = list(
            Product.objects.select_related("tax")
            .prefetch_related("prices", "categories", "categories__parent")
            .order_by("erp_nr")[:200]
        )
        rows = [self._product_to_row(p) for p in products]

        sections_map: dict = defaultdict(lambda: defaultdict(list))
        for row in rows:
            sections_map[row["category_level1_name"]][row["category_level2_name"]].append(row)

        category_sections = [
            {
                "category_name": cat1,
                "groups": [
                    {"category_name": cat2, "rows": grp_rows}
                    for cat2, grp_rows in groups.items()
                ],
            }
            for cat1, groups in sections_map.items()
        ]

        return {
            "document": document,
            "css": DocumentPdfService().get_css_content(document),
            "products": products,
            "created_at": created_at,
            "created_at_display": created_at.strftime("%d.%m.%Y"),
            "row_count": len(rows),
            "rows": rows,
            "category_sections": category_sections,
        }

    def get_model_variable_reference(self) -> list[dict]:
        reference = []
        for app_config in sorted(apps.get_app_configs(), key=lambda config: config.label):
            app_models = []
            for model in sorted(app_config.get_models(), key=lambda item: item._meta.db_table):
                fields = []
                for field in model._meta.get_fields():
                    if getattr(field, "hidden", False):
                        continue
                    name = getattr(field, "name", "")
                    if not name and hasattr(field, "get_accessor_name"):
                        name = field.get_accessor_name()
                    if not name:
                        continue
                    relation_model = getattr(field, "related_model", None)
                    fields.append(
                        {
                            "name": name,
                            "label": getattr(field, "verbose_name", name),
                            "type": field.__class__.__name__,
                            "relation": relation_model._meta.label if relation_model else "",
                            "reverse": bool(getattr(field, "auto_created", False) and not getattr(field, "concrete", False)),
                        }
                    )
                app_models.append(
                    {
                        "label": model._meta.label,
                        "table": model._meta.db_table,
                        "object_name": model._meta.object_name,
                        "fields": sorted(fields, key=lambda item: item["name"]),
                    }
                )
            if app_models:
                reference.append(
                    {
                        "label": app_config.label,
                        "name": app_config.verbose_name,
                        "models": app_models,
                    }
                )
        return reference
