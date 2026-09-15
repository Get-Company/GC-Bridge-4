from django.db import migrations

# Union of _SALUTATION_FEMALE_VALUES and _SALUTATION_MALE_VALUES
# (customer/services/webshop_mapping.py). Seeded as a RuleConstant list so rules
# can reference it via {{ @anreden }} in a not_in_list condition.
_ANREDEN = [
    "frau", "fr", "mrs", "ms", "miss", "madam", "madame", "weiblich", "female", "w", "f",
    "herr", "hr", "mr", "mister", "mann", "male", "monsieur", "m", "h",
]


def seed(apps, schema_editor):
    RuleConstant = apps.get_model("microtech", "RuleConstant")
    RuleConstant.objects.update_or_create(
        key="anreden",
        defaults={"value": ",".join(_ANREDEN), "kind": "list"},
    )


def unseed(apps, schema_editor):
    RuleConstant = apps.get_model("microtech", "RuleConstant")
    RuleConstant.objects.filter(key="anreden").delete()


class Migration(migrations.Migration):
    dependencies = [
        ("microtech", "0038_ruleengineshadowrun_and_more"),
    ]
    operations = [
        migrations.RunPython(seed, unseed),
    ]
