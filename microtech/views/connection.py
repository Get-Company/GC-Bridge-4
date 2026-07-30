from __future__ import annotations

import json

from django import forms
from django.conf import settings
from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied
from django.template.response import TemplateResponse
from django.utils.translation import gettext_lazy as _
from django.views.decorators.http import require_http_methods

from microtech.services import GraphQLMicrotechTimeout, MicrotechGraphQLClientService


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
    timeout = _admin_poll_timeout()
    can_manage_worker = _has_microtech_maintenance_permission(request)

    if request.method == "POST":
        action = str(request.POST.get("action") or "").strip()
        if action in {"stop_worker", "start_worker"}:
            if not can_manage_worker:
                raise PermissionDenied
            form = MicrotechMandantSwitchForm()
            try:
                client = MicrotechGraphQLClientService()
                if action == "stop_worker":
                    result = client.stop_microtech_worker()
                    worker = result.get("worker") or {}
                    worker_status_known = True
                    messages.success(request, result.get("message") or _("Microtech-Worker wurde beendet."))
                else:
                    client.start_microtech_worker()
                    result = client.wait_for_microtech_worker_connection(timeout=timeout)
                    worker = result.get("worker") or {}
                    worker_status_known = True
                    messages.success(request, _("Microtech-Worker wurde gestartet und die COM-Verbindung hergestellt."))
            except GraphQLMicrotechTimeout as exc:
                maintenance_error = str(exc)
                messages.error(request, _("Microtech-Worker wurde gestartet, aber die COM-Verbindung ist noch nicht bereit."))
            except Exception as exc:
                maintenance_error = str(exc)
                messages.error(request, _("Microtech-Worker-Aktion fehlgeschlagen."))
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

    if request.method == "POST" and not worker and can_manage_worker:
        try:
            worker = MicrotechGraphQLClientService().microtech_worker_status().get("worker") or {}
            worker_status_known = True
        except Exception as exc:
            maintenance_error = str(exc)

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
            "can_manage_worker": can_manage_worker,
            "form": form,
            "graphql_url": getattr(settings, "MICROTECH_GRAPHQL_URL", ""),
        }
    )
    return TemplateResponse(request, "admin/microtech_connection.html", context)
