Kundenmerge KI
==============

Öffnen Sie **Kunden → Kundenmerge KI**, suchen Sie die gewünschten Kunden und
wählen Sie **KI-Vorschlag anzeigen**. Die bisherige Ansicht **Kunden zusammenführen**
bleibt über den Umschalter verfügbar.

Der Assistent liest die Geschäftsdaten der gefundenen Kunden aus Shopware 6,
GC-Bridge und Microtech. Die erste Variante ist die Empfehlung. Oben sehen Sie,
welche Rechnungs- und Lieferadresse vorgesehen ist. Darunter zeigen drei Spalten
die Zuordnungen. Technische Felder und nicht betroffene Datensätze können Sie
bei Bedarf einblenden. Mit **Ist-Zustand ansehen** vergleichen Sie den Vorschlag
mit den bisherigen Daten. Bewegen Sie die Maus über eine Alternative, um deren
Auswirkungen vorübergehend anzusehen; ein Klick wählt sie aus.

Die Adressvorschau wird automatisch mit aktuellen Daten geprüft. Erst **Diese
Änderungen übernehmen** startet die Änderungen. Bei einer Zusammenführung führt
**Zusammenführung prüfen** in die verbindliche Shopware-Vorschau: Dort werden
Zielkonto, Zugang, Adressen und Bestellzuordnungen vor **Merge bestätigen** gezeigt.
Nach einer Zusammenführung analysieren Sie die Adresszuordnungen neu.

Offene Fragen verhindern die Übernahme. Unter **Vorschlag ändern · Einwand
ergänzen** können Sie eine fachliche Information nachreichen. Die Überarbeitung
erzeugt eine neue Version. Bei zwischenzeitlich geänderten Daten ist eine neue
Analyse erforderlich. Bei einer unvollständigen Übernahme werden bestätigte
Einzelschritte angezeigt; prüfen Sie die Systeme vor einer weiteren Bearbeitung.

Einrichtung und Betrieb
----------------------

Verwendet wird ein aktiver Eintrag unter **KI-Provider** mit der Basis-URL
``https://api.openai.com/v1``, API-Schlüssel und einem Modell mit Unterstützung für
Responses und Structured Outputs. Vorhandene Einträge werden wiederverwendet;
unter **KI-Einstellungen** ist der Provider wählbar. Schlüssel bleiben auf dem
Server. Analysen und Überarbeitungen werden separat über die OpenAI-API
abgerechnet. Vorschau, Variantenwechsel und Übernahme rufen kein Modell auf.

Die Analyse übermittelt die Geschäftsfelder und Bestellinformationen der
gewählten Kunden an OpenAI; Passwörter, Passwort-Hashes und freie technische
Erweiterungsdaten aus Shopware werden nicht mitgeschickt. Die Anfrage verwendet
``store=false``. Maximal acht Kunden und 1.000 Datensätze werden vollständig
berücksichtigt; zu umfangreiche oder unvollständige Daten werden abgewiesen.

Hintergrundaufträge laufen über die bestehende Celery-Queue ``bulk``. Ergebnisse
werden benutzergebunden für 30 Minuten im Redis-Cache ``customer_merge_ai``
aufbewahrt. Standardmäßig wird der bestehende Redis-Broker verwendet; optional
kann ``CUSTOMER_MERGE_AI_REDIS_URL`` auf eine eigene Redis-Datenbank verweisen.
Es sind keine neuen Datenbankmodelle oder Migrationen nötig. Änderungen verwenden
die bestehenden Services und werden im Django-Admin-Protokoll erfasst.
