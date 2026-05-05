from __future__ import annotations

from datetime import date
from decimal import Decimal
import re

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q
from django.utils.translation import gettext_lazy as _

from core.models import BaseModel

HEX_COLOR_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")


class Department(BaseModel):
    name = models.CharField(max_length=120, verbose_name=_("Abteilung"))
    code = models.CharField(max_length=20, blank=True, default="", verbose_name=_("Kuerzel"))
    is_active = models.BooleanField(default=True, verbose_name=_("Aktiv"))

    class Meta:
        verbose_name = _("Abteilung")
        verbose_name_plural = _("Abteilungen")
        ordering = ("name",)

    def __str__(self) -> str:
        return self.name


class HolidayCalendar(BaseModel):
    name = models.CharField(max_length=120, verbose_name=_("Bezeichnung"))
    region_code = models.CharField(max_length=30, blank=True, default="", verbose_name=_("Region"))
    is_active = models.BooleanField(default=True, verbose_name=_("Aktiv"))
    is_default = models.BooleanField(default=False, verbose_name=_("Standardkalender"))

    class Meta:
        verbose_name = _("Feiertagskalender")
        verbose_name_plural = _("Feiertagskalender")
        ordering = ("name",)

    def clean(self) -> None:
        if self.is_default:
            existing_default = type(self).objects.filter(is_default=True).exclude(pk=self.pk).exists()
            if existing_default:
                raise ValidationError({"is_default": _("Es darf nur einen Standardkalender geben.")})

    def __str__(self) -> str:
        return self.name


class EmployeeProfile(BaseModel):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="employee_profile",
        verbose_name=_("Benutzer"),
    )
    employee_number = models.CharField(
        max_length=50,
        blank=True,
        default="",
        verbose_name=_("Personalnummer"),
    )
    department = models.ForeignKey(
        Department,
        on_delete=models.SET_NULL,
        related_name="employees",
        null=True,
        blank=True,
        verbose_name=_("Abteilung"),
    )
    holiday_calendar = models.ForeignKey(
        HolidayCalendar,
        on_delete=models.SET_NULL,
        related_name="employees",
        null=True,
        blank=True,
        verbose_name=_("Feiertagskalender"),
    )
    short_code = models.CharField(max_length=10, verbose_name=_("Kuerzel"))
    color = models.CharField(max_length=20, default="#3788d8", verbose_name=_("Kalenderfarbe"))
    phone = models.CharField(max_length=50, blank=True, default="", verbose_name=_("Telefon"))
    is_active_employee = models.BooleanField(default=True, verbose_name=_("Aktiver Mitarbeiter"))
    vacation_days_per_year = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal("30.00"),
        verbose_name=_("Urlaubstage pro Jahr"),
    )
    start_date = models.DateField(null=True, blank=True, verbose_name=_("Eintrittsdatum"))
    end_date = models.DateField(null=True, blank=True, verbose_name=_("Austrittsdatum"))

    class Meta:
        verbose_name = _("Mitarbeiter")
        verbose_name_plural = _("Mitarbeiter")
        ordering = ("user__last_name", "user__first_name", "user__username")

    def clean(self) -> None:
        errors: dict[str, str] = {}
        if self.start_date and self.end_date and self.end_date < self.start_date:
            errors["end_date"] = _("Das Austrittsdatum darf nicht vor dem Eintrittsdatum liegen.")
        color = (self.color or "").strip()
        if color and not HEX_COLOR_RE.match(color):
            errors["color"] = _("Bitte eine gueltige Hex-Farbe wie #3788d8 angeben.")
        if errors:
            raise ValidationError(errors)

    @property
    def full_name(self) -> str:
        return self.user.get_full_name() or self.user.username

    def __str__(self) -> str:
        return self.full_name


