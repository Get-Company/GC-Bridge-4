from __future__ import annotations

import json
import re
from html import escape
from io import BytesIO
from zipfile import BadZipFile, ZipFile
from xml.etree import ElementTree

from bs4 import BeautifulSoup
from django.db import transaction
from django.utils import timezone

from ai.models import AIDocumentPrompt, DEFAULT_DOCUMENT_IMPORT_SYSTEM_PROMPT
from ai.services.provider import AIProviderService
from core.services import BaseService
from documents.document_version_service import DocumentVersionService
from documents.models import Document, DocumentImportJob, DocumentPlaceholderValue


class DocumentWordImportService(BaseService):
    """Convert DOCX structure into safe HTML without allowing the AI to alter legal text."""

    model = DocumentImportJob
    word_namespace = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    supported_document_types = {
        Document.DocumentType.TERMS,
        Document.DocumentType.PRIVACY,
        Document.DocumentType.WITHDRAWAL,
    }
    allowed_roles = {"h2", "h3", "p", "ol_item", "ul_item", "table"}
    placeholder_pattern = re.compile(r"<[^<>\r\n]{2,500}>")

    @classmethod
    def _word_tag(cls, name: str) -> str:
        return f"{{{cls.word_namespace}}}{name}"

    @classmethod
    def _paragraph_text(cls, paragraph) -> str:
        parts = []
        for node in paragraph.iter():
            if node.tag == cls._word_tag("t"):
                parts.append(node.text or "")
            elif node.tag == cls._word_tag("tab"):
                parts.append("\t")
            elif node.tag in {cls._word_tag("br"), cls._word_tag("cr")}:
                parts.append("\n")
        return "".join(parts).strip()

    @classmethod
    def _paragraph_metadata(cls, paragraph) -> tuple[str, int | None]:
        properties = paragraph.find(cls._word_tag("pPr"))
        if properties is None:
            return "", None
        style_node = properties.find(cls._word_tag("pStyle"))
        style = style_node.get(cls._word_tag("val"), "") if style_node is not None else ""
        number_properties = properties.find(cls._word_tag("numPr"))
        if number_properties is None:
            return style, None
        level_node = number_properties.find(cls._word_tag("ilvl"))
        try:
            level = int(level_node.get(cls._word_tag("val"), "0")) if level_node is not None else 0
        except ValueError:
            level = 0
        return style, level

    @classmethod
    def _extract_blocks_from_xml(cls, xml_content: bytes) -> list[dict]:
        root = ElementTree.fromstring(xml_content)
        body = root.find(cls._word_tag("body"))
        if body is None:
            return []

        blocks = []
        for child in body:
            if child.tag == cls._word_tag("p"):
                text = cls._paragraph_text(child)
                if not text:
                    continue
                style, list_level = cls._paragraph_metadata(child)
                blocks.append(
                    {
                        "kind": "paragraph",
                        "text": text,
                        "style": style,
                        "list_level": list_level,
                    }
                )
                continue
            if child.tag != cls._word_tag("tbl"):
                continue
            rows = []
            for row in child.findall(cls._word_tag("tr")):
                cells = []
                for cell in row.findall(cls._word_tag("tc")):
                    cell_parts = [
                        cls._paragraph_text(paragraph)
                        for paragraph in cell.findall(cls._word_tag("p"))
                    ]
                    cells.append("\n".join(part for part in cell_parts if part))
                if any(cells):
                    rows.append(cells)
            if rows:
                blocks.append({"kind": "table", "rows": rows, "text": " ".join(sum(rows, []))})

        for index, block in enumerate(blocks, start=1):
            block["id"] = f"b{index:04d}"
        return blocks

    def extract_docx_blocks(self, document: Document) -> list[dict]:
        if not document.source_docx:
            raise ValueError("Bitte zuerst eine Word-Datei am Dokument hinterlegen und speichern.")
        if not document.source_docx.name.lower().endswith(".docx"):
            raise ValueError("Der KI-Import unterstützt bewusst nur DOCX-Dateien, keine RTF-Dateien.")
        document.source_docx.open("rb")
        try:
            content = document.source_docx.read()
        finally:
            document.source_docx.close()
        try:
            with ZipFile(BytesIO(content)) as archive:
                xml_content = archive.read("word/document.xml")
        except (BadZipFile, KeyError) as exc:
            raise ValueError("Die hochgeladene Datei ist keine gültige DOCX-Datei.") from exc
        blocks = self._extract_blocks_from_xml(xml_content)
        if not blocks:
            raise ValueError("Die Word-Datei enthält keinen importierbaren Text.")
        return blocks

    def extract_placeholders(self, document: Document) -> list[str]:
        blocks = self.extract_docx_blocks(document)
        return list(
            dict.fromkeys(
                placeholder
                for block in blocks
                for placeholder in self.placeholder_pattern.findall(block["text"])
            )
        )

    @transaction.atomic
    def save_placeholder_values(
        self,
        *,
        document: Document,
        source_placeholders: list[str],
        values: dict[str, str],
    ) -> None:
        active_values = self._validate_managed_placeholder_values(
            source_blocks=[{"id": "source", "text": "\n".join(source_placeholders)}],
            placeholder_values=values,
        )
        document.placeholder_values.filter(
            placeholder__in=source_placeholders,
        ).exclude(
            placeholder__in=active_values,
        ).update(is_active=False)
        for placeholder, value in active_values.items():
            DocumentPlaceholderValue.objects.update_or_create(
                document=document,
                placeholder=placeholder,
                defaults={"value": value, "is_active": True},
            )

    @transaction.atomic
    def create_job(
        self,
        *,
        document: Document,
        prompt: AIDocumentPrompt | None,
        provider,
        placeholder_values: dict[str, str] | None = None,
        requested_by=None,
    ) -> DocumentImportJob:
        if document.document_type not in self.supported_document_types:
            raise ValueError(
                "Der Word-Import ist nur für AGB, Datenschutzerklärungen "
                "und Widerrufsbelehrungen vorgesehen."
            )
        if not provider.is_active:
            raise ValueError("Der ausgewählte KI-Provider ist nicht aktiv.")
        prompt = prompt or document.ai_document_prompt or AIDocumentPrompt.get_default()
        if not prompt:
            raise ValueError("Bitte zuerst einen aktiven KI-Dokument-Prompt anlegen oder als Standard markieren.")
        if not prompt.is_active:
            raise ValueError("Der ausgewählte KI-Dokument-Prompt ist nicht aktiv.")
        blocks = self.extract_docx_blocks(document)
        if placeholder_values is None:
            placeholder_values = dict(
                document.placeholder_values.filter(is_active=True).values_list("placeholder", "value")
            )
        placeholder_values = self._validate_managed_placeholder_values(blocks, placeholder_values)
        return self.model.objects.create(
            document=document,
            prompt=prompt,
            provider=provider,
            source_blocks=blocks,
            source_text="\n\n".join(block["text"] for block in blocks),
            system_prompt_snapshot=prompt.system_prompt,
            placeholder_values_snapshot=placeholder_values,
            requested_by=requested_by,
            status=DocumentImportJob.Status.QUEUED,
        )

    @staticmethod
    def _parse_provider_json(content: str) -> dict:
        cleaned = content.strip()
        if cleaned.startswith("```"):
            cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
            cleaned = re.sub(r"\s*```$", "", cleaned)
        try:
            payload = json.loads(cleaned)
        except json.JSONDecodeError as exc:
            raise ValueError("Die KI hat kein gültiges JSON zurückgegeben.") from exc
        if not isinstance(payload, dict):
            raise ValueError("Die KI-Rückgabe muss ein JSON-Objekt sein.")
        return payload

    def _validate_roles(self, source_blocks: list[dict], payload: dict) -> list[dict]:
        assignments = payload.get("blocks")
        if not isinstance(assignments, list):
            raise ValueError("In der KI-Rückgabe fehlt die Liste 'blocks'.")
        source_ids = [block["id"] for block in source_blocks]
        result_ids = [item.get("id") for item in assignments if isinstance(item, dict)]
        if result_ids != source_ids:
            raise ValueError("Die KI-Rückgabe enthält nicht exakt alle Word-Blöcke in ihrer Originalreihenfolge.")

        roles = []
        blocks_by_id = {block["id"]: block for block in source_blocks}
        for assignment in assignments:
            role = assignment.get("role")
            block = blocks_by_id[assignment["id"]]
            if role not in self.allowed_roles:
                raise ValueError(f"Unzulässige Dokumentrolle: {role}")
            if block["kind"] == "table" and role != "table":
                raise ValueError("Word-Tabellen müssen als Tabellen erhalten bleiben.")
            if block["kind"] != "table" and role == "table":
                raise ValueError("Textblöcke dürfen nicht in Tabellen umgewandelt werden.")
            roles.append({**block, "role": role})
        return roles

    @classmethod
    def _reference_text(cls, document: Document) -> str:
        source = document.get_template_source()
        if not source:
            return ""
        return BeautifulSoup(source, "html.parser").get_text("\n", strip=True)

    def _validate_replacements(
        self,
        source_blocks: list[dict],
        payload: dict,
        reference_text: str,
    ) -> list[dict]:
        replacements = payload.get("replacements", [])
        if not isinstance(replacements, list):
            raise ValueError("Die KI-Rückgabe enthält keine gültige Liste 'replacements'.")

        blocks_by_id = {block["id"]: block for block in source_blocks}
        normalized_reference = self._normalized_text(reference_text)
        validated = []
        seen = set()
        for replacement in replacements:
            if not isinstance(replacement, dict):
                raise ValueError("Ein KI-Platzhalterersatz ist ungültig.")
            block_id = replacement.get("id")
            placeholder = replacement.get("placeholder")
            value = replacement.get("value")
            evidence = replacement.get("evidence")
            if block_id not in blocks_by_id:
                raise ValueError("Ein KI-Platzhalterersatz verweist auf einen unbekannten Word-Block.")
            if not isinstance(placeholder, str) or not self.placeholder_pattern.fullmatch(placeholder):
                raise ValueError("Die KI darf ausschließlich Platzhalter im Format <...> ersetzen.")
            if placeholder not in blocks_by_id[block_id]["text"]:
                raise ValueError("Die KI wollte einen nicht vorhandenen Platzhalter ersetzen.")
            if not isinstance(value, str) or not value.strip() or "<" in value or ">" in value:
                raise ValueError("Die KI hat einen ungültigen Platzhalterwert geliefert.")
            if not isinstance(evidence, str) or not evidence.strip():
                raise ValueError("Für einen KI-Platzhalterersatz fehlt der Beleg aus der bisherigen Fassung.")

            normalized_value = self._normalized_text(value)
            normalized_evidence = self._normalized_text(evidence)
            if normalized_value not in normalized_reference:
                raise ValueError(
                    f"Der vorgeschlagene Wert für {placeholder} kommt nicht wortgleich in der bisherigen Fassung vor."
                )
            if normalized_evidence not in normalized_reference or normalized_value not in normalized_evidence:
                raise ValueError(
                    f"Der Beleg für {placeholder} lässt sich nicht in der bisherigen Fassung nachweisen."
                )
            key = (block_id, placeholder)
            if key in seen:
                raise ValueError("Die KI hat denselben Platzhalter mehrfach ersetzt.")
            seen.add(key)
            validated.append(
                {
                    "id": block_id,
                    "placeholder": placeholder,
                    "value": value.strip(),
                    "evidence": evidence.strip(),
                    "source": "ai_reference",
                }
            )
        return validated

    def _validate_managed_placeholder_values(
        self,
        source_blocks: list[dict],
        placeholder_values: dict[str, str],
    ) -> dict[str, str]:
        if not isinstance(placeholder_values, dict):
            raise ValueError("Die gepflegten Platzhalterwerte sind ungültig.")
        source_text = "\n".join(block["text"] for block in source_blocks)
        validated = {}
        for placeholder, value in placeholder_values.items():
            if not isinstance(placeholder, str) or not self.placeholder_pattern.fullmatch(placeholder):
                raise ValueError("Ein gepflegter Platzhalter hat nicht das Format <Bezeichnung>.")
            if placeholder not in source_text:
                raise ValueError(f"Der gepflegte Platzhalter {placeholder} kommt in der Word-Datei nicht vor.")
            if not isinstance(value, str) or not value.strip():
                continue
            if "<" in value or ">" in value:
                raise ValueError(f"Der Wert für {placeholder} darf keine spitzen Klammern enthalten.")
            validated[placeholder] = value.strip()
        return validated

    @staticmethod
    def _managed_replacements(
        source_blocks: list[dict],
        placeholder_values: dict[str, str],
    ) -> list[dict]:
        return [
            {
                "id": block["id"],
                "placeholder": placeholder,
                "value": value,
                "evidence": "Am Dokument gepflegter Platzhalterwert",
                "source": "managed",
            }
            for block in source_blocks
            for placeholder, value in placeholder_values.items()
            if placeholder in block["text"]
        ]

    @staticmethod
    def _replace_in_rows(rows: list[list[str]], placeholder: str, value: str) -> list[list[str]]:
        return [
            [cell.replace(placeholder, value) for cell in row]
            for row in rows
        ]

    def _apply_replacements(
        self,
        classified_blocks: list[dict],
        replacements: list[dict],
    ) -> list[dict]:
        replacements_by_id: dict[str, list[dict]] = {}
        for replacement in replacements:
            replacements_by_id.setdefault(replacement["id"], []).append(replacement)

        resolved_blocks = []
        for block in classified_blocks:
            resolved = dict(block)
            resolved_text = block["text"]
            resolved_rows = [list(row) for row in block.get("rows", [])]
            block_replacements = replacements_by_id.get(block["id"], [])
            for replacement in block_replacements:
                placeholder = replacement["placeholder"]
                value = replacement["value"]
                resolved_text = resolved_text.replace(placeholder, value)
                if resolved_rows:
                    resolved_rows = self._replace_in_rows(resolved_rows, placeholder, value)
            if resolved_text != block["text"]:
                resolved["resolved_text"] = resolved_text
                resolved["replacements"] = block_replacements
            if resolved_rows and resolved_rows != block.get("rows", []):
                resolved["resolved_rows"] = resolved_rows
            resolved_blocks.append(resolved)
        return resolved_blocks

    @staticmethod
    def _effective_block_text(block: dict) -> str:
        return block.get("resolved_text", block["text"])

    @staticmethod
    def _render_table(rows: list[list[str]]) -> str:
        rendered_rows = []
        for row in rows:
            rendered_cells = "".join(f"<td>{escape(cell).replace(chr(10), '<br>')}</td>" for cell in row)
            rendered_rows.append(f"<tr>{rendered_cells}</tr>")
        return f"<table><tbody>{''.join(rendered_rows)}</tbody></table>"

    def render_html(self, classified_blocks: list[dict]) -> str:
        html = ['<div class="legal-document">']
        open_list = ""

        def close_list() -> None:
            nonlocal open_list
            if open_list:
                html.append(f"</{open_list}>")
                open_list = ""

        for block in classified_blocks:
            role = block["role"]
            if role in {"ol_item", "ul_item"}:
                list_tag = "ol" if role == "ol_item" else "ul"
                if open_list != list_tag:
                    close_list()
                    html.append(f"<{list_tag}>")
                    open_list = list_tag
                text = self._effective_block_text(block)
                html.append(f"<li>{escape(text).replace(chr(10), '<br>')}</li>")
                continue
            close_list()
            if role == "table":
                html.append(self._render_table(block.get("resolved_rows", block["rows"])))
            else:
                text = self._effective_block_text(block)
                html.append(f"<{role}>{escape(text).replace(chr(10), '<br>')}</{role}>")
        close_list()
        html.append("</div>")
        return "\n".join(html)

    @staticmethod
    def _normalized_text(value: str) -> str:
        return " ".join(value.split())

    def validate_result_html(
        self,
        job: DocumentImportJob,
        *,
        require_source_match: bool = True,
    ) -> None:
        """Validate safe HTML and, for AI output, enforce verbatim source text.

        The AI result must match the extracted Word text exactly. During the
        subsequent human review, authorized users may correct extraction or
        formatting mistakes before approval; those reviewed edits still pass
        the structural and placeholder safety checks below.
        """
        soup = BeautifulSoup(job.result_html, "html.parser")
        allowed_tags = {
            "div",
            "h2",
            "h3",
            "p",
            "ol",
            "ul",
            "li",
            "table",
            "tbody",
            "tr",
            "td",
            "br",
            "strong",
            "em",
        }
        invalid_tags = sorted({tag.name for tag in soup.find_all(True) if tag.name not in allowed_tags})
        if invalid_tags:
            raise ValueError(
                "Das Importergebnis enthält nicht erlaubte HTML-Elemente: "
                + ", ".join(invalid_tags)
            )
        tags_with_invalid_attributes = [
            tag
            for tag in soup.find_all(True)
            if tag.attrs
            and not (tag.name == "div" and tag.attrs == {"class": ["legal-document"]})
        ]
        if tags_with_invalid_attributes:
            raise ValueError("Das Importergebnis darf keine HTML-Attribute enthalten.")
        if not require_source_match:
            return
        rendered_text = self._normalized_text(soup.get_text(" ", strip=True))
        if job.source_blocks:
            source_text = self._normalized_text(
                "\n\n".join(self._effective_block_text(block) for block in job.source_blocks)
            )
        else:
            source_text = self._normalized_text(job.source_text)
        if rendered_text != source_text:
            raise ValueError("Der Text des Importergebnisses weicht von der Word-Datei ab.")

    def unresolved_placeholders(self, job: DocumentImportJob) -> list[str]:
        if job.result_html:
            source = BeautifulSoup(job.result_html, "html.parser").get_text("\n", strip=True)
        else:
            source = "\n".join(
                self._effective_block_text(block)
                for block in job.source_blocks
            ) if job.source_blocks else job.source_text
        return list(dict.fromkeys(self.placeholder_pattern.findall(source)))

    def validate_for_apply(self, job: DocumentImportJob) -> None:
        # Approval is the explicit human review boundary. Keep all HTML and
        # placeholder protections, while allowing reviewed corrections to text
        # that was malformed during Word extraction.
        self.validate_result_html(job, require_source_match=False)
        unresolved = self.unresolved_placeholders(job)
        if unresolved:
            raise ValueError(
                "Das Importergebnis enthält noch offene Platzhalter: " + ", ".join(unresolved)
            )

    def execute(self, job: DocumentImportJob) -> DocumentImportJob:
        reference_text = self._reference_text(job.document)
        prompt_payload = {
            "document": job.document.title,
            "blocks": job.source_blocks,
            "existing_document_reference": reference_text,
        }
        job.rendered_prompt = json.dumps(prompt_payload, ensure_ascii=False, indent=2)
        try:
            result_text, provider_response = AIProviderService().rewrite_text_with_response(
                provider=job.provider,
                system_prompt=job.system_prompt_snapshot or DEFAULT_DOCUMENT_IMPORT_SYSTEM_PROMPT,
                user_prompt=job.rendered_prompt,
                # Reasoning models only accept their default temperature. The
                # deterministic safety boundary is enforced by the validators below.
                temperature=1,
                response_format={"type": "json_object"},
            )
            job.provider_response = provider_response
            payload = self._parse_provider_json(result_text)
            classified_blocks = self._validate_roles(job.source_blocks, payload)
            managed_values = self._validate_managed_placeholder_values(
                job.source_blocks,
                job.placeholder_values_snapshot,
            )
            managed_replacements = self._managed_replacements(job.source_blocks, managed_values)
            managed_keys = {
                (replacement["id"], replacement["placeholder"])
                for replacement in managed_replacements
            }
            payload_replacements = payload.get("replacements", [])
            if not isinstance(payload_replacements, list):
                raise ValueError("Die KI-Rückgabe enthält keine gültige Liste 'replacements'.")
            ai_payload = {
                **payload,
                "replacements": [
                    replacement
                    for replacement in payload_replacements
                    if not (
                        isinstance(replacement, dict)
                        and (replacement.get("id"), replacement.get("placeholder")) in managed_keys
                    )
                ],
            }
            ai_replacements = self._validate_replacements(job.source_blocks, ai_payload, reference_text)
            replacements = [*managed_replacements, *ai_replacements]
            resolved_blocks = self._apply_replacements(classified_blocks, replacements)
            job.source_blocks = resolved_blocks
            job.result_html = self.render_html(resolved_blocks)
            self.validate_result_html(job)
            job.status = DocumentImportJob.Status.READY
            job.error_message = ""
        except Exception as exc:  # noqa: BLE001 - the complete failure belongs to the auditable job.
            job.status = DocumentImportJob.Status.FAILED
            job.error_message = str(exc)
        job.save(
            update_fields=(
                "rendered_prompt",
                "source_blocks",
                "result_html",
                "provider_response",
                "status",
                "error_message",
                "updated_at",
            )
        )
        return job

    @transaction.atomic
    def apply(self, job: DocumentImportJob) -> DocumentImportJob:
        if job.status != DocumentImportJob.Status.READY:
            raise ValueError("Der Word-Import hat noch kein freigabefähiges Ergebnis.")
        self.validate_for_apply(job)
        document = job.document
        document.template_file = ""
        document.html_content = job.result_html
        document.use_jinja2 = True
        document.save(update_fields=("template_file", "html_content", "use_jinja2", "updated_at"))
        version_service = DocumentVersionService()
        version = version_service.create_from_document(document, label=f"Word-Import #{job.pk}")
        version_service.activate(version)
        job.status = DocumentImportJob.Status.APPLIED
        job.applied_at = timezone.now()
        job.save(update_fields=("status", "applied_at", "updated_at"))
        return job
