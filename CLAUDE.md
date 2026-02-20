# CLAUDE.md

## Current Task: Windows Server Setup (Uvicorn + Caddy)

### Situation
Deploying GC-Bridge Django app on Windows Server 2019 (hostname CLSRV01) with Uvicorn behind Caddy reverse proxy on port 4711.

### What's done
- Reset completed: old sc.exe services and scheduled tasks removed
- Files deployed: `deploy/windows/start-uvicorn.cmd`, `deploy/windows/start-caddy.cmd`, `deploy/caddy/caddy.exe`, `deploy/caddy/Caddyfile`
- Uvicorn quick-test confirmed working (HTTP 200 on /admin/)
- Python 3.14.0, Uvicorn 0.41.0, Caddy v2.10.2

### What needs to be done NOW
Run these commands in an **Admin CMD** (cd /d D:\GC-Bridge-4 first):

**1. Reset (clean slate):**
```batch
sc.exe stop GC-Bridge-Uvicorn & sc.exe delete GC-Bridge-Uvicorn
sc.exe stop Caddy & sc.exe delete Caddy
schtasks /Delete /TN "GC-Bridge-Uvicorn" /F
schtasks /Delete /TN "GC-Bridge-Caddy" /F
schtasks /Delete /TN "GC-Bridge-Start-Uvicorn" /F
schtasks /Delete /TN "GC-Bridge-Start-Caddy" /F
netsh advfirewall firewall delete rule name="GC-Bridge Caddy 4711"
```

**2. Setup (scheduled tasks, NOT sc.exe services):**
```batch
if not exist tmp\logs mkdir tmp\logs
deploy\caddy\caddy.exe validate --config deploy\caddy\Caddyfile --adapter caddyfile
schtasks /Create /TN "GC-Bridge-Uvicorn" /SC ONSTART /RU SYSTEM /RL HIGHEST /TR "\"D:\GC-Bridge-4\deploy\windows\start-uvicorn.cmd\"" /F
schtasks /Create /TN "GC-Bridge-Caddy" /SC ONSTART /DELAY 0000:10 /RU SYSTEM /RL HIGHEST /TR "\"D:\GC-Bridge-4\deploy\windows\start-caddy.cmd\"" /F
netsh advfirewall firewall add rule name="GC-Bridge Caddy 4711" dir=in action=allow protocol=TCP localport=4711
```

**3. Start:**
```batch
schtasks /Run /TN "GC-Bridge-Uvicorn"
timeout /t 5 /nobreak
schtasks /Run /TN "GC-Bridge-Caddy"
timeout /t 5 /nobreak
```

**4. Verify:**
```batch
netstat -ano | findstr /R /C:":8000 .*LISTENING"
netstat -ano | findstr /R /C:":4711 .*LISTENING"
powershell -Command "Invoke-WebRequest -Uri http://127.0.0.1:8000/admin/ -UseBasicParsing -TimeoutSec 5"
powershell -Command "Invoke-WebRequest -Uri http://127.0.0.1:4711/admin/ -UseBasicParsing -TimeoutSec 5"
```

### Key decisions
- **sc.exe services DO NOT WORK** for Uvicorn/Caddy — they don't implement the Windows SCM protocol, so the service controller kills them after ~30s
- Use **scheduled tasks** (schtasks) instead — they run the process directly without SCM
- Bitdefender GravityZone blocks .bat/.cmd files in deploy/windows/ — run commands manually or add exclusions
- Uvicorn listens on 127.0.0.1:8000, Caddy reverse-proxies on :4711
- LAN IP: 10.0.0.5

### Log files (for debugging)
- `tmp/logs/uvicorn.out.log` — Uvicorn stdout
- `tmp/logs/uvicorn.err.log` — Uvicorn errors + start/stop timestamps
- `tmp/logs/caddy.err.log` — Caddy errors + start/stop timestamps
- `tmp/logs/caddy-runtime.log` — Caddy internal log
- `tmp/logs/caddy-access.log` — Caddy access log

### Important note
- `deploy/windows/setup_server.bat` (renamed to `setup.cmd`) is blocked by Bitdefender GravityZone on the server. The file is stuck with NTFS locks. Ignore it — use manual commands instead.

---

## Deployment Pipeline: GitHub Actions + Self-Hosted Runner

### Konzept
Push eines Version-Tags (z.B. `v1.2.3`) → GitHub Actions triggert Workflow → Self-Hosted Runner auf CLSRV01 führt `deploy/windows/update.cmd` aus → git checkout, uv pip install, migrate, collectstatic, Uvicorn-Neustart.

### Deploy-Log
`tmp/logs/deploy.log` — vollständiger Log jedes Deployments

### Einmalig: Self-Hosted Runner auf CLSRV01 einrichten (Admin PowerShell)

```powershell
# 1. Runner-Verzeichnis anlegen
mkdir D:\GC-Bridge-runner
cd D:\GC-Bridge-runner

# 2. Runner herunterladen (aktuellste Version von GitHub holen)
#    GitHub → Repo → Settings → Actions → Runners → New self-hosted runner
#    → Windows x64 → die angezeigten Befehle ausführen (Token ist zeitlich begrenzt!)

# 3. Runner konfigurieren (Token aus GitHub-UI kopieren)
.\config.cmd --url https://github.com/OWNER/REPO --token TOKEN --name CLSRV01 --labels Windows,x64 --runasservice

# 4. Runner als Windows-Dienst installieren und starten
.\svc.cmd install
.\svc.cmd start
```

**Hinweis:** Der Runner-Dienst läuft als `SYSTEM` und hat damit Rechte für `schtasks /Run`.
Bitdefender-Ausnahme für `D:\GC-Bridge-runner\` ggf. eintragen.

### Deployment auslösen (von Linux-Dev-Rechner)

```bash
git tag v1.2.3
git push origin v1.2.3
```

### Update-Skript manuell testen (Admin CMD auf CLSRV01)

```batch
set DEPLOY_TAG=v1.2.3
D:\GC-Bridge-4\deploy\windows\update.cmd
```
