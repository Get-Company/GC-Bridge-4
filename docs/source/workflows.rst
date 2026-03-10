Workflows
=========

Workflow 1: Produkte synchronisieren
------------------------------------

Ziel
^^^^

Produkte aus Microtech importieren, abgelaufene Sonderpreise bereinigen,
Rueckschreiben nach Microtech und anschliessend nach Shopware synchronisieren.

Befehl
^^^^^^

.. code-block:: bash

   .venv/bin/python manage.py scheduled_product_sync --limit 200

Windows:

.. code-block:: doscon

   .venv\Scripts\python.exe manage.py scheduled_product_sync --limit 200

Ablauf intern
^^^^^^^^^^^^^

1. ``microtech_sync_products --all``
2. Bereinigung abgelaufener Sonderpreise in ``products.Price``
3. Rueckschreiben bereinigter Sonderpreise nach Microtech
4. ``shopware_sync_products --all``

Wichtige Hinweise
^^^^^^^^^^^^^^^^^

- Mit ``--exclude-inactive`` werden inaktive Microtech-Artikel beim Import ausgelassen.
- Fuer Debug-Laeufe ``--limit`` klein halten.
- Basispreis-Writeback nach Microtech ist standardmaessig deaktiviert (Schutz vor Fehlskalierung).
- Falls zwingend noetig: ``--write-base-price-back``.

Workflow 2: Offene Shopware-Bestellungen laden
-----------------------------------------------

Ziel
^^^^

Offene Shopware-Bestellungen in Django ``orders.Order`` und ``orders.OrderDetail`` uebernehmen,
inklusive Kunden- und Adressdaten.

Befehl
^^^^^^

.. code-block:: bash

   .venv/bin/python manage.py shopware_sync_open_orders --limit-orders 100

Windows:

.. code-block:: doscon

   .venv\Scripts\python.exe manage.py shopware_sync_open_orders --limit-orders 100

Optionen
^^^^^^^^

- ``--sales-channel-id <id>`` (mehrfach nutzbar)
- ``--limit-orders <n>``

Workflow 3: Einzelbestellung nach Microtech upserten
-----------------------------------------------------

Ziel
^^^^

Eine konkrete Bestellung aus Django in Microtech als Vorgang schreiben oder aktualisieren.

Befehl mit Shopware-Bestellnummer
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

.. code-block:: bash

   .venv/bin/python manage.py microtech_order_upsert SW100045

Befehl mit interner Django-ID
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

.. code-block:: bash

   .venv/bin/python manage.py microtech_order_upsert --id 42

Logpfad anpassen
^^^^^^^^^^^^^^^^

.. code-block:: bash

   .venv/bin/python manage.py microtech_order_upsert SW100045 --log-file tmp/logs/microtech_order_upsert.log

Workflow 4: Rulebuilder-Regel mit Beispiel umsetzen (PayPal + AT)
------------------------------------------------------------------

Ziel
^^^^

Eine fachliche Regel im Admin konfigurieren und mit einer Testbestellung verifizieren.

Beispielregel
^^^^^^^^^^^^^

Wenn ``payment_method`` den Text ``paypal`` enthaelt und
``shipping_address__country_code`` gleich ``AT`` ist:

1. Zusatzposition mit ERP-Nr ``P`` erzeugen
2. Im Dataset ``Vorgang`` das Feld ``ZahlArt`` auf ``22`` setzen
3. Im Dataset ``VorgangPosition`` das Feld ``KuBez`` auf ``PayPal Gebuehr`` setzen

Schritte im Admin
^^^^^^^^^^^^^^^^^

1. ``Microtech -> Operatoren``

- ``eq`` und ``contains`` aktiv

2. ``Microtech -> Django Feld Policies`` (optional)

- ``field_path = payment_method``
- erlaubte Operatoren: ``eq``, ``contains``

3. ``Microtech -> Einstellungen`` neue Regel ``AT + PayPal``

- ``is_active = Ja``
- ``priority = 10``
- ``condition_logic = all``

4. Bedingungen in der Regel

- ``django_field_path = payment_method``
- ``operator_code = contains``
- ``expected_value = paypal``

- ``django_field_path = shipping_address__country_code``
- ``operator_code = eq``
- ``expected_value = AT``

5. Aktionen in der Regel

- ``action_type = create_extra_position``, ``target_value = P``
- ``action_type = set_field``, ``dataset = Vorgang``, ``dataset_field = ZahlArt``, ``target_value = 22``
- ``action_type = set_field``, ``dataset = VorgangPosition``, ``dataset_field = KuBez``, ``target_value = PayPal Gebuehr``

Testbefehl
^^^^^^^^^^

.. code-block:: bash

   .venv/bin/python manage.py microtech_order_upsert --order-number <DEINE_BESTELLNUMMER>

Erwartung im Ergebnis
^^^^^^^^^^^^^^^^^^^^^

1. Regel matcht nur bei PayPal + AT.
2. Zusatzposition ``P`` wird erzeugt.
3. ``ZahlArt`` wird im Vorgang gesetzt.
4. ``KuBez`` wird auf der zusaetzlich erzeugten VorgangPosition gesetzt.

Workflow 5: Kunden nach Microtech upserten
------------------------------------------

Ziel
^^^^

Einen einzelnen Kunden aus Django in Microtech Adressen/Anschriften/Ansprechpartner uebertragen.

Befehle
^^^^^^^

.. code-block:: bash

   .venv/bin/python manage.py microtech_customer_upsert 100012

.. code-block:: bash

   .venv/bin/python manage.py microtech_customer_upsert --id 7

Workflow 6: Shopware-Produktsync aus Django
-------------------------------------------

Ziel
^^^^

Produktstammdaten und Preise aus Django nach Shopware updaten.

Befehle
^^^^^^^

.. code-block:: bash

   .venv/bin/python manage.py shopware_sync_products --all --batch-size 50

.. code-block:: bash

   .venv/bin/python manage.py shopware_sync_products 100001 100002

Betriebliche Kontrolle
----------------------

Nach jedem Lauf pruefen:

- ``tmp/logs/`` auf Fehlerhinweise
- Django-Admin Aenderungslog fuer Sync-bezogene Eintraege
- Stichproben in Shopware/Microtech
