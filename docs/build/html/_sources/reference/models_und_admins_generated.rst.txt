Model- und Admin-Inventar
=========================

Diese Seite wird automatisch aus dem Django-Projekt erzeugt und deckt alle lokalen Apps, Models und registrierten Admin-Klassen ab.

Generiert am: 2026-05-05 14:02:58 UTC

core
----

Keine lokalen Models in dieser App.

customer
--------

customer.Address
~~~~~~~~~~~~~~~~

* Python: ``customer.models.Address``
* DB-Tabelle: ``customer_address``
* Verbose Name: ``Adresse``
* Verbose Name Plural: ``Adressen``
* Default Ordering: ``customer, erp_ans_id, erp_asp_id``

Felder
^^^^^^

.. list-table::
   :header-rows: 1

   * - Feld
     - Typ
     - Optionen
     - Details
   * - id
     - BigAutoField
     - pk, unique, blank
     - verbose=ID
   * - created_at
     - DateTimeField
     - blank
     - verbose=Angelegt am
   * - updated_at
     - DateTimeField
     - blank
     - verbose=Aktualisiert am
   * - customer
     - ForeignKey
     - db_index
     - relation=customer.Customer, verbose=Kunde
   * - erp_combined_id
     - CharField
     - unique, null, blank
     - verbose=ERP Kombi-ID, max_length=255
   * - api_id
     - CharField
     - blank
     - verbose=Shopware Adress-ID, max_length=255
   * - erp_nr
     - IntegerField
     - null, blank
     - verbose=ERP-Nummer
   * - erp_ans_id
     - IntegerField
     - null, blank
     - verbose=Anschrift-ID
   * - erp_ans_nr
     - IntegerField
     - null, blank
     - verbose=Anschrift-Nummer
   * - erp_asp_id
     - IntegerField
     - null, blank
     - verbose=Ansprechpartner-ID
   * - erp_asp_nr
     - IntegerField
     - null, blank
     - verbose=Ansprechpartner-Nummer
   * - name1
     - CharField
     - blank
     - verbose=Name 1, max_length=255
   * - name2
     - CharField
     - blank
     - verbose=Name 2, max_length=255
   * - name3
     - CharField
     - blank
     - verbose=Name 3, max_length=255
   * - department
     - CharField
     - blank
     - verbose=Abteilung, max_length=255
   * - street
     - CharField
     - blank
     - verbose=Strasse, max_length=255
   * - postal_code
     - CharField
     - blank
     - verbose=PLZ, max_length=255
   * - city
     - CharField
     - blank
     - verbose=Ort, max_length=255
   * - country_code
     - CharField
     - blank
     - verbose=Laendercode, max_length=8
   * - email
     - EmailField
     - blank
     - verbose=E-Mail, max_length=255
   * - title
     - CharField
     - blank
     - verbose=Titel, max_length=255
   * - first_name
     - CharField
     - blank
     - verbose=Vorname, max_length=255
   * - last_name
     - CharField
     - blank
     - verbose=Nachname, max_length=255
   * - phone
     - CharField
     - blank
     - verbose=Telefon, max_length=255
   * - is_shipping
     - BooleanField
     - default=False
     - verbose=Lieferanschrift
   * - is_invoice
     - BooleanField
     - default=False
     - verbose=Rechnungsanschrift

Admin-Konfiguration
^^^^^^^^^^^^^^^^^^^

.. list-table::
   :header-rows: 1

   * - Aspekt
     - Wert
   * - Admin-Klasse
     - customer.admin.AddressAdmin
   * - list_display
     - customer, erp_ans_id, name1, city, is_invoice, is_shipping, created_at
   * - list_filter
     - ('is_invoice', <class 'unfold.contrib.filters.admin.choice_filters.BooleanRadioFilter'>), ('is_shipping', <class 'unfold.contrib.filters.admin.choice_filters.BooleanRadioFilter'>), ('country_code', <class 'unfold.contrib.filters.admin.text_filters.FieldTextFilter'>), ('created_at', <class 'unfold.contrib.filters.admin.datetime_filters.RangeDateTimeFilter'>)
   * - search_fields
     - customer__erp_nr, name1, name2, street, postal_code, city
   * - readonly_fields
     - created_at, updated_at
   * - ordering
     - -created_at
   * - list_select_related
     - False
   * - list_per_page
     - 100
   * - inlines
     - -
   * - actions
     - -
   * - action_form
     - unfold.forms.ActionForm

customer.Customer
~~~~~~~~~~~~~~~~~

* Python: ``customer.models.Customer``
* DB-Tabelle: ``customer_customer``
* Verbose Name: ``Kunde``
* Verbose Name Plural: ``Kunden``
* Default Ordering: ``erp_nr``

Felder
^^^^^^

.. list-table::
   :header-rows: 1

   * - Feld
     - Typ
     - Optionen
     - Details
   * - id
     - BigAutoField
     - pk, unique, blank
     - verbose=ID
   * - created_at
     - DateTimeField
     - blank
     - verbose=Angelegt am
   * - updated_at
     - DateTimeField
     - blank
     - verbose=Aktualisiert am
   * - erp_nr
     - CharField
     - unique
     - verbose=ERP-Nummer, max_length=64
   * - erp_id
     - IntegerField
     - unique, null, blank
     - verbose=ERP-ID
   * - name
     - CharField
     - blank
     - verbose=Name, max_length=255
   * - email
     - EmailField
     - blank
     - verbose=E-Mail, max_length=255
   * - api_id
     - CharField
     - blank
     - verbose=Shopware Kunden-ID, max_length=255
   * - vat_id
     - CharField
     - blank
     - verbose=USt-IdNr, max_length=255
   * - is_gross
     - BooleanField
     - default=True
     - verbose=Bruttopreise

Admin-Konfiguration
^^^^^^^^^^^^^^^^^^^

.. list-table::
   :header-rows: 1

   * - Aspekt
     - Wert
   * - Admin-Klasse
     - customer.admin.CustomerAdmin
   * - list_display
     - erp_nr, name, email, is_gross, created_at
   * - list_filter
     - ('is_gross', <class 'unfold.contrib.filters.admin.choice_filters.BooleanRadioFilter'>), ('created_at', <class 'unfold.contrib.filters.admin.datetime_filters.RangeDateTimeFilter'>)
   * - search_fields
     - erp_nr, name, email
   * - readonly_fields
     - created_at, updated_at
   * - ordering
     - -created_at
   * - list_select_related
     - False
   * - list_per_page
     - 100
   * - inlines
     - customer.admin.AddressInline
   * - actions
     - sync_from_microtech, sync_to_microtech
   * - action_form
     - unfold.forms.ActionForm

microtech
---------

microtech.MicrotechDatasetCatalog
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

* Python: ``microtech.models.MicrotechDatasetCatalog``
* DB-Tabelle: ``microtech_microtechdatasetcatalog``
* Verbose Name: ``Microtech Dataset``
* Verbose Name Plural: ``Microtech Datasets``
* Default Ordering: ``priority, name, id``

Felder
^^^^^^

.. list-table::
   :header-rows: 1

   * - Feld
     - Typ
     - Optionen
     - Details
   * - id
     - BigAutoField
     - pk, unique, blank
     - verbose=ID
   * - created_at
     - DateTimeField
     - blank
     - verbose=Angelegt am
   * - updated_at
     - DateTimeField
     - blank
     - verbose=Aktualisiert am
   * - code
     - CharField
     - unique
     - verbose=Code, max_length=64
   * - name
     - CharField
     - -
     - verbose=Dataset Name, max_length=255
   * - description
     - CharField
     - blank
     - verbose=Bezeichnung, max_length=255
   * - source_identifier
     - CharField
     - unique
     - verbose=Source Identifier, max_length=255
   * - is_active
     - BooleanField
     - default=True
     - verbose=Aktiv
   * - priority
     - PositiveIntegerField
     - default=100
     - verbose=Prioritaet

Admin-Konfiguration
^^^^^^^^^^^^^^^^^^^

.. list-table::
   :header-rows: 1

   * - Aspekt
     - Wert
   * - Admin-Klasse
     - microtech.admin.MicrotechDatasetCatalogAdmin
   * - list_display
     - priority, name, description, code, is_active, updated_at
   * - list_filter
     - is_active
   * - search_fields
     - code, name, description, source_identifier
   * - readonly_fields
     - created_at, updated_at
   * - ordering
     - priority, name, id
   * - list_select_related
     - False
   * - list_per_page
     - 100
   * - inlines
     - -
   * - actions
     - -
   * - action_form
     - unfold.forms.ActionForm

microtech.MicrotechDatasetField
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

