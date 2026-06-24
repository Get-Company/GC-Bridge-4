from pathlib import Path

from core.management.base import MonitoredBaseCommand

from emails.models import MjmlComponent

_TEMPLATE_DIR = Path(__file__).resolve().parents[4] / "old-emails" / "template"

_HEAD_FILES = {"head.mjml", "head_green.mjml", "styles.mjml"}

_SKIP = {"emails.css"}

_PRETTY_NAMES = {
    "4r": "4-spaltig",
    "blog_acymailing": "Blog (AcyMailing)",
    "certs_logo_green": "Zertifikate Logo (grün)",
    "contact_table": "Kontakt-Tabelle",
    "contact_table_green": "Kontakt-Tabelle (grün)",
    "disclaimer": "Disclaimer",
    "header_acryl_logo": "Header Acryl-Logo",
    "header_logo": "Header Logo",
    "head": "Head (Standard)",
    "head_green": "Head (grün)",
    "nav_items_shop": "Navigation Shop",
    "nav_items_shop_green": "Navigation Shop (grün)",
    "order_form_product": "Bestellformular Produkt",
    "order_form_product_green": "Bestellformular Produkt (grün)",
    "order_form_product_shipping_free": "Bestellformular Produkt (versandkostenfrei)",
    "product": "Produkt",
    "product_green": "Produkt (grün)",
    "product_shipping_free": "Produkt (versandkostenfrei)",
    "salutation": "Anrede",
    "styles": "Styles (CSS)",
    "subheader": "Subheader",
    "subheader_green": "Subheader (grün)",
    "title_img": "Titel-Bild",
    "title_txt": "Titel-Text",
    "view_online": "Online ansehen",
    "weihnachten": "Weihnachten",
}


class Command(MonitoredBaseCommand):
    help = "Import MJML components from old-emails/template/ into the MjmlComponent library"

    def add_arguments(self, parser):
        parser.add_argument(
            "--overwrite",
            action="store_true",
            help="Overwrite existing components with the same name",
        )

    def handle(self, *args, **options):
        overwrite = options["overwrite"]
        created = updated = skipped = 0

        mjml_files = sorted(_TEMPLATE_DIR.glob("*.mjml"))

        for path in mjml_files:
            if path.name in _SKIP:
                continue

            stem = path.stem
            placement = MjmlComponent.Placement.HEAD if path.name in _HEAD_FILES else MjmlComponent.Placement.BODY
            name = _PRETTY_NAMES.get(stem, stem.replace("_", " ").title())
            markup = path.read_text(encoding="utf-8")

            obj, was_created = MjmlComponent.objects.get_or_create(
                name=name,
                defaults={"mjml_markup": markup, "placement": placement},
            )

            if was_created:
                created += 1
                self.stdout.write(f"  created  {name}")
            elif overwrite:
                obj.mjml_markup = markup
                obj.placement = placement
                obj.save(update_fields=["mjml_markup", "placement", "updated_at"])
                updated += 1
                self.stdout.write(f"  updated  {name}")
            else:
                skipped += 1
                self.stdout.write(self.style.WARNING(f"  skipped  {name} (already exists, use --overwrite to replace)"))

        self.stdout.write(
            self.style.SUCCESS(
                f"\nDone: {created} created, {updated} updated, {skipped} skipped"
            )
        )
