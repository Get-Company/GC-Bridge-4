import jinja2


def build_env() -> jinja2.Environment:
    from products.models import Category, Product, Tax

    env = jinja2.Environment(
        autoescape=jinja2.select_autoescape(["html", "htm"]),
        undefined=jinja2.Undefined,
        keep_trailing_newline=True,
    )
    env.globals.update(
        {
            "Product": Product,
            "Category": Category,
            "Tax": Tax,
        }
    )
    return env
