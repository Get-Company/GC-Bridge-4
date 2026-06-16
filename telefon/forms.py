from __future__ import annotations

from django import forms
from django.utils.translation import gettext_lazy as _
from unfold.widgets import UnfoldAdminSingleDateWidget


class ZeitsteuerungDateForm(forms.Form):
    date = forms.DateField(
        label=_("Datum"),
        widget=UnfoldAdminSingleDateWidget,
    )
