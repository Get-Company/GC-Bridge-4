Kundenmerge KI
==============

Öffnen Sie **Kunden → Kundenmerge KI**, suchen Sie die gewünschten Kunden und
warten Sie, bis die Statusanzeige die Abfragen aus SW6, GC-Bridge und Microtech
als abgeschlossen meldet. Microtech kann über GraphQL länger benötigen. Die Anzeige
unterscheidet gefundene Kunden, keine Treffer und Fehler. **KI-Vorschlag anzeigen**
wird erst bei vollständig abgeschlossener Suche mit Treffern verfügbar. Bei einem
Fehler starten Sie die Suche erneut. Die bisherige Ansicht **Kunden zusammenführen**
bleibt über den Umschalter verfügbar.

Während der Analyse zeigt das Modal einen Spinner und den aktuellen Arbeitsschritt.
Das Ergebnis erscheint automatisch; **Status prüfen** ist nur bei einer
unterbrochenen Statusverbindung nötig. Scheitert die Analyse, können Sie mit
**Erneut analysieren** einen neuen, kostenpflichtigen Auftrag starten.

Die Suche lädt die vollständigen Geschäftsdaten einmalig und hält sie
benutzergebunden bereit. Die KI verwendet genau diesen Datenstand, auch bei einer
Überarbeitung. Variantenwechsel und Ist-Vergleich laden keine Systemdaten nach.

Links wählen Sie einen Vorschlag oder **Ist-Zustand**. Rechts zeigt die bekannte
Vergleichsmatrix SW6, GC-Bridge und Microtech mit denselben Feldern in einer Zeile.
Rechnungs- und Lieferadresse stehen oben; zugeordnete Anschriften darunter.
Vorgeschlagene Änderungen sind blau markiert. Eine kurze Erklärung beschreibt
die Wirkung; Begründung und Belege sind bei Bedarf aufklappbar.

**Vorschlag akzeptieren** prüft die Daten unmittelbar vor dem Speichern erneut.
Hat sich seit der Suche etwas geändert, wird die Übernahme abgebrochen und eine
neue Suche verlangt. Eine Zusammenführung verwendet die verbindliche Prüfung
und den verifizierten Merge des Shopware-Plugins im Hintergrund. Weicht dessen
Ergebnis vom angezeigten Vorschlag ab, wird vor dem Merge abgebrochen. Eine
weitere Bestätigung in einem zweiten Modal ist nicht erforderlich.

Offene Fragen verhindern die Übernahme. Unter **Vorschlag ändern** können Sie
einen Einwand nachreichen. Die Überarbeitung erzeugt eine neue Version mit dem
gleichen Suchstand. Bei unklarer Merge-Antwort liest **Status prüfen** ausschließlich
das Ergebnis des bestehenden Vorgangs nach; der Merge wird nicht erneut gesendet.
Nach einer Übernahme wird die Suche beim Schließen aktualisiert. Nach manuellen
Änderungen ist vor der nächsten KI-Analyse ebenfalls eine neue Suche erforderlich.

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

Die Antwortvorgabe für Belege wird aus dem jeweiligen Datenstand erzeugt. Sie
erlaubt ausschließlich existierende Kombinationen aus Datensatz und Feldname;
die serverseitige Prüfung bleibt zusätzlich bestehen.
