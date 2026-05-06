from __future__ import annotations

from datetime import date
from typing import Any

import requests

from core.services import BaseService
from hr.models import HolidayCalendar, PublicHoliday, SchoolHoliday


class OpenHolidaysApiError(Exception):
    pass


class OpenHolidaysService(BaseService):
    model = PublicHoliday

    BASE_URL = "https://openholidaysapi.org"
    DEFAULT_COUNTRY_ISO_CODE = "DE"
    DEFAULT_LANGUAGE_ISO_CODE = "DE"
    DEFAULT_SUBDIVISION_CODE = "DE-BY"
    DEFAULT_TIMEOUT_SECONDS = 20

    @staticmethod
    def get_year_date_range(year: int) -> tuple[date, date]:
        return date(year, 1, 1), date(year, 12, 31)

    @staticmethod
    def _parse_api_date(value: Any) -> date | None:
        if value in (None, ""):
            return None
        raw_value = str(value).strip()
        if not raw_value:
            return None
        raw_value = raw_value.split("T", 1)[0]
        try:
            return date.fromisoformat(raw_value)
        except ValueError:
            return None

    @staticmethod
    def _extract_localized_name(value: Any, *, language_iso_code: str) -> str:
        if isinstance(value, str):
            return value.strip()

        if isinstance(value, dict):
            for key in ("text", "name", "label", "value"):
                text = value.get(key)
                if isinstance(text, str) and text.strip():
                    return text.strip()
            return ""

        if not isinstance(value, list):
            return ""

        preferred_language = language_iso_code.strip().upper()
        fallback_text = ""
        for item in value:
            if isinstance(item, str) and item.strip() and not fallback_text:
                fallback_text = item.strip()
                continue

            if not isinstance(item, dict):
                continue

            text = OpenHolidaysService._extract_localized_name(item, language_iso_code=language_iso_code)
            if not text:
                continue

            item_language = str(
                item.get("language")
                or item.get("languageIsoCode")
                or item.get("isoCode")
                or item.get("code")
                or ""
            ).strip().upper()
            if item_language == preferred_language:
                return text
            if not fallback_text:
                fallback_text = text

        return fallback_text

    @staticmethod
    def _extract_subdivision_codes(value: Any) -> str:
        if not isinstance(value, list):
            return ""

        codes: list[str] = []
        for item in value:
            if isinstance(item, str) and item.strip():
                codes.append(item.strip())
                continue
            if not isinstance(item, dict):
                continue
            code = str(item.get("code") or item.get("isoCode") or item.get("shortName") or "").strip()
            if code:
                codes.append(code)
        return ", ".join(codes)

    @staticmethod
    def _extract_error_message(payload: Any, *, fallback_status: int | None = None) -> str:
        if isinstance(payload, dict):
            title = str(payload.get("title") or "").strip()
            error_map = payload.get("errors")
            detail_parts: list[str] = []
            if isinstance(error_map, dict):
                for field_name, messages in error_map.items():
                    if isinstance(messages, list):
                        joined_messages = "; ".join(str(message).strip() for message in messages if str(message).strip())
                        if joined_messages:
                            detail_parts.append(f"{field_name}: {joined_messages}")
            if title and detail_parts:
                return f"{title} ({' | '.join(detail_parts)})"
            if title:
                return title
        if fallback_status:
            return f"OpenHolidays API Fehler ({fallback_status})."
        return "OpenHolidays API Fehler."

    def _request(self, endpoint: str, *, params: dict[str, str]) -> list[dict[str, Any]]:
        url = f"{self.BASE_URL}/{endpoint.lstrip('/')}"
        try:
            response = requests.get(
                url,
                params=params,
                headers={"accept": "application/json"},
                timeout=self.DEFAULT_TIMEOUT_SECONDS,
            )
        except requests.RequestException as exc:
            raise OpenHolidaysApiError(f"OpenHolidays API konnte nicht erreicht werden: {exc}") from exc

        try:
            payload = response.json()
        except ValueError:
            payload = None

        if response.status_code >= 400:
            raise OpenHolidaysApiError(
                self._extract_error_message(payload, fallback_status=response.status_code)
            )

        if isinstance(payload, list):
            return [item for item in payload if isinstance(item, dict)]
        if isinstance(payload, dict):
            holidays = payload.get("holidays")
            if isinstance(holidays, list):
                return [item for item in holidays if isinstance(item, dict)]
            data = payload.get("data")
            if isinstance(data, list):
                return [item for item in data if isinstance(item, dict)]

        raise OpenHolidaysApiError("OpenHolidays API lieferte ein unerwartetes Antwortformat.")

    def fetch_public_holidays(
        self,
        *,
        year: int,
        country_iso_code: str,
        language_iso_code: str,
        subdivision_code: str,
    ) -> list[dict[str, Any]]:
        valid_from, valid_to = self.get_year_date_range(year)
        payload = self._request(
            "PublicHolidays",
            params={
                "countryIsoCode": country_iso_code,
                "validFrom": valid_from.isoformat(),
                "validTo": valid_to.isoformat(),
                "languageIsoCode": language_iso_code,
                "subdivisionCode": subdivision_code,
            },
        )
        normalized: list[dict[str, Any]] = []
        for item in payload:
            holiday_date = self._parse_api_date(item.get("startDate") or item.get("date"))
            if holiday_date is None:
                continue
            normalized.append(
                {
                    "date": holiday_date,
                    "name": self._extract_localized_name(item.get("name"), language_iso_code=language_iso_code)
                    or "Unbenannter Feiertag",
                    "is_half_day": str(item.get("temporalScope") or "").strip().lower() == "halfday",
                    "subdivisions": self._extract_subdivision_codes(item.get("subdivisions")),
                    "nationwide": bool(item.get("nationwide")),
                    "raw": item,
                }
            )
        return sorted(normalized, key=lambda item: (item["date"], item["name"]))

    def fetch_school_holidays(
        self,
        *,
        year: int,
        country_iso_code: str,
        language_iso_code: str,
        subdivision_code: str,
    ) -> list[dict[str, Any]]:
        valid_from, valid_to = self.get_year_date_range(year)
        payload = self._request(
            "SchoolHolidays",
            params={
                "countryIsoCode": country_iso_code,
                "validFrom": valid_from.isoformat(),
                "validTo": valid_to.isoformat(),
                "languageIsoCode": language_iso_code,
                "subdivisionCode": subdivision_code,
            },
        )
        normalized: list[dict[str, Any]] = []
        for item in payload:
            start_date = self._parse_api_date(item.get("startDate") or item.get("date"))
            end_date = self._parse_api_date(item.get("endDate") or item.get("date"))
            if start_date is None or end_date is None:
                continue
            normalized.append(
                {
                    "start_date": start_date,
                    "end_date": end_date,
                    "name": self._extract_localized_name(item.get("name"), language_iso_code=language_iso_code)
                    or "Unbenannte Schulferien",
                    "subdivisions": self._extract_subdivision_codes(item.get("subdivisions")),
                    "raw": item,
                }
            )
        return sorted(normalized, key=lambda item: (item["start_date"], item["end_date"], item["name"]))

    def import_public_holidays(
        self,
        *,
        calendar: HolidayCalendar,
        holidays: list[dict[str, Any]],
    ) -> dict[str, int]:
        created = 0
        updated = 0
        unchanged = 0

        for item in holidays:
            holiday_date = item.get("date")
            if not isinstance(holiday_date, date):
                continue

            existing = (
                PublicHoliday.objects.filter(calendar=calendar, date=holiday_date)
                .order_by("pk")
                .first()
            )
            if existing is None:
                created_holiday = PublicHoliday(
                    calendar=calendar,
                    date=holiday_date,
                    name=str(item.get("name") or "Unbenannter Feiertag"),
                    is_half_day=bool(item.get("is_half_day")),
                    is_active=True,
                )
                created_holiday.full_clean()
                created_holiday.save()
                created += 1
                continue

            changed = False
            target_name = str(item.get("name") or existing.name)
            target_half_day = bool(item.get("is_half_day"))
            if existing.name != target_name:
                existing.name = target_name
                changed = True
            if existing.is_half_day != target_half_day:
                existing.is_half_day = target_half_day
                changed = True
            if not existing.is_active:
                existing.is_active = True
                changed = True

            if changed:
                existing.full_clean()
                existing.save()
                updated += 1
            else:
                unchanged += 1

        return {
            "created": created,
            "updated": updated,
            "unchanged": unchanged,
        }

    def import_school_holidays(
        self,
        *,
        calendar: HolidayCalendar,
        holidays: list[dict[str, Any]],
    ) -> dict[str, int]:
        created = 0
        updated = 0
        unchanged = 0

        for item in holidays:
            start_date = item.get("start_date")
            end_date = item.get("end_date")
            if not isinstance(start_date, date) or not isinstance(end_date, date):
                continue

            target_name = str(item.get("name") or "Unbenannte Schulferien")
            target_subdivisions = str(item.get("subdivisions") or "").strip()
            existing = (
                SchoolHoliday.objects.filter(
                    calendar=calendar,
                    name=target_name,
                    start_date=start_date,
                    end_date=end_date,
                )
                .order_by("pk")
                .first()
            )
            if existing is None:
                school_holiday = SchoolHoliday(
                    calendar=calendar,
                    name=target_name,
                    start_date=start_date,
                    end_date=end_date,
                    source_subdivisions=target_subdivisions,
                    is_active=True,
                )
                school_holiday.full_clean()
                school_holiday.save()
                created += 1
                continue

            changed = False
            if existing.source_subdivisions != target_subdivisions:
                existing.source_subdivisions = target_subdivisions
                changed = True
            if not existing.is_active:
                existing.is_active = True
                changed = True

            if changed:
                existing.full_clean()
                existing.save()
                updated += 1
            else:
                unchanged += 1

        return {
            "created": created,
            "updated": updated,
            "unchanged": unchanged,
        }
