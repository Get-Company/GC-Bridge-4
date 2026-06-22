from __future__ import annotations

import urllib.error
import urllib.request
import json
import time
from urllib.parse import urlsplit, urlunsplit

from django.conf import settings
from django.contrib import admin
from django.http import JsonResponse
from django.template.response import TemplateResponse


def _wrapper_base_url() -> str:
    graphql_url = (getattr(settings, "MICROTECH_GRAPHQL_URL", "") or "").strip()
    if not graphql_url:
        return ""
    parts = urlsplit(graphql_url)
    return urlunsplit((parts.scheme, parts.netloc, "", "", ""))


def _fetch_job_stats(base_url: str) -> dict | None:
    if not base_url:
        return None
    url = base_url.rstrip("/") + "/api/jobs/stats/"
    timeout = float(getattr(settings, "MICROTECH_GRAPHQL_REQUEST_TIMEOUT", 5.0))
    try:
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=min(timeout, 5.0)) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as exc:
        return {"error": str(exc)}


def microtech_queue_view(request):
    context = {
        **admin.site.each_context(request),
        "title": "Microtech Queue",
        "wrapper_url": _wrapper_base_url(),
    }
    return TemplateResponse(request, "admin/microtech_queue.html", context)


def microtech_queue_api(request):
    base_url = _wrapper_base_url()
    stats = _fetch_job_stats(base_url)
    if stats is None:
        return JsonResponse({"error": "MICROTECH_GRAPHQL_URL nicht konfiguriert", "counts": {}, "active_jobs": [], "recent_jobs": []})
    return JsonResponse(stats)
