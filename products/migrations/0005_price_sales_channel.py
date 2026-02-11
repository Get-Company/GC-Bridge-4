from django.db import migrations, models


def assign_default_sales_channel(apps, schema_editor):
    ShopwareSettings = apps.get_model("shopware", "ShopwareSettings")
    Price = apps.get_model("products", "Price")
    default_channel = ShopwareSettings.objects.filter(is_default=True).first()
    if not default_channel:
        return
    Price.objects.filter(sales_channel__isnull=True).update(sales_channel=default_channel)


class Migration(migrations.Migration):

    dependencies = [
        ("products", "0004_alter_product_options"),
        ("shopware", "0002_sales_channel_pricing_fields"),
    ]

    operations = [
        migrations.AddField(
            model_name="price",
            name="sales_channel",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=models.deletion.CASCADE,
                related_name="prices",
                to="shopware.shopwaresettings",
            ),
        ),
        migrations.RunPython(assign_default_sales_channel, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name="price",
            constraint=models.UniqueConstraint(
                fields=("product", "sales_channel"),
                name="unique_price_per_sales_channel",
            ),
        ),
    ]
