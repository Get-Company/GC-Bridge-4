from django.db import migrations

from customer.services.webshop_mapping import EU_COUNTRY_CODES, _ITALIAN_B2B_GROUP


def seed(apps, schema_editor):
    C = apps.get_model("microtech", "RuleConstant")
    C.objects.get_or_create(
        key="eu_country_codes",
        defaults={"value": ",".join(sorted(EU_COUNTRY_CODES)), "kind": "list"},
    )
    C.objects.get_or_create(
        key="italian_b2b_group",
        defaults={"value": _ITALIAN_B2B_GROUP, "kind": "scalar"},
    )


def unseed(apps, schema_editor):
    C = apps.get_model("microtech", "RuleConstant")
    C.objects.filter(key__in=["eu_country_codes", "italian_b2b_group"]).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("microtech", "0032_ruleconstant"),
    ]

    operations = [
        migrations.RunPython(seed, unseed),
    ]
