from __future__ import annotations

from django.contrib import messages
from django.shortcuts import redirect
from django.urls import reverse
from django.views.generic import TemplateView

from telefon.forms import ZeitsteuerungDateForm
from telefon.services import NfonTimeControlService


class TelefonAdminViewMixin:
    admin_site = None
    service_class = NfonTimeControlService
    subtitle = "NFON Service Portal"
    title = ""

    def __init__(self, *args, admin_site=None, **kwargs):
        self.admin_site = admin_site
        super().__init__(*args, **kwargs)

    def get_service(self) -> NfonTimeControlService:
        return self.service_class()

    def get_context_data(self, **kwargs):
        self.request.current_app = self.admin_site.name
        context = super().get_context_data(**kwargs)
        context.update(
            {
                **self.admin_site.each_context(self.request),
                "title": self.get_title(),
                "subtitle": self.subtitle,
            }
        )
        return context

    def get_title(self) -> str:
        return self.title


class ZeitsteuerungListView(TelefonAdminViewMixin, TemplateView):
    template_name = "admin/telefon/zeitsteuerung_list.html"
    title = "Zeitsteuerungen"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        services = []
        try:
            services = [
                {
                    **service,
                    "url": reverse("admin:telefon_zeitsteuerung_detail", args=[service["id"]]),
                }
                for service in self.get_service().list_time_controls()
            ]
        except Exception as error:
            messages.error(self.request, f"NFON API Fehler: {error}")

        context["services"] = services
        return context


class ZeitsteuerungDetailView(TelefonAdminViewMixin, TemplateView):
    template_name = "admin/telefon/zeitsteuerung_detail.html"
    title = "Zeitsteuerung"
    subtitle = "Zeitsteuerung"

    def get_title(self) -> str:
        return getattr(self, "display_name", self.title)

    def post(self, request, service_id: str):
        action = request.POST.get("action")
        try:
            service = self.get_service()
            if action == "add":
                form = ZeitsteuerungDateForm(request.POST)
                if form.is_valid():
                    result = service.add_denied_date(service_id, form.cleaned_data["date"])
                    self._message_success(result)
                else:
                    messages.error(request, "Bitte ein gueltiges Datum auswaehlen.")
            elif action == "delete":
                result = service.delete_denied_date(service_id, request.POST.get("date", "").strip())
                self._message_success(result)
            else:
                messages.warning(request, "Unbekannte Aktion.")
        except ValueError as error:
            messages.warning(request, str(error))
        except Exception as error:
            messages.error(request, f"Fehler: {error}")

        return redirect("admin:telefon_zeitsteuerung_detail", service_id)

    def get_context_data(self, service_id: str, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(
            {
                "service_id": service_id,
                "display_name": service_id,
                "denied_dates": [],
                "allowed_dates": [],
                "form": ZeitsteuerungDateForm(),
                "list_url": reverse("admin:telefon_zeitsteuerung_list"),
            }
        )

        try:
            service_data = self.get_service().get_time_control_dates(service_id)
            self.display_name = service_data["display_name"]
            context.update(service_data)
            context["title"] = self.display_name
        except Exception as error:
            messages.error(self.request, f"NFON API Fehler: {error}")

        return context

    def _message_success(self, result: dict):
        messages.success(
            self.request,
            (
                f"PUT {result['status_code']}. Gesendet: {result['sent_denied']} | "
                f"Antwort referralDenied: {result['response_denied']}"
            ),
        )
