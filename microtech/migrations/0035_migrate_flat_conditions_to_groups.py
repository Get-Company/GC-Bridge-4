from django.db import migrations

from microtech.rule_engine.backfill import backfill_condition_groups


def run(apps, schema_editor):
    backfill_condition_groups(
        apps.get_model("microtech", "MicrotechOrderRule"),
        apps.get_model("microtech", "MicrotechOrderRuleConditionGroup"),
        apps.get_model("microtech", "RuleTrigger"),
    )


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [("microtech", "0034_seed_triggers")]
    operations = [migrations.RunPython(run, noop)]
