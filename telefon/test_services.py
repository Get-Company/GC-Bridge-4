from __future__ import annotations

import json
from datetime import date

from telefon.forms import ZeitsteuerungDateForm
from telefon.services import NfonTimeControlService


class FakeResponse:
    def __init__(self, payload=None, status_code=200, text="", headers=None):
        self.payload = payload
        self.status_code = status_code
        self.text = text
        self.headers = headers or {}

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


class PaginatedFakeNfonClient:
    def __init__(self, pages):
        self.pages = pages
        self.get_calls = []

    def get(self, path):
        self.get_calls.append(path)
        return FakeResponse(self.pages[path])


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


def test_list_time_controls_fetches_all_pages():
    collection_path = "/api/customers/customer/targets/time-control-services"
    second_page_path = f"{collection_path}?_offset=16&_pagesize=16"
    client = PaginatedFakeNfonClient(
        {
            collection_path: {
                "items": [
                    {
                        "href": f"{collection_path}/1",
                        "data": [{"name": "displayName", "value": "Ferien"}],
                    }
                ],
                "links": [{"rel": "next", "href": second_page_path}],
            },
            second_page_path: {
                "items": [
                    {
                        "href": f"{collection_path}/2",
                        "data": [{"name": "name", "value": "Weihnachten"}],
                    }
                ],
                "links": [],
            },
        }
    )
    service = NfonTimeControlService(client=client, customer_id="customer")

    assert service.list_time_controls() == [
        {"id": "1", "name": "Ferien"},
        {"id": "2", "name": "Weihnachten"},
    ]
    assert client.get_calls == [collection_path, second_page_path]


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
    assert result["sent_denied"] == ["Feb 03, 2026", "Mar 01, 2026"]
    assert result["service_debug"]["referralDenied"] == ["Feb 03, 2026", "Mar 01, 2026"]
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


def test_get_time_control_dates_includes_debug_state():
    client = FakeNfonClient(
        {
            "links": [{"rel": "destinationIfDenied"}],
            "data": [
                {"name": "displayName", "value": "Feiertag"},
                {"name": "evaluationStrategy", "value": "DENIED"},
                {"name": "fromDay", "value": "MONDAY"},
                {"name": "fromTimeOfDay", "value": "08:00"},
                {"name": "toDay", "value": "FRIDAY"},
                {"name": "toTimeOfDay", "value": "17:00"},
                {"name": "referralDenied", "value": ["Feb 03, 2026"]},
            ],
        }
    )
    service = NfonTimeControlService(client=client, customer_id="customer")

    result = service.get_time_control_dates("42")

    assert result["denied_dates"] == ["Feb 03, 2026"]
    assert result["service_debug"]["evaluationStrategy"] == "DENIED"
    assert result["service_debug"]["links"] == ["destinationIfDenied"]


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


def _time_control(service_id, name, *, next_id=None, outcome_id="1"):
    links = [
        {
            "rel": "destinationIfDenied",
            "href": f"/api/customers/customer/targets/ivr-services/{outcome_id}",
        }
    ]
    if next_id is not None:
        links.append(
            {
                "rel": "destinationIfAllowed",
                "href": f"/api/customers/customer/targets/time-control-services/{next_id}",
            }
        )
    else:
        links.append(
            {
                "rel": "destinationIfAllowed",
                "href": "/api/customers/customer/targets/group-services/0",
            }
        )
    return {
        "href": f"/api/customers/customer/targets/time-control-services/{service_id}",
        "links": links,
        "data": [
            {"name": "displayName", "value": name},
            {"name": "evaluationStrategy", "value": "AUTO"},
            {"name": "fromDay", "value": "MONDAY"},
            {"name": "fromTimeOfDay", "value": "07:45 AM"},
            {"name": "toDay", "value": "FRIDAY"},
            {"name": "toTimeOfDay", "value": "04:45 PM"},
            {"name": "referralAllowed", "value": []},
            {"name": "referralDenied", "value": []},
        ],
    }


