Operator-Checkliste (1 Seite)
=============================

Ziel
----

Diese Checkliste ist fuer den taeglichen Betrieb gedacht: kurz, reproduzierbar, ohne Tiefendiagnose.

Taeglicher Startcheck (3-5 Minuten)
-----------------------------------

1. Erreichbarkeit testen

.. code-block:: text

   http://127.0.0.1:4711/admin/

2. Health Check ausfuehren (Windows)

.. code-block:: doscon

   deploy\windows\health_check.cmd

3. Bei Fehlern sofort Diagnose starten

.. code-block:: doscon

   deploy\windows\diagnose_reachability.cmd

4. Kernlogs pruefen

- ``tmp\logs\uvicorn.err.log``
- ``tmp\logs\caddy.err.log``
- ``tmp\logs\deploy.log``

Taeglicher Betriebsablauf
-------------------------

1. Produkt-Sync anstossen (falls nicht per Scheduler)

.. code-block:: doscon

   .venv\Scripts\python.exe manage.py scheduled_product_sync --limit 200

2. Offene Bestellungen laden

.. code-block:: doscon

   .venv\Scripts\python.exe manage.py shopware_sync_open_orders --limit-orders 100

3. Stichprobe im Admin

- Neue/aktualisierte Produkte kontrollieren
- Neue Orders und OrderDetails pruefen
- Problemfaelle (fehlende IDs, leere Preise, Mappingprobleme) markieren

Wenn die Seite nicht erreichbar ist
-----------------------------------

1. Startskript klicken:

.. code-block:: doscon

   deploy\windows\start-server.cmd

2. Danach erneut pruefen:

.. code-block:: text

   http://127.0.0.1:4711/admin/

3. Falls weiterhin Fehler: Diagnose-Log lesen

- ``tmp\logs\diagnose_reachability.log``

Operator-Entscheidungen
-----------------------

Sofort eskalieren an Technik, wenn:

- ``health_check.cmd`` Fehler meldet, die nicht durch Neustart loesbar sind
- wiederholte DB-/Migration-Fehler auftreten
- Uvicorn/Caddy mehrfach taeglich abstuerzen
- Deployment-Log wiederholt fehlschlaegt

Schnellbefehle
--------------

Start (Windows, manuell):

.. code-block:: doscon

   deploy\windows\start-server.cmd

Status und Diagnose:

.. code-block:: doscon

   deploy\windows\health_check.cmd
   deploy\windows\diagnose_reachability.cmd

Linux-Betrieb (falls aktiv):

.. code-block:: bash

   sudo systemctl status gc-bridge-uvicorn
   sudo systemctl status caddy
