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
