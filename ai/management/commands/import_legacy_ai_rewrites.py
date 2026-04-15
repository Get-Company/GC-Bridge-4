from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from django.contrib.contenttypes.models import ContentType
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils.text import slugify

from ai.models import AIProviderConfig, AIRewriteJob, AIRewritePrompt
from ai.services import AIRewriteApplyService
from products.models import Product


class Command(BaseCommand):
    help = "Importiert AI Rewrite Provider, Prompts und Jobs aus einer Legacy-SQLite-DB oder direkt aus database.sql."

    def add_arguments(self, parser):
        parser.add_argument(
            "erp_nrs",
            nargs="*",
            help="Optionale ERP-Nummern. Wenn leer, werden alle importiert.",
        )
        parser.add_argument(
            "--sqlite-path",
            default="tmp/legacy_v3.sqlite3",
            help="Pfad zur Legacy-SQLite-Datei. Default: tmp/legacy_v3.sqlite3",
        )
        parser.add_argument(
            "--dump-path",
            default="",
            help="Optionaler Pfad zur Legacy-MySQL-Dump-Datei (database.sql). Wenn gesetzt, wird daraus bei Bedarf SQLite erzeugt.",
        )
        parser.add_argument(
            "--rebuild-sqlite",
            action="store_true",
            help="Erzeugt die Legacy-SQLite-Datei aus --dump-path neu, auch wenn sie bereits existiert.",
        )
        parser.add_argument(
            "--apply-imported",
            action="store_true",
            help="Uebernimmt importierte, freigegebene Legacy-Ergebnisse direkt in das aktuelle Produkt.",
        )

    def handle(self, *args, **options):
        sqlite_path = self._resolve_sqlite_path(
            sqlite_path_value=options["sqlite_path"],
            dump_path_value=options.get("dump_path", ""),
            rebuild_sqlite=options.get("rebuild_sqlite", False),
        )
        erp_nrs = [erp_nr.strip() for erp_nr in options.get("erp_nrs") or [] if erp_nr.strip()]
        apply_imported = options.get("apply_imported", False)

        connection = sqlite3.connect(sqlite_path)
        connection.row_factory = sqlite3.Row
        try:
            rows = list(self._load_rows(connection=connection, erp_nrs=erp_nrs))
        finally:
            connection.close()

        if not rows:
            self.stdout.write("Keine passenden Legacy Rewrite-Jobs gefunden.")
            return

        product_content_type = ContentType.objects.get_for_model(Product)
        apply_service = AIRewriteApplyService()
        created_jobs = 0
        updated_jobs = 0
        skipped_jobs = 0
        applied_jobs = 0

        with transaction.atomic():
            for row in rows:
                current_product = Product.objects.filter(erp_nr=str(row["erp_nr"] or "").strip()).first()
                if current_product is None:
                    skipped_jobs += 1
                    continue

                target_field = self._map_field_name(str(row["target_field"] or "").strip())
                source_field = self._map_field_name(str(row["source_field"] or "").strip())
                if not target_field or not hasattr(current_product, target_field):
                    skipped_jobs += 1
                    continue
                if not source_field or not hasattr(current_product, source_field):
                    source_field = target_field

                provider = self._upsert_provider(row)
                prompt = self._upsert_prompt(
                    row=row,
                    provider=provider,
                    content_type=product_content_type,
                    source_field=source_field,
                    target_field=target_field,
                )
                result_text = self._normalize_result_text(row["result"])
                source_snapshot = str(row["original_content"] or row[f"legacy_{source_field}"] or "")
                legacy_status = str(row["status"] or "").strip().upper()
                status = self._map_status(
                    legacy_status=legacy_status,
                    legacy_target_value=str(row[f"legacy_{target_field}"] or ""),
                    result_text=result_text,
                )

                job, created = AIRewriteJob.objects.update_or_create(
                    external_key=f"legacy-job:{row['id']}",
                    defaults={
                        "content_type": product_content_type,
                        "object_id": current_product.pk,
                        "object_repr": str(current_product),
                        "prompt": prompt,
                        "provider": provider,
                        "source_field": source_field,
                        "target_field": target_field,
                        "status": status,
                        "is_archived": status == AIRewriteJob.Status.APPLIED,
                        "source_snapshot": source_snapshot,
                        "rendered_prompt": str(row["rendered_prompt"] or ""),
                        "result_text": result_text,
                        "error_message": str(row["error_message"] or ""),
                    },
                )
                if created:
                    created_jobs += 1
                else:
                    updated_jobs += 1

                if apply_imported and status in {AIRewriteJob.Status.APPROVED, AIRewriteJob.Status.APPLIED} and result_text:
                    apply_service.apply(job=job)
                    applied_jobs += 1

        self.stdout.write(
            self.style.SUCCESS(
                "Legacy Rewrite-Import abgeschlossen: "
                f"created={created_jobs}, updated={updated_jobs}, skipped={skipped_jobs}, applied={applied_jobs}"
            )
        )

    def _resolve_sqlite_path(self, *, sqlite_path_value: str, dump_path_value: str, rebuild_sqlite: bool) -> Path:
        sqlite_path = Path(sqlite_path_value).resolve()
        dump_path = Path(dump_path_value).resolve() if dump_path_value else None

        if dump_path:
            if not dump_path.exists():
                raise CommandError(f"Legacy Dump-Datei nicht gefunden: {dump_path}")
            if rebuild_sqlite or not sqlite_path.exists():
                call_command("legacy_dump_to_sqlite", str(dump_path), str(sqlite_path), overwrite=True)

        if not sqlite_path.exists():
            raise CommandError(
                f"Legacy SQLite-Datei nicht gefunden: {sqlite_path}. "
                "Nutze --dump-path database.sql oder uebergib einen gueltigen --sqlite-path."
            )

        return sqlite_path

    def _load_rows(self, *, connection: sqlite3.Connection, erp_nrs: list[str]):
        base_sql = """
            SELECT
                job.id,
                job.rendered_prompt,
                job.result,
                job.error_message,
                job.original_content,
                job.source_field,
                job.target_field,
                job.status,
                prompt.id AS prompt_id,
                prompt.name AS prompt_name,
                prompt.template AS prompt_template,
                prompt.notes AS prompt_notes,
                provider.id AS provider_id,
                provider.name AS provider_name,
                provider.base_url AS provider_base_url,
                provider.model_name AS provider_model_name,
                product.erp_nr,
                product.description_de AS legacy_description_de,
                product.description_short_de AS legacy_description_short_de
            FROM ai_rewritejob AS job
            INNER JOIN ai_prompt AS prompt ON prompt.id = job.prompt_id
            INNER JOIN ai_providerconfig AS provider ON provider.id = job.provider_id
            INNER JOIN products_product AS product ON product.id = job.product_id
            WHERE job.target_field IN ('description', 'description_de', 'description_short', 'description_short_de')
        """
        params: list[str] = []
        if erp_nrs:
            placeholders = ",".join("?" for _ in erp_nrs)
            base_sql += f" AND product.erp_nr IN ({placeholders})"
            params.extend(erp_nrs)
        base_sql += " ORDER BY job.id"
        yield from connection.execute(base_sql, params)

    @staticmethod
    def _upsert_provider(row: sqlite3.Row) -> AIProviderConfig:
        external_key = f"legacy-provider:{row['provider_id']}"
        defaults = {
            "name": f"Legacy Import: {row['provider_name']}",
            "base_url": str(row["provider_base_url"] or "https://api.openai.com/v1"),
            "model_name": str(row["provider_model_name"] or "legacy-model"),
            "api_key": "",
            "is_active": False,
        }
        provider, _ = AIProviderConfig.objects.update_or_create(external_key=external_key, defaults=defaults)
        return provider

    @staticmethod
    def _upsert_prompt(
        *,
        row: sqlite3.Row,
        provider: AIProviderConfig,
        content_type: ContentType,
        source_field: str,
        target_field: str,
    ) -> AIRewritePrompt:
        external_key = f"legacy-prompt:{row['prompt_id']}"
        name = str(row["prompt_name"] or f"Legacy Prompt {row['prompt_id']}")
        defaults = {
            "name": f"Legacy Import: {name}",
            "slug": f"legacy-{row['prompt_id']}-{slugify(name)}"[:255],
            "description": str(row["prompt_notes"] or ""),
            "provider": provider,
            "content_type": content_type,
            "source_field": source_field,
            "target_field": target_field,
            "system_prompt": str(row["prompt_template"] or ""),
            "output_format": AIRewritePrompt.OutputFormat.HTML,
            "is_active": False,
        }
        prompt, _ = AIRewritePrompt.objects.update_or_create(external_key=external_key, defaults=defaults)
        return prompt

    @staticmethod
    def _map_field_name(field_name: str) -> str:
        mapping = {
            "description": "description_de",
            "description_de": "description_de",
            "description_short": "description_short_de",
            "description_short_de": "description_short_de",
        }
        return mapping.get(field_name, field_name)

    @staticmethod
    def _normalize_result_text(raw_value) -> str:
        text = str(raw_value or "")
        if not text:
            return ""
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            return text.strip()
        return str(parsed or "").strip()

    @staticmethod
    def _normalize_compare_text(value: str) -> str:
        return " ".join((value or "").split())

    def _map_status(self, *, legacy_status: str, legacy_target_value: str, result_text: str) -> str:
        if self._normalize_compare_text(legacy_target_value) and (
            self._normalize_compare_text(legacy_target_value) == self._normalize_compare_text(result_text)
        ):
            return AIRewriteJob.Status.APPLIED
        if legacy_status == "APPROVED":
            return AIRewriteJob.Status.APPROVED
        if legacy_status == "REJECTED":
            return AIRewriteJob.Status.REJECTED
        if legacy_status == "FAILED":
            return AIRewriteJob.Status.FAILED
        return AIRewriteJob.Status.PENDING_REVIEW
