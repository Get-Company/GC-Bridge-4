Erste Schritte
==============

Voraussetzungen
---------------

- Projekt liegt lokal vor (inkl. ``.env``)
- Virtuelle Umgebung ist angelegt und mit ``uv sync`` aktualisiert
- Datenbank ist erreichbar
- Ein Admin-User existiert

Serverstart auf Windows (Klick-Datei)
-------------------------------------

Fuer den manuellen Start per Doppelklick nutze:

- ``deploy\\windows\\start-server.cmd``

Diese Datei startet beide Scheduled Tasks in der richtigen Reihenfolge:

1. ``GC-Bridge-Uvicorn``
2. ``GC-Bridge-Caddy``

Einzelskripte (nur wenn noetig):

- ``deploy\\windows\\start-uvicorn.cmd``
- ``deploy\\windows\\start-caddy.cmd``

Erstlogin im Admin
------------------

1. Browser oeffnen: ``http://127.0.0.1:4711/admin/``
2. Mit Admin-Benutzer anmelden
3. Grundkonfiguration pruefen:
   - Shopware-Verbindungen und Sales-Channels
   - Microtech-Einstellungen und Order-Regeln

HR-Modul schnell aktivieren
---------------------------

Wenn die Mitarbeiterverwaltung direkt genutzt werden soll:

.. code-block:: bash

   .venv/bin/python manage.py migrate
   .venv/bin/python manage.py hr_setup_groups
   .venv/bin/python manage.py hr_bootstrap

Danach:

1. im Admin die echten User den HR-Gruppen zuweisen
2. Mitarbeiterprofile pruefen oder anlegen
3. Feiertage und Arbeitszeitmodelle kontrollieren

Die vollstaendige Betriebsanleitung steht in ``HR Mitarbeiterverwaltung``.

Schneller Funktionstest
-----------------------

Im Projektverzeichnis:

.. code-block:: bash

   .venv/bin/python manage.py check

Produkt-Synchronisation fuer ersten Test:

.. code-block:: bash

   .venv/bin/python manage.py scheduled_product_sync --limit 5

Wenn unter Windows gearbeitet wird:

.. code-block:: doscon

   .venv\Scripts\python.exe manage.py scheduled_product_sync --limit 5
