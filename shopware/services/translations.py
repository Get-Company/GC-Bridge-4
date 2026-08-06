from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from core.services import BaseService


class ShopwareTranslationService(BaseService):
    """Build native Shopware 6 translation payloads for modeltranslation fields."""

    # django-modeltranslation language code -> the locale configured in Shopware 6.
    # English may have a country suffix (for example en-GB).
    _LANGUAGES_BY_LOCALE = {
        "de_ch": "ch-de",
        "de_it": "it-de",
        "it_it": "it-it",
    }

    @classmethod
    def language_ids_for(cls, service: Any) -> dict[str, list[str]]:
        """Find Shopware language IDs for the Django translation locales."""
        language_ids: dict[str, list[str]] = {}
        page = 1
        limit = 500
        while True:
            response = service.request_post(
                "/search/language",
                payload={
                    "page": page,
                    "limit": limit,
                    "total-count-mode": 1,
                    "associations": {"locale": {}},
                },
            )
            rows = response.get("data") if isinstance(response, dict) else []
            if not isinstance(rows, list):
                raise ValueError("Shopware6 returned an invalid language response.")
            for row in rows:
                language_id = str(cls._entity_value(row, "id") or "").strip()
                language = cls._translation_language_for_locale(cls._language_locale_code(row))
                if language and language_id:
                    language_ids.setdefault(language, []).append(language_id)
            if len(rows) < limit:
                break
            page += 1
        return language_ids

    @staticmethod
    def build_translations(
        *,
        instance: Any,
        field_mapping: Mapping[str, str],
        translation_language_ids: Mapping[str, list[str]] | None,
    ) -> list[dict[str, str]]:
        """Return valid native SW6 translations for an instance.

        Shopware validates a translated entity's name even during an upsert
        that otherwise only changes description, SEO metadata, or a unit.
        Therefore a language entry is omitted until its translated name exists.
        The next sync sends every available field together with that name.
        """
        if not translation_language_ids:
            return []

        translations: list[dict[str, str]] = []
        for language, language_ids in translation_language_ids.items():
            suffix = language.replace("-", "_")
            values = {
                target_field: str(value)
                for source_field, target_field in field_mapping.items()
                if (value := getattr(instance, f"{source_field}_{suffix}", None)) is not None and str(value).strip()
            }
            required_name_field = field_mapping.get("name")
            if not values or (required_name_field and not values.get(required_name_field)):
                continue
            for language_id in language_ids:
                translations.append({"languageId": str(language_id), **values})
        return translations

    @classmethod
    def _translation_language_for_locale(cls, locale_code: object) -> str:
        normalized = str(locale_code or "").strip().lower().replace("-", "_")
        if normalized == "en" or normalized.startswith("en_"):
            return "en"
        return cls._LANGUAGES_BY_LOCALE.get(normalized, "")

    @staticmethod
    def _entity_value(entity: object, field_name: str) -> object:
        if not isinstance(entity, dict):
            return None
        if field_name in entity:
            return entity.get(field_name)
        attributes = entity.get("attributes")
        return attributes.get(field_name) if isinstance(attributes, dict) else None

    @classmethod
    def _language_locale_code(cls, entity: object) -> str:
        locale = cls._entity_value(entity, "locale")
        if isinstance(locale, dict):
            code = cls._entity_value(locale, "code")
            if code:
                return str(code)
        return str(cls._entity_value(entity, "localeCode") or "")
