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
        name="microtech.poll_graphql_jobs",
        label="Microtech GraphQL Jobs pruefen",
        description="Fallback-Poller fuer Microtech GraphQL Jobs, falls ein Webhook nicht angekommen ist.",
        fields=(
            TaskField("limit", "Limit", "int", 50),
        ),
    ),
    TaskDefinition(
        name="products.scheduled_product_sync",
        label="Produkt-Sync komplett",
        description=(
            "Microtech -> Django -> Shopware. Bilder werden optional per sicherem "
            "Loeschen-und-Neuhochladen neu aufgebaut."
        ),
        fields=(
            TaskField("include_images", "Bilder nach Shopware neu aufbauen", "bool", True),
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
    TaskDefinition(
        name="emails.queue_due_campaigns_before_send",
        label="E-Mail-Kampagnen vor Sendedatum rendern",
        description=(
            "READY-Kampagnen im Zielzeitfenster suchen und pro aktivem Newsletter-Empfaenger "
            "gerendert in die Warteschlange legen."
        ),
        fields=(
            TaskField("lead_time_hours", "Vorlauf Stunden", "int", 24, "24 = ein Tag vor Sendedatum."),
            TaskField("window_minutes", "Fenster Minuten", "int", 60, "Bei stuendlichem Beat-Lauf 60 verwenden."),
        ),
    ),
    TaskDefinition(
        name="newsletter.shopware_sync_recipients",
        label="Newsletter-Empfaenger importieren",
        description="Newsletter-Empfaenger aus Shopware per api/search/newsletter-recipient nach Django synchronisieren.",
        fields=(
            TaskField("limit", "Limit", "int", "", "Leer lassen fuer alle Empfaenger."),
            TaskField("page_size", "Batch-Groesse", "int", 100),
            TaskField("status", "Status", "text", "", "Optionaler Shopware-Statusfilter."),
            TaskField("email", "E-Mail Suche", "text", "", "Optionaler E-Mail-Suchfilter."),
            TaskField(
                "mark_missing",
                "Fehlende markieren",
                "bool",
                False,
                "Nur bei Vollsync ohne Filter: nicht mehr gefundene Empfaenger lokal markieren.",
            ),
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
