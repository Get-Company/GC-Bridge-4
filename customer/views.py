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
    CustomerSyncDirectionService,
)


def customer_merge_view(request):
    context = {
        **admin.site.each_context(request),
        "title": "Kunden Merge",
    }
    return TemplateResponse(request, "admin/customer_merge.html", context)


def customer_merge_resolve_api(request):
    """Phase 1: Resolve search terms (ERP-Nr, UUID, name) into ERP numbers."""
    query_raw = request.GET.get("q", "")
    terms = [t.strip() for t in query_raw.split(",") if t.strip()]
    if not terms:
        return JsonResponse({"error": "Keine Suchbegriffe angegeben."}, status=400)

    search_service = CustomerMergeSearchService()
    resolved_sets: dict[str, list[str]] = {}
    with ThreadPoolExecutor(max_workers=4) as executor:
        future_map = {executor.submit(search_service.resolve_query, t): t for t in terms}
        for future in as_completed(future_map):
            term = future_map[future]
            try:
                resolved_sets[term] = future.result()
            except Exception as exc:
                logger.error("Resolve error for '{}': {}", term, exc)
                resolved_sets[term] = []

    # Deduplicate, preserve order
    erp_nrs: list[str] = []
    seen: set[str] = set()
    for term in terms:
        for nr in resolved_sets.get(term, []):
            if nr not in seen:
                erp_nrs.append(nr)
                seen.add(nr)

    return JsonResponse({"erp_nrs": erp_nrs, "resolved_from": resolved_sets})


def customer_merge_search_cell_api(request):
    """Phase 2: Search a single system for a single ERP number."""
    erp_nr = request.GET.get("erp_nr", "").strip()
    system = request.GET.get("system", "").strip()
    if not erp_nr or not system:
        return JsonResponse({"error": "erp_nr und system erforderlich."}, status=400)

    search_service = CustomerMergeSearchService()
    if system == "django":
        data = search_service.search_django(erp_nr)
    elif system == "shopware":
        data = search_service.search_shopware(erp_nr)
    elif system == "microtech":
        data = search_service.search_microtech(erp_nr)
    else:
        return JsonResponse({"error": f"Unbekanntes System: {system}"}, status=400)

    return JsonResponse({"erp_nr": erp_nr, "system": system, "data": data})


def customer_merge_search_api(request):
    """Legacy: full search across all systems (used by refetchRow)."""
    query_raw = request.GET.get("erp_nrs", "")
    erp_nrs = [nr.strip() for nr in query_raw.split(",") if nr.strip()]
    if not erp_nrs:
        return JsonResponse({"error": "Keine Suchbegriffe angegeben."}, status=400)

    search_service = CustomerMergeSearchService()
    results: dict[str, dict] = {}

    def _search(system, nr):
        if system == "django":
            return (system, nr, search_service.search_django(nr))
        elif system == "shopware":
            return (system, nr, search_service.search_shopware(nr))
        else:
            return (system, nr, search_service.search_microtech(nr))

    search_tasks = []
    for nr in erp_nrs:
        results[nr] = {"django": None, "shopware": None, "microtech": None}
        for sys in ("django", "shopware", "microtech"):
            search_tasks.append((sys, nr))

    with ThreadPoolExecutor(max_workers=6) as executor:
        futures = [executor.submit(_search, sys, nr) for sys, nr in search_tasks]
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


def customer_sync_direction_api(request):
    if request.method != "POST":
        return JsonResponse({"error": "POST erforderlich."}, status=405)
    try:
        body = json.loads(request.body)
        erp_nr = body.get("erp_nr", "").strip()
        direction = body.get("direction", "").strip()

        if not erp_nr:
            return JsonResponse({"error": "erp_nr erforderlich."}, status=400)
        if not direction:
            return JsonResponse({"error": "direction erforderlich."}, status=400)

        service = CustomerSyncDirectionService()
        result = service.sync(erp_nr, direction)
        return JsonResponse({"success": True, **result})
    except ValueError as exc:
        return JsonResponse({"error": str(exc)}, status=400)
    except Exception as exc:
        logger.error("Sync direction failed: {}\n{}", exc, traceback.format_exc())
        return JsonResponse({"error": str(exc)}, status=500)
