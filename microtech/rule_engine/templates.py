from __future__ import annotations

import re

from microtech.rule_engine.context import EvaluationContext
from microtech.rule_engine.resolvers import resolve_named
from microtech.rule_engine.transforms import TRANSFORMS, apply_transform

_EXPR = re.compile(r"\{\{(.*?)\}\}")


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
