from __future__ import annotations

from django.db import transaction

from core.management.base import MonitoredBaseCommand
from products.models import Category, Product, ProductVideo, Video
from products.video_seed_data import CLASSEI_VIMEO_VIDEOS


class Command(MonitoredBaseCommand):
    help = (
        "Importiert den geprüften Classei-Vimeo-Katalog und legt nur sichere "
        "Produktzuordnungen idempotent an."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Zeigt Videos, Zuordnungen und fehlende Ziele, ohne etwas zu speichern.",
        )

    def handle(self, *args, **options):
        dry_run = bool(options.get("dry_run"))
        counters = {
            "videos_created": 0,
            "videos_existing": 0,
            "assignments_created": 0,
            "assignments_existing": 0,
            "missing_products": 0,
            "missing_categories": 0,
            "manual": 0,
        }

        self.stdout.write("Modus: DRY-RUN" if dry_run else "Modus: IMPORT")
        with transaction.atomic():
            for entry in CLASSEI_VIMEO_VIDEOS:
                video = self._get_or_create_video(entry=entry, dry_run=dry_run, counters=counters)
                target_products = self._resolve_products(entry=entry, counters=counters)

                if not target_products:
                    if entry.get("erp_numbers") or entry.get("category_slugs"):
                        self.stdout.write(
                            self.style.WARNING(
                                f"ÜBERSPRUNGEN {entry['title']}: Keines der geprüften Ziele ist vorhanden."
                            )
                        )
                        continue
                    disposition = entry.get("disposition", "manual")
                    reason = entry.get("reason", "Keine sichere Produktzuordnung hinterlegt.")
                    self.stdout.write(f"MANUELL [{disposition}] {entry['title']}: {reason}")
                    counters["manual"] += 1
                    continue

                for product in target_products:
                    self._get_or_create_assignment(
                        product=product,
                        video=video,
                        entry=entry,
                        dry_run=dry_run,
                        counters=counters,
                    )

        self.stdout.write(
            self.style.SUCCESS(
                "Ergebnis: "
                f"Videos neu {counters['videos_created']}, vorhanden {counters['videos_existing']}; "
                f"Zuordnungen neu {counters['assignments_created']}, vorhanden {counters['assignments_existing']}; "
                f"fehlende Artikel {counters['missing_products']}, "
                f"fehlende Kategorien {counters['missing_categories']}; "
                f"manuell/Kategoriebeschreibung {counters['manual']}."
            )
        )

    def _get_or_create_video(self, *, entry: dict, dry_run: bool, counters: dict) -> Video:
        existing = Video.objects.filter(vimeo_id=entry["vimeo_id"]).first()
        if existing:
            counters["videos_existing"] += 1
            return existing

        counters["videos_created"] += 1
        video = Video(title=entry["title"], vimeo_id=entry["vimeo_id"])
        video.full_clean()
        if not dry_run:
            video.save()
        self.stdout.write(f"VIDEO {'würde angelegt' if dry_run else 'angelegt'}: {video}")
        return video

    def _resolve_products(self, *, entry: dict, counters: dict) -> list[Product]:
        products_by_id: dict[int, Product] = {}
        erp_numbers = tuple(entry.get("erp_numbers", ()))
        if erp_numbers:
            found = Product.objects.filter(erp_nr__in=erp_numbers).order_by("erp_nr")
            for product in found:
                products_by_id[product.pk] = product
            found_erp_numbers = {product.erp_nr for product in found}
            for missing_erp_nr in sorted(set(erp_numbers) - found_erp_numbers):
                counters["missing_products"] += 1
                self.stdout.write(self.style.WARNING(f"FEHLT Artikel {missing_erp_nr} für {entry['title']}"))

        # Category/group mappings are intentionally exact and direct-only.
        # Descendants must be listed explicitly in source data, which keeps a
        # broad category match from silently assigning a film to unrelated rows.
        for category_slug in entry.get("category_slugs", ()):
            category = Category.objects.filter(slug=category_slug).first()
            if category is None:
                counters["missing_categories"] += 1
                self.stdout.write(
                    self.style.WARNING(f"FEHLT Kategorie {category_slug} für {entry['title']}")
                )
                continue
            for product in Product.objects.filter(categories=category).order_by("erp_nr").distinct():
                products_by_id[product.pk] = product

        return sorted(products_by_id.values(), key=lambda product: (product.erp_nr, product.pk))

    def _get_or_create_assignment(
        self,
        *,
        product: Product,
        video: Video,
        entry: dict,
        dry_run: bool,
        counters: dict,
    ) -> None:
        existing = ProductVideo.objects.filter(product=product, video__vimeo_id=entry["vimeo_id"]).first()
        if existing:
            counters["assignments_existing"] += 1
            return

        counters["assignments_created"] += 1
        if not dry_run:
            ProductVideo.objects.create(
                product=product,
                video=video,
                position=int(entry.get("position", 100)),
            )
        self.stdout.write(
            f"ZUORDNUNG {'würde angelegt' if dry_run else 'angelegt'}: "
            f"{product.erp_nr} <- {entry['title']}"
        )
