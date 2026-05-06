from __future__ import annotations

from datetime import date

from django import forms
from django.utils.translation import gettext_lazy as _

from unfold.widgets import (
    UnfoldAdminColorInputWidget,
    UnfoldAdminIntegerFieldWidget,
    UnfoldAdminSingleDateWidget,
    UnfoldAdminSelectWidget,
    UnfoldAdminTextInputWidget,
    UnfoldAdminTimeWidget,
)

from hr.models import EmployeeProfile, HolidayCalendar, WorkScheduleDay
from hr.services import OpenHolidaysService


class OpenHolidaysImportForm(forms.Form):
    calendar = forms.ModelChoiceField(
        label=_("Feiertagskalender"),
        queryset=HolidayCalendar.objects.none(),
        widget=UnfoldAdminSelectWidget,
    )
    year = forms.IntegerField(
        label=_("Jahr"),
        min_value=2000,
        max_value=2100,
        widget=UnfoldAdminIntegerFieldWidget,
    )
    country_iso_code = forms.CharField(
        label=_("Land"),
        max_length=10,
        widget=UnfoldAdminTextInputWidget,
    )
    subdivision_code = forms.CharField(
        label=_("Region"),
        max_length=30,
        widget=UnfoldAdminTextInputWidget,
    )
    language_iso_code = forms.CharField(
        label=_("Sprache"),
        max_length=10,
        widget=UnfoldAdminTextInputWidget,
    )

    def __init__(self, *args, **kwargs):
        calendar_queryset = kwargs.pop("calendar_queryset", HolidayCalendar.objects.none())
        super().__init__(*args, **kwargs)
        self.fields["calendar"].queryset = calendar_queryset

    @classmethod
    def build_initial(cls) -> dict[str, object]:
        service = OpenHolidaysService()
        default_calendar = (
            HolidayCalendar.objects.filter(is_default=True).order_by("name", "pk").first()
            or HolidayCalendar.objects.order_by("name", "pk").first()
        )
        return {
            "calendar": default_calendar.pk if default_calendar is not None else None,
            "year": date.today().year,
            "country_iso_code": service.DEFAULT_COUNTRY_ISO_CODE,
            "subdivision_code": service.DEFAULT_SUBDIVISION_CODE,
            "language_iso_code": service.DEFAULT_LANGUAGE_ISO_CODE,
        }


class EmployeeProfileAdminForm(forms.ModelForm):
    class Meta:
        model = EmployeeProfile
        fields = "__all__"
        widgets = {
            "color": UnfoldAdminColorInputWidget(),
        }


class WorkScheduleDayInlineForm(forms.ModelForm):
    class Meta:
        model = WorkScheduleDay
        fields = "__all__"
        widgets = {
            "start_time": UnfoldAdminTimeWidget(),
            "end_time": UnfoldAdminTimeWidget(),
        }

    class Media:
        js = ("core/admin/hr_work_schedule_time_fields.js",)


class EmployeeWorkingTimeOverviewForm(forms.Form):
    start_date = forms.DateField(
        label=_("Von"),
        widget=UnfoldAdminSingleDateWidget,
    )
    end_date = forms.DateField(
        label=_("Bis"),
        widget=UnfoldAdminSingleDateWidget,
    )

    def clean(self):
        cleaned_data = super().clean()
        start_date = cleaned_data.get("start_date")
        end_date = cleaned_data.get("end_date")
        if start_date and end_date and end_date < start_date:
            raise forms.ValidationError(_("Bis darf nicht vor Von liegen."))
        return cleaned_data

    @classmethod
    def build_initial(cls) -> dict[str, object]:
        today = date.today()
        return {
            "start_date": today.replace(day=1),
            "end_date": today,
        }