* Python: ``microtech.models.MicrotechDatasetField``
* DB-Tabelle: ``microtech_microtechdatasetfield``
* Verbose Name: ``Microtech Dataset Feld``
* Verbose Name Plural: ``Microtech Dataset Felder``
* Default Ordering: ``dataset__priority, dataset_id, priority, field_name, id``

Felder
^^^^^^

.. list-table::
   :header-rows: 1

   * - Feld
     - Typ
     - Optionen
     - Details
   * - id
     - BigAutoField
     - pk, unique, blank
     - verbose=ID
   * - created_at
     - DateTimeField
     - blank
     - verbose=Angelegt am
   * - updated_at
     - DateTimeField
     - blank
     - verbose=Aktualisiert am
   * - dataset
     - ForeignKey
     - db_index
     - relation=microtech.MicrotechDatasetCatalog, verbose=Dataset
   * - field_name
     - CharField
     - -
     - verbose=Feldname, max_length=128
   * - label
     - CharField
     - blank
     - verbose=Bezeichnung, max_length=255
   * - field_type
     - CharField
     - blank
     - verbose=Feldtyp, max_length=64
   * - is_calc_field
     - BooleanField
     - default=False
     - verbose=Berechnetes Feld
   * - can_access
     - BooleanField
     - default=True
     - verbose=Lesbar
   * - is_active
     - BooleanField
     - default=True
     - verbose=Aktiv
   * - priority
     - PositiveIntegerField
     - default=100
     - verbose=Prioritaet

Admin-Konfiguration
^^^^^^^^^^^^^^^^^^^

.. list-table::
   :header-rows: 1

   * - Aspekt
     - Wert
   * - Admin-Klasse
     - microtech.admin.MicrotechDatasetFieldAdmin
   * - list_display
     - priority, dataset, field_name, field_type, is_calc_field, can_access, is_active, updated_at
   * - list_filter
     - is_active, is_calc_field, can_access, field_type, dataset
   * - search_fields
     - field_name, label, field_type, dataset__name, dataset__description
   * - readonly_fields
     - created_at, updated_at
   * - ordering
     - dataset__priority, dataset__name, priority, field_name, id
   * - list_select_related
     - False
   * - list_per_page
     - 100
   * - inlines
     - -
   * - actions
     - -
   * - action_form
     - unfold.forms.ActionForm

microtech.MicrotechJob
~~~~~~~~~~~~~~~~~~~~~~

* Python: ``microtech.models.MicrotechJob``
* DB-Tabelle: ``microtech_microtechjob``
* Verbose Name: ``Microtech Job``
* Verbose Name Plural: ``Microtech Jobs``
* Default Ordering: ``priority, created_at``

Felder
^^^^^^

.. list-table::
   :header-rows: 1

   * - Feld
     - Typ
     - Optionen
     - Details
   * - id
     - BigAutoField
     - pk, unique, blank
     - verbose=ID
   * - created_at
     - DateTimeField
     - blank
     - verbose=Angelegt am
   * - updated_at
     - DateTimeField
     - blank
     - verbose=Aktualisiert am
   * - status
     - CharField
     - db_index, default=queued
     - choices=5, verbose=Status, max_length=16
   * - priority
     - PositiveSmallIntegerField
     - db_index, default=100
     - verbose=Prioritaet
   * - label
     - CharField
     - -
     - verbose=Bezeichnung, max_length=255
   * - correlation_id
     - CharField
     - unique, db_index
     - verbose=Correlation ID, max_length=64
   * - started_at
     - DateTimeField
     - null, blank
     - verbose=Gestartet
   * - finished_at
     - DateTimeField
     - null, blank
     - verbose=Beendet
   * - last_error
     - TextField
     - blank
     - verbose=Letzter Fehler

Admin-Konfiguration
^^^^^^^^^^^^^^^^^^^

.. list-table::
   :header-rows: 1

   * - Aspekt
     - Wert
   * - Registrierung
     - Kein ModelAdmin registriert

microtech.MicrotechOrderRule
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

* Python: ``microtech.models.MicrotechOrderRule``
* DB-Tabelle: ``microtech_microtechorderrule``
* Verbose Name: ``Microtech Bestellregel``
* Verbose Name Plural: ``Microtech Bestellregeln``
* Default Ordering: ``priority, id``

Felder
^^^^^^

.. list-table::
   :header-rows: 1

   * - Feld
     - Typ
     - Optionen
     - Details
   * - id
     - BigAutoField
     - pk, unique, blank
     - verbose=ID
   * - created_at
     - DateTimeField
     - blank
     - verbose=Angelegt am
   * - updated_at
     - DateTimeField
     - blank
     - verbose=Aktualisiert am
   * - name
     - CharField
     - -
     - verbose=Name, max_length=255
   * - is_active
     - BooleanField
     - default=True
     - verbose=Aktiv
   * - priority
     - PositiveIntegerField
     - default=100
     - verbose=Prioritaet
   * - condition_logic
     - CharField
     - default=all
     - choices=2, verbose=Bedingungslogik, max_length=16

Admin-Konfiguration
^^^^^^^^^^^^^^^^^^^

.. list-table::
   :header-rows: 1

   * - Aspekt
     - Wert
   * - Admin-Klasse
     - microtech.admin.MicrotechOrderRuleAdmin
   * - list_display
     - priority, name, is_active, condition_logic, updated_at
   * - list_filter
     - is_active, condition_logic
   * - search_fields
     - name
   * - readonly_fields
     - created_at, updated_at, live_rule_summary
   * - ordering
     - priority, id
   * - list_select_related
     - False
   * - list_per_page
     - 100
   * - inlines
     - microtech.admin.ConditionInline, microtech.admin.ActionInline
   * - actions
     - -
   * - action_form
     - unfold.forms.ActionForm

microtech.MicrotechOrderRuleAction
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

* Python: ``microtech.models.MicrotechOrderRuleAction``
* DB-Tabelle: ``microtech_microtechorderruleaction``
* Verbose Name: ``Microtech Bestellregel Aktion``
* Verbose Name Plural: ``Microtech Bestellregel Aktionen``
* Default Ordering: ``rule, priority, id``

Felder
^^^^^^

.. list-table::
   :header-rows: 1

   * - Feld
     - Typ
     - Optionen
     - Details
   * - id
     - BigAutoField
     - pk, unique, blank
     - verbose=ID
   * - created_at
     - DateTimeField
     - blank
     - verbose=Angelegt am
   * - updated_at
     - DateTimeField
     - blank
     - verbose=Aktualisiert am
   * - rule
     - ForeignKey
     - db_index
     - relation=microtech.MicrotechOrderRule, verbose=Regel
   * - is_active
     - BooleanField
     - default=True
     - verbose=Aktiv
   * - priority
     - PositiveIntegerField
     - default=100
     - verbose=Prioritaet
   * - action_type
     - CharField
     - default=set_field
     - choices=2, verbose=Aktionstyp, max_length=32
   * - dataset
     - ForeignKey
     - db_index, null, blank
     - relation=microtech.MicrotechDatasetCatalog, verbose=Dataset
   * - dataset_field
     - ForeignKey
     - db_index, null, blank
     - relation=microtech.MicrotechDatasetField, verbose=Dataset Feld
   * - target_value
     - CharField
     - blank
     - verbose=Zielwert, max_length=255

Admin-Konfiguration
^^^^^^^^^^^^^^^^^^^

.. list-table::
   :header-rows: 1

   * - Aspekt
     - Wert
   * - Registrierung
     - Kein ModelAdmin registriert

microtech.MicrotechOrderRuleCondition
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

* Python: ``microtech.models.MicrotechOrderRuleCondition``
* DB-Tabelle: ``microtech_microtechorderrulecondition``
* Verbose Name: ``Microtech Bestellregel Bedingung``
* Verbose Name Plural: ``Microtech Bestellregel Bedingungen``
* Default Ordering: ``rule, priority, id``

Felder
^^^^^^

.. list-table::
   :header-rows: 1

   * - Feld
     - Typ
     - Optionen
     - Details
   * - id
     - BigAutoField
     - pk, unique, blank
     - verbose=ID
   * - created_at
     - DateTimeField
     - blank
     - verbose=Angelegt am
   * - updated_at
     - DateTimeField
     - blank
     - verbose=Aktualisiert am
   * - rule
     - ForeignKey
     - db_index
     - relation=microtech.MicrotechOrderRule, verbose=Regel
   * - django_field
     - ForeignKey
     - db_index, null, blank
     - relation=microtech.MicrotechOrderRuleDjangoField, verbose=Django Feld
   * - operator
     - ForeignKey
     - db_index, null, blank
     - relation=microtech.MicrotechOrderRuleOperator, verbose=Operator
   * - is_active
     - BooleanField
     - default=True
     - verbose=Aktiv
   * - priority
     - PositiveIntegerField
     - default=100
     - verbose=Prioritaet
   * - django_field_path
     - CharField
     - blank
     - verbose=Django Feldpfad, max_length=255
   * - operator_code
     - CharField
     - default=eq
     - verbose=Operator, max_length=64
   * - expected_value
     - CharField
     - blank
     - verbose=Vergleichswert, max_length=255