def test_editor_state_prefers_root_with_inbound_number_and_marks_detached_chain():
    collection = "/api/customers/customer/targets/time-control-services"
    pages = {
        collection: {
            "items": [
                _time_control("6", "005 Brückentage", next_id="19"),
                _time_control("18", "006 Vormittags", next_id="19"),
                _time_control("19", "007 Nachmittag", next_id="16"),
                _time_control("16", "010 Feiertag"),
            ],
            "links": [],
        },
        f"{collection}/6/inbound-trunk-numbers": {"items": [{}], "links": []},
        f"{collection}/18/inbound-trunk-numbers": {"items": [], "links": []},
        f"{collection}/available-destinations": {"items": [], "links": []},
        "/api/customers/customer/targets/ivr-services": {"items": [], "links": []},
    }
    client = PaginatedFakeNfonClient(pages)
    service = NfonTimeControlService(client=client, customer_id="customer")

    state = service.get_editor_state()

    assert state["main_root_id"] == "6"
    assert [node["id"] for node in state["chain"]] == ["6", "19", "16"]
    assert [node["id"] for node in state["detached"]] == ["18"]
    assert state["chain_complete"] is False
    assert any("außerhalb der Hauptkette" in warning for warning in state["warnings"])


def test_editor_state_stops_at_node_with_missing_destination_link():
    collection = "/api/customers/customer/targets/time-control-services"
    first = _time_control("1", "Start", next_id="2")
    first["links"] = [first["links"][1]]
    pages = {
        collection: {"items": [first, _time_control("2", "Danach")], "links": []},
        f"{collection}/1/inbound-trunk-numbers": {"items": [{}], "links": []},
        f"{collection}/available-destinations": {"items": [], "links": []},
        "/api/customers/customer/targets/ivr-services": {"items": [], "links": []},
    }
    service = NfonTimeControlService(client=PaginatedFakeNfonClient(pages), customer_id="customer")

    state = service.get_editor_state()

    assert state["stopped_at"] == "1"
    assert [node["id"] for node in state["chain"]] == ["1"]
    assert [node["id"] for node in state["detached"]] == ["2"]
    assert state["chain_complete"] is False


def test_editor_state_recognizes_partial_day_gate_as_connected_chain():
    collection = "/api/customers/customer/targets/time-control-services"
    gate = _time_control("20", "006 Vormittags", next_id="19")
    gate["links"][0] = {
        "rel": "destinationIfDenied",
        "href": f"{collection}/30",
    }
    next(item for item in gate["data"] if item["name"] == "referralDenied")["value"] = ["Aug 08, 2026"]

    window = _time_control("30", "006 Vormittags · Zeitfenster", next_id="19")
    window["links"] = [
        {
            "rel": "destinationIfAllowed",
            "href": "/api/customers/customer/targets/ivr-services/17",
        },
        {
            "rel": "destinationIfDenied",
            "href": f"{collection}/19",
        },
    ]
    next(item for item in window["data"] if item["name"] == "fromTimeOfDay")["value"] = "07:45 AM"
    next(item for item in window["data"] if item["name"] == "toTimeOfDay")["value"] = "12:00 PM"

    pages = {
        collection: {
            "items": [gate, window, _time_control("19", "007 Danach")],
            "links": [],
        },
        f"{collection}/20/inbound-trunk-numbers": {"items": [{}], "links": []},
        f"{collection}/available-destinations": {"items": [], "links": []},
        "/api/customers/customer/targets/ivr-services": {"items": [], "links": []},
    }
    service = NfonTimeControlService(client=PaginatedFakeNfonClient(pages), customer_id="customer")

    state = service.get_editor_state()

    assert [node["id"] for node in state["chain"]] == ["20", "30", "19"]
    assert state["detached"] == []
    assert state["chain_complete"] is True
    assert state["chain"][0]["next_id"] == "30"
    assert state["chain"][0]["next_relation"] == "destinationIfDenied"
    assert state["chain"][0]["bypass_id"] == "19"
    assert state["chain"][0]["bypass_relation"] == "destinationIfAllowed"
    assert not any("verzweigt" in warning for warning in state["warnings"])


def test_update_editor_node_writes_weekday_hours_in_nfon_format():
    client = FakeNfonClient(_time_control("4", "Freitag"))
    service = NfonTimeControlService(client=client, customer_id="customer")

    service.update_editor_node(
        "4",
        {
            "name": "Freitag",
            "from_day": "FRIDAY",
            "from_time": "07:45",
            "to_day": "FRIDAY",
            "to_time": "12:00",
            "denied_dates": [],
        },
    )

    payload = client.put_calls[0][1]
    data = {item["name"]: item["value"] for item in payload["data"]}
    assert data["fromDay"] == "FRIDAY"
    assert data["fromTimeOfDay"] == "07:45 AM"
    assert data["toDay"] == "FRIDAY"
    assert data["toTimeOfDay"] == "12:00 PM"


