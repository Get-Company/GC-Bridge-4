Microtech Rulebuilder mit Feldkatalog (Schritt fuer Schritt)
============================================================

Ziel
----

Diese Anleitung beschreibt die komplette Bedienung des Rulebuilders mit Feldkatalog,
inklusive Feld-fuer-Feld-Erklaerung aller neuen Modelle.

Durchgehendes Beispiel (wird in allen Abschnitten verwendet)
-------------------------------------------------------------

Geschaeftsregel:

"Wenn Zahlungsart `PayPal` und Lieferland `AT`, dann setze Zahlungsart-ID `22`,
Zahlungsbedingung `Sofort ohne Abzug` und eine Zahlungs-Zusatzposition mit `2.50`."

Beispiel-Codes, die wir durchgaengig nutzen:

- Operatoren: ``eq``, ``contains``
- Source-Felder: ``payment_method``, ``shipping_country``
- Target-Felder: ``set_payment_type``, ``set_payment_terms``, ``set_fee_enabled``, ``set_fee_value``
- Regelname: ``AT + PayPal``

Voraussetzungen
---------------

1. Migrationen sind eingespielt:
   ``./.venv/bin/python manage.py migrate``
2. Admin ist erreichbar und dein Benutzer darf Modelle im Bereich ``Microtech`` bearbeiten.
3. Die Datei ``FELD_25.LST`` liegt im Projektroot.

Schnellstart
------------

1. Feldkatalog importieren

.. code-block:: bash

   ./.venv/bin/python manage.py microtech_import_dataset_fields --dry-run
   ./.venv/bin/python manage.py microtech_import_dataset_fields

2. Admin-Menue ``Microtech`` verwenden

- Operatoren
- Source Felder
- Target Felder
- Datasets
- Dataset Felder
- Einstellungen (Bestellregeln)

3. Regel mit dem Beispiel anlegen (Details weiter unten in dieser Seite)

Feldreferenz: alle neuen Modelle
--------------------------------

Die folgenden Abschnitte erklaeren jedes Feld mit Zweck und Beispielwert.

1) Microtech Dataset (``MicrotechDatasetCatalog``)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Adminpfad: ``Microtech -> Datasets``

.. list-table::
   :header-rows: 1

   * - Feld
     - Was bedeutet das?
     - Was trage ich ein?
     - Beispiel
   * - ``is_active``
     - Aktiviert/deaktiviert das Dataset im Katalog.
     - ``Ja`` fuer nutzbare Datasets.
     - ``Ja``
   * - ``priority``
     - Sortierung im Admin (kleiner = weiter oben).
     - Fuer wichtige Datasets niedrige Werte.
     - ``10`` fuer ``Vorgang``
   * - ``code``
     - Technischer eindeutiger Schluessel (intern, API-sicher).
     - Klein, eindeutig, stabil, mit ``_`` statt Leerzeichen.
     - ``vorgang_vorgange``
   * - ``name``
     - Dataset-Name aus Microtech.
     - Originalname aus der Liste.
     - ``Vorgang``
   * - ``description``
     - Menschlich lesbare Bezeichnung/Variante.
     - Originalbezeichnung aus der Liste.
     - ``Vorgange``
   * - ``source_identifier``
     - Eindeutige Quelle aus ``FELD_25.LST``.
     - Kombination aus Name und Beschreibung.
     - ``Vorgang - Vorgange``
   * - ``created_at`` / ``updated_at``
     - Zeitstempel (automatisch).
     - Nicht manuell pflegen.
     - Automatisch

Wichtig zu ``priority`` und ``code``
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

- ``priority`` ist nur Sortierung, keine Regel-Logik.
- ``code`` sollte nach dem ersten produktiven Einsatz nicht mehr geaendert werden.

2) Microtech Dataset Feld (``MicrotechDatasetField``)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Adminpfad: ``Microtech -> Dataset Felder``

