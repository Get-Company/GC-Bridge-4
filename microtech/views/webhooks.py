from __future__ import annotations

from django.http import HttpResponseBadRequest, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from microtech.services import MicrotechJobSentinelService


@csrf_exempt
@require_POST
def microtech_graphql_job_webhook(request):
    signature = request.headers.get("X-Microtech-Signature", "")
    service = MicrotechJobSentinelService()
    if not service.verify_webhook_signature(body=request.body, signature=signature):
        return JsonResponse({"ok": False, "error": "invalid_signature"}, status=403)

    try:
        payload = service.payload_from_body(request.body)
        job = service.handle_webhook(payload)
    except Exception as exc:
        return HttpResponseBadRequest(str(exc))

    return JsonResponse(
        {
            "ok": True,
            "job_id": job.pk,
            "external_job_id": job.external_job_id,
            "status": job.status,
        }
    )
