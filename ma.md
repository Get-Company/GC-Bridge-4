# Mitarbeiterverwaltung im Django-Projekt – Todo-Liste und Umsetzungsplan

## Ziel des Moduls

Es soll ein eigenes Django-Modul für die Mitarbeiterverwaltung entstehen. Das Modul soll folgende Kernbereiche abdecken:

- Mitarbeiter als Django-User anlegen und im Admin verwalten
- Mitarbeiterprofile mit zusätzlichen Feldern wie Abteilung, Kürzel, Farbe und Urlaubstage erweitern
- Login in den Django Admin ermöglichen
- Arbeitszeitmodelle mit Kernarbeitszeiten definieren
- Monatliche Sollarbeitszeit automatisch berechnen
- Arbeitszeiten nicht per Stempeluhr erfassen, sondern Abweichungen als Korrekturen buchen
- Überstunden und Minusstunden verwalten
- Krankheitstage erfassen
- Urlaubsanträge erstellen, prüfen und freigeben
- Kalenderansichten für Tag, Monat und Jahr bereitstellen
- Mitarbeiter im Kalender farblich und mit Kürzel darstellen
- Monatsübersichten mit Sollzeit, Urlaub, Krankheit, Überstunden, Minusstunden und Saldo erstellen

---

# Grundsätzliche Architekturentscheidung

## Entscheidung 1: Django User nicht ersetzen

Wenn im bestehenden Projekt bereits Benutzer, Migrationen oder Berechtigungen existieren, soll kein neues CustomUser-Modell eingeführt werden.

Stattdessen wird der bestehende User über ein eigenes Mitarbeiterprofil erweitert.

### Zielstruktur

```text
Django User
└── EmployeeProfile
    ├── Department
    ├── WorkSchedule
    ├── LeaveRequest
    ├── SickLeave
    ├── TimeAccountEntry
    └── MonthlyWorkSummary
```

### Begründung

- Django Admin Login bleibt stabil.
- Bestehende Authentifizierung bleibt erhalten.
- Bestehende User-Migrationen müssen nicht umgebaut werden.
- Mitarbeiterdaten können fachlich sauber getrennt gepflegt werden.
- Das template unfodl admin muss in allen Bereichen eingehalten werden.

---

# Phase 1 – Neue App für Mitarbeiterverwaltung anlegen

## Task 1.1 – App-Namen festlegen

Empfohlener App-Name:

```text
hr
```

Alternative:

```text
employees
```

Empfehlung: `hr`, weil das Modul nicht nur Mitarbeiterprofile enthält, sondern auch Arbeitszeiten, Urlaub, Krankheit, Zeitkonto und Kalender.

## Task 1.2 – Django-App erstellen

```bash
python manage.py startapp hr
```

## Task 1.3 – App in `INSTALLED_APPS` eintragen

Datei:

```text
settings.py
```

Eintrag ergänzen:

```python
INSTALLED_APPS = [
    # ...
    "hr",
]
```

## Task 1.4 – Grundstruktur der App vorbereiten

Empfohlene Struktur:

```text
hr/
├── __init__.py
├── admin.py
├── apps.py
├── models.py
├── urls.py
├── views.py
├── services/
│   ├── __init__.py
│   ├── calendar_service.py
│   ├── working_time_service.py
│   ├── leave_service.py
│   ├── time_account_service.py
│   └── monthly_summary_service.py
├── api/
│   ├── __init__.py
│   ├── serializers.py
│   ├── views.py
│   └── urls.py
└── templates/
    └── admin/
```

Falls noch kein REST-Framework genutzt wird, kann der `api/`-Ordner zunächst entfallen.

---

# Phase 2 – Abteilungen und Mitarbeiterprofile erstellen

## Task 2.1 – Modell `Department` erstellen

Zweck:

- Verwaltung von Abteilungen
- spätere Filterung im Admin
- spätere Filterung im Kalender
- mögliche Genehmigungslogik pro Abteilung

Felder:

| Feld | Typ | Beschreibung |
|---|---|---|
| `name` | CharField | Name der Abteilung |
| `code` | CharField | optionales Kürzel |
| `is_active` | BooleanField | aktive/inaktive Abteilung |

Beispiel:

```python
class Department(models.Model):
    name = models.CharField("Abteilung", max_length=120)
    code = models.CharField("Kürzel", max_length=20, blank=True)
    is_active = models.BooleanField("Aktiv", default=True)

    class Meta:
        verbose_name = "Abteilung"
        verbose_name_plural = "Abteilungen"
        ordering = ["name"]

    def __str__(self):
        return self.name
```

## Task 2.2 – Modell `EmployeeProfile` erstellen

Zweck:

- Erweiterung des Django Users um Mitarbeiterdaten
- Verbindung von Login/User mit HR-Funktionen
- Farbe und Kürzel für Kalenderansicht
- Abteilung und Beschäftigungsstatus pflegen

Felder:

| Feld | Typ | Beschreibung |
|---|---|---|
| `user` | OneToOneField | Verbindung zum Django User |
| `employee_number` | CharField | Personalnummer |
| `department` | ForeignKey | Abteilung |
| `short_code` | CharField | Kürzel für Kalender |
| `color` | CharField | Kalenderfarbe |
| `phone` | CharField | Telefonnummer |
| `is_active_employee` | BooleanField | aktiver Mitarbeiter |
| `vacation_days_per_year` | DecimalField | Urlaubstage pro Jahr |
| `start_date` | DateField | Eintrittsdatum |
| `end_date` | DateField | Austrittsdatum |

Beispiel:

```python
from django.conf import settings
from django.db import models


class EmployeeProfile(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="employee_profile",
        verbose_name="Benutzer",
    )

    employee_number = models.CharField(
        "Personalnummer",
        max_length=50,
        blank=True,
    )

    department = models.ForeignKey(
        "Department",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        verbose_name="Abteilung",
    )

    short_code = models.CharField(
        "Kürzel",
        max_length=10,
        help_text="Wird im Kalender angezeigt, z. B. FB",
    )

    color = models.CharField(
        "Kalenderfarbe",
        max_length=20,
        default="#3788d8",
    )

    phone = models.CharField("Telefon", max_length=50, blank=True)

    is_active_employee = models.BooleanField(
        "Aktiver Mitarbeiter",
        default=True,
    )

    vacation_days_per_year = models.DecimalField(
        "Urlaubstage pro Jahr",
        max_digits=5,
        decimal_places=2,
        default=30,
    )

    start_date = models.DateField("Eintrittsdatum", null=True, blank=True)
    end_date = models.DateField("Austrittsdatum", null=True, blank=True)

    class Meta:
        verbose_name = "Mitarbeiter"
        verbose_name_plural = "Mitarbeiter"
        ordering = ["user__last_name", "user__first_name"]

    def __str__(self):
        return self.user.get_full_name() or self.user.username
```

