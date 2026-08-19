from django.db import migrations

TRIGGERS = [
    ("order_create", "Bestellung anlegen", "orders.microtech_order_upsert", "orders.Order", 10),
    ("customer_create", "Kunde anlegen", "customer.microtech_customer_upsert", "customer.Customer", 20),
]


def seed(apps, schema_editor):
    T = apps.get_model("microtech", "RuleTrigger")
    for code, label, task, root, prio in TRIGGERS:
        T.objects.get_or_create(code=code, defaults={
            "label": label, "task_name": task, "context_root": root, "priority": prio, "is_active": True})


def unseed(apps, schema_editor):
    T = apps.get_model("microtech", "RuleTrigger")
    T.objects.filter(code__in=[c for c, *_ in TRIGGERS]).delete()


class Migration(migrations.Migration):
    dependencies = [("microtech", "0033_seed_ruleconstants")]
    operations = [migrations.RunPython(seed, unseed)]
