from pathlib import Path

from django.apps import apps
from django.conf import settings
from django.utils import timezone
from django.utils.html import escape
from django.utils.text import slugify
from pypdf import PdfWriter, PdfReader
from weasyprint import HTML as WeasyHTML

from core.services import BaseService
from documents.models import Document


class DocumentPdfService(BaseService):
    model = Document

    def get_output_dir(self) -> Path:
        return Path(getattr(settings, "DOCUMENT_PDF_ROOT", settings.BASE_DIR / "Dokumente"))

    def get_pdf_path(self, document: Document) -> Path | None:
        if not document.pdf_filename:
            return None
        return self.get_output_dir() / document.pdf_filename

    def build_pdf_filename(self, document: Document) -> str:
        filename = slugify(document.slug or document.title) or f"dokument-{document.pk or 'neu'}"
        return f"{filename}.pdf"

    def build_pdf_html(self, document: Document, context: dict | None = None) -> str:
        rendered_html = document.render(context)
        if "<html" in rendered_html.lower():
            return rendered_html
        return (
            "<!doctype html>"
            "<html lang=\"de\">"
            "<head>"
            "<meta charset=\"utf-8\">"
            f"<title>{escape(document.title)}</title>"
            f"<style>{document.css_content}</style>"
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
        if document.cover_pdf and document.cover_pdf.name:
            parts.append(Path(document.cover_pdf.path))

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
            "css": document.css_content,
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
