## RuFlo mit Claude Code und Codex CLI einrichten

Diese Anleitung beschreibt die lokale Einrichtung von **RuFlo** für ein Projekt mit **Claude Code** und **Codex CLI**.

### Voraussetzungen

Installiert und funktionsfähig sein sollten:

- **Node.js**
- **npm**
- **Claude Code**
- **Codex CLI**

Prüfen:

```bash
node -v
npm -v
claude --version
codex --version
```

Empfohlen ist eine stabile **Node-LTS-Version**, z. B. **Node 22**.

---

### Node-Version mit nvm auf LTS umstellen

Falls noch keine passende LTS-Version aktiv ist, zuerst `nvm` installieren und dann auf Node 22 wechseln.

`nvm` installieren:

```bash
curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.3/install.sh | bash
```

`nvm` in der aktuellen Shell laden:

```bash
export NVM_DIR="$HOME/.nvm"
[ -s "$NVM_DIR/nvm.sh" ] && \. "$NVM_DIR/nvm.sh"
```

Version prüfen:

```bash
nvm --version
```

Node 22 installieren und aktivieren:

```bash
nvm install 22
nvm use 22
```

Danach erneut prüfen:

```bash
node -v
npm -v
```

---

### RuFlo CLI testen

Vor der Initialisierung prüfen, ob die aktuelle RuFlo-CLI geladen werden kann:

```bash
npx ruflo@latest --version
```

Beispielausgabe:

```bash
ruflo v3.5.42
```

---

### RuFlo im Projekt initialisieren

Im Projektordner ausführen:

```bash
npx ruflo@latest init
```

Dabei werden je nach Projektzustand RuFlo- und Claude-Code-Dateien angelegt oder ergänzt.

Typisch relevant sind danach:

- `CLAUDE.md`
- `.claude/settings.json`
- `.mcp.json`
- `.claude-flow/`

---

### Wichtige Dateien im Projekt

#### `CLAUDE.md`
Enthält Projektregeln, Kontext und Hinweise für Claude Code.

#### `.claude/settings.json`
Projektweite Claude-Code-Konfiguration, z. B.:

- Hooks
- erlaubte Tools
- MCP-bezogene Einstellungen
- RuFlo-Optionen

#### `.mcp.json`
Projektlokale MCP-Server-Konfiguration.

#### `.claude-flow/config.yaml`
RuFlo-Laufzeitkonfiguration.

#### `.claude-flow/`
Enthält Runtime-Daten wie Logs, Sessions, Metriken und weitere Zustände.

---

### Claude Code prüfen

Verfügbare MCP-Server anzeigen:

```bash
claude mcp list
```

Erwartet wird ein funktionierender Eintrag für **`ruflo`**.

---

### Codex CLI prüfen

Vorhandene MCP-Server anzeigen:

```bash
codex mcp list
```

---

### RuFlo in Codex CLI einbinden

Falls RuFlo dort noch nicht vorhanden ist, global hinzufügen:

```bash
codex mcp add ruflo -- npx -y ruflo@latest mcp start
```

Anschließend erneut prüfen:

```bash
codex mcp list
```

Erwartet wird ein aktiver Eintrag ähnlich zu:

```text
ruflo  npx  -y ruflo@latest mcp start
```

---

### Codex im Projekt starten

Im Projektordner:

```bash
codex
```

Danach kann Codex direkt im Repository arbeiten und über MCP auf RuFlo zugreifen.

---

### Erster Funktionstest

Zum Testen kann in Codex oder Claude geprüft werden:

- ob **RuFlo verfügbar** ist
- ob **Memory** aktiv ist
- ob **Swarm** verfügbar ist
- ob der **Projektordner korrekt erkannt** wurde

Zusätzlich sollten Dateien wie diese sichtbar sein:

- `CLAUDE.md`
- `.mcp.json`
- `.claude/settings.json`
- `.claude-flow/config.yaml`

---

### Swarm initialisieren

Für strukturierte Aufgabenbearbeitung kann ein einfacher Swarm verwendet werden.

Typische Prüfung danach:

- Swarm läuft
- Topologie ist aktiv
- Agenten oder Rollen sind verfügbar

Beispielhafte Rollen:

- `coordinator`
- `coder`
- `researcher`

---

### Typische Nutzung im Projekt

#### Claude Code
Geeignet für:

- Architektur verstehen
- Repository analysieren
- Änderungen reviewen
- Dokumentation und Regeln berücksichtigen

#### Codex CLI
Geeignet für:

- klar abgegrenzte Features
- Fixes
- gezielte Codeänderungen
- reproduzierbare Arbeitsaufträge

#### RuFlo
Dient als Koordinationsschicht für:

- Memory
- Session-Kontext
- Task- und Swarm-Steuerung
- MCP-Werkzeuge

---

### Empfohlene Arbeitsweise

Nicht zwei Agenten gleichzeitig in derselben Working Copy schreiben lassen.

Empfohlen:

- getrennte Branches
- idealerweise getrennte `git worktree`s

Beispiel:

```bash
git worktree add ../Archithek-claude -b feat/example-claude
git worktree add ../Archithek-codex -b feat/example-codex
```

Rollenverteilung:

- **Claude** = Analyse, Architektur, Review, Doku
- **Codex** = Umsetzung
- **RuFlo** = Koordination, Memory, Swarm

---

### Praktische Reihenfolge für Fixes

1. Projektzustand analysieren lassen
2. Fix-Kandidaten priorisieren
3. genau eine Task auswählen
4. gezielt umsetzen
5. testen
6. nächsten Schritt angehen

So bleibt die Arbeit mit Claude, Codex und RuFlo kontrollierbar und nachvollziehbar.
