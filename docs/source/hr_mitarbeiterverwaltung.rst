HR Mitarbeiterverwaltung
========================

Zielbild
--------

Die HR-App bildet in Django Admin die erste nutzbare Version der Mitarbeiterverwaltung ab.
Der aktuelle Stand deckt folgende Bereiche ab:

- Abteilungen
- Mitarbeiterprofile auf Basis bestehender Django-User
- Arbeitszeitmodelle und Mitarbeiter-Zuweisungen
- Urlaubsantraege
- Krankmeldungen
- Zeitkonto-Buchungen
- Monatsuebersichten
- Feiertage und Betriebsurlaub
- Admin-Kalender fuer Abwesenheiten und Zeitkonto

Die Umsetzung ist bewusst ``Admin-first``.
Es gibt noch kein eigenes Mitarbeiterportal.


Aktueller Funktionsumfang
-------------------------

Bereits umgesetzt
^^^^^^^^^^^^^^^^^

- HR-Modelle inkl. Migrationen in ``hr``
- rollenbasierte Sichtbarkeit im Admin
- Freigabe-Logik fuer Urlaub und Zeitkonto ueber Services
- Konfliktpruefung fuer Urlaub gegen Krankheit und Betriebsurlaub
- Kalenderansicht im Admin unter ``/admin/hr/calendar/``
- Feiertage und Betriebsurlaub in Sollzeit und Monatsberechnung
- Bootstrap-Commands fuer Gruppen und Grundkonfiguration

Noch bewusst nicht enthalten
^^^^^^^^^^^^^^^^^^^^^^^^^^^^

- eigenes Self-Service-Portal
- E-Mail-Benachrichtigungen
- Resturlaub / Jahresurlaubskonto
- komplexe Genehmigungsworkflows
- automatische Behandlung ``Krank waehrend Urlaub`` ueber Warnlogik hinaus


Produktiver Start auf dem Server
--------------------------------

Voraussetzungen
^^^^^^^^^^^^^^^

- aktueller Code ist deployed
- ``.env`` ist korrekt
- Datenbank ist erreichbar
- Django-Migrationen koennen auf dem Server ausgefuehrt werden
- mindestens ein Admin-User existiert

Empfohlene Reihenfolge
^^^^^^^^^^^^^^^^^^^^^^

1. Migrationen ausfuehren
2. HR-Gruppen und Berechtigungen anlegen
3. HR-Grundkonfiguration anlegen
4. User Gruppen zuweisen
5. Mitarbeiterprofile pruefen
6. Arbeitszeitmodelle, Feiertage und Betriebsurlaub pflegen
7. ersten Kalendereintrag und ersten Urlaubsantrag im Admin testen


Schritt 1: Migrationen
----------------------

Linux:

.. code-block:: bash

   .venv/bin/python manage.py migrate

Windows:

.. code-block:: doscon

   .venv\Scripts\python.exe manage.py migrate


Schritt 2: HR-Gruppen und Permissions anlegen
---------------------------------------------

Nur die Gruppen und deren Django-Model-Permissions:

.. code-block:: bash

   .venv/bin/python manage.py hr_setup_groups

Windows:

.. code-block:: doscon

   .venv\Scripts\python.exe manage.py hr_setup_groups

Der Command ist idempotent und kann mehrfach ausgefuehrt werden.

Angelegte Gruppen:

- ``Mitarbeiter``
- ``Teamleitung``
- ``Abteilungsleitung``
- ``Personalverwaltung``
- ``Geschaeftsfuehrung``


Schritt 3: HR-Grundkonfiguration anlegen
----------------------------------------

Minimaler Setup-Lauf ohne Demo-User:

.. code-block:: bash

   .venv/bin/python manage.py hr_bootstrap

Dieser Lauf legt idempotent an:

- Abteilung ``Allgemein``
- Feiertagskalender ``Deutschland``
- Arbeitszeitmodell ``Vollzeit 40h``

Wenn direkt ein Demo- oder Pilot-Mitarbeiter angelegt werden soll:

.. code-block:: bash

   .venv/bin/python manage.py hr_bootstrap \
     --demo-username demo.hr \
     --create-demo-user \
     --demo-password 'BitteAendern123!' \
     --with-sample-records

Windows:

.. code-block:: doscon

   .venv\Scripts\python.exe manage.py hr_bootstrap --demo-username demo.hr --create-demo-user --demo-password BitteAendern123! --with-sample-records

Wirkung des Demo-Laufs:

- User wird bei Bedarf erzeugt
- User wird ``is_staff = True`` gesetzt
- User wird automatisch der Gruppe ``Mitarbeiter`` zugeordnet
- Mitarbeiterprofil wird angelegt
- Feiertagskalender und Abteilung werden zugewiesen
- Arbeitszeitmodell wird zugewiesen
- Beispiel-Urlaub, Beispiel-Krankmeldung, Beispiel-Zeitkonto und Monatsuebersicht werden erzeugt


Schritt 4: Benutzer und Gruppen zuweisen
----------------------------------------

Die eigentliche Sichtbarkeit im Admin entsteht aus:

- Django-User
- Gruppenmitgliedschaft
- Mitarbeiterprofil
- Abteilungszuordnung im Mitarbeiterprofil

Empfohlene Zuordnung
^^^^^^^^^^^^^^^^^^^^

``Mitarbeiter``

- soll eigene Daten sehen
- soll eigene Urlaubsantraege anlegen koennen
- soll Kalender sehen koennen

``Teamleitung`` / ``Abteilungsleitung``

- sieht Mitarbeiter der eigenen Abteilung
- kann Urlaubsantraege in der eigenen Abteilung sehen und bearbeiten
- sieht den Kalender der eigenen Abteilung

``Personalverwaltung``

- verwaltet Stammdaten
- sieht Krankmeldungen
- pflegt Feiertage und Betriebsurlaub
- verwaltet Monatsuebersichten, Zeitkonto und Arbeitszeitmodelle

``Geschaeftsfuehrung``

- hat denselben weiten Zugriff wie Personalverwaltung

Wichtiger Punkt
^^^^^^^^^^^^^^^

Abteilungsbezogene Sicht funktioniert nur, wenn:

- der User ein ``EmployeeProfile`` hat
- dort eine ``department`` gesetzt ist

Ohne Mitarbeiterprofil bleibt die HR-Sicht fuer Nicht-Superuser leer oder stark eingeschraenkt.


Schritt 5: Stammdaten im Admin pruefen
--------------------------------------

Danach im Admin pruefen:

- ``Mitarbeiter -> Profile``
- ``Mitarbeiter -> Urlaubsantraege``
- ``Mitarbeiter -> Krankmeldungen``
- ``Mitarbeiter -> Zeitkonto``
- ``Mitarbeiter -> Monatsuebersichten``
- ``Mitarbeiter -> Feiertage``
- ``Mitarbeiter -> Betriebsurlaub``
- ``Mitarbeiter -> Kalender``

Zusatzpruefung fuer neue Mitarbeiter:

1. User existiert und ist ``is_staff``
2. User hat mindestens eine HR-Gruppe
3. ``EmployeeProfile`` ist vorhanden
4. ``department`` ist gesetzt
5. ``holiday_calendar`` ist gesetzt oder Default-Kalender greift
6. ``EmployeeWorkSchedule`` ist vorhanden


Schritt 6: Erstkonfiguration fuer echte Nutzung
-----------------------------------------------

Empfohlene manuelle Pflege nach dem Bootstrap:

1. reale Abteilungen anlegen
2. Mitarbeiterprofilen die richtige Abteilung zuweisen
3. Arbeitszeitmodelle anpassen
4. Feiertage fuer das relevante Jahr pflegen
5. Betriebsurlaub pflegen
6. Pilot-Usern Gruppen zuweisen

Feiertage
^^^^^^^^^

``Mitarbeiter -> Feiertage`` enthaelt kalenderbezogene Feiertage.
Wenn mehrere Regionen benoetigt werden, zuerst mehrere Feiertagskalender anlegen und dann den Mitarbeiterprofilen zuordnen.