## Task 2.3 – Admin für Abteilungen erstellen

Datei:

```text
hr/admin.py
```

Anforderungen:

- Suche nach Name und Kürzel
- Filter nach aktiv/inaktiv
- Listenanzeige mit Name, Kürzel, aktiv

Beispiel:

```python
@admin.register(Department)
class DepartmentAdmin(admin.ModelAdmin):
    list_display = ("name", "code", "is_active")
    list_filter = ("is_active",)
    search_fields = ("name", "code")
```

## Task 2.4 – Admin für Mitarbeiterprofil erstellen

Anforderungen:

- User anzeigen
- Name aus User anzeigen
- Abteilung anzeigen
- Kürzel anzeigen
- Farbe anzeigen
- aktiver Mitarbeiter anzeigen
- Suche nach User, Vorname, Nachname, Personalnummer
- Filter nach Abteilung und aktiv/inaktiv

Beispiel:

```python
@admin.register(EmployeeProfile)
class EmployeeProfileAdmin(admin.ModelAdmin):
    list_display = (
        "user",
        "get_full_name",
        "department",
        "short_code",
        "color",
        "is_active_employee",
    )
    list_filter = ("department", "is_active_employee")
    search_fields = (
        "user__username",
        "user__first_name",
        "user__last_name",
        "employee_number",
        "short_code",
    )

    def get_full_name(self, obj):
        return obj.user.get_full_name()

    get_full_name.short_description = "Name"
```

## Task 2.5 – Optional: Mitarbeiterprofil automatisch erzeugen

Wenn ein neuer User angelegt wird, kann automatisch ein Mitarbeiterprofil erstellt werden.

Vorsicht:

- Nicht jeder User muss zwingend Mitarbeiter sein.
- Service-Accounts oder Admin-User können sonst unnötige Profile bekommen.

Empfehlung:

- Kein automatisches Profil für jeden User.
- Stattdessen im Admin bewusst ein Mitarbeiterprofil anlegen.

Alternative später:

- Admin-Action „Mitarbeiterprofil für User erzeugen“
- Signal nur für bestimmte Gruppen

---

# Phase 3 – Admin-Login und Rechtekonzept

## Task 3.1 – User für Admin-Login konfigurieren

Damit sich ein Mitarbeiter im Admin anmelden kann, braucht der User:

```python
is_active = True
is_staff = True
```

Nicht jeder Mitarbeiter muss Superuser sein.

```python
is_superuser = False
```

## Task 3.2 – Gruppen definieren

Empfohlene Gruppen:

```text
Mitarbeiter
Personalverwaltung
Abteilungsleitung
Geschäftsführung
```

## Task 3.3 – Rechte je Gruppe planen

### Gruppe: Mitarbeiter

Darf später:

- eigene Urlaubsanträge sehen
- eigene Urlaubsanträge erstellen
- eigene Zeitkorrekturen beantragen
- eigene Krankheitstage ggf. melden

Darf nicht:

- fremde Mitarbeiterdaten sehen
- fremde Zeitkonten ändern
- Urlaubsanträge freigeben

### Gruppe: Personalverwaltung

Darf:

- Mitarbeiter verwalten
- Abteilungen verwalten
- Arbeitszeitmodelle verwalten
- Krankheitstage eintragen
- Urlaubsanträge freigeben/ablehnen
- Zeitkonto korrigieren
- Monatsübersichten erstellen und abschließen

### Gruppe: Abteilungsleitung

Darf:

- Mitarbeiter der eigenen Abteilung sehen
- Urlaubsanträge der eigenen Abteilung freigeben
- Kalender der eigenen Abteilung sehen

### Gruppe: Geschäftsführung

Darf:

- alles sehen
- alles freigeben
- Monatsübersichten prüfen

## Task 3.4 – Admin Querysets später einschränken

Für normale Mitarbeiter sollten Admin-Querysets später eingeschränkt werden.

Beispielidee:

```python
def get_queryset(self, request):
    qs = super().get_queryset(request)
    if request.user.is_superuser:
        return qs
    return qs.filter(employee__user=request.user)
```

Das sollte aber erst umgesetzt werden, wenn die ersten Modelle stabil sind.

---

# Phase 4 – Arbeitszeitmodelle erstellen

## Task 4.1 – Modell `WorkSchedule` erstellen

Zweck:

- Definition eines Arbeitszeitmodells
- z. B. Vollzeit 40h, Teilzeit 20h, Mo-Do, Minijob usw.

Felder:

| Feld | Typ | Beschreibung |
|---|---|---|
| `name` | CharField | Bezeichnung |
| `description` | TextField | Beschreibung |
| `is_active` | BooleanField | aktiv/inaktiv |

Beispiel:

```python
class WorkSchedule(models.Model):
    name = models.CharField("Bezeichnung", max_length=120)
    description = models.TextField("Beschreibung", blank=True)
    is_active = models.BooleanField("Aktiv", default=True)

    class Meta:
        verbose_name = "Arbeitszeitmodell"
        verbose_name_plural = "Arbeitszeitmodelle"
        ordering = ["name"]

    def __str__(self):
        return self.name
```

## Task 4.2 – Modell `WorkScheduleDay` erstellen

Zweck:

- Definition der Sollarbeitszeit je Wochentag
- Unterstützung fester Arbeitszeiten
- Unterstützung flexibler Sollzeiten

Felder:

| Feld | Typ | Beschreibung |
|---|---|---|
| `schedule` | ForeignKey | Arbeitszeitmodell |
| `weekday` | IntegerField | Wochentag |
| `start_time` | TimeField | Beginn |
| `end_time` | TimeField | Ende |
| `break_minutes` | IntegerField | Pause |
| `target_minutes` | IntegerField | Soll-Arbeitszeit |
| `is_working_day` | BooleanField | Arbeitstag ja/nein |

Beispiel:

```python
class WorkScheduleDay(models.Model):
    WEEKDAY_CHOICES = [
        (0, "Montag"),
        (1, "Dienstag"),
        (2, "Mittwoch"),
        (3, "Donnerstag"),
        (4, "Freitag"),
        (5, "Samstag"),
        (6, "Sonntag"),
    ]

    schedule = models.ForeignKey(
        WorkSchedule,
        on_delete=models.CASCADE,
        related_name="days",
    )

    weekday = models.IntegerField("Wochentag", choices=WEEKDAY_CHOICES)
    start_time = models.TimeField("Beginn", null=True, blank=True)
    end_time = models.TimeField("Ende", null=True, blank=True)
    break_minutes = models.PositiveIntegerField("Pause in Minuten", default=0)
    target_minutes = models.PositiveIntegerField("Soll-Arbeitszeit in Minuten", default=0)
    is_working_day = models.BooleanField("Arbeitstag", default=True)

    class Meta:
        verbose_name = "Arbeitszeit pro Wochentag"
        verbose_name_plural = "Arbeitszeiten pro Wochentag"
        unique_together = ("schedule", "weekday")
        ordering = ["schedule", "weekday"]

    def __str__(self):
        return f"{self.schedule} - {self.get_weekday_display()}"
```

