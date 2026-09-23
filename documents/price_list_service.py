from __future__ import annotations

import json

from django.core.serializers.json import DjangoJSONEncoder
from django.db import transaction
from django.utils import timezone
from django.utils.text import slugify

from core.services import BaseService
from documents.document_version_service import DocumentVersionService
from documents.jinja2_env import price_list_catalog_sections
from documents.models import Document


class PriceListDocumentService(BaseService):
    """Create a reproducible annual price-list document from one price increase."""

    model = Document

    @staticmethod
    def _validate(price_increase) -> Document:
        from products.models import PriceIncrease

        if price_increase.status != PriceIncrease.Status.APPLIED:
            raise ValueError("Die Preiserhöhung muss vor dem Anlegen der Preisliste übernommen werden.")
        template = price_increase.price_list_template
        if template is None:
            raise ValueError("Bitte zuerst eine Preislisten-Vorlage auswählen und speichern.")
        if not template.is_active or not template.is_template:
            raise ValueError("Die ausgewählte Preislisten-Vorlage ist nicht aktiv.")
        if template.document_type != Document.DocumentType.PRICE_LIST:
            raise ValueError("Die ausgewählte Vorlage ist keine Preislisten-Vorlage.")
        return template

    @staticmethod
    def _json_safe(value):
        return json.loads(json.dumps(value, cls=DjangoJSONEncoder, ensure_ascii=False))

    def _build_snapshot(self, price_increase, template: Document) -> dict:
        items = list(
            price_increase.items.select_related("product", "source_price")
            .filter(product__is_active=True)
            .order_by("product__erp_nr", "id")
        )
        if not items:
            raise ValueError("Die Preiserhöhung enthält keine aktiven Preispositionen.")

        price_overrides = {
            item.product_id: {
                "price": item.effective_new_price,
                "rebate_quantity": item.normalized_current_rebate_quantity,
                "rebate_price": item.effective_new_rebate_price,
            }
            for item in items
        }
        sections = price_list_catalog_sections(
            document=template,
            product_ids=set(price_overrides),
            price_overrides=price_overrides,
        )
        generated_at = timezone.localtime()
        return self._json_safe(
            {
                "price_list_sections": sections,
                "price_list_source": {
                    "price_increase_id": price_increase.pk,
                    "price_increase_title": price_increase.title,
                    "template_id": template.pk,
                    "template_title": template.title,
                    "generated_at": generated_at.isoformat(),
                    "row_count": len(items),
                },
            }
        )

    @transaction.atomic
    def create_from_price_increase(self, price_increase) -> Document:
        from products.models import PriceIncrease

        if not price_increase.pk:
            raise ValueError("Die Preiserhöhung muss zuerst gespeichert werden.")
        price_increase = (
            PriceIncrease.objects.select_for_update()
            .select_related("price_list_template", "price_list_document")
            .get(pk=price_increase.pk)
        )
        template = self._validate(price_increase)
        year = timezone.localdate().year
        title = f"Preisliste {year}"
        snapshot = self._build_snapshot(price_increase, template)

        document = price_increase.price_list_document
        if document is None:
            slug_base = slugify(title) or f"preisliste-{year}"
            slug = f"{slug_base}-{price_increase.pk}"
            document = Document(slug=slug)

        document.document_type = Document.DocumentType.PRICE_LIST
        document.title = title
        document.is_template = False
        document.source_template = template
        document.valid_from = timezone.localdate()
        document.context_snapshot = snapshot
        document.template_file = ""
        document.html_content = template.get_template_source()
        document.css_content = template.css_content
        document.use_jinja2 = template.use_jinja2
        document.cover_pdf = template.cover_pdf.name if template.cover_pdf else ""
        document.end_pdf = template.end_pdf.name if template.end_pdf else ""
        document.shopware_cms_page_id = template.shopware_cms_page_id
        document.shopware_media_id = template.shopware_media_id
        document.shopware_media_folder_id = template.shopware_media_folder_id
        document.is_active = True
        document.save()
        document.price_list_duplicate_categories.set(template.price_list_duplicate_categories.all())

        if price_increase.price_list_document_id != document.pk:
            price_increase.price_list_document = document
            price_increase.save(update_fields=("price_list_document", "updated_at"))

        version_service = DocumentVersionService()
        version = version_service.create_from_document(
            document,
            label=f"Aus Preiserhöhung {price_increase.title}",
        )
        return version_service.activate(version)