class PublicHoliday(BaseModel):
    calendar = models.ForeignKey(
        HolidayCalendar,
        on_delete=models.CASCADE,
        related_name="public_holidays",
        verbose_name=_("Feiertagskalender"),
    )
    name = models.CharField(max_length=120, verbose_name=_("Feiertag"))
    date = models.DateField(verbose_name=_("Datum"))
    is_half_day = models.BooleanField(default=False, verbose_name=_("Halber Tag"))
    is_active = models.BooleanField(default=True, verbose_name=_("Aktiv"))

    class Meta:
        verbose_name = _("Feiertag")
        verbose_name_plural = _("Feiertage")
        ordering = ("date", "name")
        constraints = [
            models.UniqueConstraint(fields=("calendar", "date"), name="unique_public_holiday_per_calendar"),
        ]

    def __str__(self) -> str:
        return f"{self.name} ({self.date})"


class CompanyHoliday(BaseModel):
    name = models.CharField(max_length=120, verbose_name=_("Bezeichnung"))
    start_date = models.DateField(verbose_name=_("Von"))
    end_date = models.DateField(verbose_name=_("Bis"))
    counts_as_vacation = models.BooleanField(default=False, verbose_name=_("Zaehlt als Urlaub"))
    is_active = models.BooleanField(default=True, verbose_name=_("Aktiv"))
    note = models.TextField(blank=True, default="", verbose_name=_("Bemerkung"))

    class Meta:
        verbose_name = _("Betriebsurlaub")
        verbose_name_plural = _("Betriebsurlaube")
        ordering = ("-start_date", "-id")

    def clean(self) -> None:
        errors: dict[str, str] = {}
        if self.end_date < self.start_date:
            errors["end_date"] = _("Bis darf nicht vor Von liegen.")
        overlaps = (
            type(self).objects.filter(is_active=True, start_date__lte=self.end_date, end_date__gte=self.start_date)
            .exclude(pk=self.pk)
            .exists()
        )
        if overlaps:
            errors["start_date"] = _("Dieser Betriebsurlaub ueberschneidet sich mit einem bestehenden Eintrag.")
        if errors:
            raise ValidationError(errors)

    def __str__(self) -> str:
        return f"{self.name} ({self.start_date} bis {self.end_date})"


class WorkSchedule(BaseModel):
    name = models.CharField(max_length=120, verbose_name=_("Bezeichnung"))
    description = models.TextField(blank=True, default="", verbose_name=_("Beschreibung"))
    is_active = models.BooleanField(default=True, verbose_name=_("Aktiv"))

    class Meta:
        verbose_name = _("Arbeitszeitmodell")
        verbose_name_plural = _("Arbeitszeitmodelle")
        ordering = ("name",)

    def __str__(self) -> str:
        return self.name