.. list-table::
   :header-rows: 1

   * - Feld
     - Was bedeutet das?
     - Was trage ich ein?
     - Beispiel
   * - ``is_active``
     - Feld im Katalog sichtbar/nutzbar.
     - ``Ja`` fuer verwendete Felder.
     - ``Ja``
   * - ``priority``
     - Sortierung innerhalb des Datasets.
     - Niedrig fuer haeufige Felder.
     - ``10``
   * - ``dataset``
     - Zugehoeriges Dataset.
     - Passendes Dataset waehlen.
     - ``Vorgang - Vorgange``
   * - ``field_name``
     - Technischer Feldname aus Microtech.
     - Genau wie in ``FELD_25.LST``.
     - ``BelegNr``
   * - ``label``
     - Lesbare Feldbezeichnung.
     - Text aus Liste oder sprechend erweitern.
     - ``Belegnummer``
   * - ``field_type``
     - Microtech-Feldtyp.
     - Aus ``FELD_25.LST`` uebernehmen.
     - ``UnicodeString``
   * - ``is_calc_field``
     - Kennzeichnet berechnete Felder (``*`` in Liste).
     - Wird beim Import gesetzt.
     - ``Nein``
   * - ``can_access``
     - Laut Feldliste direkt lesbar.
     - Wird beim Import gesetzt.
     - ``Ja``
   * - ``created_at`` / ``updated_at``
     - Zeitstempel (automatisch).
     - Nicht manuell pflegen.
     - Automatisch

3) Rulebuilder Operator (``MicrotechOrderRuleOperator``)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Adminpfad: ``Microtech -> Operatoren``

.. list-table::
   :header-rows: 1

   * - Feld
     - Was bedeutet das?
     - Was trage ich ein?
     - Beispiel
   * - ``is_active``
     - Nur aktive Operatoren sind verwendbar.
     - ``Ja`` fuer freigegebene Operatoren.
     - ``Ja``
   * - ``priority``
     - Sortierung im Dropdown.
     - ``10`` fuer haeufige Operatoren.
     - ``10`` fuer ``eq``
   * - ``code``
     - Technischer Schluessel, auf den Source-Felder verweisen.
     - Kurz, eindeutig, stabil.
     - ``contains``
   * - ``name``
     - Anzeige im UI.
     - Benutzerfreundlich benennen.
     - ``enthaelt``
   * - ``engine_operator``
     - Interne Evaluationslogik.
     - Einer aus ``eq``, ``contains``, ``gt``, ``lt``.
     - ``contains``
   * - ``hint``
     - Admin-Hinweis zur Nutzung.
     - Optional, aber sinnvoll.
     - ``Nur fuer Textfelder``
   * - ``created_at`` / ``updated_at``
     - Zeitstempel (automatisch).
     - Nicht manuell pflegen.
     - Automatisch

Praxis fuer ``code``
^^^^^^^^^^^^^^^^^^^^

- ``code`` ist der Referenzwert in Source-Feldern.
- Wenn du ``code`` aenderst, koennen bestehende Source-Zuordnungen brechen.
- Empfehlung: ``code`` nur einmal sauber festlegen und danach stabil halten.

4) Rulebuilder Source Feld (``MicrotechOrderRuleConditionSource``)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Adminpfad: ``Microtech -> Source Felder``

.. list-table::
   :header-rows: 1

   * - Feld
     - Was bedeutet das?
     - Was trage ich ein?
     - Beispiel
   * - ``is_active``
     - Nur aktive Sources erscheinen in Regel-Bedingungen.
     - ``Ja`` fuer produktive Sources.
     - ``Ja``
   * - ``priority``
     - Reihenfolge im Source-Dropdown.
     - Haeufige Sources niedrig priorisieren.
     - ``10`` fuer ``payment_method``
   * - ``code``
     - Technischer Source-Schluessel, der in Bedingungen gespeichert wird.
     - Kurz, eindeutig, stabil.
     - ``payment_method``
   * - ``name``
     - Anzeige im Dropdown.
     - Klarer Fachbegriff.
     - ``Zahlungsart-Text``
   * - ``engine_source_field``
     - Auf welches Runtime-Kontextfeld ausgewertet wird.
     - Passendes Engine-Feld aus Auswahl.
     - ``payment_method``
   * - ``dataset_field``
     - Optionaler Katalogbezug fuer Dokumentation/Orientierung.
     - Passendes Feld aus Dataset-Feldern waehlen.
     - ``Adressen.Land`` (Beispielhaft)
   * - ``value_type``
     - Validierung fuer ``expected_value``.
     - Passend zum inhaltlichen Typ.
     - ``string`` fuer Zahlungsart
   * - ``operators``
     - Erlaubte Operatoren fuer genau dieses Source-Feld.
     - Mindestens passende Operatoren hinterlegen.
     - ``contains`` und ``eq``
   * - ``hint``
     - Tooltip/Hinweis im Rulebuilder.
     - Kurz erklaeren, was erwartet wird.
     - ``Wert wird klein geschrieben verglichen``
   * - ``example``
     - Beispielwert als Platzhalter.
     - Realistischen Wert eintragen.
     - ``paypal``
   * - ``created_at`` / ``updated_at``
     - Zeitstempel (automatisch).
     - Nicht manuell pflegen.
     - Automatisch

