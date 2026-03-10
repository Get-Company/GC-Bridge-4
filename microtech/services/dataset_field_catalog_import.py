from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from django.db import transaction
from django.utils.text import slugify

from core.services import BaseService
from microtech.models import MicrotechDatasetCatalog, MicrotechDatasetField


CORE_DATASET_SELECTORS: tuple[str, ...] = (
    "Adressen - Adressen",
    "Anschriften - Anschriften",
    "Ansprechpartner - Ansprechpartner",
    "Vorgang - Vorgange",
    "VorgangArten - Vorgangsarten",
    "VorgangPosition - Vorgangspositionen",
)


@dataclass(frozen=True, slots=True)
class ParsedDatasetField:
    field_name: str
    label: str
    field_type: str
    is_calc_field: bool
    can_access: bool


@dataclass(frozen=True, slots=True)
class ParsedDataset:
    name: str
    description: str
    source_identifier: str
    fields: tuple[ParsedDatasetField, ...]


@dataclass(frozen=True, slots=True)
class DatasetFieldImportReport:
    parsed_datasets: int
    parsed_fields: int
    created_datasets: int
    updated_datasets: int
    created_fields: int
    updated_fields: int
    deactivated_fields: int
    dry_run: bool


class MicrotechDatasetFieldCatalogImportService(BaseService):
    model = MicrotechDatasetField

    def parse_list_file(
        self,
        *,
        file_path: Path,
        selectors: tuple[str, ...] = CORE_DATASET_SELECTORS,
        top_level_only: bool = True,
    ) -> list[ParsedDataset]:
        lines = self._read_lines(file_path)
        return self._parse_lines(lines=lines, selectors=selectors, top_level_only=top_level_only)

    def import_from_list_file(
        self,
        *,
        file_path: Path,
        selectors: tuple[str, ...] = CORE_DATASET_SELECTORS,
        top_level_only: bool = True,
        dry_run: bool = False,
    ) -> DatasetFieldImportReport:
        datasets = self.parse_list_file(
            file_path=file_path,
            selectors=selectors,
            top_level_only=top_level_only,
        )
        parsed_fields = sum(len(item.fields) for item in datasets)
        if dry_run:
            return DatasetFieldImportReport(
                parsed_datasets=len(datasets),
                parsed_fields=parsed_fields,
                created_datasets=0,
                updated_datasets=0,
                created_fields=0,
                updated_fields=0,
                deactivated_fields=0,
                dry_run=True,
            )

        created_datasets = 0
        updated_datasets = 0
        created_fields = 0
        updated_fields = 0
        deactivated_fields = 0
        reserved_codes: set[str] = set()

        with transaction.atomic():
            for dataset_index, parsed_dataset in enumerate(datasets, start=1):
                dataset_code = self._ensure_unique_dataset_code(
                    source_identifier=parsed_dataset.source_identifier,
                    reserved_codes=reserved_codes,
                )
                dataset_obj, dataset_created = MicrotechDatasetCatalog.objects.update_or_create(
                    source_identifier=parsed_dataset.source_identifier,
                    defaults={
                        "code": dataset_code,
                        "name": parsed_dataset.name,
                        "description": parsed_dataset.description,
                        "priority": dataset_index * 10,
                        "is_active": True,
                    },
                )
                if dataset_created:
                    created_datasets += 1
                else:
                    updated_datasets += 1

                seen_field_names: set[str] = set()
                for field_index, parsed_field in enumerate(parsed_dataset.fields, start=1):
                    seen_field_names.add(parsed_field.field_name)
                    _, field_created = MicrotechDatasetField.objects.update_or_create(
                        dataset=dataset_obj,
                        field_name=parsed_field.field_name,
                        defaults={
                            "label": parsed_field.label,
                            "field_type": parsed_field.field_type,
                            "is_calc_field": parsed_field.is_calc_field,
                            "can_access": parsed_field.can_access,
                            "priority": field_index * 10,
                            "is_active": True,
                        },
                    )
                    if field_created:
                        created_fields += 1
                    else:
                        updated_fields += 1

                stale_fields_qs = MicrotechDatasetField.objects.filter(dataset=dataset_obj, is_active=True)
                if seen_field_names:
                    stale_fields_qs = stale_fields_qs.exclude(field_name__in=seen_field_names)
                deactivated_fields += stale_fields_qs.update(is_active=False)

        return DatasetFieldImportReport(
            parsed_datasets=len(datasets),
            parsed_fields=parsed_fields,
            created_datasets=created_datasets,
            updated_datasets=updated_datasets,
            created_fields=created_fields,
            updated_fields=updated_fields,
            deactivated_fields=deactivated_fields,
            dry_run=False,
        )

    @staticmethod
    def _read_lines(file_path: Path) -> list[str]:
        if not file_path.exists():
            raise FileNotFoundError(f"Datei nicht gefunden: {file_path}")
        for encoding in ("utf-8", "cp1252", "latin-1"):
            try:
                return file_path.read_text(encoding=encoding).splitlines()
            except UnicodeDecodeError:
                continue
        raise ValueError(f"Datei konnte nicht dekodiert werden: {file_path}")

    def _parse_lines(
        self,
        *,
        lines: list[str],
        selectors: tuple[str, ...],
        top_level_only: bool,
    ) -> list[ParsedDataset]:
        selector_tokens = {self._normalize_selector(item) for item in selectors if item}
        datasets: list[dict[str, object]] = []
        current_dataset: dict[str, object] | None = None

        for line in lines:
            stripped = line.strip()
            if not stripped:
                continue
            indent = len(line) - len(line.lstrip(" "))

            if indent == 0 and stripped.startswith("DataSet: "):
                parsed_dataset_header = self._parse_dataset_header(stripped)
                if not parsed_dataset_header:
                    current_dataset = None
                    continue
                dataset_name, dataset_description, source_identifier = parsed_dataset_header
                if selector_tokens and not self._matches_selector(
                    selector_tokens=selector_tokens,
                    dataset_name=dataset_name,
                    dataset_description=dataset_description,
                    source_identifier=source_identifier,
                ):
                    current_dataset = None
                    continue
                current_dataset = {
                    "name": dataset_name,
                    "description": dataset_description,
                    "source_identifier": source_identifier,
                    "fields": [],
                }
                datasets.append(current_dataset)
                continue

            if not current_dataset:
                continue
            if not stripped.startswith("Field: "):
                continue
            if top_level_only and indent != 2:
                continue

            parsed_field = self._parse_field_line(stripped)
            if not parsed_field:
                continue
            current_dataset["fields"].append(parsed_field)

        result: list[ParsedDataset] = []
        for row in datasets:
            fields: tuple[ParsedDatasetField, ...] = tuple(row["fields"])
            if not fields:
                continue
            result.append(
                ParsedDataset(
                    name=str(row["name"]),
                    description=str(row["description"]),
                    source_identifier=str(row["source_identifier"]),
                    fields=fields,
                )
            )
        return result

    @staticmethod
    def _parse_dataset_header(line: str) -> tuple[str, str, str] | None:
        payload = line.removeprefix("DataSet: ").strip()
        if not payload:
            return None
        if " - " in payload:
            dataset_name, dataset_description = payload.split(" - ", 1)
        else:
            dataset_name, dataset_description = payload, ""
        dataset_name = dataset_name.strip()
        dataset_description = dataset_description.strip()
        source_identifier = f"{dataset_name} - {dataset_description}" if dataset_description else dataset_name
        return dataset_name, dataset_description, source_identifier

    @staticmethod
    def _parse_field_line(line: str) -> ParsedDatasetField | None:
        payload = line.removeprefix("Field: ").strip()
        if not payload:
            return None

        can_access = True
        if payload.endswith("+"):
            payload = payload[:-1].rstrip()
            can_access = True
        elif payload.endswith("/"):
            payload = payload[:-1].rstrip()
            can_access = False

        if not payload.endswith(")") or " (" not in payload:
            return None
        left, field_type = payload.rsplit(" (", 1)
        field_type = field_type[:-1].strip()

        if " - " in left:
            field_name, label = left.split(" - ", 1)
        else:
            field_name, label = left, ""

        field_name = field_name.strip()
        is_calc_field = field_name.startswith("*")
        if is_calc_field:
            field_name = field_name[1:].strip()
        label = label.strip()

        if not field_name:
            return None

        return ParsedDatasetField(
            field_name=field_name,
            label=label,
            field_type=field_type,
            is_calc_field=is_calc_field,
            can_access=can_access,
        )

    @classmethod
    def _matches_selector(
        cls,
        *,
        selector_tokens: set[str],
        dataset_name: str,
        dataset_description: str,
        source_identifier: str,
    ) -> bool:
        candidates = {
            cls._normalize_selector(dataset_name),
            cls._normalize_selector(source_identifier),
        }
        if dataset_description:
            candidates.add(cls._normalize_selector(dataset_description))

        selector_tokens_ascii = {slugify(item, allow_unicode=False) for item in selector_tokens}
        candidates_ascii = {slugify(item, allow_unicode=False) for item in candidates}

        return bool(selector_tokens.intersection(candidates) or selector_tokens_ascii.intersection(candidates_ascii))

    @staticmethod
    def _normalize_selector(value: str) -> str:
        return " ".join(str(value).strip().lower().split())

    @staticmethod
    def _build_dataset_code(source_identifier: str) -> str:
        code = slugify(source_identifier, allow_unicode=False).replace("-", "_")
        if not code:
            code = "dataset"
        return code[:64]

    @classmethod
    def _ensure_unique_dataset_code(
        cls,
        *,
        source_identifier: str,
        reserved_codes: set[str],
    ) -> str:
        base_code = cls._build_dataset_code(source_identifier)
        candidate = base_code
        suffix = 2
        while (
            candidate in reserved_codes
            or MicrotechDatasetCatalog.objects.filter(code=candidate).exclude(
                source_identifier=source_identifier
            ).exists()
        ):
            suffix_text = f"_{suffix}"
            candidate = f"{base_code[: 64 - len(suffix_text)]}{suffix_text}"
            suffix += 1
        reserved_codes.add(candidate)
        return candidate


__all__ = [
    "CORE_DATASET_SELECTORS",
    "DatasetFieldImportReport",
    "MicrotechDatasetFieldCatalogImportService",
    "ParsedDataset",
    "ParsedDatasetField",
]
