from pathlib import Path

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Initialisiert zentrale Dokumente aus vorhandenen Templates (--force ueberschreibt vorhandene)"

    def add_arguments(self, parser):
        parser.add_argument(
            "--force",
            action="store_true",
            help="Vorhandene Dokumente ueberschreiben",
        )

    def handle(self, *args, **options):
        from documents.models import Document

        force = options["force"]
        self._init_price_list(Document, force=force)
        self._init_order_form(Document, force=force)
        self._init_static_documents(Document, force=force)

    def _init_price_list(self, Document, *, force: bool) -> None:
        template_path = Path("templates/admin/products/price_list_pdf.html")
        css_path = Path("templates/admin/products/includes/price_list_document_template.css")
        if not template_path.exists():
            self.stderr.write(f"Datei nicht gefunden: {template_path}")
            return

        defaults = {
            "document_type": Document.DocumentType.PRICE_LIST,
            "title": "Preisliste",
            "html_content": template_path.read_text(encoding="utf-8"),
            "css_content": css_path.read_text(encoding="utf-8") if css_path.exists() else "",
            "is_active": True,
        }
        self._upsert(Document, Document.Slug.PRICE_LIST, defaults, force=force)

    def _init_order_form(self, Document, *, force: bool) -> None:
        template_path = Path("templates/admin/products/includes/order_form.html")
        if not template_path.exists():
            self.stderr.write(f"Datei nicht gefunden: {template_path}")
            return

        defaults = {
            "document_type": Document.DocumentType.ORDER_FORM,
            "title": "Bestellschein",
            "html_content": template_path.read_text(encoding="utf-8"),
            "css_content": "",
            "is_active": True,
        }
        self._upsert(Document, Document.Slug.ORDER_FORM, defaults, force=force)

    def _init_static_documents(self, Document, *, force: bool) -> None:
        documents = [
            (
                "agb",
                {
                    "document_type": Document.DocumentType.TERMS,
                    "title": "AGB",
                    "html_content": "<h1>AGB</h1><p>Bitte hier die allgemeinen Geschaeftsbedingungen eintragen.</p>",
                    "css_content": "",
                    "is_active": True,
                },
            ),
            (
                "datenschutz",
                {
                    "document_type": Document.DocumentType.PRIVACY,
                    "title": "Datenschutzerklaerung",
                    "html_content": "<h1>Datenschutzerklaerung</h1><p>Bitte hier die Datenschutzerklaerung eintragen.</p>",
                    "css_content": "",
                    "is_active": True,
                },
            ),
            (
                "impressum",
                {
                    "document_type": Document.DocumentType.IMPRINT,
                    "title": "Impressum",
                    "html_content": "<h1>Impressum</h1><p>Bitte hier das Impressum eintragen.</p>",
                    "css_content": "",
                    "is_active": True,
                },
            ),
        ]
        for slug, defaults in documents:
            self._upsert(Document, slug, defaults, force=force)

    def _upsert(self, Document, slug, defaults, *, force: bool) -> None:
        obj, created = Document.objects.get_or_create(slug=slug, defaults=defaults)
        if created:
            self.stdout.write(self.style.SUCCESS(f"'{obj.title}' erstellt."))
        elif force:
            for field, value in defaults.items():
                setattr(obj, field, value)
            obj.save()
            self.stdout.write(self.style.WARNING(f"'{obj.title}' ueberschrieben (--force)."))
        else:
            self.stdout.write(f"'{obj.title}' bereits vorhanden - uebersprungen (--force zum Ueberschreiben).")
