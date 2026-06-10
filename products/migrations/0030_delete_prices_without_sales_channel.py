from django.db import migrations


def delete_prices_without_sales_channel(apps, schema_editor):
    Price = apps.get_model("products", "Price")
    deleted, _ = Price.objects.filter(sales_channel__isnull=True).delete()
    if deleted:
        print(f"  Deleted {deleted} Price entries without sales_channel.")


class Migration(migrations.Migration):
    dependencies = [
        ("products", "0029_fix_periodic_task_args_kwargs"),
    ]

    operations = [
        migrations.RunPython(
            delete_prices_without_sales_channel,
            migrations.RunPython.noop,
        ),
    ]
