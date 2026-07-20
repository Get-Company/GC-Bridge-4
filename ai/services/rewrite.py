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
        product=None,
        category=None,
        field: str,
        prompt: AIRewritePrompt,
        provider: AIProviderConfig,
        requested_by=None,
    ) -> AIRewriteJob:
        target = self._get_target(product=product, category=category)
        snapshot = self._get_field_value(target, field)
        return self.model.objects.create(
            product=product,
            category=category,
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
            rendered_system_prompt = self._render_system_prompt(job)
            job.result_text, job.provider_response = self.provider_service.rewrite_text_with_response(
                provider=job.provider,
                system_prompt=rendered_system_prompt,
                user_prompt=rendered,
            )
            job.status = AIRewriteJob.Status.READY
            job.error_message = ""
        except Exception as exc:  # noqa: BLE001 - Fehler landet im Job
            job.status = AIRewriteJob.Status.FAILED
            job.error_message = str(exc)
        job.save(
            update_fields=[
                "rendered_prompt",
                "result_text",
                "provider_response",
                "status",
                "error_message",
                "updated_at",
            ]
        )
        return job

    @transaction.atomic
    def apply(self, *, job: AIRewriteJob) -> AIRewriteJob:
        target = job.target
        self._apply_result_to_target(job=job, target=target)
        job.status = AIRewriteJob.Status.APPLIED
        job.applied_at = timezone.now()
        job.save(update_fields=["status", "applied_at", "updated_at"])
        return job

    @staticmethod
    def _apply_result_to_target(*, job: AIRewriteJob, target) -> None:
        setattr(target, job.field, job.result_text)
        if not job.product_id:
            target.save(update_fields=[job.field, "updated_at"])
            return

        from products.models import ProductSyncJob
        from products.services import ProductAutoSyncService, disable_product_auto_sync

        with disable_product_auto_sync():
            target.save(update_fields=[job.field, "updated_at"])

        transaction.on_commit(
            lambda: ProductAutoSyncService().enqueue_product_sync(
                product_id=target.pk,
                changed_fields=[job.field],
                trigger="ai_rewrite_apply",
                targets=(
                    ProductSyncJob.Target.MICROTECH,
                    ProductSyncJob.Target.SHOPWARE5,
                    ProductSyncJob.Target.SHOPWARE,
                ),
            )
        )

    def _render_user_prompt(self, job: AIRewriteJob) -> str:
        template = self.template_engine.from_string(DEFAULT_USER_PROMPT_TEMPLATE)
        return template.render(Context(self._get_template_context(job))).strip()

    def _render_system_prompt(self, job: AIRewriteJob) -> str:
        template = self.template_engine.from_string(job.prompt.system_prompt)
        return template.render(Context(self._get_template_context(job))).strip()

    def _get_template_context(self, job: AIRewriteJob) -> dict[str, Any]:
        target = job.target
        return {
            "product": job.product,
            "category": job.category,
            "target": target,
            "field": job.field,
            "object_repr": str(target),
            "source_value": job.source_snapshot,
            "object_context_json": json.dumps(
                self._serialize(target, field_name=job.field),
                ensure_ascii=True,
                indent=2,
            ),
        }

    @staticmethod
    def _get_field_value(obj, field_name: str) -> str:
        value = getattr(obj, field_name, "")
        return "" if value is None else str(value)

    @staticmethod
    def _get_target(*, product=None, category=None):
        if (product is None) == (category is None):
            raise ValueError("Ein AI Rewrite Job braucht genau ein Zielobjekt.")
        return product or category

    def _serialize(self, obj, *, field_name: str = "") -> dict[str, Any]:
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
        if hasattr(obj, "product_properties"):
            data["attributes"] = self._serialize_product_attributes(
                obj,
                language_suffix=self._field_language_suffix(field_name),
            )
        return data

    @staticmethod
    def _field_language_suffix(field_name: str) -> str:
        for base_name in ("description_short", "description"):
            prefix = f"{base_name}_"
            if field_name.startswith(prefix):
                return field_name.removeprefix(prefix)
        return ""

    @staticmethod
    def _translated_name(obj, *, language_suffix: str) -> str:
        if language_suffix:
            translated_name = getattr(obj, f"name_{language_suffix}", "")
            if translated_name:
                return str(translated_name)
        return str(getattr(obj, "name", ""))

    @classmethod
    def _serialize_product_attributes(cls, product, *, language_suffix: str) -> list[dict[str, Any]]:
        attribute_groups: dict[int, dict[str, Any]] = {}
        product_properties = product.product_properties.select_related("value__group").order_by(
            "value__group__name",
            "value__name",
            "id",
        )
        for product_property in product_properties:
            value = product_property.value
            group = value.group
            attribute_group = attribute_groups.setdefault(
                group.pk,
                {
                    "gruppe": cls._translated_name(group, language_suffix=language_suffix),
                    "werte": [],
                },
            )
            attribute_group["werte"].append(
                cls._translated_name(value, language_suffix=language_suffix)
            )
        return list(attribute_groups.values())
