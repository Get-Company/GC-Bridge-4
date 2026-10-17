from __future__ import annotations

from django import forms
from django.utils.translation import gettext_lazy as _
from unfold.widgets import UnfoldAdminIntegerFieldWidget, UnfoldAdminSelectWidget, UnfoldAdminTextInputWidget

from telefon.function_keys import KEY_TYPES


class UnfoldNativeDateInput(forms.DateInput):
    input_type = "date"

    def __init__(self, attrs: dict[str, str] | None = None, format: str | None = None) -> None:
        classes = [
            "border",
            "border-base-200",
            "bg-white",
            "font-medium",
            "min-w-52",
            "placeholder-base-400",
            "px-3",
            "py-2",
            "rounded-default",
            "shadow-xs",
            "text-font-default-light",
            "text-sm",
            "w-full",
            "focus:outline-2",
            "focus:-outline-offset-2",
            "focus:outline-primary-600",
            "dark:bg-base-900",
            "dark:border-base-700",
            "dark:text-font-default-dark",
            "dark:scheme-dark",
        ]
        attrs = attrs or {}
        attrs["class"] = " ".join([*classes, attrs.get("class", "")])
        super().__init__(attrs=attrs, format=format or "%Y-%m-%d")


class ZeitsteuerungDateForm(forms.Form):
    date = forms.DateField(
        label=_("Datum"),
        input_formats=["%Y-%m-%d", "%d.%m.%Y", "%d.%m.%y"],
        widget=UnfoldNativeDateInput,
    )


class FunctionKeyForm(forms.Form):
    position = forms.IntegerField(
        label="Tastenposition", min_value=1, max_value=1024,
        widget=UnfoldAdminIntegerFieldWidget,
        help_text="Die sichtbare Anordnung hängt vom Telefonmodell ab.",
    )
    type = forms.ChoiceField(label="Belegung", choices=KEY_TYPES, widget=UnfoldAdminSelectWidget)
    display_name = forms.CharField(label="Beschriftung", max_length=100, required=False,
                                   widget=UnfoldAdminTextInputWidget)
    phone_number = forms.CharField(label="Externe Rufnummer", max_length=99, required=False,
                                   widget=UnfoldAdminTextInputWidget(attrs={"placeholder": "+49 …"}))
    target = forms.ChoiceField(label="Nebenstelle / Dienst", required=False,
                               widget=UnfoldAdminSelectWidget)
    function_code = forms.CharField(label="Funktionscode", max_length=99, required=False,
                                    widget=UnfoldAdminTextInputWidget(attrs={"placeholder": "z. B. *3"}))
    fingerprint = forms.CharField(required=False, widget=forms.HiddenInput)

    def __init__(self, *args, targets=(), editing=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["target"].choices = [("", "Bitte auswählen …"),
            ("Nebenstellen", [(t["href"], t["label"]) for t in targets if t["kind"] == "MONITOR"]),
            ("Dienste", [(t["href"], t["label"]) for t in targets if t["kind"] == "SERVICE"]),
        ]
        self.fields["position"].disabled = editing
        # Only the selected type's fields participate in validation, even without JavaScript.
        kind = self.data.get("type") if self.is_bound else self.initial.get("type", "SPEEDDIAL")
        if kind not in {"MONITOR", "INTERCOM", "SERVICE"}:
            self.fields["target"].disabled = True
        else:
            self.fields["target"].required = True
        self.fields["phone_number"].required = kind == "SPEEDDIAL"
        self.fields["function_code"].required = kind == "FUNCTION_CODE"
