from __future__ import annotations

import re
import sqlite3
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError


IGNORED_STATEMENT_PREFIXES = (
    "SET ",
    "DROP DATABASE",
    "CREATE DATABASE",
    "USE ",
    "LOCK TABLES",
    "UNLOCK TABLES",
)


class Command(BaseCommand):
    help = "Converts a legacy MySQL SQL dump into a SQLite database for local inspection."

    def add_arguments(self, parser):
        parser.add_argument("dump_path", help="Pfad zur MySQL-Dump-Datei.")
        parser.add_argument(
            "sqlite_path",
            nargs="?",
            default="tmp/legacy_v3.sqlite3",
            help="Zielpfad fuer die SQLite-Datei. Default: tmp/legacy_v3.sqlite3",
        )
        parser.add_argument(
            "--overwrite",
            action="store_true",
            help="Bestehende SQLite-Datei ueberschreiben.",
        )

    def handle(self, *args, **options):
        dump_path = Path(options["dump_path"]).resolve()
        sqlite_path = Path(options["sqlite_path"]).resolve()
        overwrite = options["overwrite"]

        if not dump_path.exists():
            raise CommandError(f"Dump-Datei nicht gefunden: {dump_path}")
        if sqlite_path.exists() and not overwrite:
            raise CommandError(
                f"Zieldatei existiert bereits: {sqlite_path}. Nutze --overwrite fuer einen Neuaufbau."
            )

        sqlite_path.parent.mkdir(parents=True, exist_ok=True)
        if sqlite_path.exists():
            sqlite_path.unlink()

        raw_sql = dump_path.read_text(encoding="utf-8")
        statements = list(iter_sql_statements(raw_sql))

        connection = sqlite3.connect(sqlite_path)
        try:
            cursor = connection.cursor()
            cursor.execute("PRAGMA foreign_keys = OFF;")
            imported = 0
            skipped = 0

            for statement in statements:
                converted = convert_statement(statement)
                if not converted:
                    skipped += 1
                    continue
                try:
                    cursor.executescript(converted)
                    imported += 1
                except sqlite3.Error as exc:
                    preview = statement.strip().splitlines()[0][:160]
                    raise CommandError(f"SQLite-Importfehler bei Statement '{preview}': {exc}") from exc

            connection.commit()
        finally:
            connection.close()

        self.stdout.write(
            self.style.SUCCESS(
                f"SQLite-Datei erzeugt: {sqlite_path} (importiert={imported}, uebersprungen={skipped})"
            )
        )


def iter_sql_statements(sql_text: str):
    buffer: list[str] = []
    in_single_quote = False
    in_double_quote = False
    in_line_comment = False
    in_block_comment = False
    escaped = False
    previous = ""

    for char in sql_text:
        if in_line_comment:
            if char == "\n":
                in_line_comment = False
            previous = char
            continue

        if in_block_comment:
            if previous == "*" and char == "/":
                in_block_comment = False
                char = ""
            previous = char
            continue

        if not in_single_quote and not in_double_quote:
            if previous == "-" and char == "-" and not buffer:
                in_line_comment = True
                previous = char
                continue
            if previous == "/" and char == "*":
                if buffer and buffer[-1] == "/":
                    buffer.pop()
                in_block_comment = True
                previous = char
                continue

        buffer.append(char)

        if char == "'" and not in_double_quote and not escaped:
            in_single_quote = not in_single_quote
        elif char == '"' and not in_single_quote and not escaped:
            in_double_quote = not in_double_quote

        if char == ";" and not in_single_quote and not in_double_quote:
            statement = "".join(buffer).strip()
            if statement:
                yield statement
            buffer = []
            previous = ""
            escaped = False
            continue

        escaped = char == "\\" and not escaped
        if char != "\\":
            escaped = False
        previous = char

    statement = "".join(buffer).strip()
    if statement:
        yield statement