Admin-Konfiguration
^^^^^^^^^^^^^^^^^^^

.. list-table::
   :header-rows: 1

   * - Aspekt
     - Wert
   * - Registrierung
     - Kein ModelAdmin registriert

microtech.MicrotechOrderRuleDjangoField
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

* Python: ``microtech.models.MicrotechOrderRuleDjangoField``
* DB-Tabelle: ``microtech_microtechorderruledjangofield``
* Verbose Name: ``Microtech Django Feldkatalog``
* Verbose Name Plural: ``Microtech Django Feldkatalog``
* Default Ordering: ``priority, field_path, id``

Felder
^^^^^^

.. list-table::
   :header-rows: 1

   * - Feld
     - Typ
     - Optionen
     - Details
   * - id
     - BigAutoField
     - pk, unique, blank
     - verbose=ID
   * - created_at
     - DateTimeField
     - blank
     - verbose=Angelegt am
   * - updated_at
     - DateTimeField
     - blank
     - verbose=Aktualisiert am
   * - field_path
     - CharField
     - unique
     - verbose=Django Feldpfad, max_length=255
   * - label
     - CharField
     - -
     - verbose=Label, max_length=255
   * - value_kind
     - CharField
     - -
     - verbose=Wertetyp, max_length=32
   * - hint
     - CharField
     - blank
     - verbose=Hinweis, max_length=255
   * - example
     - CharField
     - blank
     - verbose=Beispiel, max_length=255
   * - is_active
     - BooleanField
     - default=True
     - verbose=Aktiv
   * - priority
     - PositiveIntegerField
     - default=100
     - verbose=Prioritaet

Admin-Konfiguration
^^^^^^^^^^^^^^^^^^^

.. list-table::
   :header-rows: 1

   * - Aspekt
     - Wert
   * - Admin-Klasse
     - microtech.admin.MicrotechOrderRuleDjangoFieldAdmin
   * - list_display
     - priority, label, field_path, value_kind, is_active, updated_at
   * - list_filter
     - is_active, value_kind
   * - search_fields
     - field_path, label, hint, example
   * - readonly_fields
     - created_at, updated_at
   * - ordering
     - priority, field_path, id
   * - list_select_related
     - False
   * - list_per_page
     - 100
   * - inlines
     - -
   * - actions
     - -
   * - action_form
     - unfold.forms.ActionForm

microtech.MicrotechOrderRuleDjangoFieldPolicy
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

* Python: ``microtech.models.MicrotechOrderRuleDjangoFieldPolicy``
* DB-Tabelle: ``microtech_microtechorderruledjangofieldpolicy``
* Verbose Name: ``Microtech Django Bedingungsfeld``
* Verbose Name Plural: ``Microtech Django Bedingungsfelder``
* Default Ordering: ``priority, field_path, id``

Felder
^^^^^^

.. list-table::
   :header-rows: 1

   * - Feld
     - Typ
     - Optionen
     - Details
   * - id
     - BigAutoField
     - pk, unique, blank
     - verbose=ID
   * - created_at
     - DateTimeField
     - blank
     - verbose=Angelegt am
   * - updated_at
     - DateTimeField
     - blank
     - verbose=Aktualisiert am
   * - field_path
     - CharField
     - unique
     - verbose=Django Feldpfad, max_length=255
   * - label_override
     - CharField
     - blank
     - verbose=Label Override, max_length=255
   * - hint
     - CharField
     - blank
     - verbose=Hinweis, max_length=255
   * - is_active
     - BooleanField
     - default=True
     - verbose=Aktiv
   * - priority
     - PositiveIntegerField
     - default=100
     - verbose=Prioritaet
   * - allowed_operators
     - ManyToManyField
     - blank
     - relation=microtech.MicrotechOrderRuleOperator, verbose=Erlaubte Operatoren

Admin-Konfiguration
^^^^^^^^^^^^^^^^^^^

.. list-table::
   :header-rows: 1

   * - Aspekt
     - Wert
   * - Admin-Klasse
     - microtech.admin.MicrotechOrderRuleDjangoFieldPolicyAdmin
   * - list_display
     - priority, field_path, label_override, is_active, updated_at
   * - list_filter
     - is_active
   * - search_fields
     - field_path, label_override, hint
   * - readonly_fields
     - created_at, updated_at
   * - ordering
     - priority, field_path, id
   * - list_select_related
     - False
   * - list_per_page
     - 100
   * - inlines
     - -
   * - actions
     - -
   * - action_form
     - unfold.forms.ActionForm

microtech.MicrotechOrderRuleOperator
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

* Python: ``microtech.models.MicrotechOrderRuleOperator``
* DB-Tabelle: ``microtech_microtechorderruleoperator``
* Verbose Name: ``Microtech Bestellregel Operator``
* Verbose Name Plural: ``Microtech Bestellregel Operatoren``
* Default Ordering: ``priority, id``

Felder
^^^^^^

.. list-table::
   :header-rows: 1

   * - Feld
     - Typ
     - Optionen
     - Details
   * - id
     - BigAutoField
     - pk, unique, blank
     - verbose=ID
   * - created_at
     - DateTimeField
     - blank
     - verbose=Angelegt am
   * - updated_at
     - DateTimeField
     - blank
     - verbose=Aktualisiert am
   * - code
     - CharField
     - unique
     - verbose=Code, max_length=64
   * - name
     - CharField
     - -
     - verbose=Name, max_length=255
   * - engine_operator
     - CharField
     - default=eq
     - choices=7, verbose=Engine Operator, max_length=16
   * - hint
     - CharField
     - blank
     - verbose=Hinweis, max_length=255
   * - is_active
     - BooleanField
     - default=True
     - verbose=Aktiv
   * - priority
     - PositiveIntegerField
     - default=100
     - verbose=Prioritaet

Admin-Konfiguration
^^^^^^^^^^^^^^^^^^^

.. list-table::
   :header-rows: 1

   * - Aspekt
     - Wert
   * - Admin-Klasse
     - microtech.admin.MicrotechOrderRuleOperatorAdmin
   * - list_display
     - priority, name, code, engine_operator, is_active, updated_at
   * - list_filter
     - is_active, engine_operator
   * - search_fields
     - code, name, hint
   * - readonly_fields
     - created_at, updated_at
   * - ordering
     - priority, id
   * - list_select_related
     - False
   * - list_per_page
     - 100
   * - inlines
     - -
   * - actions
     - -
   * - action_form
     - unfold.forms.ActionForm

microtech.MicrotechSettings
~~~~~~~~~~~~~~~~~~~~~~~~~~~

* Python: ``microtech.models.MicrotechSettings``
* DB-Tabelle: ``microtech_microtechsettings``
* Verbose Name: ``Microtech Konfiguration``
* Verbose Name Plural: ``Microtech Konfiguration``
* Default Ordering: ``-``

Felder
^^^^^^

.. list-table::
   :header-rows: 1

   * - Feld
     - Typ
     - Optionen
     - Details
   * - id
     - BigAutoField
     - pk, unique, blank
     - verbose=ID
   * - created_at
     - DateTimeField
     - blank
     - verbose=Angelegt am
   * - updated_at
     - DateTimeField
     - blank
     - verbose=Aktualisiert am
   * - mandant
     - CharField
     - -
     - verbose=Mandant, max_length=100
   * - firma
     - CharField
     - blank
     - verbose=Firma, max_length=255
   * - benutzer
     - CharField
     - blank
     - verbose=Benutzer (Autosync), max_length=100
   * - manual_benutzer
     - CharField
     - blank
     - verbose=Benutzer (Manuell), max_length=100
   * - default_zahlungsart_id
     - PositiveIntegerField
     - default=22
     - verbose=Standard Zahlungsart-ID
   * - default_versandart_id
     - PositiveIntegerField
     - default=10
     - verbose=Standard Versandart-ID
   * - default_vorgangsart_id
     - PositiveIntegerField
     - default=111
     - verbose=Standard Vorgangsart-ID

Admin-Konfiguration
^^^^^^^^^^^^^^^^^^^

.. list-table::
   :header-rows: 1

   * - Aspekt
     - Wert
   * - Admin-Klasse
     - microtech.admin.MicrotechSettingsAdmin
   * - list_display
     - __str__
   * - list_filter
     - -
   * - search_fields
     - -
   * - readonly_fields
     - created_at, updated_at
   * - ordering
     - -created_at
   * - list_select_related
     - False
   * - list_per_page
     - 100
   * - inlines
     - -
   * - actions
     - -
   * - action_form
     - unfold.forms.ActionForm

