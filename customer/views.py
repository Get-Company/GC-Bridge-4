from __future__ import annotations

import json
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed

from django.contrib import admin
from django.http import JsonResponse
from django.template.response import TemplateResponse
from django.utils import timezone
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
    """Phase 1: resolve matching ERP numbers and queue Microtech searches."""
    criteria = {
        "customer_number": request.GET.get("customer_number", "").strip(),
        "email": request.GET.get("email", "").strip(),
        "first_name": request.GET.get("first_name", "").strip(),
        "last_name": request.GET.get("last_name", "").strip(),
    }
    if any(criteria.values()):
        search_service = CustomerMergeSearchService()
        resolved_sets: dict[str, list[str]] = {}
        with ThreadPoolExecutor(max_workers=2) as executor:
            future_map = {
                executor.submit(search_service.resolve_shopware_erp_numbers, **criteria): "shopware",
                executor.submit(search_service.resolve_django_erp_numbers, **criteria): "django",
            }
            for future in as_completed(future_map):
                system = future_map[future]
                try:
                    resolved_sets[system] = future.result()
                except Exception as exc:
                    logger.error("{} customer resolve error: {}", system, exc)
                    resolved_sets[system] = []

        erp_nrs: list[str] = []
        if criteria["customer_number"]:
            erp_nrs.append(criteria["customer_number"])
        for system in ("shopware", "django"):
            for erp_nr in resolved_sets.get(system, []):
                if erp_nr not in erp_nrs:
                    erp_nrs.append(erp_nr)

        return JsonResponse(
            {
                "erp_nrs": erp_nrs,
                "resolved_from": resolved_sets,
                "microtech_jobs": search_service.start_microtech_resolution_search(**criteria),
            }
        )

    # Compatibility for callers of the former free-text endpoint.
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

    microtech_jobs: list[dict] = []
    for term in terms:
        microtech_jobs.extend(search_service.start_microtech_resolution_search(term))

    return JsonResponse(
        {
            "erp_nrs": erp_nrs,
            "resolved_from": resolved_sets,
            "microtech_jobs": microtech_jobs,
        }
    )


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
        result = search_service.start_microtech_customer_search(erp_nr)
        if result.get("error"):
            return JsonResponse({"erp_nr": erp_nr, "system": system, "data": result})
        return JsonResponse(
            {
                "erp_nr": erp_nr,
                "system": system,
                "pending": True,
                "microtech_job_id": result["job_id"],
            }
        )
    else:
        return JsonResponse({"error": f"Unbekanntes System: {system}"}, status=400)

    return JsonResponse({"erp_nr": erp_nr, "system": system, "data": data})


def customer_merge_microtech_search_status_api(request):
    """Expose and, if due, poll only customer-merge Sentinel jobs."""
    raw_job_ids = request.GET.get("job_ids", "")
    job_ids: list[int] = []
    for raw_job_id in raw_job_ids.split(","):
        try:
            job_id = int(raw_job_id)
        except (TypeError, ValueError):
            continue
        if job_id > 0 and job_id not in job_ids:
            job_ids.append(job_id)
    if not job_ids:
        return JsonResponse({"error": "Mindestens eine gültige Microtech-Job-ID erforderlich."}, status=400)

    # The regular Celery beat performs this polling in production. Polling due
    # jobs here as well keeps an active admin search responsive if it happens
    # between two beat ticks, while still using the Sentinel as the sole route
    # to GraphQL and Microtech.
    from microtech.models import MicrotechGraphQLJob
    from microtech.services import MicrotechJobSentinelService

    now = timezone.now()
    active_statuses = {
        MicrotechGraphQLJob.Status.QUEUED,
        MicrotechGraphQLJob.Status.SUBMITTED,
        MicrotechGraphQLJob.Status.RUNNING,
        MicrotechGraphQLJob.Status.WAITING_WEBHOOK,
    }
    due_jobs = MicrotechGraphQLJob.objects.filter(pk__in=job_ids, status__in=active_statuses).filter(
        next_poll_at__lte=now
    )
    sentinel = MicrotechJobSentinelService()
    for job in due_jobs:
        if (job.context or {}).get("source") != "customer_merge_search":
            continue
        sentinel.poll_job_once(job_id=job.pk)

    search_service = CustomerMergeSearchService()
    jobs = [search_service.get_microtech_search_job_status(job_id) for job_id in job_ids]
    return JsonResponse({"jobs": jobs})


