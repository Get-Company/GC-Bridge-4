from unittest import mock

from django.test import TestCase

from products.models import Product, ProductSyncJob


class ProductAutoSyncEmitTests(TestCase):
    def test_process_job_emits_target_events(self):
        product = Product.objects.create(erp_nr="4711", name="Test")
        job = ProductSyncJob.objects.create(
            product=product,
            target=ProductSyncJob.Target.SHOPWARE,
            status=ProductSyncJob.Status.QUEUED,
            changed_fields=["name"],
        )
        from products.services.product_auto_sync import ProductAutoSyncService

        with mock.patch("products.services.product_auto_sync.emit_event") as emit, \
             mock.patch("products.services.product_auto_sync.call_command"):
            ProductAutoSyncService().process_job(job_id=job.id)

        steps = [c.kwargs.get("step") or c.args[2] for c in emit.call_args_list]
        entities = {c.kwargs.get("entity") or c.args[1] for c in emit.call_args_list}
        statuses = [c.kwargs.get("status") or c.args[3] for c in emit.call_args_list]
        self.assertIn("4711", entities)
        self.assertTrue(any("shopware6" in str(s) for s in steps))
        self.assertIn("info", statuses)
        self.assertIn("ok", statuses)