microtech.MicrotechSwissCustomsFieldMapping
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

* Python: ``microtech.models.MicrotechSwissCustomsFieldMapping``
* DB-Tabelle: ``microtech_microtechswisscustomsfieldmapping``
* Verbose Name: ``Microtech Schweiz Zoll Feldmapping``
* Verbose Name Plural: ``Microtech Schweiz Zoll Feldmappings``
* Default Ordering: ``priority, portal_field, id``

Felder
^^^^^^

.. list-table::
   :header-rows: 1

   * - Feld
     - Typ
     - Optionen
     - Details
   * - id
     - BigAutoField
     - pk, unique, blank
     - verbose=ID
   * - created_at
     - DateTimeField
     - blank
     - verbose=Angelegt am
   * - updated_at
     - DateTimeField
     - blank
     - verbose=Aktualisiert am
   * - portal_field
     - CharField
     - unique
     - verbose=Portal Feld, max_length=255
   * - section
     - CharField
     - default=shipment
     - choices=13, verbose=Bereich, max_length=48
   * - source_type
     - CharField
     - default=static
     - choices=8, verbose=Quelltyp, max_length=32
   * - source_path
     - CharField
     - blank
     - verbose=Quellpfad / Resolver, max_length=255
   * - static_value
     - CharField
     - blank
     - verbose=Statischer Wert, max_length=255
   * - value_kind
     - CharField
     - blank, default=text
     - verbose=Wertetyp, max_length=32
   * - is_required
     - BooleanField
     - default=False
     - verbose=Pflichtfeld
   * - help_text
     - CharField
     - blank
     - verbose=Hinweis, max_length=255
   * - is_active
     - BooleanField
     - default=True
     - verbose=Aktiv
   * - priority
     - PositiveIntegerField
     - default=100
     - verbose=Prioritaet

Admin-Konfiguration
^^^^^^^^^^^^^^^^^^^

.. list-table::
   :header-rows: 1

   * - Aspekt
     - Wert
   * - Admin-Klasse
     - microtech.admin.MicrotechSwissCustomsFieldMappingAdmin
   * - list_display
     - priority, portal_field, section, source_type, source_preview_short, is_required, is_active, updated_at
   * - list_filter
     - is_active, section, source_type, is_required, value_kind
   * - search_fields
     - portal_field, source_path, static_value, help_text
   * - readonly_fields
     - created_at, updated_at
   * - ordering
     - priority, portal_field, id
   * - list_select_related
     - False
   * - list_per_page
     - 100
   * - inlines
     - -
   * - actions
     - -
   * - action_form
     - unfold.forms.ActionForm

orders
------

orders.Order
~~~~~~~~~~~~

* Python: ``orders.models.Order``
* DB-Tabelle: ``orders_order``
* Verbose Name: ``Bestellung``
* Verbose Name Plural: ``Bestellungen``
* Default Ordering: ``-purchase_date, -created_at``

Felder
^^^^^^

.. list-table::
   :header-rows: 1

   * - Feld
     - Typ
     - Optionen
     - Details
   * - id
     - BigAutoField
     - pk, unique, blank
     - verbose=ID
   * - created_at
     - DateTimeField
     - blank
     - verbose=Angelegt am
   * - updated_at
     - DateTimeField
     - blank
     - verbose=Aktualisiert am
   * - api_id
     - CharField
     - unique
     - verbose=Shopware Bestell-ID, max_length=64
   * - api_delivery_id
     - CharField
     - blank
     - verbose=Shopware Liefer-ID, max_length=64
   * - api_transaction_id
     - CharField
     - blank
     - verbose=Shopware Transaktions-ID, max_length=64
   * - sales_channel_id
     - CharField
     - blank
     - verbose=Verkaufskanal-ID, max_length=255
   * - order_number
     - CharField
     - db_index, blank
     - verbose=Bestellnummer, max_length=255
   * - erp_order_id
     - CharField
     - blank
     - verbose=ERP Vorgangsnummer, max_length=255
   * - description
     - TextField
     - blank
     - verbose=Beschreibung
   * - total_price
     - DecimalField
     - default=0.00
     - verbose=Gesamtpreis, decimal=12/2
   * - total_tax
     - DecimalField
     - default=0.00
     - verbose=Steuer gesamt, decimal=12/2
   * - shipping_costs
     - DecimalField
     - default=0.00
     - verbose=Versandkosten, decimal=12/2
   * - payment_method
     - CharField
     - blank
     - verbose=Zahlungsart, max_length=255
   * - shipping_method
     - CharField
     - blank
     - verbose=Versandart, max_length=255
   * - order_state
     - CharField
     - blank
     - verbose=Bestellstatus, max_length=64
   * - shipping_state
     - CharField
     - blank
     - verbose=Versandstatus, max_length=64
   * - payment_state
     - CharField
     - blank
     - verbose=Zahlstatus, max_length=64
   * - purchase_date
     - DateTimeField
     - null, blank
     - verbose=Bestelldatum
   * - customer
     - ForeignKey
     - db_index, null, blank
     - relation=customer.Customer, verbose=Kunde
   * - billing_address
     - ForeignKey
     - db_index, null, blank
     - relation=customer.Address, verbose=Rechnungsanschrift
   * - shipping_address
     - ForeignKey
     - db_index, null, blank
     - relation=customer.Address, verbose=Lieferanschrift

Admin-Konfiguration
^^^^^^^^^^^^^^^^^^^

.. list-table::
   :header-rows: 1

   * - Aspekt
     - Wert
   * - Admin-Klasse
     - orders.admin.OrderAdmin
   * - list_display
     - order_number, customer, total_price, purchase_date, order_state
   * - list_filter
     - ('order_state', <class 'unfold.contrib.filters.admin.text_filters.FieldTextFilter'>), ('payment_state', <class 'unfold.contrib.filters.admin.text_filters.FieldTextFilter'>), ('shipping_state', <class 'unfold.contrib.filters.admin.text_filters.FieldTextFilter'>), ('purchase_date', <class 'unfold.contrib.filters.admin.datetime_filters.RangeDateTimeFilter'>), ('created_at', <class 'unfold.contrib.filters.admin.datetime_filters.RangeDateTimeFilter'>)
   * - search_fields
     - order_number, api_id, customer__erp_nr, customer__email
   * - readonly_fields
     - created_at, updated_at
   * - ordering
     - -created_at
   * - list_select_related
     - False
   * - list_per_page
     - 100
   * - inlines
     - orders.admin.OrderDetailInline
   * - actions
     - sync_open_orders_from_shopware
   * - action_form
     - unfold.forms.ActionForm

orders.OrderDetail
~~~~~~~~~~~~~~~~~~

* Python: ``orders.models.OrderDetail``
* DB-Tabelle: ``orders_orderdetail``
* Verbose Name: ``Bestellposition``
* Verbose Name Plural: ``Bestellpositionen``
* Default Ordering: ``order, id``

Felder
^^^^^^

.. list-table::
   :header-rows: 1

   * - Feld
     - Typ
     - Optionen
     - Details
   * - id
     - BigAutoField
     - pk, unique, blank
     - verbose=ID
   * - created_at
     - DateTimeField
     - blank
     - verbose=Angelegt am
   * - updated_at
     - DateTimeField
     - blank
     - verbose=Aktualisiert am
   * - order
     - ForeignKey
     - db_index
     - relation=orders.Order, verbose=Bestellung
   * - api_id
     - CharField
     - blank
     - verbose=Shopware Position-ID, max_length=64
   * - erp_nr
     - CharField
     - blank
     - verbose=ERP-Nummer, max_length=255
   * - name
     - CharField
     - blank
     - verbose=Bezeichnung, max_length=255
   * - unit
     - CharField
     - blank
     - verbose=Einheit, max_length=64
   * - quantity
     - IntegerField
     - default=0
     - verbose=Menge
   * - unit_price
     - DecimalField
     - default=0.00
     - verbose=Einzelpreis, decimal=12/2
   * - total_price
     - DecimalField
     - default=0.00
     - verbose=Gesamtpreis, decimal=12/2
   * - tax
     - DecimalField
     - null, blank
     - verbose=Steuer, decimal=12/2

Admin-Konfiguration
^^^^^^^^^^^^^^^^^^^

.. list-table::
   :header-rows: 1

   * - Aspekt
     - Wert
   * - Admin-Klasse
     - orders.admin.OrderDetailAdmin
   * - list_display
     - order, erp_nr, name, quantity, unit_price, total_price, created_at
   * - list_filter
     - ('created_at', <class 'unfold.contrib.filters.admin.datetime_filters.RangeDateTimeFilter'>)
   * - search_fields
     - order__order_number, order__api_id, erp_nr, name
   * - readonly_fields
     - created_at, updated_at
   * - ordering
     - -created_at
   * - list_select_related
     - False
   * - list_per_page
     - 100
   * - inlines
     - -
   * - actions
     - -
   * - action_form
     - unfold.forms.ActionForm

