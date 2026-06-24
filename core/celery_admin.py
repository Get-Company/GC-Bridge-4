from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from celery import current_app
from django.conf import settings
from django.contrib import admin
from django.core.exceptions import PermissionDenied
from django.template.response import TemplateResponse


@dataclass(frozen=True, slots=True)
class TaskField:
    name: str
    label: str
    field_type: str = "text"
    default: Any = ""
    help_text: str = ""


@dataclass(frozen=True, slots=True)
class TaskDefinition:
    name: str
    label: str
    description: str
    fields: tuple[TaskField, ...] = ()


CELERY_ADMIN_TASKS: tuple[TaskDefinition, ...] = (
    TaskDefinition(
        name="products.scheduled_product_sync",
        label="Produkt-Sync komplett",
        description="Microtech -> Django, Sonderpreise bereinigen und Django -> Shopware.",
        fields=(
            TaskField("limit", "Limit", "int", "", "Leer lassen fuer alle Produkte."),
            TaskField("exclude_inactive", "Inaktive ausschliessen", "bool", False),
            TaskField("write_base_price_back", "Basispreis nach Microtech schreiben", "bool", False),
        ),
    ),
    TaskDefinition(
        name="products.microtech_sync_products",
        label="Microtech Import",
        description="Produkte aus Microtech per GraphQL nach Django importieren.",
        fields=(
            TaskField("erp_nrs", "ERP-Nummern", "csv", "", "Kommagetrennt, leer wenn Alle aktiv ist."),
            TaskField("sync_all", "Alle Produkte", "bool", True),
            TaskField("include_inactive", "Inaktive einschliessen", "bool", False),
            TaskField("preserve_is_active", "Django Aktiv-Status behalten", "bool", True),
            TaskField("limit", "Limit", "int", ""),
        ),
    ),
    TaskDefinition(
        name="products.shopware_sync_products",
        label="Shopware Export",
        description="Django-Produkte nach Shopware synchronisieren.",
        fields=(
            TaskField("erp_nrs", "ERP-Nummern", "csv", "", "Kommagetrennt, leer wenn Alle aktiv ist."),
            TaskField("sync_all", "Alle Produkte", "bool", True),
            TaskField("limit", "Limit", "int", ""),
            TaskField("batch_size", "Batch-Groesse", "int", 50),
            TaskField("only_with_images", "Nur mit Bildern", "bool", False),
            TaskField("log_images", "Bild-Logs schreiben", "bool", False),
        ),
    ),
    TaskDefinition(
        name="products.shopware_force_product_image_uploads",
        label="Shopware Bilder neu hochladen",
        description="Shopware-Bilder und Zuordnungen in 10er-Batches loeschen, neu hochladen und zuordnen.",
        fields=(
            TaskField("erp_nrs", "ERP-Nummern", "csv", "", "Kommagetrennt, leer wenn Alle aktiv ist."),
            TaskField("limit", "Limit", "int", ""),
            TaskField("batch_size", "Batch-Groesse", "int", 10),
            TaskField("log_images", "Bild-Logs schreiben", "bool", False),
        ),
    ),
    TaskDefinition(
        name="mappei.scrape_daily_prices",
        label="Mappei Preise scrapen",
        description="Mappei-Produktseiten scrapen und geaenderte Preise speichern.",
        fields=(
            TaskField("product", "Artikelnummer", "text", "", "Leer lassen fuer alle Mappei-Produkte."),
            TaskField("limit", "Limit", "int", ""),
            TaskField("log_file", "Log-Datei", "text", ""),
        ),
    ),
    TaskDefinition(
        name="orders.shopware_sync_open_orders",
        label="Offene Bestellungen importieren",
        description="Offene Shopware-Bestellungen nach Django importieren.",
        fields=(
            TaskField("sales_channel_ids", "Sales-Channel IDs", "csv", ""),
            TaskField("limit_orders", "Bestell-Limit", "int", ""),
        ),
    ),
    TaskDefinition(
        name="orders.microtech_order_upsert",
        label="Bestellung nach Microtech",
        description="Eine Django-Bestellung per GraphQL in Microtech anlegen oder aktualisieren.",
        fields=(
            TaskField("order_number", "Bestellnummer", "text", ""),
            TaskField("order_id", "Order ID", "int", ""),
            TaskField("log_file", "Log-Datei", "text", ""),
        ),
    ),
    TaskDefinition(
        name="customer.microtech_customer_upsert",
        label="Kunde nach Microtech",
        description="Einen Django-Kunden per GraphQL in Microtech anlegen oder aktualisieren.",
        fields=(
            TaskField("erp_nr", "ERP Kundennummer", "text", ""),
            TaskField("customer_id", "Customer ID", "int", ""),
        ),
    ),
    TaskDefinition(
        name="customer.microtech_customer_lookup",
        label="Kunde aus Microtech importieren",
        description="Einen Microtech-Kunden per ERP-Kundennummer nach Django synchronisieren.",
        fields=(
            TaskField("erp_nr", "ERP Kundennummer", "text", ""),
        ),
    ),
    TaskDefinition(
        name="hr.sync_holidays",
        label="Ferien & Feiertage synchronisieren",
        description=(
            "Feiertage und Schulferien aus der OpenHolidays-API abrufen und in alle aktiven "
            "Feiertagskalender einpflegen. Ohne Jahresangabe werden aktuelles und naechstes Jahr synchronisiert. "
            "Land, Region und Sprache werden aus dem Feiertagskalender abgeleitet, koennen aber hier ueberschrieben werden."
        ),
        fields=(
            TaskField("years", "Jahre", "csv", "", "Kommagetrennt, z. B. 2026,2027. Leer = nur aktuelles Jahr."),
            TaskField("calendar_id", "Kalender-ID", "int", "", "Leer = alle aktiven Kalender mit Region."),
            TaskField("country_iso_code", "Land (ISO)", "text", "", "z. B. DE. Leer = aus Kalender-Region ableiten."),
            TaskField("subdivision_code", "Region (ISO)", "text", "", "z. B. DE-BY. Leer = aus Kalender-Region ableiten."),
            TaskField("language_iso_code", "Sprache (ISO)", "text", "", "z. B. DE. Leer = DE."),
        ),
    ),
    TaskDefinition(
        name="hr.year_transition",
        label="HR Jahreswechsel",
        description="Urlaubsansprueche fuer das Zieljahr anlegen und Resturlaub uebertragen.",
        fields=(
            TaskField("year", "Zieljahr", "int", "", "Leer = naechstes Jahr."),
            TaskField("max_carryover", "Max. Uebertrag Tage", "float", ""),
            TaskField("dry_run", "Nur Testlauf", "bool", True),
        ),
    ),
    TaskDefinition(
        name="emails.apply_campaign_prices_async",
        label="E-Mail-Kampagne Sonderpreise anwenden",
        description="Sonderpreise einer E-Mail-Kampagne in Microtech und Shopware setzen.",
        fields=(
            TaskField("campaign_pk", "Kampagne ID", "int", ""),
        ),
    ),
)