class WorkScheduleDay(BaseModel):
    class Weekday(models.IntegerChoices):
        MONDAY = 0, _("Montag")
        TUESDAY = 1, _("Dienstag")
        WEDNESDAY = 2, _("Mittwoch")
        THURSDAY = 3, _("Donnerstag")
        FRIDAY = 4, _("Freitag")
        SATURDAY = 5, _("Samstag")
        SUNDAY = 6, _("Sonntag")

    schedule = models.ForeignKey(
        WorkSchedule,
        on_delete=models.CASCADE,
        related_name="days",
        verbose_name=_("Arbeitszeitmodell"),
    )
    weekday = models.IntegerField(choices=Weekday.choices, verbose_name=_("Wochentag"))
    start_time = models.TimeField(null=True, blank=True, verbose_name=_("Beginn"))
    end_time = models.TimeField(null=True, blank=True, verbose_name=_("Ende"))
    break_minutes = models.PositiveIntegerField(default=0, verbose_name=_("Pause in Minuten"))
    target_minutes = models.PositiveIntegerField(default=0, verbose_name=_("Soll-Arbeitszeit in Minuten"))
    is_working_day = models.BooleanField(default=True, verbose_name=_("Arbeitstag"))

    class Meta:
        verbose_name = _("Arbeitszeit pro Wochentag")
        verbose_name_plural = _("Arbeitszeiten pro Wochentag")
        ordering = ("schedule", "weekday")
        constraints = [
            models.UniqueConstraint(fields=("schedule", "weekday"), name="unique_work_schedule_weekday"),
            models.CheckConstraint(
                condition=Q(weekday__gte=0) & Q(weekday__lte=6),
                name="work_schedule_weekday_range",
            ),
        ]

    def clean(self) -> None:
        errors: dict[str, str] = {}
        if self.is_working_day:
            if self.target_minutes <= 0:
                errors["target_minutes"] = _("Ein Arbeitstag braucht eine positive Soll-Arbeitszeit.")
            if bool(self.start_time) != bool(self.end_time):
                errors["end_time"] = _("Beginn und Ende muessen zusammen gepflegt werden.")
            elif self.start_time and self.end_time and self.end_time <= self.start_time:
                errors["end_time"] = _("Das Ende muss nach dem Beginn liegen.")
        else:
            if self.target_minutes != 0:
                errors["target_minutes"] = _("An freien Tagen muss die Soll-Arbeitszeit 0 sein.")
            if self.break_minutes != 0:
                errors["break_minutes"] = _("An freien Tagen darf keine Pause gesetzt sein.")
            if self.start_time or self.end_time:
                errors["start_time"] = _("An freien Tagen duerfen keine Zeiten gesetzt sein.")
        if errors:
            raise ValidationError(errors)

    def __str__(self) -> str:
        return f"{self.schedule} - {self.get_weekday_display()}"


class EmployeeWorkSchedule(BaseModel):
    employee = models.ForeignKey(
        EmployeeProfile,
        on_delete=models.CASCADE,
        related_name="work_schedule_assignments",
        verbose_name=_("Mitarbeiter"),
    )
    schedule = models.ForeignKey(
        WorkSchedule,
        on_delete=models.PROTECT,
        related_name="employee_assignments",
        verbose_name=_("Arbeitszeitmodell"),
    )
    valid_from = models.DateField(verbose_name=_("Gueltig ab"))
    valid_until = models.DateField(null=True, blank=True, verbose_name=_("Gueltig bis"))

    class Meta:
        verbose_name = _("Mitarbeiter-Arbeitszeitmodell")
        verbose_name_plural = _("Mitarbeiter-Arbeitszeitmodelle")
        ordering = ("employee", "-valid_from", "-id")

    def clean(self) -> None:
        errors: dict[str, str] = {}
        if self.valid_until and self.valid_until < self.valid_from:
            errors["valid_until"] = _("Gueltig bis darf nicht vor Gueltig ab liegen.")
        if self.employee_id:
            candidate_end = self.valid_until or date.max
            overlaps = (
                type(self).objects.filter(employee=self.employee)
                .exclude(pk=self.pk)
                .order_by("valid_from", "pk")
            )
            for assignment in overlaps:
                other_end = assignment.valid_until or date.max
                if assignment.valid_from <= candidate_end and other_end >= self.valid_from:
                    errors["valid_from"] = _(
                        "Dieses Arbeitszeitmodell ueberschneidet sich mit einer bestehenden Zuweisung."
                    )
                    break
        if errors:
            raise ValidationError(errors)

    def __str__(self) -> str:
        return f"{self.employee} - {self.schedule} ab {self.valid_from}"


