from django.core.management.base import CommandError
from django.core.management.color import no_style
from django.db import connection, transaction

from core.management.base import MonitoredBaseCommand
from hr.models import TravelExpenseClaim


class Command(MonitoredBaseCommand):
    help = "Setzt die Reisekosten-ID-Sequenz nur bei leerer Tabelle auf 1 zurück."

    def handle(self, *args, **options):
        if connection.vendor != "postgresql":
            raise CommandError("Der ID-Reset ist nur für PostgreSQL vorgesehen.")

        table = connection.ops.quote_name(TravelExpenseClaim._meta.db_table)
        reset_statements = connection.ops.sequence_reset_sql(no_style(), [TravelExpenseClaim])
        if not reset_statements:
            raise CommandError("Für die Reisekostenabrechnung wurde keine ID-Sequenz gefunden.")

        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute(f"LOCK TABLE {table} IN ACCESS EXCLUSIVE MODE")
                cursor.execute(f"SELECT EXISTS (SELECT 1 FROM {table})")
                if cursor.fetchone()[0]:
                    raise CommandError("Die Reisekostentabelle ist nicht leer; die ID-Sequenz wurde nicht zurückgesetzt.")
                for statement in reset_statements:
                    cursor.execute(statement)

        self.stdout.write(self.style.SUCCESS("Reisekosten-ID-Sequenz zurückgesetzt; die nächste ID ist 1."))