products
--------

products.Category
~~~~~~~~~~~~~~~~~

* Python: ``products.models.Category``
* DB-Tabelle: ``products_category``
* Verbose Name: ``Kategorie``
* Verbose Name Plural: ``Kategorien``
* Default Ordering: ``-``

Felder
^^^^^^

.. list-table::
   :header-rows: 1

   * - Feld
     - Typ
     - Optionen
     - Details
   * - id
     - BigAutoField
     - pk, unique, blank
     - verbose=ID
   * - created_at
     - DateTimeField
     - blank
     - verbose=Angelegt am
   * - updated_at
     - DateTimeField
     - blank
     - verbose=Aktualisiert am
   * - name
     - CharField
     - -
     - verbose=Name, max_length=128
   * - name_de
     - TranslationCharField
     - null, blank
     - verbose=Name [de], max_length=128
   * - name_en
     - TranslationCharField
     - null, blank
     - verbose=Name [en], max_length=128
   * - slug
     - SlugField
     - unique, db_index
     - verbose=Slug, max_length=160
   * - parent
     - TreeForeignKey
     - db_index, null, blank
     - relation=products.Category, verbose=Oberkategorie
   * - legacy_erp_nr
     - PositiveIntegerField
     - unique, db_index, null, blank
     - verbose=Legacy ERP-Nummer
   * - legacy_api_id
     - CharField
     - db_index, blank
     - verbose=Legacy API-ID, max_length=36
   * - legacy_parent_erp_nr
     - PositiveIntegerField
     - db_index, null, blank
     - verbose=Legacy Parent ERP-Nummer
   * - image
     - CharField
     - blank
     - verbose=Bild, max_length=255
   * - description
     - TextField
     - blank
     - verbose=Beschreibung
   * - legacy_changed_at
     - DateTimeField
     - null, blank
     - verbose=Legacy geaendert am
   * - sort_order
     - PositiveIntegerField
     - db_index, default=1000
     - verbose=Sortierung
   * - lft
     - PositiveIntegerField
     - db_index, default=0
     - -
   * - rght
     - PositiveIntegerField
     - db_index, default=0
     - -
   * - tree_id
     - PositiveIntegerField
     - db_index, default=0
     - verbose=tree id
   * - level
     - PositiveIntegerField
     - db_index, default=0
     - -

Admin-Konfiguration
^^^^^^^^^^^^^^^^^^^

.. list-table::
   :header-rows: 1

   * - Aspekt
     - Wert
   * - Admin-Klasse
     - products.admin.CategoryAdmin
   * - list_display
     - name, slug, legacy_erp_nr, parent, sort_order, created_at
   * - list_filter
     - ('parent', <class 'unfold.contrib.filters.admin.dropdown_filters.RelatedDropdownFilter'>), ('created_at', <class 'unfold.contrib.filters.admin.datetime_filters.RangeDateTimeFilter'>)
   * - search_fields
     - name, slug, legacy_erp_nr, legacy_api_id, parent__name
   * - readonly_fields
     - created_at, updated_at, legacy_erp_nr, legacy_api_id, legacy_parent_erp_nr
   * - ordering
     - tree_id, lft
   * - list_select_related
     - False
   * - list_per_page
     - 100
   * - inlines
     - -
   * - actions
     - -
   * - action_form
     - unfold.forms.ActionForm

products.Image
~~~~~~~~~~~~~~

* Python: ``products.models.Image``
* DB-Tabelle: ``products_image``
* Verbose Name: ``Bild``
* Verbose Name Plural: ``Bilder``
* Default Ordering: ``id``

Felder
^^^^^^

.. list-table::
   :header-rows: 1

   * - Feld
     - Typ
     - Optionen
     - Details
   * - id
     - BigAutoField
     - pk, unique, blank
     - verbose=ID
   * - created_at
     - DateTimeField
     - blank
     - verbose=Angelegt am
   * - updated_at
     - DateTimeField
     - blank
     - verbose=Aktualisiert am
   * - path
     - CharField
     - -
     - verbose=Bildpfad, max_length=255
   * - alt_text
     - CharField
     - blank
     - verbose=Alternativtext, max_length=255

Admin-Konfiguration
^^^^^^^^^^^^^^^^^^^

.. list-table::
   :header-rows: 1

   * - Aspekt
     - Wert
   * - Admin-Klasse
     - products.admin.ImageAdmin
   * - list_display
     - image_preview, path, alt_text, created_at
   * - list_filter
     - -
   * - search_fields
     - path, alt_text
   * - readonly_fields
     - created_at, updated_at
   * - ordering
     - -created_at
   * - list_select_related
     - False
   * - list_per_page
     - 100
   * - inlines
     - -
   * - actions
     - -
   * - action_form
     - unfold.forms.ActionForm

products.Price
~~~~~~~~~~~~~~

* Python: ``products.models.Price``
* DB-Tabelle: ``products_price``
* Verbose Name: ``Preis``
* Verbose Name Plural: ``Preise``
* Default Ordering: ``product, sales_channel, price``

Felder
^^^^^^

.. list-table::
   :header-rows: 1

   * - Feld
     - Typ
     - Optionen
     - Details
   * - id
     - BigAutoField
     - pk, unique, blank
     - verbose=ID
   * - created_at
     - DateTimeField
     - blank
     - verbose=Angelegt am
   * - updated_at
     - DateTimeField
     - blank
     - verbose=Aktualisiert am
   * - product
     - ForeignKey
     - db_index
     - relation=products.Product, verbose=Produkt
   * - sales_channel
     - ForeignKey
     - db_index, null, blank
     - relation=shopware.ShopwareSettings, verbose=Verkaufskanal
   * - price
     - DecimalField
     - -
     - verbose=Preis, decimal=10/2
   * - rebate_quantity
     - IntegerField
     - null, blank
     - verbose=Staffelmenge
   * - rebate_price
     - DecimalField
     - null, blank
     - verbose=Staffelpreis, decimal=10/2
   * - special_percentage
     - DecimalField
     - null, blank
     - verbose=Sonderpreis (%), decimal=5/2
   * - special_price
     - DecimalField
     - null, blank
     - verbose=Sonderpreis, decimal=10/2
   * - special_start_date
     - DateTimeField
     - null, blank
     - verbose=Sonderpreis ab
   * - special_end_date
     - DateTimeField
     - null, blank
     - verbose=Sonderpreis bis

Admin-Konfiguration
^^^^^^^^^^^^^^^^^^^

.. list-table::
   :header-rows: 1

   * - Aspekt
     - Wert
   * - Admin-Klasse
     - products.admin.PriceAdmin
   * - list_display
     - product, sales_channel, price, special_percentage, special_price, special_active, rebate_price, created_at
   * - list_filter
     - ('sales_channel', <class 'unfold.contrib.filters.admin.dropdown_filters.RelatedDropdownFilter'>), ('price', <class 'unfold.contrib.filters.admin.numeric_filters.RangeNumericFilter'>), ('created_at', <class 'unfold.contrib.filters.admin.datetime_filters.RangeDateTimeFilter'>)
   * - search_fields
     - product__erp_nr, product__name, sales_channel__name
   * - readonly_fields
     - created_at, updated_at
   * - ordering
     - -created_at
   * - list_select_related
     - False
   * - list_per_page
     - 100
   * - inlines
     - products.admin.PriceHistoryInline
   * - actions
     - set_special_price_bulk, clear_special_price_bulk
   * - action_form
     - products.admin.PriceActionForm

products.PriceHistory
~~~~~~~~~~~~~~~~~~~~~

* Python: ``products.models.PriceHistory``
* DB-Tabelle: ``products_pricehistory``
* Verbose Name: ``Preis-Historie``
* Verbose Name Plural: ``Preis-Historie``
* Default Ordering: ``-created_at, -id``

Felder
^^^^^^

.. list-table::
   :header-rows: 1

   * - Feld
     - Typ
     - Optionen
     - Details
   * - id
     - BigAutoField
     - pk, unique, blank
     - verbose=ID
   * - created_at
     - DateTimeField
     - blank
     - verbose=Angelegt am
   * - updated_at
     - DateTimeField
     - blank
     - verbose=Aktualisiert am
   * - price_entry
     - ForeignKey
     - db_index
     - relation=products.Price, verbose=Preis
   * - change_type
     - CharField
     - default=updated
     - choices=2, verbose=Aenderungstyp, max_length=16
   * - changed_fields
     - CharField
     - blank
     - verbose=Geaenderte Felder, max_length=255
   * - price
     - DecimalField
     - -
     - verbose=Preis, decimal=10/2
   * - rebate_quantity
     - IntegerField
     - null, blank
     - verbose=Staffelmenge
   * - rebate_price
     - DecimalField
     - null, blank
     - verbose=Staffelpreis, decimal=10/2
   * - special_percentage
     - DecimalField
     - null, blank
     - verbose=Sonderpreis (%), decimal=5/2
   * - special_price
     - DecimalField
     - null, blank
     - verbose=Sonderpreis, decimal=10/2
   * - special_start_date
     - DateTimeField
     - null, blank
     - verbose=Sonderpreis ab
   * - special_end_date
     - DateTimeField
     - null, blank
     - verbose=Sonderpreis bis