def convert_statement(statement: str) -> str | None:
    normalized = statement.strip()
    upper = normalized.upper()
    if upper.startswith(IGNORED_STATEMENT_PREFIXES):
        return None
    if upper.startswith("DROP TABLE IF EXISTS"):
        return normalized.replace("`", '"') + "\n"
    if upper.startswith("CREATE TABLE"):
        return convert_create_table_statement(normalized)
    if upper.startswith("INSERT INTO"):
        return convert_insert_statement(normalized)
    return None


def convert_create_table_statement(statement: str) -> str:
    lines = statement.splitlines()
    converted_lines: list[str] = []

    for index, line in enumerate(lines):
        stripped = line.strip()
        if index == 0:
            converted_lines.append(line.replace("`", '"'))
            continue

        if stripped.startswith(("KEY ", "UNIQUE KEY", "CONSTRAINT ")):
            continue

        if stripped.startswith(") ENGINE="):
            converted_lines.append(")")
            continue

        line = line.replace("`", '"')
        line = re.sub(r"/\*![0-9]+.*?\*/", "", line)
        line = re.sub(r"\bAUTO_INCREMENT\b", "", line, flags=re.IGNORECASE)
        line = re.sub(r"\bunsigned\b", "", line, flags=re.IGNORECASE)
        line = re.sub(r"\b_[a-zA-Z0-9]+\s*'", "'", line)
        line = re.sub(r"\bCHARACTER SET\s+\w+\b", "", line, flags=re.IGNORECASE)
        line = re.sub(r"\bCOLLATE\s+[^\s,]+\b", "", line, flags=re.IGNORECASE)
        line = re.sub(r"\b(varchar|char)\(\d+\)", "TEXT", line, flags=re.IGNORECASE)
        line = re.sub(r"\b(longtext|mediumtext|text)\b", "TEXT", line, flags=re.IGNORECASE)
        line = re.sub(r"\b(json)\b", "TEXT", line, flags=re.IGNORECASE)
        line = re.sub(r"\b(datetime|timestamp|date|time)\(\d+\)", "TEXT", line, flags=re.IGNORECASE)
        line = re.sub(r"\b(datetime|timestamp|date|time)\b", "TEXT", line, flags=re.IGNORECASE)
        line = re.sub(r"\b(decimal\(\d+,\d+\))\b", "NUMERIC", line, flags=re.IGNORECASE)
        line = re.sub(r"\b(double|float|real)\b", "REAL", line, flags=re.IGNORECASE)
        line = re.sub(r"\b(bigint|int|smallint|tinyint)(\(\d+\))?\b", "INTEGER", line, flags=re.IGNORECASE)
        line = re.sub(r"\b(bool|boolean)\b", "INTEGER", line, flags=re.IGNORECASE)
        line = re.sub(r"\s+", " ", line).rstrip()
        converted_lines.append(line)

    for index in range(len(converted_lines) - 1):
        if converted_lines[index].rstrip().endswith(",") and converted_lines[index + 1].strip() == ")":
            converted_lines[index] = converted_lines[index].rstrip().rstrip(",")

    return "\n".join(converted_lines) + ";\n"


def convert_insert_statement(statement: str) -> str:
    converted: list[str] = []
    in_single_quote = False
    escape_next = False

    for char in statement.replace("`", '"'):
        if not in_single_quote:
            converted.append(char)
            if char == "'":
                in_single_quote = True
            continue

        if escape_next:
            converted.append(convert_mysql_string_escape(char))
            escape_next = False
            continue

        if char == "\\":
            escape_next = True
            continue

        if char == "'":
            converted.append("'")
            in_single_quote = False
            continue

        converted.append(char)

    if escape_next:
        converted.append("\\")

    return "".join(converted) + "\n"


def convert_mysql_string_escape(char: str) -> str:
    escape_map = {
        "0": "\x00",
        "b": "\b",
        "n": "\n",
        "r": "\r",
        "t": "\t",
        "Z": "\x1a",
        "\\": "\\",
        "'": "''",
        '"': '"',
    }
    return escape_map.get(char, char)
