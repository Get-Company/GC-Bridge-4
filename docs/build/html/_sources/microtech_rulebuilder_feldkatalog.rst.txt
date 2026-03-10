Microtech Rulebuilder mit Feldkatalog (Schritt fuer Schritt)
============================================================

Ziel
----

Diese Anleitung beschreibt den aktuellen Rulebuilder-Stand auf Basis von Django-Feldpfaden
(Bedingungen) und Microtech-Dataset-Feldern (Aktionen).

Durchgehendes Beispiel (wird in allen Abschnitten verwendet)
-------------------------------------------------------------

Geschaeftsregel:

"Wenn Zahlungsart den Text `paypal` enthaelt und Lieferland `AT` ist,
lege eine Zusatzposition mit ERP-Nr `P` an, setze im Vorgang das Feld `ZahlArt` auf `22`
und setze im neu erzeugten VorgangPosition-Datensatz `KuBez` auf `PayPal Gebuehr`."

Voraussetzungen
---------------

1. Migrationen sind eingespielt:

.. code-block:: bash

   ./.venv/bin/python manage.py migrate

2. Der Feldkatalog ist importiert:

.. code-block:: bash

   ./.venv/bin/python manage.py microtech_import_dataset_fields --dry-run
   ./.venv/bin/python manage.py microtech_import_dataset_fields

3. Admin-Menue `Microtech` ist sichtbar.

Menuepunkte im Admin
--------------------

Unter `Microtech` sind fuer den Rulebuilder relevant:

1. `Einstellungen` (enthaelt `MicrotechOrderRule` inkl. Inlines)
2. `Operatoren` (`MicrotechOrderRuleOperator`)
3. `Django Feld Policies` (`MicrotechOrderRuleDjangoFieldPolicy`)
4. `Datasets` (`MicrotechDatasetCatalog`)
5. `Dataset Felder` (`MicrotechDatasetField`)

Feldreferenz: alle Rulebuilder-Modelle
--------------------------------------

1) Microtech Dataset (``MicrotechDatasetCatalog``)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Adminpfad: ``Microtech -> Datasets``

.. list-table::
   :header-rows: 1

   * - Feld
     - Bedeutung
     - Beispiel
   * - ``is_active``
     - Dataset ist im Rulebuilder verfuegbar.
     - ``Ja``
   * - ``priority``
     - Sortierung im Admin (kleiner = weiter oben).
     - ``10``
   * - ``code``
     - Stabiler technischer Schluessel.
     - ``vorgang_vorgange``
   * - ``name``
     - Kurzer Dataset-Name.
     - ``Vorgang``
   * - ``description``
     - Lesbare Zusatzbezeichnung.
     - ``Vorgange``
   * - ``source_identifier``
     - Eindeutiger Identifier aus Feldliste.
     - ``Vorgang - Vorgange``
   * - ``created_at`` / ``updated_at``
     - Automatische Zeitstempel.
     - Automatisch

Wichtig:

- ``code`` nur einmal festlegen und danach stabil halten.
- ``priority`` ist nur Sortierung, keine fachliche Logik.

2) Microtech Dataset Feld (``MicrotechDatasetField``)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Adminpfad: ``Microtech -> Dataset Felder``

.. list-table::
   :header-rows: 1

   * - Feld
     - Bedeutung
     - Beispiel
   * - ``is_active``
     - Feld ist in Aktions-Dropdowns nutzbar.
     - ``Ja``
   * - ``priority``
     - Sortierung innerhalb eines Datasets.
     - ``10``
   * - ``dataset``
     - Zugehoeriges Dataset.
     - ``Vorgang - Vorgange``
   * - ``field_name``
     - Technischer Feldname.
     - ``ZahlArt``
   * - ``label``
     - Lesbarer Name.
     - ``Zahlungsart``
   * - ``field_type``
     - Feldtyp aus Katalog.
     - ``Integer``
   * - ``is_calc_field``
     - Kennzeichnung als berechnetes Feld.
     - ``Nein``
   * - ``can_access``
     - Feld ist les-/schreibbar laut Katalog.
     - ``Ja``
   * - ``created_at`` / ``updated_at``
     - Automatische Zeitstempel.
     - Automatisch

3) Rulebuilder Operator (``MicrotechOrderRuleOperator``)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Adminpfad: ``Microtech -> Operatoren``

