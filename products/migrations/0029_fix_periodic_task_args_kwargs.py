from django.db import migrations


def fix_periodic_task_json_fields(apps, schema_editor):
    PeriodicTask = apps.get_model("django_celery_beat", "PeriodicTask")
    for task in PeriodicTask.objects.all():
        changed = False
        if not task.args or task.args.strip() == "":
            task.args = "[]"
            changed = True
        if not task.kwargs or task.kwargs.strip() == "":
            task.kwargs = "{}"
            changed = True
        if changed:
            task.save(update_fields=["args", "kwargs"])


class Migration(migrations.Migration):
    dependencies = [
        ("products", "0028_category_description_it_it_and_more"),
        ("django_celery_beat", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(fix_periodic_task_json_fields, migrations.RunPython.noop),
    ]