class LeaveRequest(BaseModel):
    class LeaveType(models.TextChoices):
        VACATION = "vacation", _("Urlaub")
        SPECIAL_LEAVE = "special_leave", _("Sonderurlaub")
        OVERTIME_REDUCTION = "overtime_reduction", _("Ueberstundenabbau")

    class Status(models.TextChoices):
        REQUESTED = "requested", _("Beantragt")
        APPROVED = "approved", _("Freigegeben")
        REJECTED = "rejected", _("Abgelehnt")
        CANCELLED = "cancelled", _("Storniert")

    employee = models.ForeignKey(
        EmployeeProfile,
        on_delete=models.CASCADE,
        related_name="leave_requests",
        verbose_name=_("Mitarbeiter"),
    )
    leave_type = models.CharField(
        max_length=30,
        choices=LeaveType.choices,
        default=LeaveType.VACATION,
        verbose_name=_("Art"),
    )
    start_date = models.DateField(verbose_name=_("Von"))
    end_date = models.DateField(verbose_name=_("Bis"))
    half_day_start = models.BooleanField(default=False, verbose_name=_("Halber Tag am Starttag"))
    half_day_end = models.BooleanField(default=False, verbose_name=_("Halber Tag am Endtag"))
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.REQUESTED,
        verbose_name=_("Status"),
    )
    reason = models.TextField(blank=True, default="", verbose_name=_("Bemerkung"))
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="approved_leave_requests",
        null=True,
        blank=True,
        verbose_name=_("Freigegeben von"),
    )
    approved_at = models.DateTimeField(null=True, blank=True, verbose_name=_("Freigegeben am"))

    class Meta:
        verbose_name = _("Urlaubsantrag")
        verbose_name_plural = _("Urlaubsantraege")
        ordering = ("-start_date", "-id")

    def clean(self) -> None:
        errors: dict[str, str] = {}
        if self.end_date < self.start_date:
            errors["end_date"] = _("Bis darf nicht vor Von liegen.")
        if self.start_date == self.end_date and self.half_day_start and self.half_day_end:
            errors["half_day_end"] = _("Bei einem eintaeigen Antrag kann nicht beides gleichzeitig halbtags sein.")
        if self.status == self.Status.APPROVED and self.employee_id:
            from hr.services.leave_service import LeaveService

            try:
                LeaveService().validate_leave_request_conflicts(self)
            except ValidationError as exc:
                errors.update(exc.message_dict)
        if errors:
            raise ValidationError(errors)

    def __str__(self) -> str:
        return f"{self.employee} - {self.get_leave_type_display()} {self.start_date} bis {self.end_date}"


class SickLeave(BaseModel):
    employee = models.ForeignKey(
        EmployeeProfile,
        on_delete=models.CASCADE,
        related_name="sick_leaves",
        verbose_name=_("Mitarbeiter"),
    )
    start_date = models.DateField(verbose_name=_("Von"))
    end_date = models.DateField(verbose_name=_("Bis"))
    has_certificate = models.BooleanField(default=False, verbose_name=_("Attest vorhanden"))
    note = models.TextField(blank=True, default="", verbose_name=_("Bemerkung"))

    class Meta:
        verbose_name = _("Krankheit")
        verbose_name_plural = _("Krankheitstage")
        ordering = ("-start_date", "-id")

    def clean(self) -> None:
        errors: dict[str, str] = {}
        if self.end_date < self.start_date:
            errors["end_date"] = _("Bis darf nicht vor Von liegen.")
        if self.employee_id and self.start_date and self.end_date:
            from hr.services.sick_leave_service import SickLeaveService

            try:
                SickLeaveService().validate_sick_leave(self)
            except ValidationError as exc:
                errors.update(exc.message_dict)
        if errors:
            raise ValidationError(errors)

    def __str__(self) -> str:
        return f"{self.employee} krank {self.start_date} bis {self.end_date}"


