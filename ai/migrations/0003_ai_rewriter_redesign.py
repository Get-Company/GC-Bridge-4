import django.db.models.deletion
from django.db import migrations, models


def forwards(apps, schema_editor):
    AIRewriteJob = apps.get_model("ai", "AIRewriteJob")
    ContentType = apps.get_model("contenttypes", "ContentType")
    try:
        product_ct = ContentType.objects.get(app_label="products", model="product")
    except ContentType.DoesNotExist:
        product_ct = None

    status_map = {
        "applied": "applied",
        "failed": "failed",
        "draft": "ready",
        "pending_review": "ready",
        "approved": "ready",
        "rejected": "ready",
    }
    for job in AIRewriteJob.objects.all():
        if product_ct is None or job.content_type_id != product_ct.id:
            job.delete()
            continue
        job.product_id = job.object_id
        job.field = job.target_field or job.source_field or ""
        job.status = status_map.get(job.status, "ready")
        job.save(update_fields=["product_id", "field", "status"])


class Migration(migrations.Migration):
    dependencies = [
        ("ai", "0002_airewritejob_is_archived"),
        ("products", "0001_initial"),
        ("contenttypes", "0002_remove_content_type_name"),
    ]

    operations = [
        # --- AIRewritePrompt verschlanken ---
        migrations.RemoveField(model_name="airewriteprompt", name="provider"),
        migrations.RemoveField(model_name="airewriteprompt", name="content_type"),
        migrations.RemoveField(model_name="airewriteprompt", name="source_field"),
        migrations.RemoveField(model_name="airewriteprompt", name="target_field"),
        migrations.RemoveField(model_name="airewriteprompt", name="output_format"),
        migrations.RemoveField(model_name="airewriteprompt", name="user_prompt_template"),
        migrations.RemoveField(model_name="airewriteprompt", name="temperature_override"),
        migrations.AlterField(
            model_name="airewriteprompt",
            name="system_prompt",
            field=models.TextField(verbose_name="Anweisung"),
        ),
        # --- AIRewriteJob: alten Index weg, neue Spalten hinzu ---
        migrations.RemoveIndex(model_name="airewritejob", name="ai_airewrit_content_e4bda1_idx"),
        migrations.AddField(
            model_name="airewritejob",
            name="product",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="ai_rewrite_jobs",
                to="products.product",
                verbose_name="Produkt",
            ),
        ),
        migrations.AddField(
            model_name="airewritejob",
            name="field",
            field=models.CharField(default="", max_length=120, verbose_name="Feld"),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name="airewritejob",
            name="celery_task_id",
            field=models.CharField(blank=True, default="", max_length=255, verbose_name="Celery Task-ID"),
        ),
        # --- Daten uebernehmen ---
        migrations.RunPython(forwards, migrations.RunPython.noop),
        # --- alte Spalten entfernen ---
        migrations.RemoveField(model_name="airewritejob", name="content_type"),
        migrations.RemoveField(model_name="airewritejob", name="object_id"),
        migrations.RemoveField(model_name="airewritejob", name="object_repr"),
        migrations.RemoveField(model_name="airewritejob", name="approved_by"),
        migrations.RemoveField(model_name="airewritejob", name="approved_at"),
        migrations.RemoveField(model_name="airewritejob", name="is_archived"),
        migrations.RemoveField(model_name="airewritejob", name="source_field"),
        migrations.RemoveField(model_name="airewritejob", name="target_field"),
        # --- product final non-null, status neue Choices ---
        migrations.AlterField(
            model_name="airewritejob",
            name="product",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="ai_rewrite_jobs",
                to="products.product",
                verbose_name="Produkt",
            ),
        ),
        migrations.AlterField(
            model_name="airewritejob",
            name="status",
            field=models.CharField(
                choices=[
                    ("queued", "In Arbeit"),
                    ("ready", "Ergebnis vorhanden"),
                    ("applied", "Uebernommen"),
                    ("failed", "Fehlgeschlagen"),
                ],
                db_index=True,
                default="queued",
                max_length=16,
                verbose_name="Status",
            ),
        ),
    ]
