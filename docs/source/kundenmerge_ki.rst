Kundenmerge KI
==============

Öffnen Sie **Kunden → Kundenmerge KI**, suchen Sie die gewünschten Kunden und
warten Sie, bis die Statusanzeige die Abfragen aus SW6, GC-Bridge und Microtech
als abgeschlossen meldet. Microtech kann über GraphQL länger benötigen. Die Anzeige
unterscheidet gefundene Kunden, keine Treffer und Fehler. **Konten prüfen** beziehungsweise **KI-Vorschlag anzeigen**
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

Bei zwei oder mehr Shopkonten zeigt **Konten prüfen** zuerst die Auswahl
**Richtige AdrNr · bleibt erhalten** und **Falsche AdrNr · wird zusammengeführt**.
Wählen Sie beide Nummern und klicken Sie **Merge bestätigen**. Eine KI-Anfrage ist
hierfür nicht erforderlich. Der Merge wird vor der Ausführung frisch geprüft und
über das verifizierte Shopware-Plugin ausgeführt. Doppelte Bestätigungen erzeugen
keinen zweiten Vorgang. Bei mehreren falschen Konten erfolgt die Auswahl
nacheinander; die bereits bestätigte richtige AdrNr bleibt vorausgewählt.

Fehlt die richtige AdrNr bisher in GC-Bridge, wird dies in der Auswahl als
**GC-Bridge · wird angelegt** angezeigt. Nach der bestätigten Shopware-
Zusammenführung wird der Zielkunde mit seinen geprüften Shopadressen automatisch
übernommen. Anlage und lokale Zusammenführung bilden eine gemeinsame Transaktion;
vorhandene Quelldaten werden erst dabei zugeordnet. Bereits belegte IDs oder
widersprüchliche Zuordnungen verhindern weiterhin den Merge. Für die automatische
Anlage sind zusätzlich die Rechte zum Anlegen von Kunden und Adressen erforderlich.

Nach einem bestätigten Merge lädt die Ansicht die verbliebenen Kunden neu und
startet automatisch die KI-Analyse ihrer Adresszuordnungen. Bei weiteren
Shopkonten kommt zuerst wieder die AdrNr-Auswahl. Gehören die Konten nicht
zusammen, führt **Konten getrennt lassen** direkt zur Adressanalyse. Bei einem
unklaren Merge-Ergebnis erfolgt keine automatische Weiterarbeit; zuerst muss der
Vorgangsstatus geklärt werden. Ein Fehler beim anschließenden Laden lässt sich mit
**Daten neu laden** wiederholen, ohne den Merge erneut auszuführen.

Die Hauptansicht entspricht dem klassischen Kundenmerge: SW6 links,
GC-Bridge in der Mitte, Microtech rechts. Sind mehrere AdrNr in SW6 vorhanden,
markieren ein orangefarbener Hinweis und ein Pfeil den Merge-Bereich.

Nach der Analyse erscheinen Empfehlungen direkt in dieser Ansicht. Orange Pfeile
verbinden die konkreten SW6-Adress-IDs beziehungsweise Microtech-Kennungen mit den
vorgefüllten Feldern in der Mitte. Es gibt genau eine Empfehlung. Die bisherigen Kennungen stehen direkt
unter den vorgeschlagenen Werten; zusätzliche Auswahlbuttons entfallen. Vorgeschlagene Standardrollen stehen an der
jeweiligen Microtech-Adresse. Im Entwurf sind einzelne manuelle Speicher- und
Löschaktionen ausgeblendet; **Vorschlag übernehmen** bestätigt den gesamten Plan.

Shopware ist für die Rechnungs- und Lieferauswahl maßgeblich. Abweichende
Microtech-Standards werden zur Übernahme der Shopware-Auswahl vorgeschlagen.
Getrennte Shopware-IDs für inhaltlich exakt gleiche Rechnungs- und Lieferadressen
bleiben erhalten und dürfen dieselbe Microtech-AnsNr/AnspNr erhalten. Es werden
hier nur vorhandene Datensätze zugeordnet; die Analyse kopiert, löscht oder
vereinigt keine Adressen. Historische Bestellanschriften bleiben unverändert.

**Vorschlag übernehmen** prüft die Daten unmittelbar vor dem Speichern erneut.
Hat sich seit der Suche etwas geändert, wird die Übernahme abgebrochen und eine
neue Suche verlangt. Nach erfolgreicher Übernahme wird die klassische Ansicht
mit aktuellen Daten neu geladen, ohne eine weitere kostenpflichtige Analyse.

Offene Fragen verhindern die Übernahme. Unter **Einwand** kann die Empfehlung
überarbeitet werden; die neue Version verwendet denselben Suchstand. Während
Analyse und Speicherung sind die Adressen ausgegraut und nicht bedienbar.
Bei unklarer Merge-Antwort liest **Status prüfen** das Ergebnis des bestehenden
Vorgangs nach; der Merge wird nicht erneut gesendet. Nach manuellen Änderungen
ist vor der nächsten KI-Analyse ebenfalls eine neue Suche erforderlich.

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
