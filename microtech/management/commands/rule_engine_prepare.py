"""Prepare existing order rules for the engine cutover.

Assigns active rules to the order_create trigger, ensures the BEFORE execution
phase, and (only with --enable) turns on engine_enabled, so that shadow/live
mode evaluates the same rules the legacy resolver already applies.
"""
from __future__ import annotations

from django.core.management.base import BaseCommand

from microtech.models import MicrotechOrderRule, RuleTrigger
from microtech.rule_engine.order_resolver import ORDER_CREATE_TASK


class Command(BaseCommand):
    help = "Ordnet aktive Bestellregeln dem order_create-Trigger zu (Vorbereitung Engine-Cutover)."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="Nur berichten, nichts ändern.")
        parser.add_argument("--enable", action="store_true", help="Zusätzlich engine_enabled=True setzen.")

    def handle(self, *args, **opts):
        dry_run = opts["dry_run"]
        enable = opts["enable"]

        trigger = (
            RuleTrigger.objects
            .filter(task_name=ORDER_CREATE_TASK, is_active=True)
            .order_by("priority", "id")
            .first()
        )
        if trigger is None:
            self.stderr.write("Kein aktiver order_create-Trigger gefunden.")
            return

        touched = 0
        for rule in MicrotechOrderRule.objects.filter(is_active=True):
            needs = (
                rule.trigger_id is None
                or rule.execution_phase != MicrotechOrderRule.ExecutionPhase.BEFORE
                or (enable and not rule.engine_enabled)
            )
            if not needs:
                continue
            touched += 1
            prefix = "[dry-run] " if dry_run else ""
            self.stdout.write(
                f"{prefix}Regel {rule.pk} '{rule.name}' → trigger={trigger.code}, phase=before, enable={enable}"
            )
            if dry_run:
                continue
            rule.trigger = trigger
            rule.execution_phase = MicrotechOrderRule.ExecutionPhase.BEFORE
            if enable:
                rule.engine_enabled = True
            rule.save(update_fields=["trigger", "execution_phase", "engine_enabled"])

        self.stdout.write(f"Fertig. Betroffen: {touched}.")
