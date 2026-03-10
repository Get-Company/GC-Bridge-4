Microtech Rulebuilder mit Feldkatalog (Schritt fuer Schritt)
============================================================

Ziel
----

Diese Anleitung zeigt den kompletten Ablauf fuer neue Bestellregeln im Microtech-Rulebuilder,
inklusive Feldkatalog-Import aus ``FELD_25.LST`` und einem durchgehenden Praxisbeispiel.

Voraussetzungen
---------------

1. Migrationen sind eingespielt:
   ``./.venv/bin/python manage.py migrate``
2. Admin ist erreichbar und dein Benutzer darf Modelle im Bereich ``Microtech`` bearbeiten.
3. Die Datei ``FELD_25.LST`` liegt im Projektroot.

Was ist neu?
------------

Im Admin gibt es jetzt zusaetzliche Bereiche unter ``Microtech``:

- Operatoren
- Source Felder
- Target Felder
- Datasets
- Dataset Felder

Damit kannst du

- importierte Microtech-Felder zentral pflegen,
- Source/Target-Definitionen auf Katalogfelder referenzieren,
- und in Regeln nur die von dir freigegebenen Source/Operator/Target-Kombinationen nutzen.

Schritt 1: Feldkatalog importieren
----------------------------------

Zuerst die Feldliste einlesen:

.. code-block:: bash

   ./.venv/bin/python manage.py microtech_import_dataset_fields --dry-run

Wenn die Vorschau passt, echten Import ausfuehren:

.. code-block:: bash

   ./.venv/bin/python manage.py microtech_import_dataset_fields

Standardmaessig werden folgende Kern-Datasets importiert:

- ``Adressen - Adressen``
- ``Anschriften - Anschriften``
- ``Ansprechpartner - Ansprechpartner``
- ``Vorgang - Vorgange``
- ``VorgangArten - Vorgangsarten``
- ``VorgangPosition - Vorgangspositionen``

Optional:

.. code-block:: bash

   ./.venv/bin/python manage.py microtech_import_dataset_fields \
     --dataset "Vorgang - Vorgange" \
     --dataset "VorgangPosition - Vorgangspositionen"

Schritt 2: Operatoren pflegen
-----------------------------

Adminpfad: ``Microtech -> Operatoren``

Empfohlene Basisoperatoren:

- ``eq`` (==)
- ``contains`` (enthaelt)
- ``gt`` (>)
- ``lt`` (<)

Hinweis: Welche Operatoren in einer Regel wirklich waehlbar sind, wird pro Source Feld festgelegt.

Schritt 3: Source Felder definieren
-----------------------------------

Adminpfad: ``Microtech -> Source Felder``

Hier legst du fest,

- welcher fachliche Source-Code in Regeln erscheint,
- welcher Engine-Source-Wert ausgewertet wird,
- welche Operatoren erlaubt sind,
- und optional welches importierte Dataset-Feld als Referenz dient.

Beispiel-Definitionen:

1. ``shipping_country``
   - Name: ``Lieferland``
   - Engine Source Feld: ``shipping_country_code``
   - Wertetyp: ``country_code``
   - Erlaubte Operatoren: ``eq``
   - Beispiel: ``AT``

2. ``payment_method``
   - Name: ``Zahlungsart-Text``
   - Engine Source Feld: ``payment_method``
   - Wertetyp: ``string``
   - Erlaubte Operatoren: ``contains``, ``eq``
   - Beispiel: ``paypal``

Schritt 4: Target Felder definieren
-----------------------------------

Adminpfad: ``Microtech -> Target Felder``

Hier legst du fest,

- welcher fachliche Target-Code in Regeln erscheint,
- welches Engine-Target gesetzt wird,
- welchen Typ der Zielwert hat,
- und optional welches Dataset-Feld als Referenz hinterlegt ist.

Beispiel-Definitionen:

