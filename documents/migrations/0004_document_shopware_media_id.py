from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("documents", "0003_add_jinja2_cover_end_pdf"),
    ]

    operations = [
        migrations.AddField(
            model_name="document",
            name="shopware_media_id",
            field=models.CharField(
                blank=True,
                default="",
                editable=False,
                help_text="Wird beim Hochladen automatisch gesetzt und identifiziert die Datei dauerhaft in Shopware.",
                max_length=64,
                verbose_name="Shopware Media-ID",
            ),
        ),
    ]
