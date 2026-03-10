Stoerung: Seite nicht erreichbar
================================

Symptom
-------

Die GC-Bridge ist ueber ``http://<server>:4711/admin/`` nicht erreichbar.

Sofortmassnahme (Windows)
-------------------------

1. Doppelklick auf ``deploy\\windows\\diagnose_reachability.cmd``
2. Falls noetig direkt danach ``deploy\\windows\\start-server.cmd``
3. Anschliessend erneut ``deploy\\windows\\health_check.cmd`` ausfuehren

Diagnose-Logik
--------------

Das Diagnose-Skript prueft nacheinander:

1. Kritische Dateien (Python, Caddy-Binary, Caddyfile)
2. Scheduled Tasks
3. Listener auf Port 8000 (Uvicorn) und 4711 (Caddy)
4. HTTP-Antworten auf ``127.0.0.1``
5. Firewall-Regel fuer Port 4711

Am Ende wird ein ``[HINT]`` mit wahrscheinlicher Ursache ausgegeben.

Haeufige Ursachen und Aktionen
------------------------------

Uvicorn laeuft nicht
^^^^^^^^^^^^^^^^^^^^

- Symptom: Port 8000 nicht aktiv
- Aktion:

.. code-block:: doscon

   schtasks /Run /TN "GC-Bridge-Uvicorn"

Caddy laeuft nicht
^^^^^^^^^^^^^^^^^^

- Symptom: Port 8000 aktiv, Port 4711 nicht aktiv
- Aktion:

.. code-block:: doscon

   schtasks /Run /TN "GC-Bridge-Caddy"

Django antwortet intern nicht
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

- Symptom: Port 8000 offen, aber ``/admin/`` liefert keinen 200-Status
- Aktion: ``tmp\\logs\\uvicorn.err.log`` auf Tracebacks und Settings-Probleme pruefen

Firewall blockiert externe Clients
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

- Symptom: Lokal unter ``127.0.0.1:4711`` erreichbar, aber aus LAN nicht
- Aktion:

.. code-block:: doscon

   netsh advfirewall firewall add rule name="GC-Bridge Caddy 4711" dir=in action=allow protocol=TCP localport=4711

Linux-Fallback
--------------

Wenn Linux betrieben wird:

.. code-block:: bash

   sudo systemctl restart gc-bridge-uvicorn
   sudo systemctl restart caddy
   sudo journalctl -u gc-bridge-uvicorn -n 200 --no-pager
   sudo journalctl -u caddy -n 200 --no-pager
