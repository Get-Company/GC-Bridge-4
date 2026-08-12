import logging
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from jinja2 import TemplateSyntaxError

from emails_v2.signals import update_detected_variables
from emails_v2.variable_parser import extract_variables, infer_field_type


def test_extract_single_variable():
    assert extract_variables("<mj-text>{{ title }}</mj-text>") == ["title"]


def test_extract_multiple_variables():
    assert extract_variables("{{ description }} {{ price }}") == ["description", "price"]


def test_extract_variable_in_if_block():
    assert extract_variables("{% if show %}{{ label }}{% endif %}") == ["label", "show"]


def test_extract_hyphenated_component_variables():
    assert extract_variables("{{ h1-title }} {{ h1-small }}") == ["h1-small", "h1-title"]


def test_extract_invalid_jinja_syntax_raises_error():
    with pytest.raises(TemplateSyntaxError):
        extract_variables("{{ product. }}")


def test_signal_ignores_invalid_jinja_syntax(caplog):
    component = SimpleNamespace(
        pk=42,
        mjml_markup="{{ product. }}",
        detected_variables=[],
    )

    with caplog.at_level(logging.WARNING):
        update_detected_variables(sender=None, instance=component)

    assert "Detected variables were not updated for MJML component 42" in caplog.text


def test_signal_clears_detected_variables_for_shopware_components():
    component = SimpleNamespace(
        pk=42,
        rendering_mode="shopware",
        mjml_markup="{{ product. }}",
        detected_variables=["old_variable"],
    )
    queryset = Mock()
    sender = SimpleNamespace(objects=SimpleNamespace(filter=Mock(return_value=queryset)))

    update_detected_variables(sender=sender, instance=component)

    sender.objects.filter.assert_called_once_with(pk=42)
    queryset.update.assert_called_once_with(detected_variables=[])


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
