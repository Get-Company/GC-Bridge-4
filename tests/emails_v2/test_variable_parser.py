import pytest
from emails_v2.variable_parser import extract_variables, infer_field_type


def test_extract_single_variable():
    assert extract_variables("<mj-text>{{ title }}</mj-text>") == ["title"]


def test_extract_multiple_variables():
    assert extract_variables("{{ description }} {{ price }}") == ["description", "price"]


def test_extract_variable_in_if_block():
    assert extract_variables("{% if show %}{{ label }}{% endif %}") == ["label", "show"]


def test_extract_empty():
    assert extract_variables("no variables here") == []


def test_extract_empty_string():
    assert extract_variables("") == []


def test_infer_textarea():
    assert infer_field_type("description_html") == "textarea"
    assert infer_field_type("body") == "textarea"
    assert infer_field_type("intro_text") == "textarea"


def test_infer_number():
    assert infer_field_type("price") == "number"
    assert infer_field_type("discount_amount") == "number"


def test_infer_url():
    assert infer_field_type("link_url") == "url"
    assert infer_field_type("product_href") == "url"


def test_infer_text_fallback():
    assert infer_field_type("title") == "text"
    assert infer_field_type("subtitle") == "text"


@pytest.mark.django_db
def test_signal_updates_detected_variables():
    from emails.models import MjmlComponent
    comp = MjmlComponent.objects.create(
        name="Sig Test",
        mjml_markup="<mj-text>{{ headline }}</mj-text>",
    )
    comp.refresh_from_db()
    assert comp.detected_variables == ["headline"]


@pytest.mark.django_db
def test_signal_updates_on_markup_change():
    from emails.models import MjmlComponent
    comp = MjmlComponent.objects.create(name="Change Test", mjml_markup="{{ old_var }}")
    comp.mjml_markup = "{{ new_var }}"
    comp.save()
    comp.refresh_from_db()
    assert comp.detected_variables == ["new_var"]
