KI-Uebersetzungen mit Ollama
============================

Die automatische KI-Uebersetzung verarbeitet jedes Textfeld, das in
``django-modeltranslation`` registriert ist. Die deutsche Variante ist die
Quelle; alle anderen in Django angelegten Sprachen sind Ziele.

Funktionsweise
--------------

- Pro Objekt, Quellfeld und Zielsprache wird ein SHA-256-Hash des deutschen
  Originalwerts gespeichert.
- Ein naechster Scan uebersetzt nur fehlende, fehlgeschlagene oder geaenderte
  Quellwerte erneut.
- Zusaetzlich wird ein Fingerprint der Uebersetzungskonfiguration gespeichert.
  Werden Prompt, Sprachhinweise, Quellsprache, Leerwert-Verhalten oder der
  ausgewaehlte Provider bzw. dessen Modell geaendert, werden auch unveraenderte
  Quellwerte beim naechsten Scan erneut uebersetzt.
- Die Statusliste wird automatisch beim Uebersetzungsscan aufgeraeumt.
  ``Statusanzeige aufbewahren (Tage)`` in der Konfiguration legt fest, wann
  erfolgreiche oder abgebrochene Eintraege aus der Liste verschwinden; ``0``
  deaktiviert das. Die Hashes bleiben intern erhalten, damit keine unnötigen
  Neuuebersetzungen entstehen.
- Bei geleertem deutschen Quellwert werden Zielwerte standardmaessig ebenfalls
  geleert. Das Verhalten ist in der Konfiguration abschaltbar.
- HTML wird nicht vom Modell erzeugt: Tags, technische Attribute, Klassen,
  Styles, URLs und IDs bleiben unveraendert. Sichtbare Textknoten sowie die
  menschlich lesbaren Attribute ``alt``, ``title``, ``aria-label`` und
  ``placeholder`` werden als JSON-Segmente uebersetzt; das Modell muss
  dieselben Segment-IDs zurueckgeben.
- Inhalte von ``code``, ``pre``, ``script`` und ``style`` werden nicht
  uebersetzt.
- Ein Scan verarbeitet die geplanten Feld-/Sprachkombinationen als serielle
  Celery-Kette. Damit wird der einzelne TranslateGemma-Server auf dem
  Arbeits-PC nicht durch parallele Anfragen ueberlastet.

Die Konfiguration unter ``AI > Uebersetzungen`` enthaelt einen editierbaren
System-Prompt, eine Benutzer-Prompt-Vorlage und die Sprachvarianten-Hinweise.
Die Standardvorgabe fuer ``ch-de`` verlangt echten schweizerdeutschen Dialekt;
die anderen Zielsprachen verwenden die jeweilige Hochsprache. Diese Hinweise
koennen dort pro Sprachcode angepasst werden.
Bei ``it-de`` ist Deutsch zwingende Ausgabesprache fuer den suedtirolerischen
Markt. Da der technische Code von Sprachmodellen als Italienisch missverstanden
werden kann, wird diese Regel zusaetzlich verbindlich an jeden Modell-Prompt
angehaengt.

Shopware-Export
---------------

Eine erfolgreich geschriebene Produktuebersetzung startet ausschliesslich einen
Shopware-6-Produktsync. Der SW6-Payload enthaelt fuer jede dort vorhandene,
passende Locale (``en-*``, ``de-CH``, ``de-IT``, ``it-IT``) einen nativen
``translations``-Eintrag mit Name, Beschreibung und Verpackungseinheit. SW5
und Microtech erhalten keine KI-Uebersetzungen. Eine Kurzbeschreibung besitzt
in der SW6-Produktentitaet kein eigenes Standardfeld und wird deshalb nicht
exportiert.

Auch die kundenrelevanten Varianteninformationen werden uebersetzt: Name und
Beschreibung der Variantenfamilie sowie Namen von Attributgruppen und ihren
Werten. Bei einer geaenderten Sprachfassung startet der Varianten-Sync und
uebergibt diese Inhalte als native SW6-``translations`` fuer Parent-Produkt,
Property-Group und Property-Group-Option. Technische Felder, Bilder, Klassen
und die Variantenlogik bleiben unveraendert.

