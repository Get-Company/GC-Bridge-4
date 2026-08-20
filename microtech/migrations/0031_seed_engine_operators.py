from django.db import migrations

NEW = [
    ("between", "zwischen (between)", "between", 60),
    ("before", "vor (before)", "before", 61),
    ("after", "nach (after)", "after", 62),
    ("is_true", "ist wahr", "is_true", 63),
    ("is_false", "ist falsch", "is_false", 64),
]


def seed(apps, schema_editor):
    Op = apps.get_model("microtech", "MicrotechOrderRuleOperator")
    for code, name, engine, prio in NEW:
        Op.objects.get_or_create(
            code=code,
            defaults={"name": name, "engine_operator": engine, "priority": prio, "is_active": True},
        )


def unseed(apps, schema_editor):
    Op = apps.get_model("microtech", "MicrotechOrderRuleOperator")
    Op.objects.filter(code__in=[c for c, *_ in NEW]).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("microtech", "0030_alter_microtechorderruleoperator_engine_operator"),
    ]
    operations = [migrations.RunPython(seed, unseed)]
