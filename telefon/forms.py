from __future__ import annotations

from django import forms
from django.utils.translation import gettext_lazy as _
from unfold.widgets import UnfoldAdminDateWidget


class ZeitsteuerungDateForm(forms.Form):
    date = forms.DateField(
        label=_("Datum"),
        input_formats=["%d.%m.%Y", "%d.%m.%y", "%Y-%m-%d"],
        widget=UnfoldAdminDateWidget,
    )
