import json
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
from django.contrib.messages.storage.fallback import FallbackStorage
from django.http import Http404
from django.test import RequestFactory, override_settings
from django.urls import reverse

from telefon.forms import FunctionKeyForm
from telefon.function_key_views import FunctionKeyView
from telefon.function_keys import NfonFunctionKeyService


ROOT = "/api/customers/test"
EXT = ROOT + "/targets/phone-extensions/100"
KEYS = EXT + "/function-keys"
TARGET = ROOT + "/targets/phone-extensions/200"


def item(href, **fields):
    return {"href": href, "data": [{"name": name, "value": value} for name, value in fields.items()]}


class Response:
    def __init__(self, payload=None, status_code=200):
        self.payload, self.status_code = payload, status_code

    def json(self):
        return deepcopy(self.payload)

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(self.status_code)


class Client:
    def __init__(self, pages):
        self.pages = pages
        self.writes = []
        self.result = Response(status_code=204)

    def get(self, path):
        return Response(self.pages[path])

    def post(self, path, body):
        self.writes.append(("POST", path, json.loads(body)))
        return self.result

    def put(self, path, body):
        self.writes.append(("PUT", path, json.loads(body)))
        return self.result

    def delete(self, path):
        self.writes.append(("DELETE", path, None))
        return self.result


@pytest.fixture
def service():
    key = item(KEYS + "/0", keyNumber=0, type="MONITOR", displayName="Büro", targetName="Team")
    key["links"] = [{"rel": "target", "href": TARGET}]
    client = Client({KEYS: {"items": [key]}, KEYS + "/available-targets": {
        "items": [item(TARGET, displayName="Team", extensionNumber="200")]
    }})
    return NfonFunctionKeyService(client=client, customer_id="test")


def test_extensions_join_people_devices_and_public_lines_across_pages(service):
    listing = ROOT + "/targets/phone-extensions"
    service.client.pages.update({
        listing: {"items": [item(EXT, extensionNumber="100", displayName="Anna Büro", name="Anna Beispiel")],
                  "links": [{"rel": "next", "href": listing + "?_offset=1"}]},
        listing + "?_offset=1": {"items": [item(listing + "/20", extensionNumber="20", name="Empfang")]},
        ROOT + "/devices": {"items": [item("/device", extension="100", deviceType="Yealink T54W", uniqueIdentifier="123ABC", active=True),
                                       item("/unassigned", extension=None, deviceType="Yealink T46S")]},
        EXT + "/inbound-trunk-numbers": {"items": [item("/number", didNumber="+4989123100", didExtension="100")]},
        listing + "/20/inbound-trunk-numbers": {"items": []},
    })
    result = service.list_extensions()
    assert [e["number"] for e in result] == ["20", "100"]
    assert result[1]["lines"] == ["+4989123100"]
    assert result[1]["devices"] == [{"model": "Yealink T54W", "identifier": "123ABC", "active": True}]
    assert all(term in result[1]["search"] for term in ["Anna Beispiel", "Anna Büro", "100", "+4989123100", "Yealink"])


def test_key_zero_is_displayed_as_first_position_and_external_target_round_trips(service):
    external = item(KEYS + "/3", keyNumber=3, type="SPEEDDIAL", displayName="Handy")
    external["links"] = [{"rel": "target", "href": ROOT + "/targets/external/%2B49123?id=42"}]
    service.client.pages[KEYS]["items"].append(external)
    keys = service.list_keys("100")
    assert [k["position"] for k in keys] == [1, 4]
    assert keys[1]["phone_number"] == "+49123"


def test_create_speed_dial_uses_target_link_and_zero_based_key_number(service):
    service.save_key("100", {"position": 3, "type": "SPEEDDIAL", "display_name": "Mobil",
                             "phone_number": "+49 (89) 12-34", "function_code": "*3", "target": TARGET})
    method, path, payload = service.client.writes[0]
    assert (method, path) == ("POST", KEYS)
    assert payload == {"data": [{"name": "type", "value": "SPEEDDIAL"},
                                {"name": "displayName", "value": "Mobil"},
                                {"name": "keyNumber", "value": 2}],
                       "links": [{"rel": "target", "href": ROOT + "/targets/external/+49891234"}]}


