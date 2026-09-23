from __future__ import annotations


def ensure_document_prompt_default(sender, **kwargs) -> None:
    from ai.models import AIDocumentPrompt

    AIDocumentPrompt.ensure_default()