## Task 4.3 – Modell `EmployeeWorkSchedule` erstellen

Zweck:

- Mitarbeiter einem Arbeitszeitmodell zuordnen
- zeitliche Gültigkeit festhalten
- spätere Änderungen historisch korrekt abbilden

Felder:

| Feld | Typ | Beschreibung |
|---|---|---|
| `employee` | ForeignKey | Mitarbeiter |
| `schedule` | ForeignKey | Arbeitszeitmodell |
| `valid_from` | DateField | gültig ab |
| `valid_until` | DateField | gültig bis |

Beispiel:

```python
class EmployeeWorkSchedule(models.Model):
    employee = models.ForeignKey(
        EmployeeProfile,
        on_delete=models.CASCADE,
        related_name="work_schedules",
        verbose_name="Mitarbeiter",
    )

    schedule = models.ForeignKey(
        WorkSchedule,
        on_delete=models.PROTECT,
        verbose_name="Arbeitszeitmodell",
    )

    valid_from = models.DateField("Gültig ab")
    valid_until = models.DateField("Gültig bis", null=True, blank=True)

    class Meta:
        verbose_name = "Mitarbeiter-Arbeitszeitmodell"
        verbose_name_plural = "Mitarbeiter-Arbeitszeitmodelle"
        ordering = ["employee", "-valid_from"]

    def __str__(self):
        return f"{self.employee} - {self.schedule} ab {self.valid_from}"
```

## Task 4.4 – Validierung für überschneidende Arbeitszeitmodelle planen

Ein Mitarbeiter darf nicht zwei gleichzeitig gültige Arbeitszeitmodelle haben.

Prüfung:

- Zeitraum A überschneidet Zeitraum B
- offenes `valid_until = None` beachten

Umsetzung später entweder:

- in `clean()`
- in einem Service
- über Admin-Validierung

---

# Phase 5 – Urlaubsanträge erstellen

## Task 5.1 – Modell `LeaveRequest` erstellen

Zweck:

- Urlaub beantragen
- Urlaub freigeben oder ablehnen
- Überstundenabbau als Abwesenheit beantragen
- Sonderurlaub abbilden

Felder:

| Feld | Typ | Beschreibung |
|---|---|---|
| `employee` | ForeignKey | Mitarbeiter |
| `leave_type` | CharField | Urlaub, Sonderurlaub, Überstundenabbau |
| `start_date` | DateField | Von |
| `end_date` | DateField | Bis |
| `half_day_start` | BooleanField | halber Starttag |
| `half_day_end` | BooleanField | halber Endtag |
| `status` | CharField | beantragt, freigegeben, abgelehnt, storniert |
| `reason` | TextField | Bemerkung |
| `approved_by` | ForeignKey | freigegeben von |
| `approved_at` | DateTimeField | freigegeben am |
| `created_at` | DateTimeField | erstellt am |

Beispiel:

```python
class LeaveRequest(models.Model):
    LEAVE_TYPE_CHOICES = [
        ("vacation", "Urlaub"),
        ("special_leave", "Sonderurlaub"),
        ("overtime_reduction", "Überstundenabbau"),
    ]

    STATUS_CHOICES = [
        ("requested", "Beantragt"),
        ("approved", "Freigegeben"),
        ("rejected", "Abgelehnt"),
        ("cancelled", "Storniert"),
    ]

    employee = models.ForeignKey(
        EmployeeProfile,
        on_delete=models.CASCADE,
        related_name="leave_requests",
        verbose_name="Mitarbeiter",
    )

    leave_type = models.CharField(
        "Art",
        max_length=30,
        choices=LEAVE_TYPE_CHOICES,
        default="vacation",
    )

    start_date = models.DateField("Von")
    end_date = models.DateField("Bis")

    half_day_start = models.BooleanField("Halber Tag am Starttag", default=False)
    half_day_end = models.BooleanField("Halber Tag am Endtag", default=False)

    status = models.CharField(
        "Status",
        max_length=20,
        choices=STATUS_CHOICES,
        default="requested",
    )

    reason = models.TextField("Bemerkung", blank=True)

    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="approved_leave_requests",
        verbose_name="Freigegeben von",
    )

    approved_at = models.DateTimeField("Freigegeben am", null=True, blank=True)
    created_at = models.DateTimeField("Erstellt am", auto_now_add=True)

    class Meta:
        verbose_name = "Urlaubsantrag"
        verbose_name_plural = "Urlaubsanträge"
        ordering = ["-start_date"]

    def __str__(self):
        return f"{self.employee} - {self.get_leave_type_display()} {self.start_date} bis {self.end_date}"
```

## Task 5.2 – Admin für Urlaubsanträge erstellen

Anforderungen:

- Listenanzeige: Mitarbeiter, Art, Zeitraum, Status, freigegeben von
- Filter: Status, Art, Mitarbeiter, Abteilung
- Suche: Mitarbeitername, Benutzername, Kürzel
- Admin-Actions: freigeben, ablehnen, stornieren

## Task 5.3 – Admin-Action „Urlaubsanträge freigeben“ bauen

Logik:

- Nur Anträge mit Status `requested` freigeben
- `status = approved`
- `approved_by = request.user`
- `approved_at = timezone.now()`
- Meldung im Admin anzeigen

Beispiel:

```python
@admin.action(description="Ausgewählte Urlaubsanträge freigeben")
def approve_leave_requests(modeladmin, request, queryset):
    updated = 0
    for leave_request in queryset.filter(status="requested"):
        leave_request.status = "approved"
        leave_request.approved_by = request.user
        leave_request.approved_at = timezone.now()
        leave_request.save()
        updated += 1
    modeladmin.message_user(request, f"{updated} Urlaubsanträge wurden freigegeben.")
```

## Task 5.4 – Überschneidungen prüfen

Vor Freigabe sollte geprüft werden:

- Überschneidet sich der Urlaub mit anderem freigegebenen Urlaub desselben Mitarbeiters?
- Überschneidet sich der Urlaub mit Krankheit?
- Überschneidet sich der Urlaub mit Betriebsurlaub?
- Sind genug Urlaubstage verfügbar?

Diese Logik sollte nicht im Admin direkt stehen, sondern in einem Service:

```text
hr/services/leave_service.py
```

---

# Phase 6 – Krankheitstage erfassen

## Task 6.1 – Modell `SickLeave` erstellen

Zweck:

