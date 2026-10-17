# Shopware Newsletterverwaltung

Die vorhandene CMS-Vorlage mit Newsletterformular wird unter `/Newsletter/` im Footer „Shop Service“ verknüpft. Das Standardformular unterstützt Anmeldung (Double-Opt-In) und Abmeldung ohne Kundenkonto.

`provision.php` aus dem Shopware-Projektverzeichnis mit `/usr/bin/php84` ausführen. Ohne `--apply` nur Prüfung, mit `--apply` idempotente Einrichtung. Enthält ausschließlich die bestätigten IDs des Classei-Shops. Vor Änderungen anderer Shops IDs prüfen.

`newsletter-form.html.twig` gehört nach `custom/plugins/ClasseiShopTheme/src/Resources/views/storefront/element/cms-element-form/form-types/`. Danach Twig linten, Theme kompilieren und Cache leeren. Das Script füllt das native Formular aus dem URL-Fragment vor; es sendet es nicht automatisch ab. Ohne Fragment bleibt die normale Newsletteranmeldung erhalten.

Die Bridge erzeugt persönliche Links als `/Newsletter/#option=unsubscribe&email=...`. Die Adresse bleibt im Browser und wird erst mit dem Formular an Shopware übermittelt. GET-Aufrufe und Linkscanner ändern keinen Status.

Der vorhandene Bridge-Task `newsletter.shopware_sync_recipients` läuft täglich um 02:00 Europe/Berlin mit `{"page_size": 100, "mark_missing": true}`. Shopware ist führend. Aktive/bestätigte Empfänger sind zulässig, abgemeldete/unbestätigte/entfernte Empfänger werden ausgeschlossen; wartende Nachrichten werden beim Abgleich abgebrochen.

Der vorhandene Flow `newsletter.register` wird mit seiner bestehenden Double-Opt-In-Mailvorlage aktiviert. Die fehlerhaft maskierte Bestätigungs-URL wird ausschließlich für den Haupt-Verkaufskanal auf den nativen Pfad korrigiert. Der separate Bestätigungs-/Willkommensflow bleibt in seinem bisherigen Zustand.

## Vereinfachte Abmeldebestätigung

`NewsletterUnsubscribeSubscriber.php` gehört nach `custom/plugins/ClasseiShopTheme/src/Subscriber/`, `newsletter.de-DE.json` nach `src/Resources/snippet/de_DE/`. `register-subscriber.php` registriert die Klasse idempotent in der bestehenden `services.xml` und sichert deren vorherigen Inhalt im nicht öffentlichen `var/gc-newsletter-setup/`. Danach Cache leeren, Container/Twig prüfen und das Theme kompilieren.

Nur der Haupt-POST auf `frontend.form.newsletter.register.handle` mit `option=unsubscribe` wird vor der Captcha-Prüfung ausgenommen. Shopwares eigene E-Mail-Validierung und Rate-Limit bleiben bestehen. Registrierung, sonstige Formulare und GET-Aufrufe behalten ihren bisherigen Schutz. Das native Feld-Toggle blendet Captcha und Datenschutz-/AGB-Checkbox bei der Abmeldung aus und deaktiviert die Felder; beim Umschalten auf Anmeldung werden sie wieder eingeblendet. Der deutsche Bestätigungsbutton heißt „Abmelden“.

`test-unsubscribe-subscriber.php` prüft die enge Backend-Ausnahme ohne Datenbankzugriff oder Mailversand. Aus dem Shopware-Verzeichnis mit `/usr/bin/php84` aufrufen; die Subscriber-Datei muss im selben Verzeichnis wie dieser Test liegen.
