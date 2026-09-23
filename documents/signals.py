from __future__ import annotations


def ensure_document_type_defaults(sender, **kwargs) -> None:
    from ai.models import AIDocumentPrompt
    from documents.models import Document, DocumentType

    DocumentType.ensure_defaults()
    # The historic ``price_list`` record is the repository's current price-list
    # source. Mark it explicitly so existing installations can select it as a
    # template immediately after the migration.
    Document.objects.filter(
        slug=Document.Slug.PRICE_LIST,
        document_type=Document.DocumentType.PRICE_LIST,
    ).update(is_template=True)
    default_prompt = AIDocumentPrompt.ensure_default()
    Document.objects.filter(
        document_type__in=(
            Document.DocumentType.TERMS,
            Document.DocumentType.PRIVACY,
            Document.DocumentType.WITHDRAWAL,
        ),
        ai_document_prompt__isnull=True,
    ).update(ai_document_prompt=default_prompt)