- Krankheitstage speichern
- im Kalender anzeigen
- Monatsübersicht korrekt berechnen
- keine Diagnose speichern

Wichtiger Hinweis:

Es sollten keine medizinischen Diagnosen gespeichert werden. Für die Verwaltung reicht normalerweise der Zeitraum und die Information, ob ein Attest vorhanden ist.

Felder:

| Feld | Typ | Beschreibung |
|---|---|---|
| `employee` | ForeignKey | Mitarbeiter |
| `start_date` | DateField | Von |
| `end_date` | DateField | Bis |
| `has_certificate` | BooleanField | Attest vorhanden |
| `note` | TextField | interne Bemerkung |
| `created_at` | DateTimeField | erstellt am |

Beispiel:

```python
class SickLeave(models.Model):
    employee = models.ForeignKey(
        EmployeeProfile,
        on_delete=models.CASCADE,
        related_name="sick_leaves",
        verbose_name="Mitarbeiter",
    )

    start_date = models.DateField("Von")
    end_date = models.DateField("Bis")

    has_certificate = models.BooleanField("Attest vorhanden", default=False)
    note = models.TextField("Bemerkung", blank=True)
    created_at = models.DateTimeField("Erstellt am", auto_now_add=True)

    class Meta:
        verbose_name = "Krankheit"
        verbose_name_plural = "Krankheitstage"
        ordering = ["-start_date"]

    def __str__(self):
        return f"{self.employee} krank {self.start_date} bis {self.end_date}"
```

## Task 6.2 – Admin für Krankheitstage erstellen

Anforderungen:

- Listenanzeige: Mitarbeiter, Von, Bis, Attest, Erstellt am
- Filter: Mitarbeiter, Abteilung, Attest vorhanden
- Suche: Mitarbeitername, Benutzername, Kürzel
- Zeitraumfilter über `date_hierarchy = "start_date"`

## Task 6.3 – Überschneidungen prüfen

Später prüfen:

- Krankheit überschneidet sich mit Urlaub
- Krankheit überschneidet sich mit anderer Krankheit
- Krankheit überschneidet sich mit Betriebsurlaub

Entscheidung nötig:

- Darf Krankheit einen bereits genehmigten Urlaub überschreiben?
- Soll Urlaub dann automatisch korrigiert werden?

Für den ersten Stand:

- Überschneidung nur anzeigen/warnen
- keine automatische Änderung

---

# Phase 7 – Zeitkonto, Überstunden und Minusstunden

## Task 7.1 – Modell `TimeAccountEntry` erstellen

Zweck:

- Überstunden erfassen
- Minusstunden erfassen
- frühere Abwesenheit erfassen
- längeres Arbeiten erfassen
- manuelle Korrekturen erfassen
- Überstundenabbau abbilden

Felder:

| Feld | Typ | Beschreibung |
|---|---|---|
| `employee` | ForeignKey | Mitarbeiter |
| `date` | DateField | Datum |
| `entry_type` | CharField | Art der Buchung |
| `minutes` | IntegerField | Plus- oder Minusbetrag |
| `reason` | TextField | Begründung |
| `status` | CharField | beantragt, freigegeben, abgelehnt |
| `approved_by` | ForeignKey | freigegeben von |
| `approved_at` | DateTimeField | freigegeben am |
| `created_at` | DateTimeField | erstellt am |

Beispiel:

```python
class TimeAccountEntry(models.Model):
    ENTRY_TYPE_CHOICES = [
        ("extra_work", "Mehrarbeit / Überstunden"),
        ("minus_time", "Minusstunden"),
        ("correction", "Manuelle Korrektur"),
        ("overtime_reduction", "Überstundenabbau"),
    ]

    STATUS_CHOICES = [
        ("draft", "Entwurf"),
        ("requested", "Beantragt"),
        ("approved", "Freigegeben"),
        ("rejected", "Abgelehnt"),
    ]

    employee = models.ForeignKey(
        EmployeeProfile,
        on_delete=models.CASCADE,
        related_name="time_entries",
        verbose_name="Mitarbeiter",
    )

    date = models.DateField("Datum")

    entry_type = models.CharField(
        "Art",
        max_length=30,
        choices=ENTRY_TYPE_CHOICES,
    )

    minutes = models.IntegerField(
        "Minuten",
        help_text="Plus für Überstunden, Minus für Minusstunden",
    )

    reason = models.TextField("Begründung", blank=True)

    status = models.CharField(
        "Status",
        max_length=20,
        choices=STATUS_CHOICES,
        default="requested",
    )

    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="approved_time_entries",
        verbose_name="Freigegeben von",
    )

    approved_at = models.DateTimeField("Freigegeben am", null=True, blank=True)
    created_at = models.DateTimeField("Erstellt am", auto_now_add=True)

    class Meta:
        verbose_name = "Zeitkonto-Buchung"
        verbose_name_plural = "Zeitkonto-Buchungen"
        ordering = ["-date"]

    def __str__(self):
        return f"{self.employee} {self.date}: {self.minutes} Minuten"
```

## Task 7.2 – Vorzeichenlogik festlegen

Klare Regel:

```text
Positive Minuten = Guthaben / Überstunden
Negative Minuten = Abzug / Minusstunden
```

Beispiele:

| Situation | Minuten |
|---|---:|
| 1 Stunde länger gearbeitet | `+60` |
| 2 Stunden früher gegangen | `-120` |
| halber Tag Überstundenabbau | `-240` |
| manuelle Korrektur zugunsten Mitarbeiter | `+480` |

## Task 7.3 – Admin für Zeitkonto erstellen

Anforderungen:

- Listenanzeige: Mitarbeiter, Datum, Art, Minuten, Status, freigegeben von
- Filter: Status, Art, Mitarbeiter, Abteilung
- Suche: Mitarbeiter, Grund
- Admin-Actions: freigeben, ablehnen

## Task 7.4 – Admin-Action „Zeitbuchungen freigeben“ bauen

Logik:

- Nur Einträge mit Status `requested` freigeben
- `status = approved`
- `approved_by = request.user`
- `approved_at = timezone.now()`

## Task 7.5 – Service für Zeitkonto-Saldo erstellen

Datei:

```text
hr/services/time_account_service.py
```

Funktionen:

```python
def get_time_account_balance(employee, until_date=None):
    pass


def get_month_time_entries(employee, year, month):
    pass


def get_approved_minutes_for_month(employee, year, month):
    pass
```

---

# Phase 8 – Monatsübersicht und Sollzeitberechnung

## Task 8.1 – Modell `MonthlyWorkSummary` erstellen

Zweck:

- Monatliche Zusammenfassung je Mitarbeiter
- Sollzeit speichern
- Urlaub speichern
- Krankheit speichern
- Überstunden speichern
- Minusstunden speichern
- Saldo speichern
- Monat abschließen/einfrieren

