# Shopware Newsletterverwaltung

Die vorhandene CMS-Vorlage mit Newsletterformular wird unter `/Newsletter/` im Footer „Shop Service“ verknüpft. Das Standardformular unterstützt Anmeldung (Double-Opt-In) und Abmeldung ohne Kundenkonto.

`provision.php` aus dem Shopware-Projektverzeichnis mit `/usr/bin/php84` ausführen. Ohne `--apply` nur Prüfung, mit `--apply` idempotente Einrichtung. Enthält ausschließlich die bestätigten IDs des Classei-Shops. Vor Änderungen anderer Shops IDs prüfen.

`newsletter-form.html.twig` gehört nach `custom/plugins/ClasseiShopTheme/src/Resources/views/storefront/element/cms-element-form/form-types/`. Danach Twig linten, Theme kompilieren und Cache leeren. Das Script füllt das native Formular aus dem URL-Fragment vor; es sendet es nicht automatisch ab. Ohne Fragment bleibt die normale Newsletteranmeldung erhalten.

Die Bridge erzeugt persönliche Links als `/Newsletter/#option=unsubscribe&email=...`. Die Adresse bleibt im Browser und wird erst mit dem Formular an Shopware übermittelt. GET-Aufrufe und Linkscanner ändern keinen Status.

Der vorhandene Bridge-Task `newsletter.shopware_sync_recipients` läuft täglich um 02:00 Europe/Berlin mit `{"page_size": 100, "mark_missing": true}`. Shopware ist führend. Aktive/bestätigte Empfänger sind zulässig, abgemeldete/unbestätigte/entfernte Empfänger werden ausgeschlossen; wartende Nachrichten werden beim Abgleich abgebrochen.

Der vorhandene Flow `newsletter.register` wird mit seiner bestehenden Double-Opt-In-Mailvorlage aktiviert. Die fehlerhaft maskierte Bestätigungs-URL wird ausschließlich für den Haupt-Verkaufskanal auf den nativen Pfad korrigiert. Der separate Bestätigungs-/Willkommensflow bleibt in seinem bisherigen Zustand.