Kategorien werden fuer Name, Beschreibung, Kurzbeschreibung sowie SEO-Titel,
SEO-Beschreibung und SEO-Keywords gescannt. Eine KI-Uebersetzung schreibt die
SW6-Standardfelder Name, Beschreibung und SEO-Metadaten als nativen
``translations``-Payload zurueck. Die Kurzbeschreibung bleibt in Django
uebersetzt; die Standard-Kategorie von Shopware 6 hat dafuer kein eigenes
Feld. Wird eine vorhandene Kategorie lokal an einem kundenrelevanten Feld oder
an einer Produktzuordnung geaendert, stellt ein separater SW6-Task den
Kategorieninhalt samt nativen ``translations`` wieder her. Die direkten
``product_category``-Zuordnungen werden dabei exakt abgeglichen: neue Produkte
werden zugeordnet und entfernte Zuordnungen in SW6 geloescht.

Ollama auf dem Arbeits-PC im LAN bereitstellen
----------------------------------------------

Ollama bindet standardmaessig nur an ``127.0.0.1:11434``. Damit der Server den
Arbeits-PC erreichen kann, muss auf dem Arbeits-PC die Umgebungsvariable
``OLLAMA_HOST`` gesetzt werden:

Fuer diesen Linux-Mint-Arbeits-PC wird Ollama gezielt an seine LAN-Adresse
gebunden. Die aktuelle Adresse ist ``10.0.0.155``. Die dauerhafte
systemd-Konfiguration lautet:

.. code-block:: ini

   # /etc/systemd/system/ollama.service.d/override.conf
   [Service]
   Environment="OLLAMA_HOST=10.0.0.155:11434"

Danach muessen ``systemctl daemon-reload`` und ``systemctl restart ollama``
ausgefuehrt werden. Wenn sich diese LAN-Adresse aendert, ist die Einstellung
anzupassen oder eine DHCP-Reservierung einzurichten.

Unter Windows wird die entsprechende Umgebungsvariable im Benutzerkonto
gesetzt und Ollama anschliessend neu gestartet. Die offizielle
Ollama-Dokumentation beschreibt die Konfiguration und den Standard-Bind-Host
unter https://docs.ollama.com/faq#how-can-i-expose-ollama-on-my-network.

Sicherheit
~~~~~~~~~~

Der lokale Ollama-Endpunkt hat bei einer LAN-Freigabe keine eigene
Anwendungs-Authentifizierung. Daher ist zwingend eine Linux-Firewall-Regel
einzurichten:

- eingehend TCP-Port ``11434`` erlauben;
- als Remote-IP ausschliesslich die feste IP-Adresse des GC-Bridge-Servers
  eintragen;
- keine Freigabe fuer das Internet, Gastnetz oder beliebige LAN-Clients.

Vor der Django-Konfiguration muss der Server den Endpunkt erreichen koennen:

.. code-block:: bash

   curl http://<IP-DES-ARBEITS-PC>:11434/api/tags

Die Ausgabe muss ``translategemma:12b`` enthalten. Verwende fuer die
Server-Verbindung immer eine feste IP-Adresse oder einen internen DNS-Namen,
nie ``localhost``.

Django konfigurieren
--------------------

1. Unter ``AI > Provider`` einen aktiven Eintrag anlegen:

   - Name: ``Ollama TranslateGemma``
   - Base URL: ``http://<IP-DES-ARBEITS-PC>:11434/v1``
   - Modellname: ``translategemma:12b``
   - API-Key: leer lassen
   - Timeout: fuer das 12B-Modell ausreichend hoch setzen, zum Beispiel
     ``600`` Sekunden.

2. Unter ``AI > Uebersetzungen`` eine aktive Konfiguration erstellen und den
   Provider aus Schritt 1 auswaehlen. Zunaechst empfiehlt sich eine kleine
   Batchgroesse, zum Beispiel 20 Uebersetzungen pro Lauf.

3. Im gleichen Bereich lassen sich der vorgeschlagene strikte System-Prompt,
   die Benutzer-Prompt-Vorlage und die Spracheigenheiten jederzeit aendern.
   Der native Unfold-Aktionseintrag ``Uebersetzungsscan jetzt starten`` dient
   zum kontrollierten manuellen Test.

4. Unter ``System > Celery Scheduler`` einen ``CrontabSchedule`` und einen
   ``PeriodicTask`` anlegen:

   - Task: ``ai.queue_translation_scan``
   - Zeit: taeglich, beispielsweise 02:30 Uhr (Server-Zeitzone
     ``Europe/Berlin``)
   - Argumente: leer

Der Celery-Worker muss nachts laufen und der Arbeits-PC mit Ollama muss zu
dieser Zeit eingeschaltet sowie im LAN erreichbar sein.