Felder:

| Feld | Typ | Beschreibung |
|---|---|---|
| `employee` | ForeignKey | Mitarbeiter |
| `year` | PositiveIntegerField | Jahr |
| `month` | PositiveIntegerField | Monat |
| `target_minutes` | IntegerField | Soll-Minuten |
| `vacation_minutes` | IntegerField | Urlaubs-Minuten |
| `sick_minutes` | IntegerField | Krankheits-Minuten |
| `overtime_minutes` | IntegerField | Überstunden |
| `minus_minutes` | IntegerField | Minusstunden |
| `balance_minutes` | IntegerField | Monats-Saldo |
| `calculated_at` | DateTimeField | berechnet am |
| `locked` | BooleanField | abgeschlossen |

Beispiel:

```python
class MonthlyWorkSummary(models.Model):
    employee = models.ForeignKey(
        EmployeeProfile,
        on_delete=models.CASCADE,
        related_name="monthly_summaries",
        verbose_name="Mitarbeiter",
    )

    year = models.PositiveIntegerField("Jahr")
    month = models.PositiveIntegerField("Monat")

    target_minutes = models.IntegerField("Soll-Minuten", default=0)
    vacation_minutes = models.IntegerField("Urlaubs-Minuten", default=0)
    sick_minutes = models.IntegerField("Krankheits-Minuten", default=0)
    overtime_minutes = models.IntegerField("Überstunden", default=0)
    minus_minutes = models.IntegerField("Minusstunden", default=0)
    balance_minutes = models.IntegerField("Saldo", default=0)

    calculated_at = models.DateTimeField("Berechnet am", auto_now=True)
    locked = models.BooleanField("Abgeschlossen", default=False)

    class Meta:
        unique_together = ("employee", "year", "month")
        verbose_name = "Monatsübersicht Arbeitszeit"
        verbose_name_plural = "Monatsübersichten Arbeitszeit"
        ordering = ["-year", "-month", "employee"]

    def __str__(self):
        return f"{self.employee} - {self.month:02d}/{self.year}"
```

## Task 8.2 – Service für Arbeitstage im Monat erstellen

Datei:

```text
hr/services/working_time_service.py
```

Funktionen:

```python
def get_days_in_month(year, month):
    pass


def get_employee_schedule_for_date(employee, date):
    pass


def get_target_minutes_for_date(employee, date):
    pass


def calculate_month_target_minutes(employee, year, month):
    pass
```

## Task 8.3 – Logik für Sollzeit definieren

Regel:

```text
Für jeden Kalendertag im Monat:
1. gültiges Arbeitszeitmodell des Mitarbeiters suchen
2. Wochentag bestimmen
3. WorkScheduleDay suchen
4. wenn Arbeitstag: target_minutes addieren
5. wenn kein Arbeitstag: 0 Minuten
```

Später ergänzen:

- Feiertage abziehen
- Betriebsurlaub berücksichtigen
- Eintrittsdatum beachten
- Austrittsdatum beachten
- Teilzeitwechsel im Monat beachten

## Task 8.4 – Urlaub und Krankheit in Monatsberechnung berücksichtigen

Für jeden genehmigten Urlaubstag:

- Sollzeit des Tages ermitteln
- bei vollem Tag: volle Sollzeit als Urlaub rechnen
- bei halbem Tag: halbe Sollzeit rechnen

Für Krankheit:

- Sollzeit des Tages ermitteln
- volle Sollzeit als Krankheit rechnen

Wichtig:

Urlaub und Krankheit sind keine Minusstunden.

## Task 8.5 – Zeitkonto in Monatsberechnung berücksichtigen

Nur genehmigte Zeitkonto-Buchungen berücksichtigen.

Regel:

```text
approved TimeAccountEntry im Monat summieren
positive Minuten = overtime_minutes
negative Minuten = minus_minutes
```

## Task 8.6 – Monatszusammenfassung berechnen

Datei:

```text
hr/services/monthly_summary_service.py
```

Funktionen:

```python
def calculate_monthly_summary(employee, year, month, save=False):
    pass


def recalculate_monthly_summary(employee, year, month):
    pass


def lock_monthly_summary(summary):
    pass
```

## Task 8.7 – Abgeschlossene Monate schützen

Wenn `locked = True`, dann dürfen Änderungen an alten Buchungen nicht unbemerkt die Monatswerte verändern.

Mögliche Regeln:

- Änderungen an abgeschlossenen Monaten verbieten
- Änderungen erlauben, aber Warnung anzeigen
- Änderungen als Korrekturbuchung im aktuellen Monat erfassen

Empfehlung:

```text
Abgeschlossene Monate nicht direkt ändern.
Korrekturen als neue Zeitkonto-Buchung im aktuellen Monat erfassen.
```

---

# Phase 9 – Feiertage und Betriebsurlaub vorbereiten

## Task 9.1 – Modell `HolidayCalendar` planen

Zweck:

- Feiertagskalender für Bundesland/Land
- später mehrere Standorte möglich

Felder:

| Feld | Typ | Beschreibung |
|---|---|---|
| `name` | CharField | z. B. Bayern |
| `country` | CharField | z. B. DE |
| `state` | CharField | z. B. BY |

## Task 9.2 – Modell `PublicHoliday` planen

Felder:

| Feld | Typ | Beschreibung |
|---|---|---|
| `calendar` | ForeignKey | Feiertagskalender |
| `date` | DateField | Datum |
| `name` | CharField | Name |
| `reduces_target_time` | BooleanField | reduziert Sollzeit |

## Task 9.3 – Modell `CompanyHoliday` planen

Zweck:

- Betriebsurlaub
- Brückentage
- interne Schließtage

Felder:

| Feld | Typ | Beschreibung |
|---|---|---|
| `name` | CharField | Bezeichnung |
| `start_date` | DateField | Von |
| `end_date` | DateField | Bis |
| `reduces_target_time` | BooleanField | reduziert Sollzeit |
| `counts_as_vacation` | BooleanField | zählt als Urlaub |

Empfehlung:

Diese Modelle erst umsetzen, wenn die Basismodelle laufen.

---

# Phase 10 – Kalender-API erstellen

## Task 10.1 – Kalenderdaten nicht doppelt speichern

Der Kalender soll keine eigene Datenwahrheit haben.

Stattdessen erzeugt ein Service Kalender-Events aus:

- genehmigten Urlaubsanträgen
- Krankheitstagen
- Zeitkonto-Einträgen
- Überstundenabbau
- Feiertagen
- Betriebsurlaub

## Task 10.2 – Service `calendar_service.py` erstellen

Datei:

```text
hr/services/calendar_service.py
```

Funktionen:

