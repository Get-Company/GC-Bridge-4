from __future__ import annotations

import json
import os
from datetime import datetime

from django.contrib import messages
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from django.urls import reverse

from core.services.nfon_client import NfonClient


def _get_client() -> NfonClient:
    return NfonClient(
        api_key_id=os.environ["NFON_API_KEY_ID"],
        api_key_secret=os.environ["NFON_API_KEY_SECRET"],
        customer_id=os.environ["NFON_CUSTOMER_ID"],
    )


def _data_value(data: list, name: str):
    for item in data:
        if item.get("name") == name:
            return item.get("value")
    return None


def zeitsteuerung_list(request):
    client = _get_client()
    customer_id = os.environ["NFON_CUSTOMER_ID"]
    path = f"/api/customers/{customer_id}/targets/time-control-services"

    services = []
    try:
        r = client.get(path)
        r.raise_for_status()
        raw = r.json()
        items = raw if isinstance(raw, list) else raw.get("items", [raw])
        for item in items:
            data = item.get("data", [])
            href = item.get("href", "")
            service_id = href.rstrip("/").split("/")[-1]
            display_name = _data_value(data, "displayName") or _data_value(data, "name") or service_id
            services.append({
                "id": service_id,
                "name": display_name,
                "url": reverse("admin:telefon_zeitsteuerung_detail", args=[service_id]),
            })
    except Exception as e:
        messages.error(request, f"NFON API Fehler: {e}")

    return TemplateResponse(request, "admin/telefon/zeitsteuerung_list.html", {
        "title": "Zeitsteuerungen",
        "subtitle": "NFON Service Portal",
        "services": services,
    })


def zeitsteuerung_detail(request, service_id: str):
    client = _get_client()
    customer_id = os.environ["NFON_CUSTOMER_ID"]
    path = f"/api/customers/{customer_id}/targets/time-control-services/{service_id}"

    if request.method == "POST":
        action = request.POST.get("action")
        date_str = request.POST.get("date", "").strip()

        try:
            r = client.get(path)
            r.raise_for_status()
            service = r.json()
            data = service.get("data", [])

            denied_item = next((d for d in data if d["name"] == "referralDenied"), None)
            current_dates: list = list(denied_item["value"]) if denied_item else []

            if action == "add" and date_str:
                dt = datetime.strptime(date_str, "%Y-%m-%d")
                _months = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]
                formatted = f"{_months[dt.month - 1]} {dt.day:02d}, {dt.year}"
                if formatted not in current_dates:
                    current_dates.append(formatted)
                    current_dates.sort(key=lambda d: datetime.strptime(d, "%b %d, %Y"))
            elif action == "delete":
                before = list(current_dates)
                current_dates = [d for d in current_dates if d != date_str]
                if len(current_dates) == len(before):
                    messages.warning(request, f"Datum nicht gefunden: '{date_str}' in {before}")

            if denied_item:
                denied_item["value"] = current_dates
            else:
                data.append({"name": "referralDenied", "value": current_dates})

            # Strip read-only fields before PUT (per API schema)
            service.pop("href", None)
            writable_rels = {"destinationIfAllowed", "destinationIfDenied", "inboundTrunkNumbers"}
            service["links"] = [l for l in service.get("links", []) if l.get("rel") in writable_rels]
            writable_data_fields = {
                "name", "serviceNumber", "serviceCode", "extensionNumber",
                "displayName", "evaluationStrategy",
                "fromDay", "fromTimeOfDay", "toDay", "toTimeOfDay",
                "referralAllowed", "referralDenied",
            }
            service["data"] = [d for d in data if d.get("name") in writable_data_fields]
            body = json.dumps(service).encode("utf-8")
            put_r = client.put(path, body)
            sent_denied = [d["value"] for d in service["data"] if d.get("name") == "referralDenied"]
            if put_r.status_code < 300:
                try:
                    resp_denied = [d["value"] for d in put_r.json().get("data",[]) if d.get("name") == "referralDenied"]
                except Exception:
                    resp_denied = put_r.text[:100]
                messages.success(request, f"PUT {put_r.status_code}. Gesendet: {sent_denied} | Antwort referralDenied: {resp_denied}")
            else:
                messages.error(request, f"API-Fehler {put_r.status_code}: {put_r.text[:300]}")
        except Exception as e:
            messages.error(request, f"Fehler: {e}")

        return redirect("admin:telefon_zeitsteuerung_detail", service_id)

    display_name = service_id
    denied_dates = []
    try:
        r = client.get(path)
        r.raise_for_status()
        service = r.json()
        data = service.get("data", [])
        display_name = _data_value(data, "displayName") or _data_value(data, "name") or service_id
        denied_dates = _data_value(data, "referralDenied") or []
    except Exception as e:
        messages.error(request, f"NFON API Fehler: {e}")

    return TemplateResponse(request, "admin/telefon/zeitsteuerung_detail.html", {
        "title": display_name,
        "subtitle": "Zeitsteuerung",
        "service_id": service_id,
        "display_name": display_name,
        "denied_dates": denied_dates,
        "list_url": reverse("admin:telefon_zeitsteuerung_list"),
    })
