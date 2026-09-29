import importlib
from io import StringIO
from unittest.mock import patch

from django.contrib.admin.sites import AdminSite
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.test import SimpleTestCase, TestCase

from core.admin import BaseAdmin
from products.admin import ProductAdmin, ProductVideoInline, VideoAdmin
from products.models import Product, ProductSyncJob, ProductVideo, Video, parse_vimeo_reference
from products.services import disable_product_auto_sync
from products.video_seed_data import CLASSEI_VIMEO_VIDEOS


class VimeoReferenceValidationTest(SimpleTestCase):
    def test_accepts_numeric_public_and_unlisted_references(self):
        self.assertEqual(parse_vimeo_reference("241517278"), ("241517278", ""))
        self.assertEqual(parse_vimeo_reference("https://vimeo.com/241517278"), ("241517278", ""))
        self.assertEqual(
            parse_vimeo_reference("https://vimeo.com/241517278/a1b2c3d4"),
            ("241517278", "a1b2c3d4"),
        )
        self.assertEqual(
            parse_vimeo_reference("https://player.vimeo.com/video/241517278?h=a1b2c3d4"),
            ("241517278", "a1b2c3d4"),
        )

    def test_rejects_non_vimeo_or_non_https_references(self):
        for value in ("https://example.com/241517278", "http://vimeo.com/241517278", "not-a-video"):
            with self.subTest(value=value), self.assertRaises(ValidationError):
                parse_vimeo_reference(value)

    def test_model_normalizes_an_unlisted_url(self):
        video = Video(title="Unlisted", vimeo_id="https://vimeo.com/241517278/a1b2c3d4")

        video.clean()

        self.assertEqual(video.vimeo_id, "241517278")
        self.assertEqual(video.privacy_hash, "a1b2c3d4")

    def test_public_url_clears_an_old_privacy_hash(self):
        video = Video(
            title="Public",
            vimeo_id="https://vimeo.com/241517278",
            privacy_hash="oldhash",
        )

        video.clean()

        self.assertEqual(video.vimeo_id, "241517278")
        self.assertEqual(video.privacy_hash, "")


class ProductVideoAdminTest(SimpleTestCase):
    def test_video_admin_and_product_inline_use_bridge_base_admin_classes(self):
        self.assertTrue(issubclass(VideoAdmin, BaseAdmin))
        self.assertIn(ProductVideoInline, ProductAdmin.inlines)
        inline = ProductVideoInline(Product, AdminSite())
        self.assertEqual(inline.ordering_field, "position")
        self.assertTrue(inline.hide_ordering_field)


class ClasseiVimeoMigrationDataTest(SimpleTestCase):
    def test_data_migration_matches_the_reviewed_source_mapping(self):
        migration = importlib.import_module("products.migrations.0050_seed_classei_vimeo_videos")
        migration_mapping = {
            vimeo_id: tuple(erp_numbers)
            for vimeo_id, _title, erp_numbers in migration.VIDEOS
        }
        source_mapping = {
            entry["vimeo_id"]: tuple(entry.get("erp_numbers", ()))
            for entry in CLASSEI_VIMEO_VIDEOS
        }

        self.assertEqual(migration_mapping, source_mapping)
        self.assertEqual(len(migration_mapping), 14)


class ProductVideoAutoSyncSignalTest(TestCase):
    @patch("products.tasks.process_product_sync_job.delay")
    def test_assignment_change_queues_only_shopware_sync(self, mock_delay):
        mock_delay.return_value.id = "celery-task"
        with disable_product_auto_sync():
            product = Product.objects.create(erp_nr="VIDEO-1", name="Videoartikel")
            video = Video.objects.create(title="Produktvideo", vimeo_id="123456")

        with self.captureOnCommitCallbacks(execute=True):
            ProductVideo.objects.create(product=product, video=video, position=10)

        jobs = list(ProductSyncJob.objects.all())
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0].target, ProductSyncJob.Target.SHOPWARE)
        self.assertEqual(jobs[0].trigger, "product_video_save")
        self.assertIn("product_video.position", jobs[0].changed_fields)

    @patch("products.tasks.process_product_sync_job.delay")
    def test_video_change_queues_all_assigned_products_for_shopware(self, mock_delay):
        mock_delay.return_value.id = "celery-task"
        with disable_product_auto_sync():
            first = Product.objects.create(erp_nr="VIDEO-2", name="Erster")
            second = Product.objects.create(erp_nr="VIDEO-3", name="Zweiter")
            video = Video.objects.create(title="Alt", vimeo_id="654321")
            ProductVideo.objects.create(product=first, video=video)
            ProductVideo.objects.create(product=second, video=video)

        with self.captureOnCommitCallbacks(execute=True):
            video.title = "Neu"
            video.save(update_fields=("title",))

        jobs = ProductSyncJob.objects.order_by("product__erp_nr")
        self.assertEqual(list(jobs.values_list("product__erp_nr", flat=True)), ["VIDEO-2", "VIDEO-3"])
        self.assertEqual({job.target for job in jobs}, {ProductSyncJob.Target.SHOPWARE})
        self.assertEqual({tuple(job.changed_fields) for job in jobs}, {("video.title",)})


class ClasseiVimeoSeedCommandTest(TestCase):
    def test_source_contains_all_channel_videos_and_reviewed_exclusions(self):
        self.assertEqual(len(CLASSEI_VIMEO_VIDEOS), 14)
        entries = {entry["vimeo_id"]: entry for entry in CLASSEI_VIMEO_VIDEOS}
        self.assertNotIn("erp_numbers", entries["56743453"])
        self.assertNotIn("806017", entries["32567030"]["erp_numbers"])
        self.assertEqual(
            entries["41014047"]["erp_numbers"],
            ("900043", "900044", "900047", "900048", "900049", "900050", "900052"),
        )

    def test_dry_run_does_not_write(self):
        Product.objects.create(erp_nr="204451", name="Klarsichtmappe")

        call_command("seed_classei_vimeo_videos", "--dry-run", stdout=StringIO())

        self.assertFalse(Video.objects.exists())
        self.assertFalse(ProductVideo.objects.exists())

    def test_import_is_idempotent_and_keeps_manual_videos_unassigned(self):
        product = Product.objects.create(erp_nr="204451", name="Klarsichtmappe")

        call_command("seed_classei_vimeo_videos", stdout=StringIO())
        call_command("seed_classei_vimeo_videos", stdout=StringIO())

        self.assertEqual(Video.objects.count(), 14)
        self.assertEqual(ProductVideo.objects.count(), 1)
        assignment = ProductVideo.objects.get()
        self.assertEqual(assignment.product, product)
        self.assertEqual(assignment.video.vimeo_id, "340139648")
        self.assertFalse(ProductVideo.objects.filter(video__vimeo_id="56743453").exists())