def test_update_blf_preserves_position_and_omits_read_only_fields(service):
    key = service.list_keys("100")[0]
    service.save_key("100", {"position": 1, "type": "MONITOR", "display_name": "Team", "target": TARGET},
                     existing_number=0, expected=key["fingerprint"])
    assert service.client.writes == [("PUT", KEYS + "/0", {
        "data": [{"name": "type", "value": "MONITOR"}, {"name": "displayName", "value": "Team"}],
        "links": [{"rel": "target", "href": TARGET}],
    })]


def test_function_code_does_not_send_stale_target(service):
    service.save_key("100", {"position": 2, "type": "FUNCTION_CODE", "display_name": "Abholen",
                             "function_code": "*3200", "target": TARGET})
    payload = service.client.writes[0][2]
    assert payload["links"] == []
    assert {"name": "functionCode", "value": "*3200"} in payload["data"]


@pytest.mark.parametrize("action", ["update", "delete"])
def test_changed_keys_are_never_overwritten_or_deleted(service, action):
    key = service.list_keys("100")[0]
    service.client.pages[KEYS]["items"][0]["data"].append({"name": "functionCode", "value": "changed"})
    with pytest.raises(ValueError, match="inzwischen geändert"):
        if action == "delete":
            service.delete_key("100", 0, expected=key["fingerprint"])
        else:
            service.save_key("100", {"position": 1}, existing_number=0, expected=key["fingerprint"])
    assert service.client.writes == []


def test_create_never_replaces_occupied_key(service):
    with pytest.raises(ValueError, match="bereits belegt"):
        service.save_key("100", {"position": 1})
    assert service.client.writes == []


@pytest.mark.parametrize("values", [
    {"type": "SERVICE", "target": TARGET},
    {"type": "MONITOR", "target": "/api/customers/other/targets/phone-extensions/200"},
    {"type": "SPEEDDIAL", "phone_number": "https://example.com/123"},
    {"type": "FUNCTION_CODE", "function_code": "+49123"},
    {"type": "UNKNOWN"},
])
def test_invalid_targets_and_codes_never_reach_nfon(service, values):
    with pytest.raises(ValueError):
        service.save_key("100", {"position": 2, "display_name": "Test", **values})
    assert service.client.writes == []


def test_delete_uses_current_fingerprint_and_reports_api_errors(service):
    key = service.list_keys("100")[0]
    service.client.result = Response({"title": "Forbidden"}, status_code=403)
    with pytest.raises(ValueError, match="HTTP 403"):
        service.delete_key("100", 0, expected=key["fingerprint"])
    assert service.client.writes == [("DELETE", KEYS + "/0", None)]


@pytest.mark.parametrize("next_url", ["https://example.com/secret", "/api/customers/other/devices", ROOT + "/../other/devices", ROOT + "/devices"])
def test_pagination_rejects_foreign_paths_and_cycles(service, next_url):
    path = ROOT + "/devices"
    service.client.pages[path] = {"items": [], "links": [{"rel": "next", "href": next_url}]}
    with pytest.raises(ValueError):
        service._collection(path)


def test_form_requires_only_fields_for_selected_key_type():
    form = FunctionKeyForm({"position": "2", "type": "FUNCTION_CODE", "function_code": "*3", "target": "stale"})
    assert form.is_valid(), form.errors
    form = FunctionKeyForm({"position": "2", "type": "SPEEDDIAL"})
    assert not form.is_valid()
    assert "phone_number" in form.errors


def test_edit_form_ignores_tampered_position():
    form = FunctionKeyForm(
        {"position": "999", "type": "MONITOR", "target": TARGET},
        initial={"position": 1}, editing=True,
        targets=[{"href": TARGET, "label": "Team", "kind": "MONITOR"}],
    )
    assert form.is_valid(), form.errors
    assert form.cleaned_data["position"] == 1


def request(method="get", query="?extension=100", data=None):
    factory = RequestFactory()
    req = getattr(factory, method)("/admin/telefon/tastenbelegung/" + query, data=data or {})
    req.user = SimpleNamespace(is_active=True, is_staff=True)
    req.session = {}
    req._messages = FallbackStorage(req)
    return req