5) Rulebuilder Target Feld (``MicrotechOrderRuleActionTarget``)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Adminpfad: ``Microtech -> Target Felder``

.. list-table::
   :header-rows: 1

   * - Feld
     - Was bedeutet das?
     - Was trage ich ein?
     - Beispiel
   * - ``is_active``
     - Nur aktive Targets erscheinen in Regel-Aktionen.
     - ``Ja`` fuer produktive Targets.
     - ``Ja``
   * - ``priority``
     - Reihenfolge im Target-Dropdown.
     - Wichtige Targets niedrig priorisieren.
     - ``10`` fuer Zahlungsart-ID
   * - ``code``
     - Technischer Target-Schluessel in Aktionen.
     - Kurz, eindeutig, stabil.
     - ``set_payment_type``
   * - ``name``
     - Anzeige im Dropdown.
     - Klarer Fachbegriff.
     - ``Zahlungsart setzen``
   * - ``engine_target_field``
     - Welches Resolver-Zielfeld gesetzt wird.
     - Passendes Engine-Feld waehlen.
     - ``zahlungsart_id``
   * - ``dataset_field``
     - Optionaler Katalogbezug fuer Dokumentation.
     - Passendes Feld aus Dataset-Feldern.
     - ``VorgangArten.ID`` (Beispielhaft)
   * - ``value_type``
     - Validierung fuer ``target_value``.
     - Muss zum Ziel passen.
     - ``int`` fuer IDs
   * - ``enum_values``
     - Nur bei ``value_type = enum`` relevant.
     - Kommagetrennte gueltige Werte.
     - ``auto,firma_or_salutation,salutation_only,static``
   * - ``hint``
     - Tooltip/Hinweis im Rulebuilder.
     - Erwartetes Format erklaeren.
     - ``Positive Ganzzahl, z. B. 22``
   * - ``example``
     - Platzhalter im Eingabefeld.
     - Realistischen Wert eintragen.
     - ``22``
   * - ``created_at`` / ``updated_at``
     - Zeitstempel (automatisch).
     - Nicht manuell pflegen.
     - Automatisch

6) Bestellregel (``MicrotechOrderRule`` inkl. Inlines)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Adminpfad: ``Microtech -> Einstellungen``

Regelkopf
^^^^^^^^^

.. list-table::
   :header-rows: 1

   * - Feld
     - Was bedeutet das?
     - Beispiel
   * - ``name``
     - Anzeigename der Regel.
     - ``AT + PayPal``
   * - ``is_active``
     - Nur aktive Regeln werden ausgewertet.
     - ``Ja``
   * - ``priority``
     - Reihenfolge der Regelauswertung (kleiner zuerst).
     - ``10``
   * - ``condition_logic``
     - Verknuepfung der Bedingungen: ``all`` (UND) oder ``any`` (ODER).
     - ``all``

Bedingungs-Inline (``MicrotechOrderRuleCondition``)
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

.. list-table::
   :header-rows: 1

   * - Feld
     - Was bedeutet das?
     - Beispiel
   * - ``is_active``
     - Nur aktive Bedingungen zaehlen.
     - ``Ja``
   * - ``priority``
     - Reihenfolge innerhalb der Regel.
     - ``10`` fuer Zahlungsart, ``20`` fuer Lieferland
   * - ``source_field``
     - Verweis auf Source-``code``.
     - ``payment_method``
   * - ``operator``
     - Verweis auf Operator-``code``.
     - ``contains``
   * - ``expected_value``
     - Vergleichswert.
     - ``paypal``

