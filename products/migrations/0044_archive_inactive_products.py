from django.db import migrations


def archive_inactive_products(apps, schema_editor):
    """Move all currently inactive products into the archive.

    This is the initial one-off "move the inactive products into the archive"
    step. Relations stay untouched; only the is_archived flag is set.
    """
    Product = apps.get_model("products", "Product")
    Product.objects.filter(is_active=False).update(is_archived=True)


def unarchive_all_products(apps, schema_editor):
    Product = apps.get_model("products", "Product")
    Product.objects.filter(is_archived=True).update(is_archived=False)


class Migration(migrations.Migration):

    dependencies = [
        ("products", "0043_archivedproduct_product_is_archived"),
    ]

    operations = [
        migrations.RunPython(archive_inactive_products, unarchive_all_products),
    ]
