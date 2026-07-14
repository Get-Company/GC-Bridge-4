from __future__ import annotations

import json
from decimal import Decimal
from typing import Any

from django.db import transaction
from django.template import Context, Engine
from django.utils import timezone

from core.services import BaseService
from ai.models import AIProviderConfig, AIRewriteJob, AIRewritePrompt
from .provider import AIProviderService


DEFAULT_USER_PROMPT_TEMPLATE = """Bearbeite den Feldinhalt fuer das Feld "{{ field }}".

Objekt: {{ object_repr }}

Aktueller Feldinhalt:
{{ source_value }}

Objektkontext (JSON):
{{ object_context_json }}

Gib ausschliesslich den neuen Feldinhalt fuer "{{ field }}" zurueck.
"""


class AIRewriteService(BaseService):
    model = AIRewriteJob

    def __init__(self) -> None:
        super().__init__()
        self.provider_service = AIProviderService()
        self.template_engine = Engine(autoescape=False)

    @transaction.atomic
    def create_job(
        self,
        *,
        product,
        field: str,
        prompt: AIRewritePrompt,
        provider: AIProviderConfig,
        requested_by=None,
    ) -> AIRewriteJob:
        snapshot = self._get_field_value(product, field)
        return self.model.objects.create(
            product=product,
            field=field,
            prompt=prompt,
            provider=provider,
            source_snapshot=snapshot,
            requested_by=requested_by,
            status=AIRewriteJob.Status.QUEUED,
        )

    def execute(self, job: AIRewriteJob) -> AIRewriteJob:
        rendered = self._render_user_prompt(job)
        job.rendered_prompt = rendered
        try:
            job.result_text = self.provider_service.rewrite_text(
                provider=job.provider,
                system_prompt=job.prompt.system_prompt,
                user_prompt=rendered,
            )
            job.status = AIRewriteJob.Status.READY
            job.error_message = ""
        except Exception as exc:  # noqa: BLE001 - Fehler landet im Job
            job.status = AIRewriteJob.Status.FAILED
            job.error_message = str(exc)
        job.save(update_fields=["rendered_prompt", "result_text", "status", "error_message", "updated_at"])
        return job

    @transaction.atomic
    def apply(self, *, job: AIRewriteJob) -> AIRewriteJob:
        product = job.product
        setattr(product, job.field, job.result_text)
        product.save(update_fields=[job.field, "updated_at"])
        job.status = AIRewriteJob.Status.APPLIED
        job.applied_at = timezone.now()
        job.save(update_fields=["status", "applied_at", "updated_at"])
        return job

    def _render_user_prompt(self, job: AIRewriteJob) -> str:
        context = {
            "field": job.field,
            "object_repr": str(job.product),
            "source_value": job.source_snapshot,
            "object_context_json": json.dumps(self._serialize(job.product), ensure_ascii=True, indent=2),
        }
        template = self.template_engine.from_string(DEFAULT_USER_PROMPT_TEMPLATE)
        return template.render(Context(context)).strip()

    @staticmethod
    def _get_field_value(obj, field_name: str) -> str:
        value = getattr(obj, field_name, "")
        return "" if value is None else str(value)

    def _serialize(self, obj) -> dict[str, Any]:
        data: dict[str, Any] = {}
        for f in obj._meta.fields:
            value = getattr(obj, f.name, None)
            if value is None or isinstance(value, (str, int, float, bool)):
                data[f.name] = value
            elif isinstance(value, Decimal):
                data[f.name] = str(value)
            else:
                data[f.name] = str(value)
        if hasattr(obj, "categories"):
            data["categories"] = list(obj.categories.values_list("name", flat=True))
        return data
