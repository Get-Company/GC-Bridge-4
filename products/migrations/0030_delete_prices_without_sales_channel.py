from django.db import migrations


def delete_prices_without_sales_channel(apps, schema_editor):
    Price = apps.get_model("products", "Price")
    table_name = schema_editor.quote_name(Price._meta.db_table)
    column_name = schema_editor.quote_name("sales_channel_id")
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(f"DELETE FROM {table_name} WHERE {column_name} IS NULL")
        deleted = cursor.rowcount
    if deleted and deleted > 0:
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
