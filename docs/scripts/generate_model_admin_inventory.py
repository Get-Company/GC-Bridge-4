from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "GC_Bridge_4.settings")

import django  # noqa: E402


def _rst_escape(value: object) -> str:
    text = str(value)
    text = text.replace("\\", "\\\\")
    text = text.replace("*", "\\*")
    text = text.replace("`", "\\`")
    text = text.replace("|", "\\|")
    text = " ".join(text.splitlines())
    return text.strip() or "-"


def _iterable_to_rst(value: object) -> str:
    if value in (None, (), [], {}, ""):
        return "-"
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, str):
        return _rst_escape(value)

    rendered: list[str] = []
    for item in value:
        if callable(item):
            rendered.append(getattr(item, "__name__", repr(item)))
        else:
            rendered.append(str(item))
    return ", ".join(_rst_escape(item) for item in rendered) if rendered else "-"


def _default_to_rst(field) -> str:
    if not hasattr(field, "default"):
        return "-"
    default = field.default
    if default is django.db.models.NOT_PROVIDED:
        return "-"
    if callable(default):
        return f"callable:{getattr(default, '__name__', default.__class__.__name__)}"
    return _rst_escape(default)


def _field_details(field) -> tuple[str, str, str]:
    field_type = field.__class__.__name__

    options: list[str] = []
    if getattr(field, "primary_key", False):
        options.append("pk")
    if getattr(field, "unique", False):
        options.append("unique")
    if getattr(field, "db_index", False):
        options.append("db_index")
    if getattr(field, "null", False):
        options.append("null")
    if getattr(field, "blank", False):
        options.append("blank")

    default_repr = _default_to_rst(field)
    if default_repr != "-":
        options.append(f"default={default_repr}")

    relation = getattr(field, "remote_field", None)
    details_parts: list[str] = []
    if relation is not None and getattr(relation, "model", None) is not None:
        model = relation.model
        model_label = getattr(model, "_meta", None)
        if model_label is not None:
            details_parts.append(f"relation={model._meta.label}")
        else:
            details_parts.append(f"relation={model}")

    choices = getattr(field, "choices", None)
    if choices:
        details_parts.append(f"choices={len(list(choices))}")

    help_text = getattr(field, "help_text", "")
    if help_text:
        details_parts.append(f"help={_rst_escape(help_text)}")

    verbose_name = getattr(field, "verbose_name", "")
    if verbose_name and str(verbose_name) != field.name:
        details_parts.append(f"verbose={_rst_escape(verbose_name)}")

    if getattr(field, "max_length", None):
        details_parts.append(f"max_length={field.max_length}")

    if getattr(field, "decimal_places", None) is not None and getattr(field, "max_digits", None) is not None:
        details_parts.append(f"decimal={field.max_digits}/{field.decimal_places}")

    options_rst = ", ".join(options) if options else "-"
    details_rst = ", ".join(details_parts) if details_parts else "-"
    return field_type, options_rst, details_rst


def _model_fields(model) -> list[tuple[str, str, str, str]]:
    rows: list[tuple[str, str, str, str]] = []
    for field in model._meta.get_fields():
        if field.auto_created and not field.concrete:
            continue
        if not hasattr(field, "name"):
            continue

        field_type, options_rst, details_rst = _field_details(field)
        rows.append((field.name, field_type, options_rst, details_rst))
    return rows


