from django.core.management.base import BaseCommand
from django.db import transaction
from django_celery_beat.models import IntervalSchedule, PeriodicTask


class Command(BaseCommand):
    help = "Enable the five-minute Shopware payment-status sync in Django Celery Beat."

    @transaction.atomic
    def handle(self, *args, **options):
        interval, _ = IntervalSchedule.objects.get_or_create(every=5, period=IntervalSchedule.MINUTES)
        task, created = PeriodicTask.objects.update_or_create(
            name="Zahlungsstatus aus Shopware alle 5 Minuten aktualisieren",
            defaults={
                "task": "orders.shopware_sync_payment_states",
                "interval": interval,
                "crontab": None, "solar": None, "clocked": None,
                "args": "[]", "kwargs": "{}", "queue": "orders",
                "enabled": True, "one_off": False, "expires": None, "expire_seconds": 240,
                "description": "Aktualisiert Zahlungsstatus und Zahlungsreferenzen aller importierten Bestellungen aus Shopware.",
            },
        )
        self.stdout.write(f"{'Created' if created else 'Updated'} periodic task {task.pk}: {task.name}")
