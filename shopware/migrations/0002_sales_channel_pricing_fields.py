from decimal import Decimal

from django.db import migrations, models
from django.db.models import Q


class Migration(migrations.Migration):

    dependencies = [
        ("shopware", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="shopwaresettings",
            name="price_factor",
            field=models.DecimalField(decimal_places=4, default=Decimal("1.0"), max_digits=10),
        ),
        migrations.AddField(
            model_name="shopwaresettings",
            name="is_default",
            field=models.BooleanField(default=False),
        ),
        migrations.AddConstraint(
            model_name="shopwaresettings",
            constraint=models.UniqueConstraint(
                fields=("is_default",),
                condition=Q(is_default=True),
                name="unique_default_sales_channel",
            ),
        ),
    ]
