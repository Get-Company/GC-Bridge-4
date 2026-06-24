from __future__ import annotations

from contextlib import contextmanager
from threading import local

from django.core.management import call_command
from django.db import IntegrityError, transaction
from django.utils import timezone

from core.services import BaseService
from products.models import Product, ProductSyncJob

_state = local()


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

    targets = (ProductSyncJob.Target.SHOPWARE,)

    def enqueue_product_sync(
        self,
        *,
        product_id: int,
        changed_fields: list[str],
        trigger: str = "product_save",
    ) -> list[ProductSyncJob]:
        if not Product.objects.filter(pk=product_id).exists():
            return []

        jobs = []
        cleaned_fields = sorted({str(field).strip() for field in changed_fields if str(field).strip()})
        for target in self.targets:
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
            target = job.target

        try:
            if target != ProductSyncJob.Target.SHOPWARE:
                raise ValueError(f"Unsupported product sync target: {target}")
            call_command("shopware_sync_products", product_erp_nr, skip_images=True)
        except Exception as exc:
            with transaction.atomic():
                job = ProductSyncJob.objects.select_for_update().get(pk=job_id)
                job.status = ProductSyncJob.Status.FAILED
                job.finished_at = timezone.now()
                job.last_error = str(exc)
                job.save(update_fields=("status", "finished_at", "last_error", "updated_at"))
            raise

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
