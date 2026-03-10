Model- und Admin-Inventar
=========================

Diese Seite wird automatisch aus dem Django-Projekt erzeugt und deckt alle lokalen Apps, Models und registrierten Admin-Klassen ab.

Generiert am: 2026-03-10 10:32:44 UTC

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
     - created_at, updated_at
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
     - choices=4, verbose=Engine Operator, max_length=16
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
     - ForeignKey
     - db_index, null, blank
     - relation=products.Category, verbose=Oberkategorie

Admin-Konfiguration
^^^^^^^^^^^^^^^^^^^

.. list-table::
   :header-rows: 1

   * - Aspekt
     - Wert
   * - Admin-Klasse
     - products.admin.CategoryAdmin
   * - list_display
     - name, slug, parent, created_at
   * - list_filter
     - ('parent', <class 'unfold.contrib.filters.admin.dropdown_filters.RelatedDropdownFilter'>), ('created_at', <class 'unfold.contrib.filters.admin.datetime_filters.RangeDateTimeFilter'>)
   * - search_fields
     - name, slug, parent__name
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
   * - Registrierung
     - Kein ModelAdmin registriert

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
     - -
   * - actions
     - set_special_price_bulk, clear_special_price_bulk
   * - action_form
     - products.admin.PriceActionForm

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

Admin-Konfiguration
^^^^^^^^^^^^^^^^^^^

.. list-table::
   :header-rows: 1

   * - Aspekt
     - Wert
   * - Admin-Klasse
     - products.admin.ProductAdmin
   * - list_display
     - erp_nr, name, is_active, created_at
   * - list_filter
     - ('is_active', <class 'unfold.contrib.filters.admin.choice_filters.BooleanRadioFilter'>), ('tax', <class 'unfold.contrib.filters.admin.dropdown_filters.RelatedDropdownFilter'>), ('categories', <class 'unfold.contrib.filters.admin.dropdown_filters.RelatedDropdownFilter'>), ('created_at', <class 'unfold.contrib.filters.admin.datetime_filters.RangeDateTimeFilter'>)
   * - search_fields
     - erp_nr, sku, name
   * - readonly_fields
     - created_at, updated_at
   * - ordering
     - -created_at
   * - list_select_related
     - False
   * - list_per_page
     - 100
   * - inlines
     - products.admin.StorageInline, products.admin.PriceInline
   * - actions
     - sync_from_microtech, sync_to_shopware, set_special_price_for_channel, clear_special_price_for_channel
   * - action_form
     - products.admin.ProductSpecialPriceActionForm

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
