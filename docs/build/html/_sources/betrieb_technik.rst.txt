Betrieb und Technik
===================

Dienste und Lauforte
--------------------

Windows Server (CLSRV01)
^^^^^^^^^^^^^^^^^^^^^^^^

- Uvicorn als Scheduled Task ``GC-Bridge-Uvicorn``
- Caddy als Scheduled Task ``GC-Bridge-Caddy``
- Reverse-Proxy: ``:4711 -> 127.0.0.1:8000``

Linux (Alternative)
^^^^^^^^^^^^^^^^^^^

- Uvicorn via systemd-Service ``gc-bridge-uvicorn.service``
- Caddy als Frontend/Reverse-Proxy

Relevante Dateien
-----------------

Start/Runtime (Windows)
^^^^^^^^^^^^^^^^^^^^^^^

- ``deploy\\windows\\start-server.cmd`` (manueller Schnellstart per Doppelklick)
- ``deploy\\windows\\start-uvicorn.cmd``
- ``deploy\\windows\\start-caddy.cmd``
- ``deploy\\windows\\health_check.cmd``
- ``deploy\\windows\\diagnose_reachability.cmd``

Deployment
^^^^^^^^^^

- ``deploy\\windows\\update.cmd`` (wird durch GitHub Actions Runner angestossen)
- ``deploy\\linux\\gc-bridge-uvicorn.service``
- ``deploy\\caddy\\Caddyfile``

Wo liegen die Logs?
-------------------

Standardpfad:

- ``tmp\\logs\\``

Wichtige Dateien:

- ``tmp\\logs\\uvicorn.out.log``
- ``tmp\\logs\\uvicorn.err.log``
- ``tmp\\logs\\caddy.err.log``
- ``tmp\\logs\\caddy-runtime.log``
- ``tmp\\logs\\caddy-access.log``
- ``tmp\\logs\\deploy.log``
- ``tmp\\logs\\health_check.log``
- ``tmp\\logs\\diagnose_reachability.log``

Technische Schnellchecks
------------------------

Django Integritaet:

.. code-block:: bash

   .venv/bin/python manage.py check
   .venv/bin/python manage.py migrate --check

Windows Erreichbarkeit/Status:

.. code-block:: doscon

   deploy\windows\health_check.cmd
   deploy\windows\diagnose_reachability.cmd

Linux Status:

.. code-block:: bash

   sudo systemctl status gc-bridge-uvicorn
   sudo systemctl status caddy
   sudo journalctl -u gc-bridge-uvicorn -n 100 --no-pager