1. ``set_payment_type``
   - Engine Target Feld: ``zahlungsart_id``
   - Wertetyp: ``int``
   - Beispiel: ``22``

2. ``set_payment_terms``
   - Engine Target Feld: ``zahlungsbedingung``
   - Wertetyp: ``string``
   - Beispiel: ``Sofort ohne Abzug``

3. ``set_fee_enabled``
   - Engine Target Feld: ``add_payment_position``
   - Wertetyp: ``bool``
   - Beispiel: ``true``

4. ``set_fee_value``
   - Engine Target Feld: ``payment_position_value``
   - Wertetyp: ``decimal``
   - Beispiel: ``2.50``

Durchgehendes Beispiel
----------------------

Anforderung:

"Wenn Zahlungsart `PayPal` und Lieferland `AT`, dann setze Zahlungsart-ID 22,
Zahlungsbedingung `Sofort ohne Abzug` und fuege eine Zahlungs-Zusatzposition mit 2.50 hinzu."

1. Regel anlegen
~~~~~~~~~~~~~~~~

Adminpfad: ``Microtech -> Einstellungen`` (Bestellregeln)

- Name: ``AT + PayPal``
- Aktiv: ``Ja``
- Prioritaet: ``10``
- Bedingungslogik: ``UND``

2. Bedingungen anlegen
~~~~~~~~~~~~~~~~~~~~~~

Bedingung A:

- Source Feld: ``payment_method``
- Operator: ``contains``
- Vergleichswert: ``paypal``

Bedingung B:

- Source Feld: ``shipping_country``
- Operator: ``eq``
- Vergleichswert: ``AT``

Wichtig: Im Operator-Dropdown erscheinen nur die beim jeweiligen Source Feld erlaubten Operatoren.

3. Aktionen anlegen
~~~~~~~~~~~~~~~~~~~

Aktion A:

- Target Feld: ``set_payment_type``
- Zielwert: ``22``

Aktion B:

- Target Feld: ``set_payment_terms``
- Zielwert: ``Sofort ohne Abzug``

Aktion C:

- Target Feld: ``set_fee_enabled``
- Zielwert: ``true``

Aktion D:

- Target Feld: ``set_fee_value``
- Zielwert: ``2.50``

4. Ergebnis pruefen
~~~~~~~~~~~~~~~~~~~

Eine passende Testbestellung sollte beim Upsert in Microtech folgende Rule-Auswirkung zeigen:

- ``zahlungsart_id = 22``
- ``zahlungsbedingung = Sofort ohne Abzug``
- ``add_payment_position = true``
- ``payment_position_value = 2.50``

Schneller Test ueber Command:

.. code-block:: bash

   ./.venv/bin/python manage.py microtech_order_upsert --order-number <DEINE_BESTELLNUMMER>

Typische Fehler und Loesung
---------------------------

1. Source Feld wird nicht angeboten

- Source Feld ist in ``Microtech -> Source Felder`` nicht aktiv.
- Code ist leer oder doppelt.

2. Operator fehlt im Dropdown

- Operator ist beim Source Feld nicht in ``Erlaubte Operatoren`` hinterlegt.
- Operator selbst ist in ``Microtech -> Operatoren`` inaktiv.

3. Aktion wird ignoriert

- ``target_value`` passt nicht zum Typ (z. B. Text statt Zahl).
- Enum-Wert ist nicht in ``enum_values`` des Target Felds enthalten.

4. Katalogfeld nicht sichtbar

- Feldimport noch nicht gelaufen.
- Import wurde mit zu engem ``--dataset``-Filter gestartet.

Empfohlener Betriebsablauf
--------------------------

1. ``microtech_import_dataset_fields --dry-run``
2. ``microtech_import_dataset_fields``
3. Operatoren kontrollieren
4. Source/Target-Felder pflegen
5. Regel anlegen und mit einer echten Bestellung testen
6. Bei Aenderungen zuerst inaktivieren, dann iterativ anpassen
