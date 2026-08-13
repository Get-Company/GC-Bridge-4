from __future__ import annotations


def ensure_document_type_defaults(sender, **kwargs) -> None:
    from documents.models import DocumentType

    DocumentType.ensure_defaults()
