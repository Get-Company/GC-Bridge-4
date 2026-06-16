from __future__ import annotations

import json
from datetime import date

from telefon.forms import ZeitsteuerungDateForm
from telefon.services import NfonTimeControlService


class FakeResponse:
    def __init__(self, payload=None, status_code=200, text=""):
        self.payload = payload
        self.status_code = status_code
        self.text = text

    def json(self):
        return self.payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(self.text or self.status_code)


class FakeNfonClient:
    def __init__(self, payload):
        self.payload = payload
        self.put_calls = []

    def get(self, path):
        return FakeResponse(self.payload)

    def put(self, path, body):
        self.put_calls.append((path, json.loads(body.decode("utf-8"))))
        self.payload = self.put_calls[-1][1]
        return FakeResponse(self.payload)


def test_list_time_controls_normalizes_list_payload():
    client = FakeNfonClient(
        [
            {
                "href": "/api/customers/customer/targets/time-control-services/42",
                "data": [{"name": "displayName", "value": "Ferien"}],
            }
        ]
    )
    service = NfonTimeControlService(client=client, customer_id="customer")

    assert service.list_time_controls() == [{"id": "42", "name": "Ferien"}]


def test_add_denied_date_filters_writable_payload_and_sorts_dates():
    client = FakeNfonClient(
        {
            "href": "/readonly",
            "links": [
                {"rel": "destinationIfDenied", "href": "/allowed"},
                {"rel": "readonly", "href": "/blocked"},
            ],
            "data": [
                {"name": "displayName", "value": "Feiertag"},
                {"name": "readonly", "value": "blocked"},
                {"name": "referralDenied", "value": ["Mar 01, 2026"]},
            ],
        }
    )
    service = NfonTimeControlService(client=client, customer_id="customer")

    result = service.add_denied_date("42", date(2026, 2, 3))

    assert result["status_code"] == 200
    assert client.put_calls[0][0] == "/api/customers/customer/targets/time-control-services/42"
    payload = client.put_calls[0][1]
    assert "href" not in payload
    assert payload["links"] == [{"rel": "destinationIfDenied", "href": "/allowed"}]
    assert payload["data"] == [
        {"name": "displayName", "value": "Feiertag"},
        {"name": "referralDenied", "value": ["Feb 03, 2026", "Mar 01, 2026"]},
    ]


def test_date_form_uses_native_calendar_input():
    form = ZeitsteuerungDateForm()

    assert form.fields["date"].widget.input_type == "date"
    assert 'type="date"' in form.as_p()


def test_date_form_value_is_formatted_for_nfon_payload():
    client = FakeNfonClient({"data": [{"name": "referralDenied", "value": []}]})
    form = ZeitsteuerungDateForm({"date": "2026-02-03"})

    assert form.is_valid(), form.errors

    service = NfonTimeControlService(client=client, customer_id="customer")
    service.add_denied_date("42", form.cleaned_data["date"])

    payload = client.put_calls[0][1]
    assert payload["data"] == [{"name": "referralDenied", "value": ["Feb 03, 2026"]}]


def test_date_form_accepts_german_date_for_debug_fallback():
    form = ZeitsteuerungDateForm({"date": "03.02.2026"})

    assert form.is_valid(), form.errors
    assert form.cleaned_data["date"] == date(2026, 2, 3)


def test_add_denied_date_raises_when_nfon_does_not_persist_date():
    class NonPersistingClient(FakeNfonClient):
        def put(self, path, body):
            self.put_calls.append((path, json.loads(body.decode("utf-8"))))
            return FakeResponse(self.put_calls[-1][1])

    client = NonPersistingClient({"data": [{"name": "referralDenied", "value": []}]})
    service = NfonTimeControlService(client=client, customer_id="customer")

    try:
        service.add_denied_date("42", date(2026, 2, 3))
    except ValueError as error:
        message = str(error)
        assert "nicht uebernommen" in message
        assert "2026-02-03" in message
        assert "Feb 03, 2026" in message
    else:
        raise AssertionError("Expected ValueError")


def test_delete_denied_date_raises_when_date_is_missing():
    client = FakeNfonClient({"data": [{"name": "referralDenied", "value": ["Mar 01, 2026"]}]})
    service = NfonTimeControlService(client=client, customer_id="customer")

    try:
        service.delete_denied_date("42", "Apr 01, 2026")
    except ValueError as error:
        assert "Datum nicht gefunden" in str(error)
    else:
        raise AssertionError("Expected ValueError")

    assert client.put_calls == []
