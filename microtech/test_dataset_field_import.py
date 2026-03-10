from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory

from django.core.management import call_command
from django.test import TestCase

from microtech.models import (
    MicrotechDatasetCatalog,
    MicrotechDatasetField,
    MicrotechOrderRuleAction,
    MicrotechOrderRuleActionTarget,
    MicrotechOrderRuleCondition,
    MicrotechOrderRuleConditionSource,
)


class MicrotechDatasetFieldImportCommandTest(TestCase):
    def _write_list(self, directory: Path, name: str, content: str) -> Path:
        file_path = directory / name
        file_path.write_text(content.strip() + "\n", encoding="utf-8")
        return file_path

    def test_imports_only_selected_dataset_and_top_level_fields(self):
        with TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            file_path = self._write_list(
                root,
                "sample.lst",
                """
DataSet: Adressen - Adressen
  Field: Nr - Nummer (UnicodeString) +
  NestedDataSet: Kontakt - Kontakt
    Field: NestedFoo - Nested Feld (UnicodeString) +
  Field: SuchBeg - Suchbegriff (UnicodeString) +

DataSet: Vorgang - Vorgange
  Field: BelegNr - Belegnummer (UnicodeString) +
                """,
            )

            call_command(
                "microtech_import_dataset_fields",
                "--file",
                str(file_path),
                "--dataset",
                "Adressen - Adressen",
            )

        self.assertEqual(MicrotechDatasetCatalog.objects.count(), 1)
        dataset = MicrotechDatasetCatalog.objects.get()
        self.assertEqual(dataset.name, "Adressen")
        self.assertEqual(dataset.description, "Adressen")

        fields = list(
            MicrotechDatasetField.objects
            .filter(dataset=dataset)
            .order_by("field_name")
            .values_list("field_name", flat=True)
        )
        self.assertEqual(fields, ["Nr", "SuchBeg"])
        self.assertFalse(MicrotechDatasetField.objects.filter(field_name="NestedFoo").exists())

    def test_reimport_deactivates_removed_fields(self):
        with TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            file_path = self._write_list(
                root,
                "sample.lst",
                """
DataSet: Adressen - Adressen
  Field: Nr - Nummer (UnicodeString) +
  Field: Bez - Bezeichnung (UnicodeString) +
                """,
            )
            call_command(
                "microtech_import_dataset_fields",
                "--file",
                str(file_path),
                "--dataset",
                "Adressen - Adressen",
            )

            self._write_list(
                root,
                "sample.lst",
                """
DataSet: Adressen - Adressen
  Field: Nr - Nummer (UnicodeString) +
                """,
            )
            call_command(
                "microtech_import_dataset_fields",
                "--file",
                str(file_path),
                "--dataset",
                "Adressen - Adressen",
            )

        nr_field = MicrotechDatasetField.objects.get(field_name="Nr")
        bez_field = MicrotechDatasetField.objects.get(field_name="Bez")
        self.assertTrue(nr_field.is_active)
        self.assertFalse(bez_field.is_active)


class MicrotechRuleBuilderDatasetReferenceTest(TestCase):
    def test_condition_source_and_action_target_accept_dataset_field_reference(self):
        dataset = MicrotechDatasetCatalog.objects.create(
            code="vorgang_vorgange",
            name="Vorgang",
            description="Vorgange",
            source_identifier="Vorgang - Vorgange",
            priority=10,
        )
        field = MicrotechDatasetField.objects.create(
            dataset=dataset,
            field_name="BelegNr",
            label="Belegnummer",
            field_type="UnicodeString",
            priority=10,
        )

        condition_source = MicrotechOrderRuleConditionSource.objects.create(
            code="order_number",
            name="Bestellnummer",
            engine_source_field=MicrotechOrderRuleCondition.SourceField.ORDER_NUMBER,
            value_type=MicrotechOrderRuleCondition.ValueType.STRING,
            dataset_field=field,
        )
        action_target = MicrotechOrderRuleActionTarget.objects.create(
            code="vorgangsart_id",
            name="Vorgangsart-ID",
            engine_target_field=MicrotechOrderRuleAction.TargetField.VORGANGSART_ID,
            value_type=MicrotechOrderRuleAction.ValueType.INT,
            dataset_field=field,
        )

        self.assertEqual(condition_source.dataset_field_id, field.id)
        self.assertEqual(action_target.dataset_field_id, field.id)