def customer_merge_search_api(request):
    """Legacy full-search endpoint; Microtech cells are returned as Sentinel jobs."""
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
            result = search_service.start_microtech_customer_search(nr)
            if result.get("error"):
                return (system, nr, result)
            return (system, nr, {"pending": True, "microtech_job_id": result["job_id"]})

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


def customer_delete_addresses_api(request):
    if request.method != "POST":
        return JsonResponse({"error": "POST erforderlich."}, status=405)
    try:
        body = json.loads(request.body)
        address_ids = body.get("address_ids", [])
        logger.info("Delete-addresses request: address_ids={}", address_ids)
        if not address_ids:
            return JsonResponse({"error": "Keine Adressen ausgewaehlt."}, status=400)

        from customer.models import Address

        addresses = list(Address.objects.filter(id__in=address_ids))
        logger.info("Delete-addresses: found {} addresses in DB", len(addresses))
        if not addresses:
            return JsonResponse({"error": "Keine Adressen gefunden."}, status=400)

        errors = []

        # Delete in Shopware
        sw_ids = [a.api_id for a in addresses if a.api_id]
        logger.info("Delete-addresses: {} Shopware-IDs to delete: {}", len(sw_ids), sw_ids)
        if sw_ids:
            try:
                from shopware.services.shopware6 import Shopware6Service
                sw = Shopware6Service()
                for sw_id in sw_ids:
                    try:
                        logger.info("Delete-addresses: Shopware deleting {}", sw_id)
                        sw.request_delete(f"/customer-address/{sw_id}")
                        logger.info("Delete-addresses: Shopware deleted {}", sw_id)
                    except Exception as exc:
                        errors.append(f"Shopware {sw_id}: {exc}")
                        logger.warning("Delete-addresses: Shopware {} failed: {}", sw_id, exc)
            except Exception as exc:
                errors.append(f"Shopware: {exc}")
                logger.warning("Delete-addresses: Shopware init failed: {}", exc)
        logger.info("Delete-addresses: Shopware phase done")

        # Delete in Microtech
        mt_addresses = [
            (a.customer.erp_nr, a.erp_ans_nr, a.erp_asp_nr)
            for a in addresses
            if a.erp_ans_nr is not None
        ]
        logger.info("Delete-addresses: {} Microtech-Anschriften to delete: {}", len(mt_addresses), mt_addresses)
        if mt_addresses:
            try:
                from microtech.services import microtech_connection
                logger.info("Delete-addresses: Microtech connecting...")
                with microtech_connection() as client:
                    logger.info("Delete-addresses: Microtech connected")
                    for erp_nr, ans_nr, asp_nr in mt_addresses:
                        try:
                            logger.info("Delete-addresses: Microtech deleting {}/{}", erp_nr, ans_nr)
                            address_number = int(erp_nr)
                            address_sub_number = int(ans_nr)
                            if asp_nr is not None:
                                client.delete_contact_person(address_number, address_sub_number, int(asp_nr))
                            client.delete_postal_address(address_number, address_sub_number)
                            logger.info("Delete-addresses: Microtech deleted {}/{}", erp_nr, ans_nr)
                        except Exception as exc:
                            errors.append(f"Microtech {erp_nr}/{ans_nr}: {exc}")
                            logger.warning("Delete-addresses: Microtech {}/{} failed: {}", erp_nr, ans_nr, exc)
            except Exception as exc:
                errors.append(f"Microtech: {exc}")
                logger.warning("Delete-addresses: Microtech connection failed: {}", exc)
        logger.info("Delete-addresses: Microtech phase done")

        # Delete in Django
        count = len(addresses)
        logger.info("Delete-addresses: deleting {} addresses in Django...", count)
        Address.objects.filter(id__in=address_ids).delete()
        logger.info("Delete-addresses: DONE - deleted {} addresses, errors: {}", count, errors)
        return JsonResponse({"success": True, "deleted": count, "errors": errors})
    except Exception as exc:
        logger.error("Address delete failed: {}\n{}", exc, traceback.format_exc())
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
