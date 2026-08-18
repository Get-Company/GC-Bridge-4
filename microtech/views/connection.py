from __future__ import annotations

import json

from django import forms
from django.conf import settings
from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied
from django.template.response import TemplateResponse
from django.urls import reverse
from django.utils.translation import gettext_lazy as _
from django.views.decorators.http import require_http_methods

from microtech.services import GraphQLMicrotechTimeout, MicrotechGraphQLClientService, MicrotechJobSentinelService
from microtech.services.backup_mode import MicrotechBackupModeService


class MicrotechMandantSwitchForm(forms.Form):
    mandant = forms.CharField(
        label=_("Mandant"),
        max_length=50,
        widget=forms.TextInput(
            attrs={
                "class": "vTextField",
                "placeholder": "58",
                "autocomplete": "off",
            }
        ),
    )

    def clean_mandant(self):
        mandant = str(self.cleaned_data["mandant"] or "").strip()
        if not mandant:
            raise forms.ValidationError(_("Der Mandant darf nicht leer sein."))
        return mandant


def _has_microtech_connection_permission(request) -> bool:
    user = request.user
    return bool(
        getattr(user, "is_superuser", False)
        or user.has_perm("microtech.view_microtechsettings")
    )


def _has_microtech_maintenance_permission(request) -> bool:
    user = request.user
    return bool(
        getattr(user, "is_superuser", False)
        or user.has_perm("microtech.change_microtechsettings")
    )


def _admin_poll_timeout() -> float:
    return float(getattr(settings, "MICROTECH_CONNECTION_ADMIN_POLL_TIMEOUT", 30.0))


def _raw_json(value: dict | None) -> str:
    if not value:
        return "{}"
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True)


# Die Einzelschritte bleiben fuer die Fehlersuche erhalten; im Regelfall wird
# das Backup-Fenster als Ganzes geoeffnet und geschlossen.
MAINTENANCE_ACTIONS = {
    "stop_worker": "stopMicrotechWorker",
    "start_worker": "startMicrotechWorker",
    "enter_backup_mode": "enterMicrotechBackupMode",
    "leave_backup_mode": "leaveMicrotechBackupMode",
}

MAINTENANCE_MESSAGES = {
    "stop_worker": _("Der Worker wird beendet."),
    "start_worker": _("Der Worker wird gestartet."),
    "enter_backup_mode": _(
        "Das Backup-Fenster wird geoeffnet. Warten Sie die Freigabe ab, bevor das Backup startet."
    ),
    "leave_backup_mode": _("Das Backup-Fenster wird geschlossen und microtech wieder verbunden."),
}


@require_http_methods(["GET", "POST"])
def microtech_connection_admin_view(request):
    if not _has_microtech_connection_permission(request):
        raise PermissionDenied

    form = MicrotechMandantSwitchForm(request.POST or None)
    connection: dict | None = None
    worker: dict | None = None
    worker_status_known = False
    error = ""
    maintenance_error = ""
    maintenance_job = None
    maintenance_job_url = ""
    backup_mode: dict | None = None
    backup_mode_known = False
    backup_mode_error = ""
    timeout = _admin_poll_timeout()
    can_manage_worker = _has_microtech_maintenance_permission(request)

    if request.method == "POST":
        action = str(request.POST.get("action") or "").strip()
        if action in MAINTENANCE_ACTIONS:
            if not can_manage_worker:
                raise PermissionDenied
            form = MicrotechMandantSwitchForm()
            try:
                operation = MAINTENANCE_ACTIONS[action]
                maintenance_job = MicrotechJobSentinelService().enqueue_microtech_worker_operation(
                    operation=operation,
                    context={
                        "source": "microtech_connection_admin",
                        "requested_by": str(getattr(request.user, "pk", "") or ""),
                    },
                )
                maintenance_job_url = reverse(
                    "admin:microtech_microtechgraphqljob_change",
                    args=(maintenance_job.pk,),
                )
                messages.success(request, MAINTENANCE_MESSAGES[action])
            except Exception as exc:
                maintenance_error = str(exc)
                messages.error(request, _("Microtech-Wartungsaktion fehlgeschlagen."))
        elif form.is_valid():
            mandant = form.cleaned_data["mandant"]
            try:
                client = MicrotechGraphQLClientService()
                connection = client.switch_microtech_mandant(mandant, timeout=timeout)
                messages.success(request, _("Microtech-Mandant wurde gewechselt."))
                form = MicrotechMandantSwitchForm(initial={"mandant": connection.get("mandant") or mandant})
            except GraphQLMicrotechTimeout as exc:
                error = str(exc)
                messages.error(request, _("Mandantenwechsel laeuft noch oder hat das Zeitlimit erreicht."))
            except Exception as exc:
                error = str(exc)
                messages.error(request, _("Mandantenwechsel fehlgeschlagen."))
    else:
        try:
            client = MicrotechGraphQLClientService()
            connection = client.microtech_connection(timeout=timeout)
            form = MicrotechMandantSwitchForm(initial={"mandant": connection.get("mandant") or ""})
        except GraphQLMicrotechTimeout as exc:
            error = str(exc)
        except Exception as exc:
            error = str(exc)

        if can_manage_worker:
            try:
                worker = MicrotechGraphQLClientService().microtech_worker_status().get("worker") or {}
                worker_status_known = True
            except Exception as exc:
                maintenance_error = str(exc)

            try:
                backup_mode = MicrotechGraphQLClientService().microtech_backup_mode()
                backup_mode_known = True
            except Exception as exc:
                # Der lokale Zustand bleibt aussagekraeftig, auch wenn der
                # Wrapper gerade nicht antwortet.
                backup_mode_error = str(exc)

    context = admin.site.each_context(request)
    context.update(
        {
            "title": _("Microtech Verbindung"),
            "connection": connection or {},
            "connection_raw": _raw_json(connection),
            "error": error,
            "worker": worker or {},
            "worker_status_known": worker_status_known,
            "maintenance_error": maintenance_error,
            "maintenance_job": maintenance_job,
            "maintenance_job_url": maintenance_job_url,
            "can_manage_worker": can_manage_worker,
            "backup_mode": backup_mode or {},
            "backup_mode_known": backup_mode_known,
            "backup_mode_error": backup_mode_error,
            "backup_mode_local": MicrotechBackupModeService.load(),
            "form": form,
            "graphql_url": getattr(settings, "MICROTECH_GRAPHQL_URL", ""),
        }
    )
    return TemplateResponse(request, "admin/microtech_connection.html", context)