def test_date_selection_accepts_datetime_values_and_expands_inclusive_range():
    service = NfonTimeControlService(client=FakeNfonClient({}), customer_id="customer")

    assert service._normalize_date_selection(
        {
            "date_mode": "single",
            "dates": ["2026-12-24T13:30", "2026-12-31T08:00"],
        }
    ) == ["Dec 24, 2026", "Dec 31, 2026"]
    assert service._normalize_date_selection(
        {
            "date_mode": "range",
            "range_start": "2026-12-24T13:30",
            "range_end": "2026-12-27T08:00",
        }
    ) == ["Dec 24, 2026", "Dec 25, 2026", "Dec 26, 2026", "Dec 27, 2026"]


def test_date_selection_rejects_backwards_range():
    service = NfonTimeControlService(client=FakeNfonClient({}), customer_id="customer")

    try:
        service._normalize_date_selection(
            {
                "date_mode": "range",
                "range_start": "2026-12-27T08:00",
                "range_end": "2026-12-24T13:30",
            }
        )
    except ValueError as error:
        assert "nicht vor dem Start" in str(error)
    else:
        raise AssertionError("Expected ValueError")


def test_destination_options_include_all_nfon_outcomes_but_not_time_controls():
    collection = "/api/customers/customer/targets/time-control-services"
    pages = {
        f"{collection}/available-destinations": {
            "items": [
                {
                    "href": "/api/customers/customer/targets/phone-extensions/12",
                    "data": [{"name": "displayName", "value": "Empfang"}],
                },
                {
                    "href": f"{collection}/9",
                    "data": [{"name": "displayName", "value": "Andere Zeitsteuerung"}],
                },
            ],
            "links": [],
        },
        "/api/customers/customer/targets/ivr-services": {
            "items": [
                {
                    "href": "/api/customers/customer/targets/ivr-services/3",
                    "data": [{"name": "displayName", "value": "Feiertagsansage"}],
                }
            ],
            "links": [],
        },
    }
    service = NfonTimeControlService(
        client=PaginatedFakeNfonClient(pages),
        customer_id="customer",
    )

    options = service.list_destination_options()

    assert {option["kind"] for option in options} == {"ivr-services", "phone-extensions"}
    assert {option["name"] for option in options} == {"Feiertagsansage", "Empfang"}


class InsertFakeNfonClient:
    def __init__(self):
        self.collection = "/api/customers/customer/targets/time-control-services"
        self.ivr_href = "/api/customers/customer/targets/ivr-services/17"
        self.predecessor = _time_control("6", "005 Brückentage", next_id="19")
        self.post_calls = []
        self.put_calls = []
        self.delete_calls = []

    def get(self, path):
        if path == f"{self.collection}/6":
            return FakeResponse(self.predecessor)
        if path == f"{self.collection}/available-destinations":
            return FakeResponse({"items": [], "links": []})
        if path == "/api/customers/customer/targets/ivr-services":
            return FakeResponse(
                {
                    "items": [
                        {
                            "href": self.ivr_href,
                            "data": [{"name": "displayName", "value": "Ansage Vormittags"}],
                        }
                    ],
                    "links": [],
                }
            )
        raise AssertionError(f"Unexpected GET {path}")

    def post(self, path, body):
        payload = json.loads(body.decode("utf-8"))
        self.post_calls.append((path, payload))
        new_id = str(30 + len(self.post_calls) - 1)
        return FakeResponse({"href": f"{self.collection}/{new_id}"}, status_code=201)

    def put(self, path, body):
        payload = json.loads(body.decode("utf-8"))
        self.put_calls.append((path, payload))
        return FakeResponse(payload)

    def delete(self, path):
        self.delete_calls.append(path)
        return FakeResponse(status_code=204)


def test_update_editor_node_changes_outcome_without_touching_chain_link():
    client = InsertFakeNfonClient()
    service = NfonTimeControlService(client=client, customer_id="customer")

    service.update_editor_node(
        "6",
        {
            "name": "005 Brückentage",
            "from_day": "MONDAY",
            "from_time": "00:00",
            "to_day": "SUNDAY",
            "to_time": "23:59",
            "outcome_relation": "destinationIfDenied",
            "outcome_href": client.ivr_href,
        },
    )

    links = {link["rel"]: link["href"] for link in client.put_calls[0][1]["links"]}
    assert links["destinationIfAllowed"].endswith("/time-control-services/19")
    assert links["destinationIfDenied"] == client.ivr_href

    try:
        service.update_editor_node(
            "6",
            {
                "name": "005 Brückentage",
                "from_day": "MONDAY",
                "from_time": "00:00",
                "to_day": "SUNDAY",
                "to_time": "23:59",
                "outcome_relation": "destinationIfAllowed",
                "outcome_href": client.ivr_href,
            },
        )
    except ValueError as error:
        assert "nächsten Zeitsteuerung" in str(error)
    else:
        raise AssertionError("Expected ValueError")


