from __future__ import annotations

from django.db import migrations


def create_task_fehler_category(apps, schema_editor):
    IssueCategory = apps.get_model("issues", "IssueCategory")
    IssueCategory.objects.get_or_create(
        name="Automatische Task-Fehler",
        defaults={"color": "#f97316", "is_active": True},
    )


def remove_task_fehler_category(apps, schema_editor):
    IssueCategory = apps.get_model("issues", "IssueCategory")
    IssueCategory.objects.filter(name="Automatische Task-Fehler").delete()


class Migration(migrations.Migration):
    dependencies = [
        ("issues", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(create_task_fehler_category, remove_task_fehler_category),
    ]
