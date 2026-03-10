from __future__ import annotations

import json

from django.contrib import admin
from django.http import JsonResponse
from django.template.response import TemplateResponse
from django.utils import timezone

from microtech.models import MicrotechJob


def microtech_queue_view(request):
    jobs = MicrotechJob.objects.order_by("-created_at")[:200]
    context = {
        **admin.site.each_context(request),
        "title": "Microtech Queue",
        "jobs": jobs,
    }
    return TemplateResponse(request, "admin/microtech_queue.html", context)


def microtech_queue_api(request):
    """JSON endpoint for live polling."""
    jobs = MicrotechJob.objects.order_by("-created_at")[:200]
    data = []
    for job in jobs:
        data.append({
            "id": job.id,
            "status": job.status,
            "priority": job.priority,
            "label": job.label,
            "correlation_id": job.correlation_id,
            "created_at": job.created_at.isoformat() if job.created_at else None,
            "started_at": job.started_at.isoformat() if job.started_at else None,
            "finished_at": job.finished_at.isoformat() if job.finished_at else None,
            "last_error": job.last_error,
        })
    return JsonResponse({"jobs": data})


def microtech_queue_action(request):
    """POST: cancel or delete a job, or change priority."""
    if request.method != "POST":
        return JsonResponse({"success": False, "error": "POST required"}, status=405)
    try:
        body = json.loads(request.body)
        action = str(body.get("action", "")).strip()
        job_id = body.get("job_id")
    except Exception:
        return JsonResponse({"success": False, "error": "Invalid request"}, status=400)

    try:
        job = MicrotechJob.objects.get(id=job_id)
    except MicrotechJob.DoesNotExist:
        return JsonResponse({"success": False, "error": "Job not found"}, status=404)

    if action == "cancel":
        if job.status != MicrotechJob.Status.QUEUED:
            return JsonResponse({"success": False, "error": "Only queued jobs can be cancelled"})
        job.status = MicrotechJob.Status.CANCELLED
        job.finished_at = timezone.now()
        job.save(update_fields=["status", "finished_at", "updated_at"])
        return JsonResponse({"success": True})

    if action == "delete":
        if job.status == MicrotechJob.Status.RUNNING:
            return JsonResponse({"success": False, "error": "Cannot delete a running job"})
        job.delete()
        return JsonResponse({"success": True})

    if action == "set_priority":
        if job.status != MicrotechJob.Status.QUEUED:
            return JsonResponse({"success": False, "error": "Only queued jobs can be re-prioritized"})
        try:
            new_priority = int(body.get("priority", job.priority))
        except (TypeError, ValueError):
            return JsonResponse({"success": False, "error": "Invalid priority"}, status=400)
        job.priority = max(0, min(new_priority, 9999))
        job.save(update_fields=["priority", "updated_at"])
        return JsonResponse({"success": True})

    return JsonResponse({"success": False, "error": f"Unknown action: {action}"}, status=400)
