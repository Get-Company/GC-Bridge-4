from django import template
from django.utils.html import escape
from django.utils.safestring import mark_safe

register = template.Library()


@register.filter
def log_highlight(value: str) -> str:
    """
    Convert a highlighted log line (with \x00match\x00 markers) to safe HTML.
    Parts between \x00 markers are wrapped in <mark>; everything else is HTML-escaped.
    """
    if not value:
        return ""

    parts = value.split("\x00")
    html_parts = []
    for i, part in enumerate(parts):
        escaped = escape(part)
        if i % 2 == 1:
            html_parts.append(f'<mark class="bg-yellow-300 dark:bg-yellow-700 dark:text-white rounded px-0.5">{escaped}</mark>')
        else:
            html_parts.append(escaped)

    return mark_safe("".join(html_parts))