```python
def get_calendar_events(start_date, end_date, employees=None):
    pass


def get_leave_events(start_date, end_date, employees=None):
    pass


def get_sick_leave_events(start_date, end_date, employees=None):
    pass


def get_time_account_events(start_date, end_date, employees=None):
    pass
```

## Task 10.3 – Einheitliches Event-Format definieren

Beispiel:

```json
{
  "title": "FB Urlaub",
  "start": "2026-05-12",
  "end": "2026-05-15",
  "color": "#2f80ed",
  "employee": "Florian Buchner",
  "short_code": "FB",
  "type": "vacation"
}
```

## Task 10.4 – Kalender-Endpoint erstellen

Beispiel-URL:

```text
/api/hr/calendar-events/?start=2026-05-01&end=2026-05-31
```

Query-Parameter:

| Parameter | Beschreibung |
|---|---|
| `start` | Startdatum |
| `end` | Enddatum |
| `employee` | optionaler Mitarbeiterfilter |
| `department` | optionale Abteilung |
| `type` | Urlaub, Krankheit, Zeitkonto usw. |

## Task 10.5 – Frontend-Kalender auswählen

Empfehlung:

```text
FullCalendar
```

Benötigte Ansichten:

- Tagesansicht
- Monatsansicht
- Jahresansicht

Hinweis:

FullCalendar bietet Tages- und Monatsansichten direkt. Eine Jahresansicht muss je nach gewünschter Darstellung ggf. angepasst oder mit zusätzlicher Ansicht umgesetzt werden.

## Task 10.6 – Darstellung im Kalender festlegen

Darstellung je Event:

```text
[Kürzel] Art
```

Beispiele:

```text
FB Urlaub
JN Krank
MS +2h
```

Farben:

- Grundfarbe aus Mitarbeiterprofil
- optional andere Darstellung nach Event-Art

Mögliche Lösung:

- Mitarbeiterfarbe als Hintergrund
- Event-Art über Text oder Icon

---

# Phase 11 – Admin-Kalenderansicht einbauen

## Task 11.1 – Eigene Admin-View für Kalender erstellen

Ziel:

Im Django Admin soll eine Kalenderseite erreichbar sein.

Beispielpfad:

```text
/admin/hr/calendar/
```

## Task 11.2 – Template für Kalender erstellen

Datei:

```text
hr/templates/admin/hr/calendar.html
```

Inhalt:

- FullCalendar Container
- JS für Event-Endpoint
- Filter für Abteilung
- Filter für Mitarbeiter
- Filter für Event-Art

## Task 11.3 – Admin-URL erweitern

In `admin.py` kann `get_urls()` verwendet werden, um eigene Admin-URLs zu ergänzen.

## Task 11.4 – Rechte für Kalenderansicht prüfen

Regeln:

- Superuser sieht alles
- Personalverwaltung sieht alles
- Abteilungsleitung sieht eigene Abteilung
- Mitarbeiter sieht nur eigene Events

---

# Phase 12 – Formulare und Self-Service vorbereiten

## Task 12.1 – Entscheidung treffen: Admin-only oder eigenes Mitarbeiterportal

Kurzfristig:

```text
Django Admin reicht für Verwaltung.
```

Mittelfristig besser:

```text
Eigenes kleines Mitarbeiterportal für Anträge.
```

Warum?

- Django Admin ist für Mitarbeiter oft zu technisch.
- Ein Urlaubsantrag sollte einfach sein.
- Mitarbeiter sollen nicht zu viele Admin-Funktionen sehen.

## Task 12.2 – Minimaler Self-Service später

Seiten:

```text
/mein-urlaub/
/mein-zeitkonto/
/meine-antraege/
/urlaub-beantragen/
/zeitkorrektur-beantragen/
```

## Task 12.3 – Mitarbeiter darf nur eigene Daten sehen

In Views immer filtern:

```python
employee = request.user.employee_profile
```

Dann nur dessen Daten anzeigen.

---

# Phase 13 – Validierungen und Geschäftslogik

## Task 13.1 – Datumsvalidierung

Für Urlaub, Krankheit und Zeitkonto:

- Startdatum darf nicht nach Enddatum liegen
- Enddatum darf nicht vor Startdatum liegen
- Monatsangaben müssen gültig sein
- Zeitraum darf optional nicht vor Eintritt liegen
- Zeitraum darf optional nicht nach Austritt liegen

## Task 13.2 – Überschneidungen prüfen

Prüfen bei:

- Urlaub gegen Urlaub
- Urlaub gegen Krankheit
- Krankheit gegen Krankheit
- Krankheit gegen Urlaub
- Zeitkorrekturen mehrfach am selben Tag

## Task 13.3 – Statuswechsel kontrollieren

Erlaubte Statuswechsel für Urlaub:

```text
requested -> approved
requested -> rejected
approved -> cancelled
rejected -> requested optional nicht empfohlen
```

Erlaubte Statuswechsel für Zeitkonto:

```text
draft -> requested
requested -> approved
requested -> rejected
approved -> correction only
```

## Task 13.4 – Direkte Änderungen an genehmigten Daten einschränken

Empfehlung:

- genehmigte Einträge nicht still ändern
- Änderung über Storno/Korrektur abbilden
- abgeschlossene Monate schützen

---

# Phase 14 – Datenbankmigrationen

## Task 14.1 – Migrationen erstellen

```bash
python manage.py makemigrations hr
```

## Task 14.2 – Migrationen prüfen

```bash
python manage.py sqlmigrate hr 0001
```

## Task 14.3 – Migrationen ausführen

```bash
python manage.py migrate
```

## Task 14.4 – Admin prüfen

```bash
python manage.py runserver
```

Dann im Admin prüfen:

```text
/admin/
```

---

# Phase 15 – Erste Testdaten anlegen

## Task 15.1 – Abteilungen anlegen

Beispiele:

```text
Geschäftsführung
Verwaltung
Archiv
Technik
Vertrieb
```

## Task 15.2 – Arbeitszeitmodell Vollzeit anlegen

Beispiel:

```text
Vollzeit 40h
Montag: 08:00–16:30, 30 Minuten Pause, 480 Minuten Sollzeit
Dienstag: 08:00–16:30, 30 Minuten Pause, 480 Minuten Sollzeit
Mittwoch: 08:00–16:30, 30 Minuten Pause, 480 Minuten Sollzeit
Donnerstag: 08:00–16:30, 30 Minuten Pause, 480 Minuten Sollzeit
Freitag: 08:00–16:30, 30 Minuten Pause, 480 Minuten Sollzeit
Samstag: kein Arbeitstag
Sonntag: kein Arbeitstag
```

## Task 15.3 – Mitarbeiterprofil anlegen

Für bestehenden User:

- Personalnummer eintragen
- Abteilung zuweisen
- Kürzel eintragen
- Farbe wählen
- Urlaubstage setzen
- Eintrittsdatum setzen

