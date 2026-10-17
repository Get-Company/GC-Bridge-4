from urllib.parse import urlencode

import requests
from django.contrib import messages
from django.http import Http404
from django.shortcuts import redirect
from django.urls import reverse
from django.views.generic import TemplateView

from telefon.forms import FunctionKeyForm
from telefon.function_keys import NfonFunctionKeyService
from telefon.views import TelefonAdminViewMixin


class FunctionKeyView(TelefonAdminViewMixin, TemplateView):
    template_name = "admin/telefon/function_keys.html"
    service_class = NfonFunctionKeyService
    title = "Tastenbelegung"

    def _load(self):
        self.service = self.get_service()
        self.extensions = self.service.list_extensions()
        number = self.request.GET.get("extension", "")
        self.selected = next((e for e in self.extensions if e["number"] == number), None)
        if number and self.selected is None:
            raise Http404("Nebenstelle nicht gefunden.")
        self.keys = self.service.list_keys(number) if self.selected else []
        self.targets = self.service.list_targets(number) if self.selected else []
        self.editing = None
        key = self.request.GET.get("key")
        if key is not None:
            self.editing = next((k for k in self.keys if str(k["key_number"]) == key), None)
            if self.editing is None:
                raise Http404("Tastenbelegung nicht gefunden.")

    def _form(self, data=None):
        used = {key["position"] for key in self.keys}
        position = next((p for p in range(1, 1025) if p not in used), 1)
        initial = self.editing or {"position": position, "type": "SPEEDDIAL"}
        return FunctionKeyForm(data, initial=initial, targets=self.targets, editing=self.editing is not None)

    def get(self, request, *args, **kwargs):
        try:
            self._load()
            self.form = self._form()
        except (requests.RequestException, ValueError, KeyError) as error:
            self.api_error = self._api_error(error)
        return self.render_to_response(self.get_context_data())

    def post(self, request, *args, **kwargs):
        try:
            self._load()
            if not self.selected:
                raise Http404("Bitte zuerst eine Nebenstelle auswählen.")
            action = request.POST.get("action")
            self.form = self._form(request.POST if action == "save" else None)
            if action == "delete" and self.editing:
                self.service.delete_key(self.selected["number"], self.editing["key_number"],
                                        expected=request.POST.get("fingerprint", ""))
                messages.success(request, "Die Tastenbelegung wurde bei NFON entfernt.")
            elif action == "save" and self.form.is_valid():
                self.service.save_key(
                    self.selected["number"], self.form.cleaned_data,
                    existing_number=self.editing["key_number"] if self.editing else None,
                    expected=self.form.cleaned_data["fingerprint"],
                )
                messages.success(request, "Die Tastenbelegung wurde bei NFON gespeichert.")
            elif action not in {"save", "delete"} or action == "delete":
                self.form.add_error(None, "Ungültige Aktion.")
                return self.render_to_response(self.get_context_data(), status=400)
            else:
                return self.render_to_response(self.get_context_data(), status=400)
            return redirect(reverse("admin:telefon_function_keys") + "?" + urlencode({"extension": self.selected["number"]}))
        except (requests.RequestException, ValueError, KeyError) as error:
            if getattr(self, "form", None) is not None and self.form.is_bound:
                self.form.add_error(None, self._api_error(error))
            else:
                self.api_error = self._api_error(error)
            return self.render_to_response(self.get_context_data(), status=400)

    @staticmethod
    def _api_error(error):
        if isinstance(error, KeyError):
            return "Die NFON-Konfiguration oder Antwort ist unvollständig. Bitte die Verbindung prüfen."
        if isinstance(error, requests.RequestException):
            return "NFON ist momentan nicht erreichbar oder hat den Zugriff abgelehnt. Bitte erneut laden."
        return str(error)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update({
            "extensions": getattr(self, "extensions", []),
            "selected": getattr(self, "selected", None),
            "keys": getattr(self, "keys", []),
            "targets": getattr(self, "targets", []),
            "editing": getattr(self, "editing", None),
            "form": getattr(self, "form", None),
            "api_error": getattr(self, "api_error", ""),
            "list_url": reverse("admin:telefon_function_keys"),
        })
        return context
