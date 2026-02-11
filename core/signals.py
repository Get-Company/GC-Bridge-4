from django.conf import settings
from django.db.models.signals import post_migrate
from django.dispatch import receiver


@receiver(post_migrate)
def ensure_daily_sync_task(sender, **kwargs) -> None:
    if sender.name != "core":
        return

    try:
        from django_celery_beat.models import CrontabSchedule, PeriodicTask
    except Exception:
        return

    schedule_kwargs = {
        "minute": "0",
        "hour": "14",
        "day_of_week": "*",
        "day_of_month": "*",
        "month_of_year": "*",
    }
    if any(field.name == "timezone" for field in CrontabSchedule._meta.fields):
        schedule_kwargs["timezone"] = settings.TIME_ZONE

    schedule, _ = CrontabSchedule.objects.get_or_create(**schedule_kwargs)

    PeriodicTask.objects.update_or_create(
        name="daily_microtech_shopware_sync",
        defaults={
            "crontab": schedule,
            "task": "core.tasks.daily_microtech_shopware_sync",
            "enabled": True,
            "one_off": False,
            "args": "[]",
            "kwargs": "{}",
        },
    )
