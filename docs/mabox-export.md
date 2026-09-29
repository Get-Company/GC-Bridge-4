# Mabox-Produktexport

Der Exportservice bildet die 50 Spalten aus `resource_2.py` ab. Er liefert alle
aktiven, nicht archivierten Produkte sowie die für Mabox aktivierten Pakete als
Kindartikel. Er ist als Grundlage für den geplanten wöchentlichen CSV-Versand per
E-Mail vorgesehen; ein öffentlicher Feed ist nicht eingerichtet.

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