Admin-Konfiguration
^^^^^^^^^^^^^^^^^^^

.. list-table::
   :header-rows: 1

   * - Aspekt
     - Wert
   * - Admin-Klasse
     - products.admin.PriceHistoryAdmin
   * - list_display
     - price_entry, change_type, changed_fields, price, special_price, rebate_quantity, rebate_price, created_at
   * - list_filter
     - change_type, ('created_at', <class 'unfold.contrib.filters.admin.datetime_filters.RangeDateTimeFilter'>)
   * - search_fields
     - price_entry__product__erp_nr, price_entry__product__name, price_entry__sales_channel__name, changed_fields
   * - readonly_fields
     - created_at, updated_at
   * - ordering
     - -created_at
   * - list_select_related
     - False
   * - list_per_page
     - 100
   * - inlines
     - -
   * - actions
     - -
   * - action_form
     - unfold.forms.ActionForm

products.PriceIncrease
~~~~~~~~~~~~~~~~~~~~~~

* Python: ``products.models.PriceIncrease``
* DB-Tabelle: ``products_priceincrease``
* Verbose Name: ``Preiserhoehung``
* Verbose Name Plural: ``Preiserhoehungen``
* Default Ordering: ``-created_at, -id``

Felder
^^^^^^

.. list-table::
   :header-rows: 1

   * - Feld
     - Typ
     - Optionen
     - Details
   * - id
     - BigAutoField
     - pk, unique, blank
     - verbose=ID
   * - created_at
     - DateTimeField
     - blank
     - verbose=Angelegt am
   * - updated_at
     - DateTimeField
     - blank
     - verbose=Aktualisiert am
   * - title
     - CharField
     - -
     - verbose=Titel, max_length=255
   * - status
     - CharField
     - db_index, default=draft
     - choices=2, verbose=Status, max_length=16
   * - sales_channel
     - ForeignKey
     - db_index, null, blank
     - relation=shopware.ShopwareSettings, verbose=Standard-Verkaufskanal
   * - general_percentage
     - DecimalField
     - default=2.50
     - verbose=Generelle Erhoehung (%), decimal=5/2
   * - positions_synced_at
     - DateTimeField
     - null, blank
     - verbose=Positionen synchronisiert am
   * - applied_at
     - DateTimeField
     - null, blank
     - verbose=Uebernommen am

Admin-Konfiguration
^^^^^^^^^^^^^^^^^^^

.. list-table::
   :header-rows: 1

   * - Aspekt
     - Wert
   * - Admin-Klasse
     - products.admin.PriceIncreaseAdmin
   * - list_display
     - title, status, sales_channel, general_percentage, position_count, positions_synced_at, applied_at, created_at
   * - list_filter
     - status, ('created_at', <class 'unfold.contrib.filters.admin.datetime_filters.RangeDateTimeFilter'>), ('applied_at', <class 'unfold.contrib.filters.admin.datetime_filters.RangeDateTimeFilter'>)
   * - search_fields
     - title, sales_channel__name
   * - readonly_fields
     - created_at, updated_at, status, sales_channel, position_count, positions_synced_at, applied_at
   * - ordering
     - -created_at
   * - list_select_related
     - False
   * - list_per_page
     - 100
   * - inlines
     - -
   * - actions
     - export_price_list_pdf
   * - action_form
     - unfold.forms.ActionForm

products.PriceIncreaseItem
~~~~~~~~~~~~~~~~~~~~~~~~~~

* Python: ``products.models.PriceIncreaseItem``
* DB-Tabelle: ``products_priceincreaseitem``
* Verbose Name: ``Preiserhoehungs-Position``
* Verbose Name Plural: ``Preiserhoehungs-Positionen``
* Default Ordering: ``product__erp_nr, id``

Felder
^^^^^^

.. list-table::
   :header-rows: 1

   * - Feld
     - Typ
     - Optionen
     - Details
   * - id
     - BigAutoField
     - pk, unique, blank
     - verbose=ID
   * - created_at
     - DateTimeField
     - blank
     - verbose=Angelegt am
   * - updated_at
     - DateTimeField
     - blank
     - verbose=Aktualisiert am
   * - price_increase
     - ForeignKey
     - db_index
     - relation=products.PriceIncrease, verbose=Preiserhoehung
   * - product
     - ForeignKey
     - db_index
     - relation=products.Product, verbose=Produkt
   * - source_price
     - ForeignKey
     - db_index
     - relation=products.Price, verbose=Quellpreis
   * - unit
     - CharField
     - blank
     - verbose=Einheit, max_length=255
   * - current_price
     - DecimalField
     - -
     - verbose=Aktueller Preis, decimal=10/2
   * - current_rebate_quantity
     - IntegerField
     - null, blank
     - verbose=Aktuelle Staffelmenge
   * - current_rebate_price
     - DecimalField
     - null, blank
     - verbose=Aktueller Staffelpreis, decimal=10/2
   * - new_price
     - DecimalField
     - null, blank
     - verbose=Neuer Preis, decimal=10/2
   * - new_rebate_price
     - DecimalField
     - null, blank
     - verbose=neuer Rab.Preis, decimal=10/2
   * - last_status_message
     - CharField
     - blank
     - verbose=Letzter Status, max_length=255
   * - last_changed_by
     - ForeignKey
     - db_index, null, blank
     - relation=auth.User, verbose=Letzte Aenderung durch
   * - last_changed_at
     - DateTimeField
     - null, blank
     - verbose=Letzte Aenderung am

Admin-Konfiguration
^^^^^^^^^^^^^^^^^^^

.. list-table::
   :header-rows: 1

   * - Aspekt
     - Wert
   * - Admin-Klasse
     - products.admin.PriceIncreaseItemAdmin
   * - list_display
     - erp_nr_display, price_display, rebate_quantity_display, rebate_price_display, unit_display, new_price, new_rebate_price
   * - list_filter
     - ('price_increase', <class 'unfold.contrib.filters.admin.dropdown_filters.RelatedDropdownFilter'>)
   * - search_fields
     - price_increase__title, product__erp_nr, product__name
   * - readonly_fields
     - price_increase, product, source_price, unit, current_price, current_rebate_quantity, current_rebate_price
   * - ordering
     - product__erp_nr, id
   * - list_select_related
     - False
   * - list_per_page
     - 200
   * - inlines
     - -
   * - actions
     - -
   * - action_form
     - unfold.forms.ActionForm

products.Product
~~~~~~~~~~~~~~~~

* Python: ``products.models.Product``
* DB-Tabelle: ``products_product``
* Verbose Name: ``Produkt``
* Verbose Name Plural: ``Produkte``
* Default Ordering: ``erp_nr, name``

Felder
^^^^^^