def test_insert_partial_day_node_creates_date_gate_and_time_window_before_rewire():
    client = InsertFakeNfonClient()
    service = NfonTimeControlService(client=client, customer_id="customer")

    result = service.insert_editor_node(
        {
            "after_id": "6",
            "name": "006 Vormittags",
            "dates": "2026-04-01, 2026-04-02",
            "mode": "morning",
            "from_time": "08:00",
            "to_time": "12:00",
            "destination_href": client.ivr_href,
        }
    )

    assert result["created_ids"] == ["30", "31"]
    assert len(client.post_calls) == 2
    window_payload = client.post_calls[0][1]
    gate_payload = client.post_calls[1][1]
    window_data = {item["name"]: item["value"] for item in window_payload["data"]}
    gate_data = {item["name"]: item["value"] for item in gate_payload["data"]}
    assert window_data["fromTimeOfDay"] == "08:00 AM"
    assert window_data["toTimeOfDay"] == "12:00 PM"
    assert window_data["referralDenied"] == []
    assert gate_data["referralDenied"] == ["Apr 01, 2026", "Apr 02, 2026"]
    assert gate_payload["links"][1]["href"].endswith("/30")
    predecessor_links = {link["rel"]: link["href"] for link in client.put_calls[0][1]["links"]}
    assert predecessor_links["destinationIfAllowed"].endswith("/31")
    assert client.delete_calls == []


def test_configure_partial_day_node_moves_announcement_to_matching_time_window():
    client = InsertFakeNfonClient()
    service = NfonTimeControlService(client=client, customer_id="customer")

    result = service.configure_partial_day_node(
        "6",
        {
            "name": "006 Zeitsteuerung Vormittags Ansage",
            "date_mode": "single",
            "dates": ["2026-08-08T07:45"],
            "from_time": "07:45",
            "to_time": "12:00",
            "destination_href": client.ivr_href,
        },
    )

    assert result == {
        "service_id": "6",
        "window_service_id": "30",
        "dates": ["Aug 08, 2026"],
        "from_time": "07:45",
        "to_time": "12:00",
    }
    window_payload = client.post_calls[0][1]
    window_data = {item["name"]: item["value"] for item in window_payload["data"]}
    window_links = {link["rel"]: link["href"] for link in window_payload["links"]}
    assert window_data["fromTimeOfDay"] == "07:45 AM"
    assert window_data["toTimeOfDay"] == "12:00 PM"
    assert window_data["referralDenied"] == []
    assert window_links["destinationIfAllowed"] == client.ivr_href
    assert window_links["destinationIfDenied"].endswith("/time-control-services/19")

    gate_payload = client.put_calls[0][1]
    gate_data = {item["name"]: item["value"] for item in gate_payload["data"]}
    gate_links = {link["rel"]: link["href"] for link in gate_payload["links"]}
    assert gate_data["fromTimeOfDay"] == "12:00 AM"
    assert gate_data["toTimeOfDay"] == "11:59 PM"
    assert gate_data["referralDenied"] == ["Aug 08, 2026"]
    assert gate_links["destinationIfAllowed"].endswith("/time-control-services/19")
    assert gate_links["destinationIfDenied"].endswith("/time-control-services/30")


def test_insert_node_rolls_back_created_service_if_predecessor_rewire_fails():
    class RewireFailingClient(InsertFakeNfonClient):
        def put(self, path, body):
            self.put_calls.append((path, json.loads(body.decode("utf-8"))))
            return FakeResponse(
                {"title": "Validation failed", "errors": []},
                status_code=400,
                text="Validation failed",
            )

    client = RewireFailingClient()
    service = NfonTimeControlService(client=client, customer_id="customer")

    try:
        service.insert_editor_node(
            {
                "after_id": "6",
                "name": "Feiertag",
                "dates": "2026-12-24",
                "mode": "full_day",
                "destination_href": client.ivr_href,
            }
        )
    except ValueError as error:
        assert "Validation failed" in str(error)
    else:
        raise AssertionError("Expected ValueError")

    assert client.delete_calls == [f"{client.collection}/30"]
