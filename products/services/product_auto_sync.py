from __future__ import annotations

from contextlib import contextmanager
from threading import local

from django.core.management import call_command
from django.db import IntegrityError, transaction
from django.utils import timezone

from core.live_events import emit_event
from core.services import BaseService
from products.models import Product, ProductSyncJob

_state = local()

_TARGET_LABELS = {
    ProductSyncJob.Target.SHOPWARE: "shopware6",
    ProductSyncJob.Target.SHOPWARE5: "shopware5",
    ProductSyncJob.Target.MICROTECH: "microtech",
}


def is_product_auto_sync_disabled() -> bool:
    return bool(getattr(_state, "disabled", False))


@contextmanager
def disable_product_auto_sync():
    previous = is_product_auto_sync_disabled()
    _state.disabled = True
    try:
        yield
    finally:
        _state.disabled = previous


class ProductAutoSyncService(BaseService):
    model = ProductSyncJob

    targets = (
        ProductSyncJob.Target.SHOPWARE,
        ProductSyncJob.Target.SHOPWARE5,
        ProductSyncJob.Target.MICROTECH,
    )

    def enqueue_product_sync(
        self,
        *,
        product_id: int,
        changed_fields: list[str],
        trigger: str = "product_save",
        targets: tuple[str, ...] | None = None,
    ) -> list[ProductSyncJob]:
        if not Product.objects.filter(pk=product_id).exists():
            return []

        jobs = []
        cleaned_fields = sorted({str(field).strip() for field in changed_fields if str(field).strip()})
        for target in targets or self.targets:
            job = self._upsert_queued_job(
                product_id=product_id,
                target=target,
                changed_fields=cleaned_fields,
                trigger=trigger,
            )
            jobs.append(job)
            if not job.celery_task_id:
                self._dispatch_job(job)
        return jobs

    def process_job(self, *, job_id: int) -> ProductSyncJob | None:
        with transaction.atomic():
            job = (
                ProductSyncJob.objects.select_for_update()
                .select_related("product")
                .filter(pk=job_id)
                .first()
            )
            if job is None or job.status != ProductSyncJob.Status.QUEUED:
                return job

            job.status = ProductSyncJob.Status.RUNNING
            job.attempt += 1
            job.started_at = timezone.now()
            job.finished_at = None
            job.last_error = ""
            job.save(update_fields=("status", "attempt", "started_at", "finished_at", "last_error", "updated_at"))
            product_erp_nr = job.product.erp_nr
            product_id = job.product_id
            changed_fields = list(job.changed_fields or [])
            target = job.target

        task = "products.auto_sync"
        run_id = str(job_id)
        target_label = _TARGET_LABELS.get(target, str(target))
        emit_event(
            task, entity=product_erp_nr, step=f"→ {target_label}", status="info",
            summary=f"Produkt {product_erp_nr} → {target_label}",
            run_id=run_id, target=target_label,
        )
        try:
            if target == ProductSyncJob.Target.SHOPWARE:
                call_command("shopware_sync_products", product_erp_nr, skip_images=True)
                from products.services.variant_family import ProductVariantFamilyResolverService

                variant_family_slugs = [
                    family.slug
                    for family in ProductVariantFamilyResolverService().families_for_product(job.product)
                ]
                if variant_family_slugs:
                    call_command(
                        "shopware_sync_variants",
                        *variant_family_slugs,
                        apply=True,
                        skip_product_sync=True,
                    )
            elif target == ProductSyncJob.Target.SHOPWARE5:
                call_command("shopware5_sync_products", product_erp_nr)
            elif target == ProductSyncJob.Target.MICROTECH:
                self._submit_microtech_sentinel_jobs(
                    product_id=product_id,
                    product_sync_job_id=job_id,
                    product_erp_nr=product_erp_nr,
                    changed_fields=changed_fields,
                )
            else:
                raise ValueError(f"Unsupported product sync target: {target}")
        except Exception as exc:
            emit_event(
                task, entity=product_erp_nr, step=f"→ {target_label}", status="error",
                summary=f"{target_label}-Fehler: {exc}",
                run_id=run_id, target=target_label, payload={"error": str(exc)},
            )
            with transaction.atomic():
                job = ProductSyncJob.objects.select_for_update().get(pk=job_id)
                job.status = ProductSyncJob.Status.FAILED
                job.finished_at = timezone.now()
                job.last_error = str(exc)
                job.save(update_fields=("status", "finished_at", "last_error", "updated_at"))
            raise
        else:
            emit_event(
                task, entity=product_erp_nr, step=f"→ {target_label}", status="ok",
                summary=f"Produkt {product_erp_nr} nach {target_label} geschrieben",
                run_id=run_id, target=target_label,
            )

        with transaction.atomic():
            job = ProductSyncJob.objects.select_for_update().get(pk=job_id)
            job.status = ProductSyncJob.Status.SUCCEEDED
            job.finished_at = timezone.now()
            job.last_error = ""
            job.save(update_fields=("status", "finished_at", "last_error", "updated_at"))
            return job

    def _upsert_queued_job(
        self,
        *,
        product_id: int,
        target: str,
        changed_fields: list[str],
        trigger: str,
    ) -> ProductSyncJob:
        try:
            job, created = ProductSyncJob.objects.get_or_create(
                product_id=product_id,
                target=target,
                status=ProductSyncJob.Status.QUEUED,
                defaults={
                    "changed_fields": changed_fields,
                    "trigger": trigger,
                },
            )
        except IntegrityError:
            job = ProductSyncJob.objects.get(
                product_id=product_id,
                target=target,
                status=ProductSyncJob.Status.QUEUED,
            )
            created = False

        if created:
            return job

        merged_fields = sorted({*job.changed_fields, *changed_fields})
        if merged_fields != job.changed_fields or job.trigger != trigger:
            job.changed_fields = merged_fields
            job.trigger = trigger
            job.save(update_fields=("changed_fields", "trigger", "updated_at"))
        return job

    @staticmethod
    def _dispatch_job(job: ProductSyncJob) -> None:
        from products.tasks import process_product_sync_job

        try:
            async_result = process_product_sync_job.delay(job.pk)
        except Exception as exc:
            ProductSyncJob.objects.filter(pk=job.pk).update(last_error=f"Celery enqueue failed: {exc}")
            return
        ProductSyncJob.objects.filter(pk=job.pk, celery_task_id="").update(
            celery_task_id=getattr(async_result, "id", "") or "",
            last_error="",
        )

    @staticmethod
    def _submit_microtech_sentinel_jobs(
        *,
        product_id: int,
        product_sync_job_id: int,
        product_erp_nr: str,
        changed_fields: list[str],
    ) -> None:
        from microtech.management.commands.microtech_update_product import Command as MicrotechUpdateProductCommand
        from microtech.services import MicrotechJobSentinelService

        product = Product.objects.select_related("tax").get(pk=product_id)
        sentinel = MicrotechJobSentinelService()
        base_context = {
            "source": "product_auto_sync",
            "product_sync_job_id": product_sync_job_id,
            "product_id": product_id,
            "erp_nr": product_erp_nr,
            "changed_fields": changed_fields,
        }

        product_payload = MicrotechUpdateProductCommand()._build_input_data(product)
        sentinel.submit_product_update(
            erp_number=product_erp_nr,
            input_data=product_payload,
            context={**base_context, "payload": "product_with_prices"},
            next_step="Produktdaten und Preise per Auto-Sync nach Microtech schreiben.",
        )