.. list-table::
   :header-rows: 1

   * - Feld
     - Typ
     - Optionen
     - Details
   * - id
     - BigAutoField
     - pk, unique, blank
     - verbose=ID
   * - created_at
     - DateTimeField
     - blank
     - verbose=Angelegt am
   * - updated_at
     - DateTimeField
     - blank
     - verbose=Aktualisiert am
   * - shopware_image_sync_hash
     - CharField
     - blank
     - verbose=Shopware Bild-Sync-Hash, max_length=64
   * - sku
     - CharField
     - unique, null, blank
     - verbose=Artikelnummer (SKU), max_length=64
   * - erp_nr
     - CharField
     - unique
     - verbose=ERP-Nummer, max_length=64
   * - gtin
     - CharField
     - blank
     - verbose=GTIN, max_length=32
   * - name
     - CharField
     - null, blank
     - verbose=Name, max_length=255
   * - name_de
     - TranslationCharField
     - null, blank
     - verbose=Name [de], max_length=255
   * - name_en
     - TranslationCharField
     - null, blank
     - verbose=Name [en], max_length=255
   * - sort_order
     - PositiveIntegerField
     - default=1000
     - verbose=Sortierung
   * - description
     - TextField
     - null, blank
     - verbose=Beschreibung
   * - description_de
     - TranslationTextField
     - null, blank
     - verbose=Beschreibung [de]
   * - description_en
     - TranslationTextField
     - null, blank
     - verbose=Beschreibung [en]
   * - description_short
     - TextField
     - null, blank
     - verbose=Kurzbeschreibung
   * - description_short_de
     - TranslationTextField
     - null, blank
     - verbose=Kurzbeschreibung [de]
   * - description_short_en
     - TranslationTextField
     - null, blank
     - verbose=Kurzbeschreibung [en]
   * - is_active
     - BooleanField
     - default=True
     - verbose=Aktiv
   * - factor
     - IntegerField
     - null, blank
     - verbose=Faktor
   * - unit
     - CharField
     - null, blank
     - verbose=Einheit, max_length=255
   * - unit_de
     - TranslationCharField
     - null, blank
     - verbose=Einheit [de], max_length=255
   * - unit_en
     - TranslationCharField
     - null, blank
     - verbose=Einheit [en], max_length=255
   * - min_purchase
     - IntegerField
     - null, blank
     - verbose=Mindestabnahme
   * - purchase_unit
     - IntegerField
     - null, blank
     - verbose=Kaufeinheit
   * - customs_tariff_number
     - CharField
     - blank
     - verbose=Statistische Warennummer, max_length=32
   * - weight_gross
     - DecimalField
     - null, blank
     - verbose=Bruttogewicht (kg), decimal=10/4
   * - weight_net
     - DecimalField
     - null, blank
     - verbose=Nettogewicht (kg), decimal=10/4
   * - tax
     - ForeignKey
     - db_index, null, blank
     - relation=products.Tax, verbose=Steuer
   * - categories
     - ManyToManyField
     - blank
     - relation=products.Category, verbose=Kategorien
   * - images
     - ManyToManyField
     - blank
     - relation=products.Image, verbose=Bilder
   * - properties
     - ManyToManyField
     - blank
     - relation=products.PropertyValue, verbose=Attribute

Admin-Konfiguration
^^^^^^^^^^^^^^^^^^^

.. list-table::
   :header-rows: 1

   * - Aspekt
     - Wert
   * - Admin-Klasse
     - products.admin.ProductAdmin
   * - list_display
     - image_preview, erp_nr, name, customs_tariff_number, is_active, created_at
   * - list_filter
     - ('is_active', <class 'unfold.contrib.filters.admin.choice_filters.BooleanRadioFilter'>), ('tax', <class 'unfold.contrib.filters.admin.dropdown_filters.RelatedDropdownFilter'>), ('categories', <class 'unfold.contrib.filters.admin.dropdown_filters.RelatedDropdownFilter'>), ('created_at', <class 'unfold.contrib.filters.admin.datetime_filters.RangeDateTimeFilter'>)
   * - search_fields
     - erp_nr, sku, name
   * - readonly_fields
     - created_at, updated_at
   * - ordering
     - -is_active, erp_nr
   * - list_select_related
     - False
   * - list_per_page
     - 100
   * - inlines
     - products.admin.ProductImageInline, products.admin.ProductPropertyInline, products.admin.StorageInline, products.admin.PriceInline
   * - actions
     - sync_from_microtech, sync_to_shopware, set_special_price_for_channel, clear_special_price_for_channel
   * - action_form
     - products.admin.ProductSpecialPriceActionForm

products.ProductImage
~~~~~~~~~~~~~~~~~~~~~

* Python: ``products.models.ProductImage``
* DB-Tabelle: ``products_productimage``
* Verbose Name: ``Produktbild``
* Verbose Name Plural: ``Produktbilder``
* Default Ordering: ``product, order, id``

Felder
^^^^^^

.. list-table::
   :header-rows: 1

   * - Feld
     - Typ
     - Optionen
     - Details
   * - id
     - BigAutoField
     - pk, unique, blank
     - verbose=ID
   * - created_at
     - DateTimeField
     - blank
     - verbose=Angelegt am
   * - updated_at
     - DateTimeField
     - blank
     - verbose=Aktualisiert am
   * - product
     - ForeignKey
     - db_index
     - relation=products.Product, verbose=Produkt
   * - image
     - ForeignKey
     - db_index
     - relation=products.Image, verbose=Bild
   * - order
     - PositiveIntegerField
     - db_index, default=1
     - verbose=Reihenfolge

Admin-Konfiguration
^^^^^^^^^^^^^^^^^^^

.. list-table::
   :header-rows: 1

   * - Aspekt
     - Wert
   * - Registrierung
     - Kein ModelAdmin registriert

products.ProductProperty
~~~~~~~~~~~~~~~~~~~~~~~~

* Python: ``products.models.ProductProperty``
* DB-Tabelle: ``products_productproperty``
* Verbose Name: ``Produktattribut``
* Verbose Name Plural: ``Produktattribute``
* Default Ordering: ``product__erp_nr, value__group__name, value__name``

Felder
^^^^^^

.. list-table::
   :header-rows: 1

   * - Feld
     - Typ
     - Optionen
     - Details
   * - id
     - BigAutoField
     - pk, unique, blank
     - verbose=ID
   * - created_at
     - DateTimeField
     - blank
     - verbose=Angelegt am
   * - updated_at
     - DateTimeField
     - blank
     - verbose=Aktualisiert am
   * - external_key
     - CharField
     - db_index, blank
     - verbose=Externe Referenz, max_length=255
   * - product
     - ForeignKey
     - db_index
     - relation=products.Product, verbose=Produkt
   * - value
     - ForeignKey
     - db_index
     - relation=products.PropertyValue, verbose=Attributwert

Admin-Konfiguration
^^^^^^^^^^^^^^^^^^^

.. list-table::
   :header-rows: 1

   * - Aspekt
     - Wert
   * - Registrierung
     - Kein ModelAdmin registriert

products.PropertyGroup
~~~~~~~~~~~~~~~~~~~~~~

* Python: ``products.models.PropertyGroup``
* DB-Tabelle: ``products_propertygroup``
* Verbose Name: ``Attributgruppe``
* Verbose Name Plural: ``Attributgruppen``
* Default Ordering: ``name``

Felder
^^^^^^

.. list-table::
   :header-rows: 1

   * - Feld
     - Typ
     - Optionen
     - Details
   * - id
     - BigAutoField
     - pk, unique, blank
     - verbose=ID
   * - created_at
     - DateTimeField
     - blank
     - verbose=Angelegt am
   * - updated_at
     - DateTimeField
     - blank
     - verbose=Aktualisiert am
   * - external_key
     - CharField
     - db_index, blank
     - verbose=Externe Referenz, max_length=255
   * - name
     - CharField
     - -
     - verbose=Name, max_length=255
   * - name_de
     - TranslationCharField
     - null, blank
     - verbose=Name [de], max_length=255
   * - name_en
     - TranslationCharField
     - null, blank
     - verbose=Name [en], max_length=255

Admin-Konfiguration
^^^^^^^^^^^^^^^^^^^

.. list-table::
   :header-rows: 1

   * - Aspekt
     - Wert
   * - Admin-Klasse
     - products.admin.PropertyGroupAdmin
   * - list_display
     - name, created_at
   * - list_filter
     - -
   * - search_fields
     - name, name_de, name_en
   * - readonly_fields
     - created_at, updated_at
   * - ordering
     - name
   * - list_select_related
     - False
   * - list_per_page
     - 100
   * - inlines
     - -
   * - actions
     - -
   * - action_form
     - unfold.forms.ActionForm

products.PropertyValue
~~~~~~~~~~~~~~~~~~~~~~

* Python: ``products.models.PropertyValue``
* DB-Tabelle: ``products_propertyvalue``
* Verbose Name: ``Attributwert``
* Verbose Name Plural: ``Attributwerte``
* Default Ordering: ``group__name, name``

Felder
^^^^^^

.. list-table::
   :header-rows: 1

   * - Feld
     - Typ
     - Optionen
     - Details
   * - id
     - BigAutoField
     - pk, unique, blank
     - verbose=ID
   * - created_at
     - DateTimeField
     - blank
     - verbose=Angelegt am
   * - updated_at
     - DateTimeField
     - blank
     - verbose=Aktualisiert am
   * - external_key
     - CharField
     - db_index, blank
     - verbose=Externe Referenz, max_length=255
   * - group
     - ForeignKey
     - db_index
     - relation=products.PropertyGroup, verbose=Attributgruppe
   * - name
     - CharField
     - -
     - verbose=Wert, max_length=255
   * - name_de
     - TranslationCharField
     - null, blank
     - verbose=Wert [de], max_length=255
   * - name_en
     - TranslationCharField
     - null, blank
     - verbose=Wert [en], max_length=255

Admin-Konfiguration
^^^^^^^^^^^^^^^^^^^

