from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from hr.services.setup_service import HrSetupService


class Command(BaseCommand):
    help = "Erzeugt idempotent die HR-Grundkonfiguration und optional Demo-Daten."

    def add_arguments(self, parser):
        parser.add_argument(
            "--demo-username",
            type=str,
            default="",
            help="Optionaler Username fuer ein Demo-Mitarbeiterprofil.",
        )
        parser.add_argument(
            "--create-demo-user",
            action="store_true",
            help="Erzeugt den Demo-User, falls er noch nicht existiert.",
        )
        parser.add_argument(
            "--demo-password",
            type=str,
            default="",
            help="Optionales Passwort fuer einen neu erzeugten Demo-User.",
        )
        parser.add_argument(
            "--with-sample-records",
            action="store_true",
            help="Erzeugt Beispiel-Urlaub, Krankheit, Zeitkonto und Monatsuebersicht fuer den Demo-Mitarbeiter.",
        )

    def handle(self, *args, **options):
        demo_username = (options.get("demo_username") or "").strip()
        create_demo_user = options.get("create_demo_user", False)
        demo_password = options.get("demo_password") or ""
        with_sample_records = options.get("with_sample_records", False)

        if with_sample_records and not demo_username:
            raise CommandError("--with-sample-records erfordert --demo-username.")

        try:
            result = HrSetupService().bootstrap(
                demo_username=demo_username,
                create_demo_user=create_demo_user,
                demo_password=demo_password,
                with_sample_records=with_sample_records,
            )
        except ValueError as exc:
            raise CommandError(str(exc)) from exc

        self.stdout.write(self.style.SUCCESS("HR-Bootstrap erfolgreich abgeschlossen."))
        self.stdout.write(f"Gruppen: {', '.join(result['groups'])}")
        self.stdout.write(
            f"Stammdaten: department={result['department_id']} holiday_calendar={result['holiday_calendar_id']} "
            f"work_schedule={result['work_schedule_id']}"
        )
        if result.get("employee_profile_id"):
            self.stdout.write(
                f"Demo-Mitarbeiterprofil: {result['employee_profile_id']} "
                f"(user_created={result.get('created_demo_user', False)})"
            )
        if result.get("samples"):
            self.stdout.write(f"Beispieldaten: {result['samples']}")
