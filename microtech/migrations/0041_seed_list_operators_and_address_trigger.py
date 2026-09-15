from django.db import migrations

_OPERATORS = [
    ("in_list", "ist in Liste", "in_list", 70),
    ("not_in_list", "ist nicht in Liste", "not_in_list", 71),
]

_TRIGGER = ("address_write", "Anschrift schreiben", "customer.microtech_postal_address", "customer.Address", 30)


def seed(apps, schema_editor):
    Op = apps.get_model("microtech", "MicrotechOrderRuleOperator")
    for code, name, engine, prio in _OPERATORS:
        Op.objects.get_or_create(
            code=code,
            defaults={"name": name, "engine_operator": engine, "priority": prio, "is_active": True},
        )
    Trigger = apps.get_model("microtech", "RuleTrigger")
    code, label, task, root, prio = _TRIGGER
    Trigger.objects.get_or_create(
        code=code,
        defaults={"label": label, "task_name": task, "context_root": root, "priority": prio, "is_active": True},
    )


def unseed(apps, schema_editor):
    Op = apps.get_model("microtech", "MicrotechOrderRuleOperator")
    Op.objects.filter(code__in=[c for c, *_ in _OPERATORS]).delete()
    Trigger = apps.get_model("microtech", "RuleTrigger")
    Trigger.objects.filter(code=_TRIGGER[0]).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("microtech", "0040_alter_microtechorderruleoperator_engine_operator"),
        ("microtech", "0039_seed_anreden_constant"),
    ]
    operations = [migrations.RunPython(seed, unseed)]
