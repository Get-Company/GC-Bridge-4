from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('microtech', '0006_microtechjob'),
    ]

    operations = [
        migrations.DeleteModel(
            name='MicrotechJob',
        ),
    ]
