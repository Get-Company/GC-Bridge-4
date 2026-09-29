# Mabox-Produktexport

Der Exportservice bildet die 50 Spalten aus `resource_2.py` ab. Er liefert alle
aktiven, nicht archivierten Produkte sowie die für Mabox aktivierten Pakete als
Kindartikel. Der aktuelle Stand wird einmal im Monat als CSV-Anhang per E-Mail
versendet; ein öffentlicher Feed ist nicht eingerichtet.

## Einmalige Einrichtung auf dem Server

```bash
.venv/bin/python manage.py migrate

.venv/bin/python manage.py import_legacy_packages \
  --dump-path /media/fbuchner/Daten/htdocs/python/GC_Bridge_v3_django/backups/database.sql \
  --sqlite-path /tmp/gc_bridge_v3_packages.sqlite3 \
  --rebuild-sqlite \
  --dry-run

.venv/bin/python manage.py import_legacy_packages \
  --dump-path /media/fbuchner/Daten/htdocs/python/GC_Bridge_v3_django/backups/database.sql \
  --sqlite-path /tmp/gc_bridge_v3_packages.sqlite3
```

Beim Docker-Deployment wird die Migration im Web-Container ausgeführt:

```bash
docker exec -i gc_bridge_4_web python manage.py migrate
```

## E-Mail-Versand einrichten

Die SMTP-Zugangsdaten werden im Django-Admin unter **Organisation →
Ansprechpartner** beim versendenden Mitarbeiter gepflegt. Dazu gehören Server,
Port, Verschlüsselungsart, Benutzername, Passwort, Absenderadresse und Timeout.
Bleibt die besondere SMTP-Absenderadresse leer, wird die öffentliche E-Mail des
Ansprechpartners beziehungsweise die E-Mail seines Benutzerkontos verwendet.
Die Aktion **SMTP-Verbindung testen** prüft Serververbindung und Anmeldung mit
den gespeicherten Daten, ohne eine E-Mail zu versenden.

Im Django-Admin unter **Produkte** befindet sich die Aktion **Mabox-Export**.
Dort werden Empfänger, der versendende Ansprechpartner, Versandtag (1 bis 28),
Uhrzeit, Betreff und Nachricht gepflegt. Der Versand ist zunächst deaktiviert.
Nach dem Speichern wird der monatliche Celery-Beat-Eintrag automatisch angelegt
beziehungsweise aktualisiert. Die Uhrzeit verwendet die Server-Zeitzone
`Europe/Berlin`. Änderungen an den SMTP-Daten des ausgewählten Ansprechpartners
aktualisieren den Zeitplan ebenfalls automatisch.

Zwei Aktionen stehen direkt in der Konfiguration bereit:

- **Aktuelle CSV herunterladen** erstellt den Export sofort im Browser.
- **Test-E-Mail mit aktuellem CSV einreihen** sendet über den Bulk-Worker eine
  Testmail; dafür muss der monatliche Versand noch nicht aktiviert sein.

Der reguläre Task versendet höchstens einmal pro Kalendermonat. Erfolgszeit,
Datensatzanzahl und der letzte Fehler werden in der Konfiguration angezeigt.

Der Import ist idempotent: vorhandene Pakete werden anhand ihrer Paket-Artikelnummer
aktualisiert. Er übernimmt Menge, Paket-GTIN, Legacy-ID, Zeitstempel und die frühere
Mabox-Zuordnung (Legacy-Sub-Marktplatz 5). Pakete anderer Marktplätze bleiben in der
Bridge erhalten, werden aber nicht automatisch im Mabox-Feed ausgegeben.

Der ursprünglich genannte Pfad `backups/databse.sql` enthält einen Tippfehler. Die
Datei `gc_bridge_db_v3_backup_20250723_102043.sql` ist in der geprüften Ablage leer;
`backups/database.sql` enthält die verwertbaren Tabellen und Datensätze.

## Preis- und Bestandsregeln

- Produktpreise sind die normalen Preise des aktiven Standard-Verkaufskanals.
- Paketpreise sind `Preis / Produktfaktor × Paketmenge`.
- Ab der hinterlegten Staffelmenge wird der Staffelpreis verwendet. Sonderpreise
  werden für den Mabox-Export nicht herangezogen.
- Elternartikel mit Mabox-Paketen behalten gemäß Legacy-Mapping leere Preisfelder.
- EK ist 70 % des jeweiligen VK, Lieferzeit ist 2 Tage, Dropshipping ist 0.
- Bestand ist der echte Bridge-Bestand. Bei Paketen wird die Zahl vollständig
  lieferbarer Pakete abgerundet.
- Fehlt bei einem exportierten Produkt Preis oder Steuer, bricht die Erzeugung ab,
  statt eine fachlich unvollständige Datei auszuliefern.
