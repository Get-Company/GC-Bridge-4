# GC-Bridge-4

Django integration bridge between Microtech and Shopware 6.

## Inhaltsverzeichnis

- [Projektueberblick](#projektueberblick)
- [Grundregeln im Projekt](#grundregeln-im-projekt)
- [Lokales Setup](#lokales-setup)
- [Server Setup](#server-setup)
  - [Linux Server](#linux-server)
  - [Windows Server 2019 (CLSRV01)](#windows-server-2019-clsrv01)
    - [Architektur](#architektur)
    - [Scheduled Tasks](#scheduled-tasks)
    - [Ersteinrichtung](#ersteinrichtung)
    - [Server starten](#server-starten)
    - [Server stoppen](#server-stoppen)
    - [Server neustarten](#server-neustarten)
    - [Status pruefen](#status-pruefen)
    - [Vollstaendige Diagnose](#vollstaendige-diagnose)
    - [Logdateien](#logdateien)
- [Deployment Pipeline (GitHub Actions)](#deployment-pipeline-github-actions)
- [Health Check](#health-check)
  - [Schnellcheck](#schnellcheck)
  - [Vollstaendiger Health Check](#vollstaendiger-health-check)
  - [Was wird geprueft](#was-wird-geprueft)
  - [Health-Check-Log](#health-check-log)
- [Umgebungsvariablen (.env)](#umgebungsvariablen-env)
- [Sync-Commands](#sync-commands)
  - [Produkte: Microtech -> Django -> Shopware](#produkte-microtech---django---shopware)
  - [Bestellungen: Shopware -> Django -> Microtech](#bestellungen-shopware---django---microtech)
- [Adminer / Datenbank](#adminer--datenbank)

---

## Projektueberblick

Wichtige Basisklassen:

- `BaseModel` (`core/models/base.py`) mit `created_at` und `updated_at`
- `BaseAdmin` (`core/admin.py`) auf Basis von Unfold
- `BaseService` (`core/services/base.py`) als Service-Grundlage

---

## Grundregeln im Projekt

- Secrets nie committen, nur in lokale `.env`.
- Fuer neue Modelle `BaseModel` verwenden.
- Fuer neue Admin-Klassen `BaseAdmin` verwenden.
- Fuer neue Services `BaseService` verwenden.
- Lokale Python-Commands immer mit `.venv/bin/python` ausfuehren.

---

## Lokales Setup

1. Abhaengigkeiten installieren:
```bash
uv sync
```
2. `.env` im Projektroot anlegen (siehe [Umgebungsvariablen](#umgebungsvariablen-env)).
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

---

## Server Setup

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

---

### Windows Server 2019 (CLSRV01)

| | |
|---|---|
| **Projektpfad** | `D:\GC-Bridge-4` |
| **LAN-IP** | `10.0.0.5` |
| **Port (extern)** | `4711` |
| **Hostname** | `CLSRV01` |

#### Architektur

```
Browser / Client im LAN
         |
         | http://10.0.0.5:4711
         v
+------------------+
|  Caddy v2        |  Reverse Proxy, hoert auf :4711
|  (Scheduled Task)|  deploy\caddy\Caddyfile
+------------------+
         |
         | http://127.0.0.1:8000  (nur localhost)
         v
+------------------+
|  Uvicorn         |  ASGI-Server, 1 Worker
|  (Scheduled Task)|  GC_Bridge_4.asgi:application
+------------------+
         |
         v
+------------------+
|  Django App      |
|  GC-Bridge-4     |
+------------------+
```

Uvicorn und Caddy laufen als **Windows Scheduled Tasks** (nicht als sc.exe-Services, da
Uvicorn und Caddy das Windows SCM-Protokoll nicht implementieren und nach ~30 Sekunden
vom Service Controller beendet wuerden).

---

#### Scheduled Tasks

| Task-Name | Trigger | Verzoegerung | Skript | Funktion |
|-----------|---------|--------------|--------|----------|
| `GC-Bridge-Uvicorn` | `ONSTART` | 0 s | `deploy\windows\start-uvicorn.cmd` | Startet Uvicorn ASGI-Server auf `127.0.0.1:8000` |
| `GC-Bridge-Caddy` | `ONSTART` | 10 s | `deploy\windows\start-caddy.cmd` | Startet Caddy Reverse Proxy auf `:4711` |

Beide Tasks laufen unter dem Konto `SYSTEM` mit hoechsten Rechten (`/RL HIGHEST`).
Die 10-Sekunden-Verzoegerung bei Caddy stellt sicher, dass Uvicorn bereits laeuft,
bevor Caddy Verbindungen annimmt.

---

#### Ersteinrichtung

Alle Befehle in einer **Admin CMD** (`cd /d D:\GC-Bridge-4`):

1. Dependencies installieren:
```cmd
uv pip install -r requirements.txt
```
2. `.env` im Projektroot anlegen (siehe [Umgebungsvariablen](#umgebungsvariablen-env)).
3. Migrationen ausfuehren:
```cmd
.venv\Scripts\python.exe manage.py migrate
```
4. Static Files sammeln:
```cmd
.venv\Scripts\python.exe manage.py collectstatic --noinput
```
5. Superuser anlegen (falls noch nicht vorhanden):
```cmd
.venv\Scripts\python.exe manage.py createsuperuser
```
6. Scheduled Tasks anlegen:
```cmd
schtasks /Create /TN "GC-Bridge-Uvicorn" /SC ONSTART /RU SYSTEM /RL HIGHEST /TR "\"D:\GC-Bridge-4\deploy\windows\start-uvicorn.cmd\"" /F
schtasks /Create /TN "GC-Bridge-Caddy" /SC ONSTART /DELAY 0000:10 /RU SYSTEM /RL HIGHEST /TR "\"D:\GC-Bridge-4\deploy\windows\start-caddy.cmd\"" /F
```
7. Firewall-Regel fuer Port 4711 oeffnen:
```cmd
netsh advfirewall firewall add rule name="GC-Bridge Caddy 4711" dir=in action=allow protocol=TCP localport=4711
```
8. Tasks sofort starten:
```cmd
schtasks /Run /TN "GC-Bridge-Uvicorn"
timeout /t 5 /nobreak
schtasks /Run /TN "GC-Bridge-Caddy"
```

---

#### Server starten

Admin CMD:

```cmd
schtasks /Run /TN "GC-Bridge-Uvicorn"
timeout /t 5 /nobreak
schtasks /Run /TN "GC-Bridge-Caddy"
```

---

#### Server stoppen

Admin CMD:

```cmd
:: Caddy stoppen
taskkill /F /FI "IMAGENAME eq caddy.exe"

:: Uvicorn stoppen (findet den Python-Prozess auf Port 8000)
powershell -Command "Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess | ForEach-Object { Stop-Process -Id $_ -Force -ErrorAction SilentlyContinue }"
```

---

#### Server neustarten

Admin CMD:

```cmd
:: 1. Stoppen
taskkill /F /FI "IMAGENAME eq caddy.exe"
powershell -Command "Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess | ForEach-Object { Stop-Process -Id $_ -Force -ErrorAction SilentlyContinue }"
timeout /t 3 /nobreak

:: 2. Starten
schtasks /Run /TN "GC-Bridge-Uvicorn"
timeout /t 5 /nobreak
schtasks /Run /TN "GC-Bridge-Caddy"
```

---

#### Status pruefen

```cmd
:: Tasks abfragen
schtasks /Query /TN "GC-Bridge-Uvicorn" /FO LIST
schtasks /Query /TN "GC-Bridge-Caddy" /FO LIST

:: Ports pruefen (8000 = Uvicorn, 4711 = Caddy)
netstat -ano | findstr /C:":8000 " /C:":4711 "

:: HTTP-Test Uvicorn direkt
powershell -Command "(Invoke-WebRequest -Uri http://127.0.0.1:8000/admin/ -UseBasicParsing -TimeoutSec 5).StatusCode"

:: HTTP-Test ueber Caddy
powershell -Command "(Invoke-WebRequest -Uri http://127.0.0.1:4711/admin/ -UseBasicParsing -TimeoutSec 5).StatusCode"
```

Erwarteter Rueckgabewert: `200`

Aufruf im Browser:
- `http://localhost:4711/admin/`
- `http://10.0.0.5:4711/admin/`

---

#### Vollstaendige Diagnose

Das Skript `deploy\windows\check_server.bat` prueft automatisch alles auf einmal:
Dateien, Python/Uvicorn/Caddy-Version, Scheduled Tasks, Ports, Firewall-Regeln,
die letzten 20 Zeilen jeder Logdatei sowie einen Uvicorn-Schnelltest mit HTTP-Antwort.

```cmd
:: Diagnose in der Konsole
deploy\windows\check_server.bat

:: Diagnose in eine Datei schreiben (zum Weiterleiten)
deploy\windows\check_server.bat > diagnose.txt 2>&1
```

---

#### Logdateien

Alle Logs liegen in `tmp\logs\` (wird beim ersten Start automatisch angelegt):

| Datei | Inhalt |
|-------|--------|
| `tmp\logs\uvicorn.out.log` | Uvicorn stdout (Request-Logs) |
| `tmp\logs\uvicorn.err.log` | Uvicorn Fehler + Start/Stop-Zeitstempel |
| `tmp\logs\caddy.err.log` | Caddy Fehler + Start/Stop-Zeitstempel |
| `tmp\logs\caddy-runtime.log` | Caddy internes Log |
| `tmp\logs\caddy-access.log` | Caddy Access-Log |
| `tmp\logs\deploy.log` | Deployment-Log (GitHub Actions) |

Letzte 50 Zeilen eines Logs anzeigen (PowerShell):

```powershell
Get-Content D:\GC-Bridge-4\tmp\logs\uvicorn.err.log -Tail 50
Get-Content D:\GC-Bridge-4\tmp\logs\deploy.log -Tail 50
```

---

## Deployment Pipeline (GitHub Actions)

Neue Versionen werden automatisch auf CLSRV01 deployed, sobald ein Git-Tag gepusht wird.

### Ablauf

```
git tag v1.2.3 && git push origin v1.2.3
        |
        v
GitHub erkennt Tag --> startet Workflow (.github/workflows/deploy.yml)
        |
        v
Self-Hosted Runner auf CLSRV01 fuehrt aus:
  1. git fetch --tags origin
  2. git checkout -f v1.2.3
  3. uv pip install -r requirements.txt
  4. manage.py migrate --noinput
  5. manage.py collectstatic --noinput
  6. Uvicorn neustarten (Port 8000 + schtasks /Run)
        |
        v
Ergebnis in tmp\logs\deploy.log + GitHub Actions UI
```

### Deployment ausloesen (von Linux-Dev-Rechner)

```bash
git tag v1.2.3
git push origin v1.2.3
```

### Deployment manuell testen (Admin CMD auf CLSRV01)

```cmd
cd /d D:\GC-Bridge-4
set DEPLOY_TAG=v1.2.3
deploy\windows\update.cmd
```

### Self-Hosted Runner einrichten (einmalig, Admin PowerShell auf CLSRV01)

1. GitHub oeffnen: Repo → **Settings** → **Actions** → **Runners** → **New self-hosted runner**
2. Windows / x64 auswaehlen → die angezeigten Download- und Konfigurationsbefehle kopieren
3. Runner-Verzeichnis anlegen und konfigurieren:

```powershell
mkdir D:\GC-Bridge-runner
cd D:\GC-Bridge-runner

# Download-Befehl aus GitHub-UI einfuegen (aktuellste Version)
# Dann konfigurieren (Token aus GitHub-UI, ist zeitlich begrenzt):
.\config.cmd --url https://github.com/OWNER/REPO --token GITHUB_TOKEN --name CLSRV01 --labels Windows,x64 --runasservice
```

4. Als Windows-Dienst installieren und starten:

```powershell
.\svc.cmd install
.\svc.cmd start
```

Der Runner-Dienst laeuft als `SYSTEM` und hat damit die noetigen Rechte fuer
`schtasks /Run`. Ggf. Bitdefender-Ausnahme fuer `D:\GC-Bridge-runner\` eintragen.

### Runner-Dienst verwalten

```powershell
# Status
.\svc.cmd status

# Stoppen / Starten
.\svc.cmd stop
.\svc.cmd start

# Deinstallieren
.\svc.cmd uninstall
```

---

---

## Health Check

### Schnellcheck

Vier Befehle fuer eine sofortige Uebersicht — in **Admin CMD** auf CLSRV01:

```cmd
:: Ports
netstat -ano | findstr /C:":8000 " /C:":4711 "

:: HTTP-Status
powershell -Command "(Invoke-WebRequest -Uri http://127.0.0.1:8000/admin/ -UseBasicParsing -TimeoutSec 5).StatusCode"
powershell -Command "(Invoke-WebRequest -Uri http://127.0.0.1:4711/admin/ -UseBasicParsing -TimeoutSec 5).StatusCode"

:: Aktuelle Version
type D:\GC-Bridge-4\VERSION
```

Erwartete Ausgabe: Ports LISTENING, HTTP-Status `200`, Versionsstring wie `v1.2.3`.

---

### Vollstaendiger Health Check

Das Skript `deploy\windows\health_check.cmd` prueft alle kritischen Komponenten
automatisch, gibt ein klares `[OK]` / `[WARN]` / `[ERROR]` pro Pruefpunkt aus
und schreibt alles in `tmp\logs\health_check.log`.

**Aufruf in Admin CMD:**

```cmd
cd /d D:\GC-Bridge-4
deploy\windows\health_check.cmd
```

**Ergebnis in Datei speichern** (zum Weiterleiten):

```cmd
deploy\windows\health_check.cmd > health_check_output.txt 2>&1
```

**Exitcode:**
- `0` — alles OK (kein einziger ERROR)
- `1` — mindestens ein Fehler vorhanden

---

### Was wird geprueft

| # | Bereich | Pruefpunkt | OK-Kriterium |
|---|---------|------------|--------------|
| 1 | **Version** | `VERSION`-Datei | Datei vorhanden und nicht leer |
| 2 | **Ports** | Port 8000 (Uvicorn) | LISTENING |
| 2 | **Ports** | Port 4711 (Caddy) | LISTENING |
| 3 | **HTTP** | `http://127.0.0.1:8000/admin/` | HTTP 200 |
| 3 | **HTTP** | `http://127.0.0.1:4711/admin/` | HTTP 200 |
| 4 | **Django** | `manage.py check` | Kein Fehler |
| 4 | **Django** | `manage.py migrate --check` | Keine offenen Migrationen |
| 5 | **Scheduled Tasks** | `GC-Bridge-Uvicorn` | Task registriert |
| 5 | **Scheduled Tasks** | `GC-Bridge-Caddy` | Task registriert |
| 5 | **Scheduled Tasks** | `GC-Bridge-Runner` | Task registriert |
| 6 | **Runner** | GitHub Actions Runner Dienst | Status RUNNING |
| 7 | **Disk** | Freier Speicher auf `D:\` | Mehr als 2 GB frei |
| 8 | **Logs** | `uvicorn.err.log` (letzte 200 Zeilen) | Keine ERROR-Eintraege |
| 8 | **Logs** | `caddy.err.log` (letzte 200 Zeilen) | Keine ERROR-Eintraege |
| 8 | **Logs** | `deploy.log` (letzte 200 Zeilen) | Keine ERROR-Eintraege |

**Ausgabe-Beispiel:**

```
================================================================
 GC-Bridge Health Check  20.02.2026 12:00:00
================================================================

--- VERSION ---
[OK]    Deployed Version: v1.2.3

--- PORTS ---
[OK]    Port 8000 - Uvicorn aktiv
[OK]    Port 4711 - Caddy aktiv

--- HTTP CHECKS ---
[OK]    http://127.0.0.1:8000/admin/ - HTTP 200
[OK]    http://127.0.0.1:4711/admin/ - HTTP 200

--- DJANGO ---
[OK]    manage.py check - OK
[OK]    Migrationen - aktuell

--- SCHEDULED TASKS ---
[OK]    Task GC-Bridge-Uvicorn - registriert
[OK]    Task GC-Bridge-Caddy - registriert
[OK]    Task GC-Bridge-Runner - registriert

--- GITHUB ACTIONS RUNNER ---
[OK]    GitHub Actions Runner - RUNNING

--- DISK SPACE ---
[OK]    D:\ freier Speicher: 45.3 GB

--- LOGS (letzte 200 Zeilen) ---
[OK]    uvicorn.err.log - keine Fehler
[OK]    caddy.err.log - keine Fehler
[OK]    deploy.log - keine Fehler

================================================================
 ERGEBNIS: 0 Fehler  /  0 Warnungen
================================================================
```

---

### Health-Check-Log

Das Skript schreibt bei jedem Aufruf ein vollstaendiges Protokoll nach:

```
tmp\logs\health_check.log
```

Der Log wird bei jedem Aufruf **neu ueberschrieben** (kein Anhaengen), damit er
immer den aktuellen Zustand repraesentiert. Letzten Check anzeigen:

```powershell
Get-Content D:\GC-Bridge-4\tmp\logs\health_check.log
```

---

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
DJANGO_CSRF_TRUSTED_ORIGINS=http://localhost:4711,http://127.0.0.1:4711,http://10.0.0.5:4711
```

---

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

---

## Adminer / Datenbank

- Adminer URL: `http://localhost:8082`
- System: `PostgreSQL`
- Server: `localhost` (oder `db`, falls Django im Docker-Container laeuft)
- Username/Password/Database: aus `.env`