.. list-table::
   :header-rows: 1

   * - Aspekt
     - Wert
   * - Admin-Klasse
     - products.admin.PropertyValueAdmin
   * - list_display
     - name, group, external_key, created_at
   * - list_filter
     - ('group', <class 'unfold.contrib.filters.admin.dropdown_filters.RelatedDropdownFilter'>), ('created_at', <class 'unfold.contrib.filters.admin.datetime_filters.RangeDateTimeFilter'>)
   * - search_fields
     - name, name_de, name_en, group__name, group__name_de, external_key
   * - readonly_fields
     - created_at, updated_at
   * - ordering
     - group__name, name
   * - list_select_related
     - False
   * - list_per_page
     - 100
   * - inlines
     - -
   * - actions
     - -
   * - action_form
     - unfold.forms.ActionForm

products.Storage
~~~~~~~~~~~~~~~~

* Python: ``products.models.Storage``
* DB-Tabelle: ``products_storage``
* Verbose Name: ``Lagerbestand``
* Verbose Name Plural: ``Lagerbestaende``
* Default Ordering: ``product``

Felder
^^^^^^

.. list-table::
   :header-rows: 1

   * - Feld
     - Typ
     - Optionen
     - Details
   * - id
     - BigAutoField
     - pk, unique, blank
     - verbose=ID
   * - created_at
     - DateTimeField
     - blank
     - verbose=Angelegt am
   * - updated_at
     - DateTimeField
     - blank
     - verbose=Aktualisiert am
   * - product
     - OneToOneField
     - unique, db_index, null, blank
     - relation=products.Product, verbose=Produkt
   * - stock
     - IntegerField
     - null, blank
     - verbose=Bestand
   * - location
     - CharField
     - null, blank
     - verbose=Lagerort, max_length=255
   * - virtual_stock
     - PositiveIntegerField
     - default=0
     - verbose=Virtueller Bestand

Admin-Konfiguration
^^^^^^^^^^^^^^^^^^^

.. list-table::
   :header-rows: 1

   * - Aspekt
     - Wert
   * - Admin-Klasse
     - products.admin.StorageAdmin
   * - list_display
     - product, stock, virtual_stock, location, created_at
   * - list_filter
     - ('stock', <class 'unfold.contrib.filters.admin.numeric_filters.RangeNumericFilter'>), ('created_at', <class 'unfold.contrib.filters.admin.datetime_filters.RangeDateTimeFilter'>)
   * - search_fields
     - product__erp_nr, product__name, location
   * - readonly_fields
     - created_at, updated_at
   * - ordering
     - -created_at
   * - list_select_related
     - False
   * - list_per_page
     - 100
   * - inlines
     - -
   * - actions
     - -
   * - action_form
     - unfold.forms.ActionForm

products.Tax
~~~~~~~~~~~~

* Python: ``products.models.Tax``
* DB-Tabelle: ``products_tax``
* Verbose Name: ``Steuer``
* Verbose Name Plural: ``Steuern``
* Default Ordering: ``name``

Felder
^^^^^^

.. list-table::
   :header-rows: 1

   * - Feld
     - Typ
     - Optionen
     - Details
   * - id
     - BigAutoField
     - pk, unique, blank
     - verbose=ID
   * - created_at
     - DateTimeField
     - blank
     - verbose=Angelegt am
   * - updated_at
     - DateTimeField
     - blank
     - verbose=Aktualisiert am
   * - name
     - CharField
     - -
     - verbose=Steuerbezeichnung, max_length=64
   * - rate
     - DecimalField
     - -
     - verbose=Steuersatz (%), decimal=5/2
   * - shopware_id
     - CharField
     - blank
     - verbose=Shopware Steuer-ID, max_length=64

Admin-Konfiguration
^^^^^^^^^^^^^^^^^^^

.. list-table::
   :header-rows: 1

   * - Aspekt
     - Wert
   * - Admin-Klasse
     - products.admin.TaxAdmin
   * - list_display
     - name, rate, shopware_id, created_at
   * - list_filter
     - ('rate', <class 'unfold.contrib.filters.admin.numeric_filters.RangeNumericFilter'>), ('created_at', <class 'unfold.contrib.filters.admin.datetime_filters.RangeDateTimeFilter'>)
   * - search_fields
     - name, shopware_id
   * - readonly_fields
     - created_at, updated_at
   * - ordering
     - -created_at
   * - list_select_related
     - False
   * - list_per_page
     - 100
   * - inlines
     - -
   * - actions
     - -
   * - action_form
     - unfold.forms.ActionForm

shopware
--------

shopware.ShopwareConnection
~~~~~~~~~~~~~~~~~~~~~~~~~~~

* Python: ``shopware.models.ShopwareConnection``
* DB-Tabelle: ``shopware_shopwareconnection``
* Verbose Name: ``Shopware Verbindung``
* Verbose Name Plural: ``Shopware Verbindung``
* Default Ordering: ``-``

Felder
^^^^^^

.. list-table::
   :header-rows: 1

   * - Feld
     - Typ
     - Optionen
     - Details
   * - id
     - BigAutoField
     - pk, unique, blank
     - verbose=ID
   * - created_at
     - DateTimeField
     - blank
     - verbose=Angelegt am
   * - updated_at
     - DateTimeField
     - blank
     - verbose=Aktualisiert am
   * - api_url
     - CharField
     - -
     - help=z.B. https://mein-shop.de/api, verbose=API URL, max_length=500
   * - client_id
     - CharField
     - blank
     - verbose=Client ID, max_length=255
   * - client_secret
     - CharField
     - blank
     - verbose=Client Secret, max_length=500
   * - grant_type
     - CharField
     - default=resource_owner
     - choices=2, verbose=Grant Type, max_length=32
   * - username
     - CharField
     - blank
     - verbose=Benutzername, max_length=255
   * - password
     - CharField
     - blank
     - verbose=Passwort, max_length=500

Admin-Konfiguration
^^^^^^^^^^^^^^^^^^^

.. list-table::
   :header-rows: 1

   * - Aspekt
     - Wert
   * - Admin-Klasse
     - shopware.admin.ShopwareConnectionAdmin
   * - list_display
     - __str__
   * - list_filter
     - -
   * - search_fields
     - -
   * - readonly_fields
     - created_at, updated_at
   * - ordering
     - -created_at
   * - list_select_related
     - False
   * - list_per_page
     - 100
   * - inlines
     - -
   * - actions
     - -
   * - action_form
     - unfold.forms.ActionForm

shopware.ShopwareSettings
~~~~~~~~~~~~~~~~~~~~~~~~~

* Python: ``shopware.models.ShopwareSettings``
* DB-Tabelle: ``shopware_shopwaresettings``
* Verbose Name: ``Shopware Konfiguration``
* Verbose Name Plural: ``Shopware Konfigurationen``
* Default Ordering: ``-``

Felder
^^^^^^

.. list-table::
   :header-rows: 1

   * - Feld
     - Typ
     - Optionen
     - Details
   * - id
     - BigAutoField
     - pk, unique, blank
     - verbose=ID
   * - created_at
     - DateTimeField
     - blank
     - verbose=Angelegt am
   * - updated_at
     - DateTimeField
     - blank
     - verbose=Aktualisiert am
   * - name
     - CharField
     - unique
     - verbose=Bezeichnung, max_length=100
   * - sales_channel_id
     - CharField
     - blank
     - verbose=Verkaufskanal-ID, max_length=255
   * - tax_high_id
     - CharField
     - blank
     - verbose=Steuer-ID hoch, max_length=255
   * - tax_low_id
     - CharField
     - blank
     - verbose=Steuer-ID niedrig, max_length=255
   * - currency_id
     - CharField
     - blank
     - verbose=Waehrungs-ID, max_length=255
   * - rule_id_price
     - CharField
     - blank
     - verbose=Preisregel-ID, max_length=255
   * - price_factor
     - DecimalField
     - default=1.0
     - verbose=Preisfaktor, decimal=10/4
   * - is_default
     - BooleanField
     - default=False
     - verbose=Standardkanal
   * - is_active
     - BooleanField
     - default=True
     - verbose=Aktiv

Admin-Konfiguration
^^^^^^^^^^^^^^^^^^^

.. list-table::
   :header-rows: 1

   * - Aspekt
     - Wert
   * - Admin-Klasse
     - shopware.admin.ShopwareSettingsAdmin
   * - list_display
     - name, sales_channel_id, is_default, price_factor, is_active
   * - list_filter
     - ('is_default', <class 'unfold.contrib.filters.admin.choice_filters.BooleanRadioFilter'>), ('is_active', <class 'unfold.contrib.filters.admin.choice_filters.BooleanRadioFilter'>)
   * - search_fields
     - name, sales_channel_id
   * - readonly_fields
     - created_at, updated_at
   * - ordering
     - -created_at
   * - list_select_related
     - False
   * - list_per_page
     - 100
   * - inlines
     - -
   * - actions
     - -
   * - action_form
     - unfold.forms.ActionForm