## Task 15.4 – Arbeitszeitmodell zuweisen

Eintrag in `EmployeeWorkSchedule`:

```text
Mitarbeiter: Beispieluser
Arbeitszeitmodell: Vollzeit 40h
Gültig ab: 2026-01-01
Gültig bis: leer
```

## Task 15.5 – Beispiel-Urlaubsantrag anlegen

```text
Mitarbeiter: Beispieluser
Art: Urlaub
Von: 2026-05-12
Bis: 2026-05-14
Status: Beantragt
```

Dann im Admin freigeben.

## Task 15.6 – Beispiel-Krankheit anlegen

```text
Mitarbeiter: Beispieluser
Von: 2026-05-20
Bis: 2026-05-21
Attest: ja/nein
```

## Task 15.7 – Beispiel-Zeitkonto buchen

```text
Mitarbeiter: Beispieluser
Datum: 2026-05-22
Art: Mehrarbeit / Überstunden
Minuten: 60
Status: Beantragt
```

Dann im Admin freigeben.

---

# Phase 16 – Tests schreiben

## Task 16.1 – Tests für Arbeitszeitberechnung

Testfälle:

- Vollzeitmodell Mo–Fr
- Wochenende ergibt 0 Minuten
- Teilzeitmodell mit freien Tagen
- Mitarbeiter ohne Arbeitszeitmodell
- Arbeitszeitmodell-Wechsel im Monat

## Task 16.2 – Tests für Urlaub

Testfälle:

- Urlaub über einen Tag
- Urlaub über mehrere Tage
- Urlaub mit Wochenende dazwischen
- Urlaub mit halbem Starttag
- Urlaub mit halbem Endtag
- abgelehnter Urlaub zählt nicht
- beantragter Urlaub zählt noch nicht in Monatsübersicht

## Task 16.3 – Tests für Krankheit

Testfälle:

- Krankheit über einen Tag
- Krankheit über mehrere Tage
- Krankheit am Wochenende zählt mit 0 Sollzeit
- Krankheit reduziert nicht das Urlaubskonto

## Task 16.4 – Tests für Zeitkonto

Testfälle:

- genehmigte Überstunde zählt positiv
- genehmigte Minusstunde zählt negativ
- beantragte Buchung zählt nicht
- abgelehnte Buchung zählt nicht

## Task 16.5 – Tests für Monatsübersicht

Testfälle:

- Sollzeit korrekt
- Urlaub korrekt abgezogen/ausgewiesen
- Krankheit korrekt ausgewiesen
- Überstunden korrekt
- Minusstunden korrekt
- Saldo korrekt
- abgeschlossener Monat wird nicht automatisch überschrieben

---

# Phase 17 – Datenschutz und Rechte beachten

## Task 17.1 – Krankheitsdaten sparsam speichern

Nicht speichern:

```text
Diagnosen
medizinische Details
Arztberichte
private Gesundheitsinformationen
```

Speichern reicht:

```text
Zeitraum
Attest vorhanden ja/nein
optionale interne Bemerkung
```

## Task 17.2 – Rechte auf Krankheitstage streng begrenzen

Nur diese Rollen sollten Krankheitstage sehen:

- Personalverwaltung
- Geschäftsführung
- eventuell direkte Leitung, falls rechtlich/organisatorisch gewünscht

Normale Mitarbeiter sollen keine Krankheitstage anderer Mitarbeiter sehen.

## Task 17.3 – Kalenderdarstellung für Krankheit prüfen

Im Kalender sollte eventuell nicht überall „krank“ stehen.

Alternative Anzeige:

```text
abwesend
```

Oder Sicht abhängig von Rolle:

- Personalverwaltung sieht „krank“
- Mitarbeiter sehen nur „abwesend“

---

# Phase 18 – Erweiterungen für später

## Erweiterung 18.1 – Benachrichtigungen

Mögliche Benachrichtigungen:

- Neuer Urlaubsantrag an Personalverwaltung
- Urlaubsantrag freigegeben
- Urlaubsantrag abgelehnt
- Zeitkorrektur beantragt
- Zeitkorrektur freigegeben

Kanäle:

- E-Mail
- interne Benachrichtigung
- Admin-Dashboard

## Erweiterung 18.2 – Dashboard

Mögliche Widgets:

- offene Urlaubsanträge
- offene Zeitkorrekturen
- heutige Abwesenheiten
- aktuelle Krankheitstage
- Zeitkonto-Salden
- Mitarbeiter ohne Arbeitszeitmodell

## Erweiterung 18.3 – Export

Mögliche Exporte:

- Monatsübersicht als CSV
- Zeitkonto je Mitarbeiter als CSV
- Urlaubsliste als CSV
- Jahresübersicht als PDF

## Erweiterung 18.4 – Vertretungen

Urlaubsantrag könnte später ein Feld bekommen:

```text
Vertretung
```

Oder eigenes Modell:

```text
LeaveReplacement
```

## Erweiterung 18.5 – Genehmigungsregeln

Später möglich:

- Abteilungsleitung genehmigt zuerst
- Personalverwaltung finalisiert
- Geschäftsführung ab bestimmter Dauer
- automatische Freigabe bei Sonderfällen

---

# Empfohlene erste Umsetzungsversion

## Version 1 – Minimal nutzbar

Diese Modelle direkt umsetzen:

```text
Department
EmployeeProfile
WorkSchedule
WorkScheduleDay
EmployeeWorkSchedule
LeaveRequest
SickLeave
TimeAccountEntry
MonthlyWorkSummary
```

Diese Funktionen direkt bauen:

```text
Admin für alle Modelle
Urlaubsanträge freigeben/ablehnen
Zeitkonto freigeben/ablehnen
Sollzeit pro Monat berechnen
Monatsübersicht erstellen
Kalender-Event-Service vorbereiten
```

## Noch nicht in Version 1 nötig

```text
Feiertage
Betriebsurlaub
komplexe Genehmigungsworkflows
Self-Service-Portal
E-Mail-Benachrichtigungen
PDF-Export
Jahresurlaubskonto mit Resturlaub
```

Diese Punkte können später ergänzt werden.

---

# Konkrete Reihenfolge für die Umsetzung

## Schritt 1

App `hr` anlegen und in `INSTALLED_APPS` eintragen.

## Schritt 2

Modelle `Department` und `EmployeeProfile` erstellen.

## Schritt 3

Admin für `Department` und `EmployeeProfile` erstellen.

## Schritt 4

Migration erstellen und ausführen.

## Schritt 5

Testuser und Mitarbeiterprofil im Admin anlegen.

## Schritt 6

Admin-Login mit Mitarbeiteruser prüfen.

## Schritt 7

Modelle `WorkSchedule`, `WorkScheduleDay` und `EmployeeWorkSchedule` erstellen.

