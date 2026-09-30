from core.management.base import MonitoredBaseCommand

from emails.mjml import normalize_legacy_asset_urls, normalize_legacy_recipient_placeholders
from emails.models import MjmlComponent


class Command(MonitoredBaseCommand):
    help = "Normalisiert alte Joomla-Bildpfade und AcyMailing-Empfaengerplatzhalter."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Aenderungen nur zaehlen und keine Komponenten speichern.",
        )

    def handle(self, *args, **options):
        dry_run = bool(options.get("dry_run"))
        changed = 0

        for component in MjmlComponent.objects.order_by("pk").iterator():
            markup = component.mjml_markup or ""
            normalized = normalize_legacy_asset_urls(markup)
            if component.rendering_mode == MjmlComponent.RenderingMode.DJANGO_JINJA:
                normalized = normalize_legacy_recipient_placeholders(normalized)
            if normalized == markup:
                continue

            changed += 1
            if not dry_run:
                component.mjml_markup = normalized
                component.save(update_fields=("mjml_markup", "updated_at"))

        mode = "wuerden aktualisiert" if dry_run else "aktualisiert"
        self.stdout.write(self.style.SUCCESS(f"{changed} Newsletter-Komponenten {mode}."))
