from __future__ import annotations

import json
from decimal import Decimal
from typing import Any

from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.db import transaction
from django.template import Context, Engine
from django.utils import timezone

from core.services import BaseService

from ai.models import AIRewriteJob, AIRewritePrompt
from .provider import AIProviderService


DEFAULT_USER_PROMPT_TEMPLATE = """Bearbeite den Feldinhalt fuer das Zielfeld "{{ target_field }}".

Modell: {{ model_label }}
Objekt: {{ object_repr }}
Quellfeld: {{ source_field }}

Aktueller Feldinhalt:
{{ source_value }}

Objektkontext (JSON):
{{ object_context_json }}

Gib ausschliesslich den neuen Feldinhalt fuer "{{ target_field }}" zurueck.
"""


class AIRewriteService(BaseService):
    model = AIRewriteJob

    def __init__(self) -> None:
        super().__init__()
        self.provider_service = AIProviderService()
        self.template_engine = Engine(autoescape=False)

    @transaction.atomic
    def request_rewrite(
        self,
        *,
        content_object,
        prompt: AIRewritePrompt,
        requested_by=None,
    ) -> AIRewriteJob:
        self._validate_prompt(content_object=content_object, prompt=prompt)

        source_snapshot = self._get_field_value(content_object, prompt.source_field)
        rendered_prompt = self._render_user_prompt(
            content_object=content_object,
            prompt=prompt,
            source_snapshot=source_snapshot,
        )
        job = self.model.objects.create(
            content_type=ContentType.objects.get_for_model(content_object),
            object_id=content_object.pk,
            object_repr=str(content_object),
            prompt=prompt,
            provider=prompt.provider,
            source_field=prompt.source_field,
            target_field=prompt.target_field,
            source_snapshot=source_snapshot,
            rendered_prompt=rendered_prompt,
            requested_by=requested_by,
            status=AIRewriteJob.Status.DRAFT,
        )
        try:
            job.result_text = self.provider_service.rewrite_text(
                provider=prompt.provider,
                system_prompt=prompt.system_prompt,
                user_prompt=rendered_prompt,
                temperature=float(prompt.temperature_override) if prompt.temperature_override is not None else None,
            )
            job.status = AIRewriteJob.Status.PENDING_REVIEW
            job.error_message = ""
        except Exception as exc:
            job.status = AIRewriteJob.Status.FAILED
            job.error_message = str(exc)
        job.save(
            update_fields=[
                "result_text",
                "status",
                "error_message",
                "updated_at",
            ]
        )
        return job

    def _validate_prompt(self, *, content_object, prompt: AIRewritePrompt) -> None:
        prompt_model = prompt.content_type.model_class()
        if prompt_model is None or not isinstance(content_object, prompt_model):
            raise ValidationError(
                f"Prompt '{prompt.name}' passt nicht zu {content_object._meta.label}."
            )
        for field_name in (prompt.source_field, prompt.target_field):
            if not hasattr(content_object, field_name):
                raise ValidationError(
                    f"Feld '{field_name}' existiert nicht auf {content_object._meta.label}."
                )

    def _render_user_prompt(
        self,
        *,
        content_object,
        prompt: AIRewritePrompt,
        source_snapshot: str,
    ) -> str:
        context = self._build_prompt_context(
            content_object=content_object,
            prompt=prompt,
            source_snapshot=source_snapshot,
        )
        template = prompt.user_prompt_template or DEFAULT_USER_PROMPT_TEMPLATE
        return self.template_engine.from_string(template).render(Context(context)).strip()

    def _build_prompt_context(
        self,
        *,
        content_object,
        prompt: AIRewritePrompt,
        source_snapshot: str,
    ) -> dict[str, Any]:
        object_context = self._serialize_object(content_object)
        return {
            "model_label": content_object._meta.label,
            "object_repr": str(content_object),
            "source_field": prompt.source_field,
            "target_field": prompt.target_field,
            "source_value": source_snapshot,
            "object_context": object_context,
            "object_context_json": json.dumps(object_context, ensure_ascii=True, indent=2),
        }

    @staticmethod
    def _get_field_value(content_object, field_name: str) -> str:
        value = getattr(content_object, field_name, "")
        return "" if value is None else str(value)

    def _serialize_object(self, content_object) -> dict[str, Any]:
        data: dict[str, Any] = {}
        for field in content_object._meta.fields:
            if field.many_to_many or field.one_to_many:
                continue
            value = getattr(content_object, field.name, None)
            if value is None:
                data[field.name] = None
            elif isinstance(value, (str, int, float, bool)):
                data[field.name] = value
            elif isinstance(value, Decimal):
                data[field.name] = str(value)
            else:
                data[field.name] = str(value)

        if hasattr(content_object, "categories"):
            data["categories"] = list(content_object.categories.values_list("name", flat=True))
        if hasattr(content_object, "get_images"):
            data["images"] = [image.path for image in content_object.get_images() if getattr(image, "path", "")]
        return data


class AIRewriteApplyService(BaseService):
    model = AIRewriteJob

    @transaction.atomic
    def approve(self, *, job: AIRewriteJob, approved_by=None) -> AIRewriteJob:
        if job.status == AIRewriteJob.Status.APPLIED:
            return job
        job.status = AIRewriteJob.Status.APPROVED
        job.approved_by = approved_by
        job.approved_at = timezone.now()
        job.save(update_fields=["status", "approved_by", "approved_at", "updated_at"])
        return job

    @transaction.atomic
    def reject(self, *, job: AIRewriteJob, approved_by=None) -> AIRewriteJob:
        job.status = AIRewriteJob.Status.REJECTED
        job.approved_by = approved_by
        job.approved_at = timezone.now()
        job.save(update_fields=["status", "approved_by", "approved_at", "updated_at"])
        return job

    @transaction.atomic
    def apply(self, *, job: AIRewriteJob, approved_by=None) -> AIRewriteJob:
        content_object = job.content_object
        if content_object is None:
            raise ValidationError("Der Rewrite-Job verweist auf kein existierendes Objekt mehr.")
        if not hasattr(content_object, job.target_field):
            raise ValidationError(f"Zielfeld '{job.target_field}' existiert nicht mehr.")
        setattr(content_object, job.target_field, job.result_text)
        content_object.save(update_fields=[job.target_field, "updated_at"])
        job.status = AIRewriteJob.Status.APPLIED
        job.is_archived = True
        job.approved_by = approved_by
        if not job.approved_at:
            job.approved_at = timezone.now()
        job.applied_at = timezone.now()
        job.object_repr = str(content_object)
        job.save(
            update_fields=[
                "status",
                "is_archived",
                "approved_by",
                "approved_at",
                "applied_at",
                "object_repr",
                "updated_at",
            ]
        )
        return job
