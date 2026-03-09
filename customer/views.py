from __future__ import annotations

import json
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed

from django.contrib import admin
from django.http import JsonResponse
from django.template.response import TemplateResponse
from loguru import logger

from customer.services.customer_merge import (
    CustomerIdUpdateService,
    CustomerMergeSearchService,
    CustomerMergeService,
)


def customer_merge_view(request):
    context = {
        **admin.site.each_context(request),
        "title": "Kunden Merge",
    }
    return TemplateResponse(request, "admin/customer_merge.html", context)


def customer_merge_search_api(request):
    erp_nrs_raw = request.GET.get("erp_nrs", "")
    erp_nrs = [nr.strip() for nr in erp_nrs_raw.split(",") if nr.strip()]
    if not erp_nrs:
        return JsonResponse({"error": "Keine ERP-Nummern angegeben."}, status=400)

    search_service = CustomerMergeSearchService()
    results = {}

    def _search_django(nr):
        return ("django", nr, search_service.search_django(nr))

    def _search_shopware(nr):
        return ("shopware", nr, search_service.search_shopware(nr))

    def _search_microtech(nr):
        return ("microtech", nr, search_service.search_microtech(nr))

    tasks = []
    for nr in erp_nrs:
        results[nr] = {"django": None, "shopware": None, "microtech": None}
        tasks.append(("django", nr))
        tasks.append(("shopware", nr))
        tasks.append(("microtech", nr))

    with ThreadPoolExecutor(max_workers=6) as executor:
        futures = []
        for system, nr in tasks:
            if system == "django":
                futures.append(executor.submit(_search_django, nr))
            elif system == "shopware":
                futures.append(executor.submit(_search_shopware, nr))
            else:
                futures.append(executor.submit(_search_microtech, nr))

        for future in as_completed(futures):
            try:
                system, nr, data = future.result()
                results[nr][system] = data
            except Exception as exc:
                logger.error("Search error: {}", exc)

    return JsonResponse({"results": results})


def customer_merge_execute_api(request):
    if request.method != "POST":
        return JsonResponse({"error": "POST erforderlich."}, status=405)
    try:
        body = json.loads(request.body)
        target_erp_nr = body.get("target_erp_nr", "").strip()
        source_erp_nr = body.get("source_erp_nr", "").strip()
        address_mapping = body.get("address_mapping", {})
        merge_shopware = body.get("merge_shopware_orders", True)

        if not target_erp_nr or not source_erp_nr:
            return JsonResponse(
                {"error": "Ziel- und Quell-ERP-Nummer erforderlich."}, status=400
            )

        service = CustomerMergeService()
        result = service.merge_customers(
            target_erp_nr=target_erp_nr,
            source_erp_nr=source_erp_nr,
            address_mapping=address_mapping,
            merge_shopware_orders=merge_shopware,
        )
        return JsonResponse({"success": True, **result})
    except ValueError as exc:
        return JsonResponse({"error": str(exc)}, status=400)
    except Exception as exc:
        logger.error("Merge failed: {}\n{}", exc, traceback.format_exc())
        return JsonResponse({"error": str(exc)}, status=500)


def customer_update_ids_api(request):
    if request.method != "POST":
        return JsonResponse({"error": "POST erforderlich."}, status=405)
    try:
        body = json.loads(request.body)
        action = body.get("action", "")
        customer_id = body.get("customer_id")
        value = body.get("value", "").strip()

        if not customer_id:
            return JsonResponse({"error": "customer_id erforderlich."}, status=400)

        service = CustomerIdUpdateService()

        if action == "update_erp_nr":
            result = service.update_erp_nr(int(customer_id), value)
        elif action == "update_shopware_id":
            result = service.update_shopware_id(int(customer_id), value)
        else:
            return JsonResponse({"error": f"Unbekannte Aktion: {action}"}, status=400)

        return JsonResponse({"success": True, **result})
    except ValueError as exc:
        return JsonResponse({"error": str(exc)}, status=400)
    except Exception as exc:
        logger.error("ID update failed: {}\n{}", exc, traceback.format_exc())
        return JsonResponse({"error": str(exc)}, status=500)
