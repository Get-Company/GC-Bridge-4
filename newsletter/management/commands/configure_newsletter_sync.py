import json

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django_celery_beat.models import CrontabSchedule, PeriodicTask


class Command(BaseCommand):
    help = "Richtet den täglichen vollständigen Shopware-Newsletterabgleich um 02:00 ein."

    @transaction.atomic
    def handle(self, *args, **options):
        tasks = PeriodicTask.objects.filter(task="newsletter.shopware_sync_recipients")
        if tasks.count() > 1:
            raise CommandError("Mehrere Newsletter-Zeitpläne vorhanden; bitte zuerst zusammenführen.")
        schedule, _ = CrontabSchedule.objects.get_or_create(
            minute="0", hour="2", day_of_week="*", day_of_month="*", month_of_year="*",
            timezone="Europe/Berlin",
        )
        task = tasks.first() or PeriodicTask(task="newsletter.shopware_sync_recipients")
        task.name = "Newsletter-Empfänger täglich synchronisieren"
        task.crontab = schedule
        task.interval = None
        task.solar = None
        task.clocked = None
        task.args = "[]"
        task.kwargs = json.dumps({"page_size": 100, "mark_missing": True})
        task.enabled = True
        task.one_off = False
        task.start_time = None
        task.expires = None
        task.expire_seconds = None
        task.save()
        self.stdout.write(self.style.SUCCESS("Newsletterabgleich: täglich 02:00 Europe/Berlin."))
