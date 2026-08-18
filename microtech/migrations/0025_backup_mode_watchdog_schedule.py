from django.db import migrations

TASK_NAME = "Microtech Backup-Fenster Watchdog"
TASK_PATH = "microtech.backup_mode_watchdog"


def create_watchdog_schedule(apps, schema_editor):
    """Den Watchdog fest einplanen.

    Er ist eine Sicherheitsfunktion: bleibt der Klick zum Schliessen des
    Backup-Fensters aus, faehrt er microtech wieder hoch. Darauf zu vertrauen,
    dass jemand ihn nach dem Deploy von Hand im Admin anlegt, waere zu wenig.
    """
    IntervalSchedule = apps.get_model("django_celery_beat", "IntervalSchedule")
    PeriodicTask = apps.get_model("django_celery_beat", "PeriodicTask")

    schedule, _ = IntervalSchedule.objects.get_or_create(every=5, period="minutes")
    PeriodicTask.objects.get_or_create(
        task=TASK_PATH,
        defaults={
            "name": TASK_NAME,
            "interval": schedule,
            "args": "[]",
            "kwargs": "{}",
            "enabled": True,
            "description": (
                "Schliesst ein Microtech-Backup-Fenster, dessen Frist abgelaufen ist."
            ),
        },
    )


def remove_watchdog_schedule(apps, schema_editor):
    PeriodicTask = apps.get_model("django_celery_beat", "PeriodicTask")
    PeriodicTask.objects.filter(task=TASK_PATH).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("microtech", "0024_microtechsettings_backup_mode_active_and_more"),
        ("django_celery_beat", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(create_watchdog_schedule, remove_watchdog_schedule),
    ]
