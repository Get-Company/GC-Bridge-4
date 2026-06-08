from pathlib import Path
from types import SimpleNamespace

from django.apps import apps
from django.conf import settings
from django.utils import timezone
from django.utils.html import escape
from django.utils.text import slugify
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
        WeasyHTML(string=html, base_url=str(settings.BASE_DIR)).write_pdf(target=str(pdf_path))
        document.pdf_filename = pdf_path.name
        document.pdf_generated_at = timezone.now()
        document.save(update_fields=("pdf_filename", "pdf_generated_at", "updated_at"))
        return pdf_path


class DocumentTemplateContextService(BaseService):
    model = Document

    def build_preview_context(self, document: Document) -> dict:
        created_at = timezone.now()
        rows = [
            {
                "erp_nr": "10001",
                "product_name": "Beispielprodukt A",
                "attributes": "Farbe: Blau<br>Groesse: L",
                "price": 12.5,
                "price_display": "12,50 EUR",
                "price_source": "Standardpreis",
                "rebate_quantity": 10,
                "rebate_quantity_display": "10",
                "rebate_price": 10.9,
                "rebate_price_display": "10,90 EUR",
                "vpe_display": "1 Stueck",
                "unit": "Stk",
                "factor": 1,
                "min_purchase": 1,
                "purchase_unit": 1,
                "category_level1_name": "Musterkategorie",
                "category_level1_id": 1,
                "category_level2_name": "Unterkategorie",
                "category_level2_id": 2,
            },
            {
                "erp_nr": "10002",
                "product_name": "Beispielprodukt B",
                "attributes": "",
                "price": 24,
                "price_display": "24,00 EUR",
                "price_source": "Standardpreis",
                "rebate_quantity": None,
                "rebate_quantity_display": "-",
                "rebate_price": None,
                "rebate_price_display": "-",
                "vpe_display": "6 Stueck",
                "unit": "Stk",
                "factor": 6,
                "min_purchase": 1,
                "purchase_unit": 1,
                "category_level1_name": "Musterkategorie",
                "category_level1_id": 1,
                "category_level2_name": "Unterkategorie",
                "category_level2_id": 2,
            },
        ]
        return {
            "document": document,
            "css": document.css_content,
            "price_increase": SimpleNamespace(
                title="Demo-Preiserhoehung",
                general_percentage=5,
                sales_channel="Standard",
                status="preview",
            ),
            "created_at": created_at,
            "created_at_display": created_at.strftime("%d.%m.%Y"),
            "general_percentage_display": "5 %",
            "sales_channel": "Standard",
            "scope_label": "Demo-Umfang",
            "root_category": SimpleNamespace(id=1, name="Musterkategorie"),
            "row_count": len(rows),
            "rows": rows,
            "category_sections": [
                {
                    "category_name": "Musterkategorie",
                    "groups": [
                        {
                            "category_name": "Unterkategorie",
                            "rows": rows,
                        }
                    ],
                }
            ],
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