.. list-table::
   :header-rows: 1

   * - Feld
     - Bedeutung
     - Beispiel
   * - ``is_active``
     - Nur aktive Operatoren stehen zur Wahl.
     - ``Ja``
   * - ``priority``
     - Sortierung im Operator-Dropdown.
     - ``10``
   * - ``code``
     - Technischer Operator-Code.
     - ``contains``
   * - ``name``
     - Anzeige im UI.
     - ``enthaelt``
   * - ``engine_operator``
     - Interne Auswertung (`eq`, `contains`, `gt`, `lt`).
     - ``contains``
   * - ``hint``
     - Kurzinfo fuer Admin-Nutzer.
     - ``Textvergleich``
   * - ``created_at`` / ``updated_at``
     - Automatische Zeitstempel.
     - Automatisch

Wichtig:

- ``code`` ist die Referenz in Bedingungen.
- ``engine_operator`` steuert das reale Vergleichsverhalten.

4) Django Feld Policy (``MicrotechOrderRuleDjangoFieldPolicy``)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Adminpfad: ``Microtech -> Django Feld Policies``

Zweck:

- Optionales Whitelisting pro Django-Feldpfad.
- Ohne Policy sind alle vom System angebotenen Felder aktiv.
- Mit Policy kannst du Felder ausblenden oder Operatoren begrenzen.

.. list-table::
   :header-rows: 1

   * - Feld
     - Bedeutung
     - Beispiel
   * - ``is_active``
     - Policy ist aktiv.
     - ``Ja``
   * - ``priority``
     - Sortierung in der Policy-Verwaltung.
     - ``10``
   * - ``field_path``
     - Exakter Django-Feldpfad aus Autocomplete.
     - ``payment_method``
   * - ``label_override``
     - Eigene Anzeigebezeichnung fuer das Feld.
     - ``Zahlungsart (Shop)``
   * - ``allowed_operators``
     - Erlaubte Operatoren fuer genau dieses Feld.
     - ``eq``, ``contains``
   * - ``hint``
     - Tooltip fuer das Feld.
     - ``Vergleich gegen Shopware Zahlungsname``
   * - ``created_at`` / ``updated_at``
     - Automatische Zeitstempel.
     - Automatisch

5) Bestellregel (``MicrotechOrderRule``)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Adminpfad: ``Microtech -> Einstellungen``

Regelkopf:

.. list-table::
   :header-rows: 1

   * - Feld
     - Bedeutung
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
     - Verknuepfung der Bedingungen (`all`/UND oder `any`/ODER).
     - ``all``

Wichtig zu ``priority`` und ``code`` im Betrieb:

- Die Regel mit der kleinsten ``priority`` wird zuerst geprueft.
- Sobald eine Regel matcht, werden keine nachfolgenden Regeln ausgewertet.
- ``code``-Felder (bei Operatoren/Datasets) sollten nicht nachtraeglich umbenannt werden.

6) Bedingungs-Inline (``MicrotechOrderRuleCondition``)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

In der Regel unterhalb des Regelkopfs.

.. list-table::
   :header-rows: 1

   * - Feld
     - Bedeutung
     - Beispiel
   * - ``is_active``
     - Nur aktive Bedingungen werden geprueft.
     - ``Ja``
   * - ``priority``
     - Reihenfolge innerhalb der Regel.
     - ``10``
   * - ``django_field_path``
     - Django-Feldpfad (Textfeld mit Autocomplete).
     - ``shipping_address__country_code``
   * - ``operator_code``
     - Operator aus Dropdown, automatisch feldtypgefiltert.
     - ``eq``
   * - ``expected_value``
     - Vergleichswert als Text.
     - ``AT``

Hinweis:

- Die Auswahl ``django_field_path`` steuert, welche Operatoren erlaubt sind.
- Typbeispiele:
  - Textfeld: ``eq``, ``contains``
  - Zahl/Datum: ``eq``, ``gt``, ``lt``
  - Bool: ``eq``

7) Aktions-Inline (``MicrotechOrderRuleAction``)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

In der Regel unterhalb der Bedingungen.

.. list-table::
   :header-rows: 1

   * - Feld
     - Bedeutung
     - Beispiel
   * - ``is_active``
     - Nur aktive Aktionen werden ausgefuehrt.
     - ``Ja``
   * - ``priority``
     - Reihenfolge der Ausfuehrung.
     - ``10``
   * - ``action_type``
     - Aktionstyp (`set_field` oder `create_extra_position`).
     - ``set_field``
   * - ``dataset``
     - Ziel-Dataset fuer `set_field`.
     - ``Vorgang - Vorgange``
   * - ``dataset_field``
     - Ziel-Feld, gefiltert nach gewaehltem Dataset.
     - ``ZahlArt``
   * - ``target_value``
     - Zu schreibender Wert oder ERP-Nr bei `create_extra_position`.
     - ``22`` oder ``P``

