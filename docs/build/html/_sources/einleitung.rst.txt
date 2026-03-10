Einleitung
==========

Was ist die GC-Bridge?
----------------------

Die GC-Bridge verbindet Microtech ERP, Shopware 6 und die interne Django-Datenhaltung.
Sie sorgt fuer einen kontrollierten Datenaustausch zwischen Produkt-, Kunden- und Bestellwelt.

Zielgruppen
-----------

- Admins, die Datenpflege und Integrationsparameter im Django-Admin betreuen
- Operatoren, die regelmaessige Sync-Laeufe ausfuehren und pruefen
- Technik-Verantwortliche, die Dienste, Logs und Deployment betreiben

Hauptprinzipien
---------------

- Produktfluss: Microtech -> Django -> Shopware
- Bestellfluss: Shopware -> Django -> Microtech
- Revisionsfaehigkeit ueber Admin-Logeintraege und Laufzeit-Logs

Systemueberblick
----------------

- Django-App: GC-Bridge Kernlogik und Admin-UI
- Uvicorn: ASGI-App-Server auf Port 8000 (localhost)
- Caddy: Reverse-Proxy auf Port 4711
- PostgreSQL: persistente Datenhaltung fuer GC-Bridge Models

Referenzbereich fuer Models/Admins
----------------------------------

Eine vollstaendige, automatisch erzeugte Referenz zu allen lokalen Models und registrierten Admin-Klassen findest du unter:

- :doc:`reference/models_und_admins_generated`

Diese Seite wird beim Sphinx-Build aus dem aktuellen Codebestand generiert.