def view_service():
    service = Mock()
    service.list_extensions.return_value = [{"number": "100", "name": "Anna", "devices": [], "lines": []}]
    service.list_keys.return_value = []
    service.list_targets.return_value = []
    return service


def test_view_selects_person_and_keeps_invalid_input_without_writing():
    service = view_service()
    admin_site = Mock(each_context=lambda request: {})
    with patch.object(FunctionKeyView, "get_service", return_value=service):
        response = FunctionKeyView.as_view(admin_site=admin_site)(request())
        assert response.context_data["selected"]["name"] == "Anna"
        assert response.context_data["form"].initial["position"] == 1
        response = FunctionKeyView.as_view(admin_site=admin_site)(request("post", data={"action": "save", "type": "SPEEDDIAL", "position": 2}))
        assert response.status_code == 400
        assert "phone_number" in response.context_data["form"].errors
    service.save_key.assert_not_called()


def test_view_rejects_unknown_extension_and_redirects_after_save():
    service = view_service()
    with patch.object(FunctionKeyView, "get_service", return_value=service):
        with pytest.raises(Http404):
            FunctionKeyView.as_view()(request(query="?extension=999"))
        response = FunctionKeyView.as_view()(request("post", data={
            "action": "save", "position": "2", "type": "SPEEDDIAL", "phone_number": "+49123",
        }))
    assert response.status_code == 302
    assert response.url == reverse("admin:telefon_function_keys") + "?extension=100"
    service.save_key.assert_called_once()


def test_failed_delete_retains_editor_without_unrelated_required_errors(service):
    svc = view_service()
    key = service.list_keys("100")[0]
    svc.list_keys.return_value = [key]
    svc.list_targets.return_value = service.list_targets("100")
    svc.delete_key.side_effect = ValueError("NFON hat den Zugriff abgelehnt.")
    site = Mock(each_context=lambda request: {})
    with patch.object(FunctionKeyView, "get_service", return_value=svc):
        response = FunctionKeyView.as_view(admin_site=site)(request(
            "post", "?extension=100&key=0", {"action": "delete", "fingerprint": key["fingerprint"]},
        ))
    assert response.status_code == 400
    assert not response.context_data["form"].errors
    assert response.context_data["api_error"] == "NFON hat den Zugriff abgelehnt."
    svc.delete_key.assert_called_once_with("100", 0, expected=key["fingerprint"])


def test_admin_entry_point_rejects_anonymous_requests():
    from django.contrib.auth.models import AnonymousUser
    from django.urls import resolve

    req = request()
    req.user = AnonymousUser()
    response = resolve(reverse("admin:telefon_function_keys")).func(req)
    assert response.status_code == 302
    assert "/admin/login/" in response.url


def test_admin_entry_point_requires_csrf_before_writing():
    from django.urls import resolve

    req = request("post", data={"action": "save"})
    with patch.object(FunctionKeyView, "get_service") as get_service:
        response = resolve(reverse("admin:telefon_function_keys")).func(req)
    assert response.status_code == 403
    get_service.assert_not_called()


@override_settings(STORAGES={"staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"}})
def test_full_admin_template_renders_person_devices_and_key_zero(service):
    from django.contrib.auth.models import User

    svc = view_service()
    svc.list_keys.return_value = service.list_keys("100")
    svc.list_extensions.return_value[0]["devices"] = [{"model": "Yealink T54W", "identifier": "demo", "active": True}]
    svc.list_targets.return_value = service.list_targets("100")
    req = request(query="?extension=100&key=0")
    req.user = User(is_active=True, is_staff=True, is_superuser=True, username="Test")
    admin_site = Mock()
    admin_site.name = "admin"
    admin_site.each_context.return_value = {"is_nav_sidebar_enabled": False}
    with patch.object(FunctionKeyView, "get_service", return_value=svc):
        response = FunctionKeyView.as_view(admin_site=admin_site)(req)
        response.render()
    html = response.content.decode()
    assert "Yealink T54W" in html
    assert "Anna" in html
    assert "Taste 1 bearbeiten" in html
    assert "Taste 1 entfernen" in html
    assert 'name="fingerprint"' in html
