# GC-Bridge-4

Django integration bridge between Microtech and Shopware 6.

## Inhaltsverzeichnis

- [Projektueberblick](#projektueberblick)
- [Grundregeln im Projekt](#grundregeln-im-projekt)
- [Lokales Setup](#lokales-setup)
- [Server Setup (ohne SSL, lokal/LAN)](#server-setup-ohne-ssl-lokallan)
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

## Server Setup (ohne SSL, lokal/LAN)

Dieses Setup nutzt `uvicorn` (App-Server) plus `caddy` (Reverse Proxy) auf Port `8080`.

### Linux Server

1. Projekt deployen, `.env` anlegen, dann Dependencies installieren:
```bash
uv sync
```
2. Migrationen ausfuehren:
```bash
.venv/bin/python manage.py migrate
```
3. Caddy installieren (Debian/Ubuntu Beispiel):
```bash
sudo apt update
sudo apt install -y caddy
```
4. Caddyfile deployen:
```bash
sudo cp deploy/caddy/Caddyfile /etc/caddy/Caddyfile
sudo systemctl restart caddy
sudo systemctl enable caddy
```
5. systemd Service fuer Uvicorn installieren:
```bash
sudo cp deploy/linux/gc-bridge-uvicorn.service /etc/systemd/system/gc-bridge-uvicorn.service
sudo systemctl daemon-reload
sudo systemctl enable gc-bridge-uvicorn
sudo systemctl start gc-bridge-uvicorn
```
6. Status pruefen:
```bash
sudo systemctl status gc-bridge-uvicorn
sudo systemctl status caddy
```

### Windows Server 2019

1. Projekt nach `C:\Apps\GC-Bridge-4` deployen, `.env` anlegen, dann Dependencies installieren:
```powershell
cd C:\Apps\GC-Bridge-4
uv sync
```
2. Migrationen ausfuehren:
```powershell
.venv\Scripts\python.exe manage.py migrate
```
3. Django fuer LAN-Zugriff auf `10.0.0.5` konfigurieren (`C:\Apps\GC-Bridge-4\.env`):
```dotenv
DJANGO_SECRET_KEY=change-me
DJANGO_DEBUG=0
DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1,10.0.0.5
DJANGO_CSRF_TRUSTED_ORIGINS=http://localhost:8080,http://127.0.0.1:8080,http://10.0.0.5:8080
DJANGO_SECURE_SSL_REDIRECT=0
DJANGO_SESSION_COOKIE_SECURE=0
DJANGO_CSRF_COOKIE_SECURE=0
DJANGO_USE_X_FORWARDED_HOST=1
DJANGO_USE_X_FORWARDED_PROTO=0
```
4. Caddy installieren:
   - Caddy fuer Windows herunterladen und `caddy.exe` nach `C:\caddy\caddy.exe` legen.
   - `C:\caddy\Caddyfile` mit folgendem Inhalt anlegen:
```caddy
{
    auto_https off
}

http://10.0.0.5:8080, http://localhost:8080, http://127.0.0.1:8080 {
    reverse_proxy 127.0.0.1:8000
}
```
5. Caddy als Service registrieren (PowerShell als Administrator):
```powershell
sc.exe create Caddy binPath= "\"C:\caddy\caddy.exe\" run --config \"C:\caddy\Caddyfile\"" start= auto
sc.exe start Caddy
```
6. Uvicorn als Service registrieren (mit NSSM, PowerShell als Administrator):
   - NSSM herunterladen und z. B. nach `C:\nssm\nssm.exe` legen.
```powershell
C:\nssm\nssm.exe install GC-Bridge-Uvicorn cmd.exe "/c C:\Apps\GC-Bridge-4\deploy\windows\start-uvicorn.cmd"
C:\nssm\nssm.exe set GC-Bridge-Uvicorn AppDirectory C:\Apps\GC-Bridge-4
C:\nssm\nssm.exe set GC-Bridge-Uvicorn Start SERVICE_AUTO_START
C:\nssm\nssm.exe set GC-Bridge-Uvicorn AppStdout C:\Apps\GC-Bridge-4\tmp\logs\uvicorn.out.log
C:\nssm\nssm.exe set GC-Bridge-Uvicorn AppStderr C:\Apps\GC-Bridge-4\tmp\logs\uvicorn.err.log
```
7. Windows-Firewall fuer LAN-Zugriff oeffnen:
```powershell
netsh advfirewall firewall add rule name="GC-Bridge Caddy 8080" dir=in action=allow protocol=TCP localport=8080
```
8. Services starten und pruefen:
```powershell
nssm start GC-Bridge-Uvicorn
sc.exe query Caddy
sc.exe query GC-Bridge-Uvicorn
```
9. Von einem anderen Rechner im gleichen Netz testen:
```powershell
Test-NetConnection 10.0.0.5 -Port 8080
```

Aufruf danach:

- `http://localhost:8080/admin/`
- `http://127.0.0.1:8080/admin/`
- `http://10.0.0.5:8080/admin/`

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

DJANGO_SECRET_KEY=change-me
DJANGO_DEBUG=0
DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1,10.0.0.5
DJANGO_CSRF_TRUSTED_ORIGINS=http://localhost:8080,http://127.0.0.1:8080,http://10.0.0.5:8080
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
