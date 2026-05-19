from __future__ import annotations

import logging
from datetime import date

from celery import shared_task
from django.core.management import call_command

logger = logging.getLogger(__name__)


@shared_task(name="hr.sync_holidays")
def sync_holidays(
    *,
    years: list[int | str] | None = None,
    calendar_id: int | None = None,
    country_iso_code: str = "",
    language_iso_code: str = "",
    subdivision_code: str = "",
) -> dict:
    """Fetch public and school holidays from OpenHolidays API and upsert into the database.

    For each active HolidayCalendar with a region_code the API is queried and results upserted.
    API parameters are resolved in this order (first non-empty wins):
      country_iso_code : task kwarg → derived from calendar.region_code → service default (DE)
      subdivision_code : task kwarg → calendar.region_code (when it contains '-') → service default
      language_iso_code: task kwarg → service default (DE)
    """
    from hr.models import HolidayCalendar
    from hr.services.open_holidays_service import OpenHolidaysApiError, OpenHolidaysService

    parsed_years: list[int] = []
    for y in years or []:
        try:
            parsed_years.append(int(y))
        except (TypeError, ValueError):
            pass
    if not parsed_years:
        parsed_years = [date.today().year]

    service = OpenHolidaysService()
    calendars = HolidayCalendar.objects.filter(is_active=True).exclude(region_code="")
    if calendar_id is not None:
        calendars = calendars.filter(pk=calendar_id)

    results: list[dict] = []
    for calendar in calendars:
        # Derive per-calendar defaults from region_code (e.g. "DE-BY" → country="DE", subdivision="DE-BY").
        region = calendar.region_code.strip()
        calendar_country = region.split("-", 1)[0].upper() if region else ""
        calendar_subdivision = region if "-" in region else ""

        resolved_country = (country_iso_code.strip().upper() or calendar_country or service.DEFAULT_COUNTRY_ISO_CODE)
        resolved_subdivision = (subdivision_code.strip() or calendar_subdivision or service.DEFAULT_SUBDIVISION_CODE)
        resolved_language = (language_iso_code.strip().upper() or service.DEFAULT_LANGUAGE_ISO_CODE)

        for year in parsed_years:
            calendar_result: dict = {
                "calendar": str(calendar),
                "year": year,
                "country": resolved_country,
                "subdivision": resolved_subdivision,
                "language": resolved_language,
            }
            try:
                public_holidays = service.fetch_public_holidays(
                    year=year,
                    country_iso_code=resolved_country,
                    language_iso_code=resolved_language,
                    subdivision_code=resolved_subdivision,
                )
                school_holidays = service.fetch_school_holidays(
                    year=year,
                    country_iso_code=resolved_country,
                    language_iso_code=resolved_language,
                    subdivision_code=resolved_subdivision,
                )
                pub_stats = service.import_public_holidays(calendar=calendar, holidays=public_holidays)
                sch_stats = service.import_school_holidays(calendar=calendar, holidays=school_holidays)
                calendar_result.update({"public": pub_stats, "school": sch_stats, "error": None})
                logger.info(
                    "Holiday sync %s %d (%s/%s/%s): public=%s school=%s",
                    calendar, year, resolved_country, resolved_subdivision, resolved_language,
                    pub_stats, sch_stats,
                )
            except OpenHolidaysApiError as exc:
                calendar_result["error"] = str(exc)
                logger.error("Holiday sync failed for %s %d: %s", calendar, year, exc)
            results.append(calendar_result)

    return {"results": results}


@shared_task(name="hr.year_transition")
def year_transition(
    *,
    year: int | None = None,
    max_carryover: float | None = None,
    dry_run: bool = True,
) -> None:
    call_command(
        "hr_year_transition",
        year=year,
        max_carryover=max_carryover,
        dry_run=dry_run,
    )