class TimeAccountEntry(BaseModel):
    class EntryType(models.TextChoices):
        EXTRA_WORK = "extra_work", _("Mehrarbeit / Ueberstunden")
        MINUS_TIME = "minus_time", _("Minusstunden")
        CORRECTION = "correction", _("Manuelle Korrektur")
        OVERTIME_REDUCTION = "overtime_reduction", _("Ueberstundenabbau")

    class Status(models.TextChoices):
        DRAFT = "draft", _("Entwurf")
        REQUESTED = "requested", _("Beantragt")
        APPROVED = "approved", _("Freigegeben")
        REJECTED = "rejected", _("Abgelehnt")

    employee = models.ForeignKey(
        EmployeeProfile,
        on_delete=models.CASCADE,
        related_name="time_account_entries",
        verbose_name=_("Mitarbeiter"),
    )
    date = models.DateField(verbose_name=_("Datum"))
    entry_type = models.CharField(max_length=30, choices=EntryType.choices, verbose_name=_("Art"))
    minutes = models.IntegerField(
        verbose_name=_("Minuten"),
        help_text=_("Plus fuer Ueberstunden, Minus fuer Minusstunden."),
    )
    reason = models.TextField(blank=True, default="", verbose_name=_("Begruendung"))
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.REQUESTED,
        verbose_name=_("Status"),
    )
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="approved_time_account_entries",
        null=True,
        blank=True,
        verbose_name=_("Freigegeben von"),
    )
    approved_at = models.DateTimeField(null=True, blank=True, verbose_name=_("Freigegeben am"))

    class Meta:
        verbose_name = _("Zeitkonto-Buchung")
        verbose_name_plural = _("Zeitkonto-Buchungen")
        ordering = ("-date", "-id")

    def clean(self) -> None:
        errors: dict[str, str] = {}
        if self.minutes == 0:
            errors["minutes"] = _("Die Minuten duerfen nicht 0 sein.")
        if self.entry_type == self.EntryType.EXTRA_WORK and self.minutes <= 0:
            errors["minutes"] = _("Mehrarbeit muss als positive Minuten gebucht werden.")
        if self.entry_type in {self.EntryType.MINUS_TIME, self.EntryType.OVERTIME_REDUCTION} and self.minutes >= 0:
            errors["minutes"] = _("Diese Buchungsart muss als negative Minuten gebucht werden.")
        if errors:
            raise ValidationError(errors)

    def __str__(self) -> str:
        return f"{self.employee} {self.date}: {self.minutes} Minuten"


class MonthlyWorkSummary(BaseModel):
    employee = models.ForeignKey(
        EmployeeProfile,
        on_delete=models.CASCADE,
        related_name="monthly_summaries",
        verbose_name=_("Mitarbeiter"),
    )
    year = models.PositiveIntegerField(verbose_name=_("Jahr"))
    month = models.PositiveIntegerField(verbose_name=_("Monat"))
    target_minutes = models.IntegerField(default=0, verbose_name=_("Soll-Minuten"))
    vacation_minutes = models.IntegerField(default=0, verbose_name=_("Urlaubs-Minuten"))
    sick_minutes = models.IntegerField(default=0, verbose_name=_("Krankheits-Minuten"))
    overtime_minutes = models.IntegerField(default=0, verbose_name=_("Ueberstunden"))
    minus_minutes = models.IntegerField(default=0, verbose_name=_("Minusstunden"))
    balance_minutes = models.IntegerField(default=0, verbose_name=_("Saldo"))
    calculated_at = models.DateTimeField(null=True, blank=True, verbose_name=_("Berechnet am"))
    locked = models.BooleanField(default=False, verbose_name=_("Abgeschlossen"))

    class Meta:
        verbose_name = _("Monatsuebersicht Arbeitszeit")
        verbose_name_plural = _("Monatsuebersichten Arbeitszeit")
        ordering = ("-year", "-month", "employee")
        constraints = [
            models.UniqueConstraint(fields=("employee", "year", "month"), name="unique_monthly_work_summary"),
            models.CheckConstraint(condition=Q(month__gte=1) & Q(month__lte=12), name="monthly_summary_month_range"),
        ]

    def clean(self) -> None:
        errors: dict[str, str] = {}
        if self.month < 1 or self.month > 12:
            errors["month"] = _("Der Monat muss zwischen 1 und 12 liegen.")
        if errors:
            raise ValidationError(errors)

    def __str__(self) -> str:
        return f"{self.employee} - {self.month:02d}/{self.year}"
