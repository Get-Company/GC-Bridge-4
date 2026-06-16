from __future__ import annotations

import json
import os
from datetime import datetime

from django.contrib import messages
from django.shortcuts import redirect
from django.template.response import TemplateResponse

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

    try:
        r = client.get(path)
        r.raise_for_status()
        raw = r.json()
        items = raw if isinstance(raw, list) else raw.get("items", [raw])
        services = []
        for item in items:
            data = item.get("data", [])
            href = item.get("href", "")
            service_id = href.rstrip("/").split("/")[-1]
            services.append({
                "id": service_id,
                "name": _data_value(data, "displayName") or _data_value(data, "name") or service_id,
            })
    except Exception as e:
        services = []
        messages.error(request, f"NFON API Fehler: {e}")

    return TemplateResponse(request, "admin/telefon/zeitsteuerung_list.html", {
        "title": "Zeitsteuerungen",
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
                formatted = dt.strftime("%b %d, %Y").replace(" 0", " ")
                if formatted not in current_dates:
                    current_dates.append(formatted)

            elif action == "delete":
                current_dates = [d for d in current_dates if d != date_str]

            if denied_item:
                denied_item["value"] = current_dates
            else:
                data.append({"name": "referralDenied", "value": current_dates})

            service["data"] = data
            body = json.dumps(service).encode("utf-8")
            put_r = client.put(path, body)
            if put_r.status_code < 300:
                messages.success(request, "Gespeichert.")
            else:
                messages.error(request, f"API-Fehler beim Speichern: {put_r.status_code} {put_r.text[:200]}")
        except Exception as e:
            messages.error(request, f"Fehler: {e}")

        return redirect("admin:telefon_zeitsteuerung_detail", service_id=service_id)

    try:
        r = client.get(path)
        r.raise_for_status()
        service = r.json()
        data = service.get("data", [])
        display_name = _data_value(data, "displayName") or _data_value(data, "name") or service_id
        denied_dates: list = _data_value(data, "referralDenied") or []
    except Exception as e:
        display_name = service_id
        denied_dates = []
        messages.error(request, f"NFON API Fehler: {e}")

    return TemplateResponse(request, "admin/telefon/zeitsteuerung_detail.html", {
        "title": display_name,
        "service_id": service_id,
        "display_name": display_name,
        "denied_dates": denied_dates,
    })