## Schritt 8

Admin für Arbeitszeitmodelle erstellen, idealerweise mit Inline für Wochentage.

## Schritt 9

Arbeitszeitmodell „Vollzeit 40h“ im Admin anlegen.

## Schritt 10

Arbeitszeitmodell einem Mitarbeiter zuweisen.

## Schritt 11

Service `working_time_service.py` erstellen.

## Schritt 12

Funktion zur Berechnung der Sollzeit eines Tages bauen.

## Schritt 13

Funktion zur Berechnung der Sollzeit eines Monats bauen.

## Schritt 14

Modell `LeaveRequest` erstellen.

## Schritt 15

Admin für Urlaubsanträge erstellen.

## Schritt 16

Admin-Actions für Freigabe und Ablehnung von Urlaubsanträgen bauen.

## Schritt 17

Modell `SickLeave` erstellen.

## Schritt 18

Admin für Krankheitstage erstellen.

## Schritt 19

Modell `TimeAccountEntry` erstellen.

## Schritt 20

Admin für Zeitkonto-Buchungen erstellen.

## Schritt 21

Admin-Actions für Freigabe und Ablehnung von Zeitkonto-Buchungen bauen.

## Schritt 22

Modell `MonthlyWorkSummary` erstellen.

## Schritt 23

Service `monthly_summary_service.py` erstellen.

## Schritt 24

Monatsübersicht aus Sollzeit, Urlaub, Krankheit und Zeitkonto berechnen.

## Schritt 25

Admin für Monatsübersichten erstellen.

## Schritt 26

Admin-Action „Monat neu berechnen“ bauen.

## Schritt 27

Admin-Action „Monat abschließen“ bauen.

## Schritt 28

Service `calendar_service.py` erstellen.

## Schritt 29

Kalender-Events aus Urlaub erzeugen.

## Schritt 30

Kalender-Events aus Krankheit erzeugen.

## Schritt 31

Kalender-Events aus Zeitkonto erzeugen.

## Schritt 32

API-Endpunkt für Kalenderdaten erstellen.

## Schritt 33

FullCalendar oder andere Kalenderansicht einbauen.

## Schritt 34

Tagesansicht prüfen.

## Schritt 35

Monatsansicht prüfen.

## Schritt 36

Jahresansicht planen oder umsetzen.

## Schritt 37

Berechtigungen für Mitarbeiter, Personalverwaltung und Geschäftsführung verfeinern.

## Schritt 38

Tests für Arbeitszeitberechnung schreiben.

## Schritt 39

Tests für Urlaub, Krankheit und Zeitkonto schreiben.

## Schritt 40

Tests für Monatsübersichten schreiben.

---

# Wichtige fachliche Regeln

## Regel 1 – Urlaub ist keine Minusstunde

Urlaub reduziert nicht das Zeitkonto als Minusstunde. Urlaub wird separat als genehmigte Abwesenheit geführt.

## Regel 2 – Krankheit ist keine Minusstunde

Krankheit wird separat geführt und darf nicht als Minusstunde gerechnet werden.

## Regel 3 – Überstunden entstehen nur durch genehmigte Buchungen

Da nicht gestempelt wird, entstehen Überstunden nur durch freigegebene Zeitkonto-Einträge.

## Regel 4 – Sollzeit kommt aus Arbeitszeitmodell

Die Sollarbeitszeit wird aus dem gültigen Arbeitszeitmodell des Mitarbeiters berechnet.

## Regel 5 – Alte Monate sollten eingefroren werden

Wenn ein Monat abgeschlossen ist, sollen spätere Änderungen nicht still alte Werte verändern.

## Regel 6 – Kalender ist nur Darstellung

Die Datenwahrheit liegt in Urlaub, Krankheit, Zeitkonto und Arbeitszeitmodell. Der Kalender zeigt diese Daten nur an.

---

# Offene Entscheidungen vor Produktivbetrieb

## Entscheidung 1 – Krankheit im Kalender sichtbar?

Optionen:

```text
A: Alle sehen „krank“
B: Nur Personalverwaltung sieht „krank“, andere sehen „abwesend“
C: Krankheitstage werden nur intern angezeigt
```

Empfehlung:

```text
B: Rollenabhängige Anzeige
```

## Entscheidung 2 – Dürfen Mitarbeiter in den Django Admin?

Optionen:

```text
A: Ja, aber stark eingeschränkt
B: Nein, Mitarbeiter erhalten eigenes Portal
```

Empfehlung kurzfristig:

```text
A: Admin eingeschränkt verwenden
```

Empfehlung langfristig:

```text
B: eigenes kleines Mitarbeiterportal
```

## Entscheidung 3 – Was passiert bei Krankheit während Urlaub?

Optionen:

```text
A: Nur Warnung anzeigen
B: Urlaub automatisch stornieren
C: Urlaubstage automatisch wieder gutschreiben
```

Empfehlung für Version 1:

```text
A: Nur Warnung anzeigen
```

## Entscheidung 4 – Werden Feiertage sofort benötigt?

Empfehlung:

```text
Für saubere Monats-Sollzeit ja, aber für Version 1 kann es zunächst manuell oder später ergänzt werden.
```

## Entscheidung 5 – Sollen halbe Urlaubstage erlaubt sein?

Im Modell bereits vorbereitet.

Empfehlung:

```text
Ja, halbe Tage vorbereiten.
```

---

# Ergebnis nach Umsetzung der ersten Version

Nach Version 1 kann das System:

- Mitarbeiter im Django Admin verwalten
- Mitarbeiter mit Django User verbinden
- Mitarbeiter im Admin einloggen lassen
- Abteilungen pflegen
- Mitarbeiter mit Kürzel und Farbe versehen
- Arbeitszeitmodelle definieren
- Kernarbeitszeiten je Wochentag festlegen
- Sollarbeitszeit pro Monat berechnen
- Urlaub beantragen und freigeben
- Krankheitstage erfassen
- Überstunden und Minusstunden buchen
- Zeitkonto-Buchungen freigeben
- Monatsübersichten berechnen
- Kalenderdaten für Urlaub, Krankheit und Zeitkonto erzeugen

---

# Kurzfazit

Das Modul sollte nicht nur als Erweiterung des Django Users gebaut werden, sondern als eigenständige HR-App mit klar getrennten Bereichen:

```text
Mitarbeiterprofil
Arbeitszeitmodell
Abwesenheiten
Zeitkonto
Monatsübersicht
Kalenderdarstellung
```

Die wichtigste fachliche Leitlinie lautet:

```text
Sollzeit automatisch berechnen.
Abweichungen separat buchen.
Urlaub und Krankheit separat führen.
Monatsstände einfrieren.
Kalender nur als Darstellung verwenden.
```