Betriebsurlaub
^^^^^^^^^^^^^^

``Mitarbeiter -> Betriebsurlaub`` gilt global.

Feld ``counts_as_vacation``:

- ``Nein``: blockiert ueberschneidenden Urlaub/Krankheit, zaehlt aber nicht als Urlaub
- ``Ja``: fliesst zusaetzlich in Urlaubsminuten der Monatsuebersicht ein


Typische Startbefehle fuer den Betrieb
--------------------------------------

Nur Gruppen nachziehen:

.. code-block:: bash

   .venv/bin/python manage.py hr_setup_groups

Nur Grundkonfiguration nachziehen:

.. code-block:: bash

   .venv/bin/python manage.py hr_bootstrap

Pilot-Benutzer mit Beispieldaten anlegen:

.. code-block:: bash

   .venv/bin/python manage.py hr_bootstrap --demo-username max.muster --create-demo-user --demo-password 'BitteAendern123!' --with-sample-records


Fachlogik im aktuellen Stand
----------------------------

Sichtbarkeit
^^^^^^^^^^^^

- Superuser sieht alles
- ``Personalverwaltung`` und ``Geschaeftsfuehrung`` sehen alles
- ``Teamleitung`` und ``Abteilungsleitung`` sehen nur die eigene Abteilung
- normale ``Mitarbeiter`` sehen nur ihr eigenes Profil und ihre eigenen Daten

Urlaub
^^^^^^

- Freigabe laeuft ueber Service-Logik
- Konflikte gegen freigegebenen Urlaub werden geprueft
- Konflikte gegen Krankmeldungen werden geprueft
- Konflikte gegen Betriebsurlaub werden geprueft
- halbe Urlaubstage sind im Modell vorbereitet

Krankheit
^^^^^^^^^

- Krankmeldungen werden separat gefuehrt
- fuer nicht privilegierte Rollen wird im Kalender datensparsam ``Abwesend`` statt ``Krank`` angezeigt

Zeitkonto
^^^^^^^^^

- Freigaben laufen ueber Service-Logik
- positive und negative Minuten werden in Monatsuebersichten getrennt ausgewiesen

Sollzeit und Monatsuebersicht
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

- Sollzeit kommt aus ``WorkSchedule`` und ``WorkScheduleDay``
- Feiertage und Betriebsurlaub reduzieren die effektive Sollzeit
- Betriebsurlaub mit ``counts_as_vacation = True`` wird zusaetzlich als Urlaub ausgewiesen


Empfohlener Pilotablauf
-----------------------

1. ``hr_setup_groups`` ausfuehren
2. ``hr_bootstrap`` ausfuehren
3. einen realen Pilot-User einer passenden Gruppe zuweisen
4. Mitarbeiterprofil, Abteilung und Arbeitszeitmodell pruefen
5. Feiertage fuer das laufende Jahr pflegen
6. einen Test-Urlaubsantrag anlegen
7. als HR- oder Leitungsrolle freigeben
8. Kalender unter ``/admin/hr/calendar/`` pruefen
9. Monatsuebersicht neu berechnen


Wichtige Einschraenkungen
-------------------------

- kein Resturlaubskonto
- keine automatische Rueckverrechnung von Krankheit waehrend Urlaub
- keine Benachrichtigungen
- kein Mitarbeiterportal ausserhalb des Django-Admins
- halbtaegige Feiertage sind modelliert, aber fachlich noch nicht in der Sollzeitberechnung differenziert


Empfehlung fuer den direkten Start
----------------------------------

Wenn du sofort loslegen willst, ist die kuerzeste produktive Reihenfolge:

1. ``manage.py migrate``
2. ``manage.py hr_setup_groups``
3. ``manage.py hr_bootstrap``
4. reale User den Gruppen zuweisen
5. Mitarbeiterprofile und Abteilungen vervollstaendigen
6. Feiertage pflegen
7. Pilotbetrieb mit 1-2 Mitarbeitern starten
