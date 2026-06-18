from django.template import Context, Template


def test_get_item_filter_returns_value():
    t = Template("{% load email_builder_tags %}{{ mydict|get_item:key }}")
    c = Context({"mydict": {"hello": "world"}, "key": "hello"})
    assert t.render(c) == "world"


def test_get_item_filter_returns_empty_list_for_missing():
    t = Template("{% load email_builder_tags %}{% for x in mydict|get_item:key %}{{ x }}{% endfor %}")
    c = Context({"mydict": {}, "key": "missing"})
    assert t.render(c) == ""
