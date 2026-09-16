from __future__ import annotations

import re
from collections.abc import Collection

from microtech.rule_engine.context import EvaluationContext
from microtech.rule_engine.resolvers import RESOLVERS, resolve_named
from microtech.rule_engine.transforms import TRANSFORMS, apply_transform

_EXPR = re.compile(r"\{\{(.*?)\}\}")


class TemplateValidationError(ValueError):
    """Raised when an editor value contains an unsafe or unknown template."""


def validate_template(template: str, *, allowed_paths: Collection[str] | None = None) -> None:
    """Validate the deliberately small rule-template language before saving.

    The renderer intentionally supports only field paths, quoted literals,
    registered transforms, and registered named resolvers.  Validation keeps
    invalid paths and misspelled helpers from becoming runtime fallbacks.
    """
    value = "" if template is None else str(template)
    if value.count("{{") != value.count("}}"):
        raise TemplateValidationError("Nicht abgeschlossener Template-Ausdruck.")

    known_paths = set(allowed_paths) if allowed_paths is not None else None
    for match in _EXPR.finditer(value):
        expression = match.group(1).strip()
        if not expression:
            raise TemplateValidationError("Leerer Template-Ausdruck.")
        have_value = False
        for part in (item.strip() for item in expression.split("|")):
            name, _, _arg = part.partition(":")
            name = name.strip()
            if have_value and name in TRANSFORMS:
                continue
            if not part:
                raise TemplateValidationError("Leeres Glied in einer Template-Kette.")
            if part.startswith("@"):
                resolver = part[1:].strip()
                if resolver not in RESOLVERS:
                    raise TemplateValidationError(f"Unbekannter Resolver: @{resolver}")
            elif len(part) >= 2 and part[0] == part[-1] and part[0] in {"'", '"'}:
                pass
            elif known_paths is not None and part not in known_paths:
                raise TemplateValidationError(f"Unbekannter Feldpfad im Template: {part}")
            have_value = True


def _resolve_atom(atom: str, context: EvaluationContext) -> str:
    atom = atom.strip()
    if not atom:
        return ""
    if atom.startswith("@"):
        return resolve_named(atom[1:].strip(), context)
    if len(atom) >= 2 and atom[0] == atom[-1] and atom[0] in {'"', "'"}:
        return atom[1:-1]
    value = context.get(atom)
    return "" if value is None else str(value)


def _eval_expression(expr: str, context: EvaluationContext) -> str:
    parts = [p.strip() for p in expr.split("|")]
    value = ""
    have_value = False
    for part in parts:
        name, _, arg = part.partition(":")
        name = name.strip()
        if have_value and name in TRANSFORMS:
            value = apply_transform(name, value, arg.strip())
            continue
        # Fallback-Glied: nimm ersten nicht-leeren Wert
        candidate = _resolve_atom(part, context)
        if candidate:
            value = candidate
            have_value = True
    return value


def render_template(template: str, context: EvaluationContext) -> str:
    template = "" if template is None else str(template)
    if "{{" not in template:
        return template
    return _EXPR.sub(lambda m: _eval_expression(m.group(1), context), template)
