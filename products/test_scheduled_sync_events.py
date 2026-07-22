from django.test import SimpleTestCase


class ScheduledSyncEmitTests(SimpleTestCase):
    def test_emit_helpers_are_importable(self):
        # Der Import stellt sicher, dass die scheduled_product_sync-Schleife
        # skipped/ok-Events emittieren kann statt nur zu loggen.
        import products.tasks as tasks

        self.assertTrue(hasattr(tasks, "emit_event"))
        self.assertTrue(hasattr(tasks, "emit_run_started"))
        self.assertTrue(hasattr(tasks, "emit_run_finished"))