def _admin_rows(model) -> list[tuple[str, str]]:
    from django.contrib import admin

    model_admin = admin.site._registry.get(model)
    if model_admin is None:
        return [("Registrierung", "Kein ModelAdmin registriert")]

    cls = model_admin.__class__
    rows: list[tuple[str, str]] = [
        ("Admin-Klasse", f"{cls.__module__}.{cls.__name__}"),
        ("list_display", _iterable_to_rst(getattr(model_admin, "list_display", ()))),
        ("list_filter", _iterable_to_rst(getattr(model_admin, "list_filter", ()))),
        ("search_fields", _iterable_to_rst(getattr(model_admin, "search_fields", ()))),
        ("readonly_fields", _iterable_to_rst(getattr(model_admin, "readonly_fields", ()))),
        ("ordering", _iterable_to_rst(getattr(model_admin, "ordering", ()))),
        ("list_select_related", _iterable_to_rst(getattr(model_admin, "list_select_related", ()))),
    ]

    if getattr(model_admin, "list_per_page", None):
        rows.append(("list_per_page", str(model_admin.list_per_page)))

    inlines = getattr(model_admin, "inlines", ()) or ()
    inline_names = [f"{inline.__module__}.{inline.__name__}" for inline in inlines]
    rows.append(("inlines", _iterable_to_rst(inline_names)))

    actions = getattr(model_admin, "actions", ())
    rows.append(("actions", _iterable_to_rst(actions)))

    action_form = getattr(model_admin, "action_form", None)
    if action_form is not None:
        rows.append(("action_form", f"{action_form.__module__}.{action_form.__name__}"))

    return rows


def _write_list_table(lines: list[str], headers: tuple[str, ...], rows: list[tuple[str, ...]]) -> None:
    lines.extend(
        [
            ".. list-table::",
            "   :header-rows: 1",
            "",
            "   * - " + "\n     - ".join(_rst_escape(header) for header in headers),
        ]
    )

    for row in rows:
        lines.append("   * - " + "\n     - ".join(_rst_escape(col) for col in row))

    lines.append("")


def generate(output_path: Path) -> None:
    django.setup()

    local_apps = {"core", "customer", "orders", "products", "shopware", "microtech"}
    from django.apps import apps

    lines: list[str] = []
    title = "Model- und Admin-Inventar"
    lines.append(title)
    lines.append("=" * len(title))
    lines.append("")
    lines.append(
        "Diese Seite wird automatisch aus dem Django-Projekt erzeugt und deckt alle lokalen Apps, Models und registrierten Admin-Klassen ab."
    )
    lines.append("")
    lines.append(
        f"Generiert am: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} UTC"
    )
    lines.append("")

    app_configs = sorted(
        [cfg for cfg in apps.get_app_configs() if cfg.label in local_apps],
        key=lambda cfg: cfg.label,
    )

    for app_config in app_configs:
        lines.append(app_config.label)
        lines.append("-" * len(app_config.label))
        lines.append("")

        models = sorted(app_config.get_models(), key=lambda model: model.__name__)
        if not models:
            lines.append("Keine lokalen Models in dieser App.")
            lines.append("")
            continue

        for model in models:
            model_label = model._meta.label
            lines.append(model_label)
            lines.append("~" * len(model_label))
            lines.append("")
            lines.append(f"* Python: ``{model.__module__}.{model.__name__}``")
            lines.append(f"* DB-Tabelle: ``{model._meta.db_table}``")
            lines.append(f"* Verbose Name: ``{_rst_escape(model._meta.verbose_name)}``")
            lines.append(f"* Verbose Name Plural: ``{_rst_escape(model._meta.verbose_name_plural)}``")
            ordering = _iterable_to_rst(getattr(model._meta, "ordering", ()))
            lines.append(f"* Default Ordering: ``{ordering}``")
            lines.append("")
            lines.append("Felder")
            lines.append("^^^^^^")
            lines.append("")

            field_rows = _model_fields(model)
            _write_list_table(
                lines,
                headers=("Feld", "Typ", "Optionen", "Details"),
                rows=field_rows,
            )

            lines.append("Admin-Konfiguration")
            lines.append("^^^^^^^^^^^^^^^^^^^")
            lines.append("")
            admin_rows = _admin_rows(model)
            _write_list_table(
                lines,
                headers=("Aspekt", "Wert"),
                rows=admin_rows,
            )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate Sphinx inventory for models and admins.")
    parser.add_argument(
        "--output",
        default=str(PROJECT_ROOT / "docs" / "source" / "reference" / "models_und_admins_generated.rst"),
        help="Path to output RST file.",
    )
    args = parser.parse_args()

    output_path = Path(args.output).resolve()
    generate(output_path)
    print(f"Wrote {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