Wichtig:

- Bei ``create_extra_position`` muessen ``dataset`` und ``dataset_field`` leer sein.
- Bei ``set_field`` muessen ``dataset`` und ``dataset_field`` gesetzt sein.

Durchgehendes Beispiel: komplette Umsetzung im Admin
----------------------------------------------------

1. Operatoren pruefen
~~~~~~~~~~~~~~~~~~~~~

In ``Microtech -> Operatoren`` sicherstellen:

- ``eq`` (Engine ``eq``)
- ``contains`` (Engine ``contains``)

2. Optional: Feld-Policy fuer Zahlungsart
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

In ``Microtech -> Django Feld Policies``:

- ``field_path``: ``payment_method``
- ``label_override``: ``Zahlungsart (Shop)``
- ``allowed_operators``: ``eq`` und ``contains``
- ``is_active``: ``Ja``

3. Regelkopf anlegen
~~~~~~~~~~~~~~~~~~~~

In ``Microtech -> Einstellungen`` neue Regel:

- ``name``: ``AT + PayPal``
- ``is_active``: ``Ja``
- ``priority``: ``10``
- ``condition_logic``: ``all``

4. Bedingungen anlegen
~~~~~~~~~~~~~~~~~~~~~~

Bedingung A:

- ``priority``: ``10``
- ``django_field_path``: ``payment_method``
- ``operator_code``: ``contains``
- ``expected_value``: ``paypal``

Bedingung B:

- ``priority``: ``20``
- ``django_field_path``: ``shipping_address__country_code``
- ``operator_code``: ``eq``
- ``expected_value``: ``AT``

5. Aktionen anlegen
~~~~~~~~~~~~~~~~~~~

Aktion A (zusaetzliche Position):

- ``priority``: ``10``
- ``action_type``: ``create_extra_position``
- ``target_value``: ``P``

Aktion B (Vorgang-Feld setzen):

- ``priority``: ``20``
- ``action_type``: ``set_field``
- ``dataset``: ``Vorgang - Vorgange``
- ``dataset_field``: ``ZahlArt``
- ``target_value``: ``22``

Aktion C (Feld auf der neu erstellten VorgangPosition setzen):

- ``priority``: ``30``
- ``action_type``: ``set_field``
- ``dataset``: ``VorgangPosition - Vorgangspositionen``
- ``dataset_field``: ``KuBez``
- ``target_value``: ``PayPal Gebuehr``

6. Testlauf
~~~~~~~~~~~

.. code-block:: bash

   ./.venv/bin/python manage.py microtech_order_upsert --order-number <DEINE_BESTELLNUMMER>

Erwartete Wirkung fuer das Beispiel:

1. Bedingungen matchen nur bei PayPal + AT.
2. Zusatzposition mit ERP-Nr ``P`` wird angelegt.
3. Im Vorgang wird ``ZahlArt = 22`` gesetzt.
4. In der neu erzeugten VorgangPosition wird ``KuBez = PayPal Gebuehr`` gesetzt.

Typische Fehler und Loesungen
-----------------------------

1. Feldpfad wird nicht akzeptiert

- Schreibweise stimmt nicht exakt mit dem Autocomplete ueberein.
- Das Feld wurde per Policy deaktiviert.

2. Operator fehlt im Dropdown

- Feldtyp erlaubt den Operator nicht.
- In ``Django Feld Policies`` wurde der Operator nicht freigegeben.

3. ``set_field`` speichert nicht

- ``dataset_field`` passt nicht zum ausgewaehlten ``dataset``.
- Zielwert passt nicht zum Feldtyp.

4. Aktion auf VorgangPosition greift nicht

- Es wurde keine ``create_extra_position``-Aktion ausgefuehrt.

Empfohlener Betrieb
-------------------

1. Feldkatalog zuerst per ``--dry-run`` pruefen.
2. Operatoren klein halten (nur benoetigte freigeben).
3. Policies nur einsetzen, wenn du Felder bewusst einschranken willst.
4. Neue Regeln erst mit hoher ``priority`` (z. B. 900) testen.
5. Nach erfolgreichem Test ``priority`` auf produktiven Wert senken.
