from jinja2 import Environment, meta

_HTML_PATTERNS = ("_html", "description", "body", "text", "content", "intro")
_NUMBER_PATTERNS = ("price", "discount", "amount", "qty", "quantity", "count")
_URL_PATTERNS = ("url", "href", "link", "src")


def extract_variables(mjml_markup: str) -> list[str]:
    if not mjml_markup:
        return []
    env = Environment()
    ast = env.parse(mjml_markup)
    return sorted(meta.find_undeclared_variables(ast))


def infer_field_type(name: str) -> str:
    lower = name.lower()
    if any(p in lower for p in _HTML_PATTERNS):
        return "textarea"
    if any(p in lower for p in _NUMBER_PATTERNS):
        return "number"
    if any(p in lower for p in _URL_PATTERNS):
        return "url"
    return "text"
