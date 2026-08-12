from jinja2 import Environment, meta

from emails.mjml import find_hyphenated_placeholders, normalize_hyphenated_placeholders

_HTML_PATTERNS = ("_html", "description", "body", "text", "content", "intro")
_NUMBER_PATTERNS = ("price", "discount", "amount", "qty", "quantity", "count")
_URL_PATTERNS = ("url", "href", "link", "src")


def extract_variables(mjml_markup: str) -> list[str]:
    if not mjml_markup:
        return []
    env = Environment()
    hyphenated_variables = find_hyphenated_placeholders(mjml_markup)
    ast = env.parse(normalize_hyphenated_placeholders(mjml_markup))
    variables = meta.find_undeclared_variables(ast) - {"__component_variables"}
    return sorted(variables | hyphenated_variables)


def infer_field_type(name: str) -> str:
    lower = name.lower()
    if any(p in lower for p in _HTML_PATTERNS):
        return "textarea"
    if any(p in lower for p in _NUMBER_PATTERNS):
        return "number"
    if any(p in lower for p in _URL_PATTERNS):
        return "url"
    return "text"
