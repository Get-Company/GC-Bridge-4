# GC-Bridge-4

Django integration bridge between Microtech and Shopware 6.

## Inhaltsverzeichnis

- [Projektueberblick](#projektueberblick)
- [Grundregeln im Projekt](#grundregeln-im-projekt)
- [Lokales Setup](#lokales-setup)
- [Umgebungsvariablen (.env)](#umgebungsvariablen-env)
- [Sync-Commands](#sync-commands)
  - [Produkte: Microtech -> Django -> Shopware](#produkte-microtech---django---shopware)
  - [Bestellungen: Shopware -> Django -> Microtech](#bestellungen-shopware---django---microtech)
- [Adminer / Datenbank](#adminer--datenbank)

## Projektueberblick

Wichtige Basisklassen:

- `BaseModel` (`core/models/base.py`) mit `created_at` und `updated_at`
- `BaseAdmin` (`core/admin.py`) auf Basis von Unfold
- `BaseService` (`core/services/base.py`) als Service-Grundlage

## Grundregeln im Projekt

- Secrets nie committen, nur in lokale `.env`.
- Fuer neue Modelle `BaseModel` verwenden.
- Fuer neue Admin-Klassen `BaseAdmin` verwenden.
- Fuer neue Services `BaseService` verwenden.
- Lokale Python-Commands immer mit `.venv/bin/python` ausfuehren.

## Lokales Setup

1. Abhaengigkeiten installieren:
```bash
uv sync
```
2. `.env` im Projektroot anlegen (siehe unten).
3. Datenbank starten:
```bash
docker compose up -d
```
4. Migrationen ausfuehren:
```bash
.venv/bin/python manage.py migrate
```
5. Superuser anlegen:
```bash
.venv/bin/python manage.py createsuperuser
```
6. Dev-Server starten:
```bash
.venv/bin/python manage.py runserver
```

## Umgebungsvariablen (.env)

Beispiel:

```dotenv
POSTGRES_DB=gc_bridge_4
POSTGRES_USER=gc_bridge_4
POSTGRES_PASSWORD=gc_bridge_4_dev
POSTGRES_HOST=localhost
POSTGRES_PORT=5432

SHOPWARE6_ADMIN_API_URL=https://your-shopware.example/api
SHOPWARE6_ID=your-client-id
SHOPWARE6_SECRET=your-client-secret
SHOPWARE6_GRANT_TYPE=client_credentials
SHOPWARE6_USER=
SHOPWARE6_PASSWORD=

MICROTECH_MANDANT=
MICROTECH_FIRMA=
MICROTECH_BENUTZER=
MICROTECH_PASSWORT=
```

## Sync-Commands

### Produkte: Microtech -> Django -> Shopware

Gesamtlauf:

```bash
.venv/bin/python manage.py microtech_sync_products --all
.venv/bin/python manage.py shopware_sync_products --all
```

Nur bestimmte Artikel:

```bash
.venv/bin/python manage.py microtech_sync_products 204113 123456
.venv/bin/python manage.py shopware_sync_products 204113 123456
```

Mit Limit/Batch:

```bash
.venv/bin/python manage.py microtech_sync_products --all --limit 100
.venv/bin/python manage.py shopware_sync_products --all --limit 100 --batch-size 50
```

### Bestellungen: Shopware -> Django -> Microtech

Offene Shopware-Bestellungen nach Django:

```bash
.venv/bin/python manage.py shopware_sync_open_orders
```

Eine Bestellung nach Microtech upserten:

```bash
.venv/bin/python manage.py microtech_order_upsert <BESTELLNUMMER>
```

Alternativ per Django-ID:

```bash
.venv/bin/python manage.py microtech_order_upsert --id <ORDER_ID>
```

## Adminer / Datenbank

- Adminer URL: `http://localhost:8082`
- System: `PostgreSQL`
- Server: `localhost` (oder `db`, falls Django im Docker-Container laeuft)
- Username/Password/Database: aus `.env`