Aktions-Inline (``MicrotechOrderRuleAction``)
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

.. list-table::
   :header-rows: 1

   * - Feld
     - Was bedeutet das?
     - Beispiel
   * - ``is_active``
     - Nur aktive Aktionen werden angewendet.
     - ``Ja``
   * - ``priority``
     - Reihenfolge innerhalb der Regel.
     - ``10``, ``20``, ``30``, ``40``
   * - ``target_field``
     - Verweis auf Target-``code``.
     - ``set_payment_type``
   * - ``target_value``
     - Zu setzender Wert.
     - ``22``

Durchgehendes Beispiel: komplette Umsetzung im Admin
----------------------------------------------------

1. Datasets importieren
~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: bash

   ./.venv/bin/python manage.py microtech_import_dataset_fields --dry-run
   ./.venv/bin/python manage.py microtech_import_dataset_fields

2. Operatoren anlegen
~~~~~~~~~~~~~~~~~~~~~

In ``Microtech -> Operatoren``:

- ``eq`` (Engine: ``eq``)
- ``contains`` (Engine: ``contains``)

3. Source Felder anlegen
~~~~~~~~~~~~~~~~~~~~~~~~

In ``Microtech -> Source Felder``:

- ``payment_method``
  - Engine Source: ``payment_method``
  - Value Type: ``string``
  - Operatoren: ``contains``, ``eq``
  - Beispiel: ``paypal``
- ``shipping_country``
  - Engine Source: ``shipping_country_code``
  - Value Type: ``country_code``
  - Operatoren: ``eq``
  - Beispiel: ``AT``

4. Target Felder anlegen
~~~~~~~~~~~~~~~~~~~~~~~~

In ``Microtech -> Target Felder``:

- ``set_payment_type`` -> ``zahlungsart_id`` (``int``), Beispiel ``22``
- ``set_payment_terms`` -> ``zahlungsbedingung`` (``string``), Beispiel ``Sofort ohne Abzug``
- ``set_fee_enabled`` -> ``add_payment_position`` (``bool``), Beispiel ``true``
- ``set_fee_value`` -> ``payment_position_value`` (``decimal``), Beispiel ``2.50``

5. Regel anlegen
~~~~~~~~~~~~~~~~

In ``Microtech -> Einstellungen``:

- Regelkopf:
  - Name: ``AT + PayPal``
  - Aktiv: ``Ja``
  - Prioritaet: ``10``
  - Bedingungslogik: ``UND``
- Bedingungen:
  - ``payment_method`` + ``contains`` + ``paypal``
  - ``shipping_country`` + ``eq`` + ``AT``
- Aktionen:
  - ``set_payment_type`` = ``22``
  - ``set_payment_terms`` = ``Sofort ohne Abzug``
  - ``set_fee_enabled`` = ``true``
  - ``set_fee_value`` = ``2.50``

6. Testen
~~~~~~~~~

.. code-block:: bash

   ./.venv/bin/python manage.py microtech_order_upsert --order-number <DEINE_BESTELLNUMMER>

Erwartete Wirkung:

- ``zahlungsart_id = 22``
- ``zahlungsbedingung = Sofort ohne Abzug``
- ``add_payment_position = true``
- ``payment_position_value = 2.50``

Typische Fehler und Loesungen
-----------------------------

1. Source oder Target wird im Dropdown nicht angeboten

- ``is_active`` ist aus.
- ``code`` ist doppelt oder ungueltig.

2. Operator fehlt trotz vorhandenem Operator-Datensatz

- Der Operator ist im Source-Feld nicht unter ``operators`` zugeordnet.

3. Aktion wird ignoriert

- ``target_value`` passt nicht zu ``value_type`` (z. B. Text statt ``int``).
- Bei ``enum`` ist ``target_value`` nicht in ``enum_values`` enthalten.

4. Katalogfeld fehlt

- Import nicht gelaufen oder falscher ``--dataset`` Filter.

Empfohlener Betrieb
-------------------

1. Erst ``--dry-run``
2. Dann echter Feldimport
3. Operatoren pflegen
4. Source/Target mit klaren ``code``-Konventionen pflegen
5. Regeln mit niedriger Prioritaet testen
6. Erst danach produktiv priorisieren