def _visible_task(task: TaskDefinition) -> dict[str, Any]:
    return {
        "name": task.name,
        "label": task.label,
        "description": task.description,
        "fields": [
            {
                "name": field.name,
                "label": field.label,
                "type": field.field_type,
                "default": field.default,
                "help_text": field.help_text,
            }
            for field in task.fields
        ],
    }


def _task_area(task_name: str) -> str:
    if "." not in task_name:
        return "system"
    return task_name.split(".", 1)[0]


def _registered_task_rows() -> list[dict[str, Any]]:
    configured = {task.name: _visible_task(task) for task in CELERY_ADMIN_TASKS}
    names = {
        str(name)
        for name in current_app.tasks.keys()
        if str(name) and not str(name).startswith("celery.")
    }
    names.update(configured.keys())

    rows: list[dict[str, Any]] = []
    for name in sorted(names):
        definition = configured.get(name)
        rows.append(
            {
                "name": name,
                "label": definition["label"] if definition else name,
                "description": definition["description"] if definition else "",
                "area": _task_area(name),
                "source": "konfiguriert" if definition else "registriert",
                "parameters": ", ".join(field["label"] for field in definition["fields"]) if definition else "",
            }
        )
    return rows


_BEAT_SCHEDULE_LABELS: dict[str, str] = {}

_BEAT_SCHEDULE_ENV_FLAGS: dict[str, str] = {}


def _beat_schedule_rows() -> list[dict[str, str]]:
    configured = getattr(settings, "CELERY_BEAT_SCHEDULE", {})
    rows = []
    for name in sorted(configured.keys()):
        entry = configured.get(name, {})
        env_flag = _BEAT_SCHEDULE_ENV_FLAGS.get(name, "")
        rows.append(
            {
                "name": str(name),
                "label": _BEAT_SCHEDULE_LABELS.get(name, str(name)),
                "task": str(entry.get("task", "")),
                "schedule": str(entry.get("schedule", "")) if entry else "",
                "kwargs": str(entry.get("kwargs", {})) if entry else "",
                "enabled": True,
                "env_flag": env_flag,
            }
        )
    return rows


def _masked_url(raw_url: str) -> str:
    if not raw_url:
        return ""
    try:
        parts = urlsplit(raw_url)
    except ValueError:
        return raw_url
    if not parts.password:
        return raw_url
    username = parts.username or ""
    hostname = parts.hostname or ""
    port = f":{parts.port}" if parts.port else ""
    netloc = f"{username}:***@{hostname}{port}" if username else f"***@{hostname}{port}"
    return urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))


def celery_tasks_admin_view(request):
    if not getattr(request.user, "is_superuser", False):
        raise PermissionDenied

    context = admin.site.each_context(request)
    context.update(
        {
            "title": "Task-Uebersicht",
            "tasks": _registered_task_rows(),
            "beat_schedule": _beat_schedule_rows(),
            "broker_url": _masked_url(getattr(settings, "CELERY_BROKER_URL", "")),
        }
    )
    return TemplateResponse(request, "admin/celery_tasks.html", context)
