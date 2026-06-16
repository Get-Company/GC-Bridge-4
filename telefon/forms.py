from __future__ import annotations

from django import forms
from django.utils.translation import gettext_lazy as _


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
