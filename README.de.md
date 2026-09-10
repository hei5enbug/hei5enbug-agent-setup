# hei5enbug-agent-setup

[English](./README.md) | [한국어](./README.ko.md) | [日本語](./README.ja.md) | [简体中文](./README.zh-CN.md) | [Español](./README.es.md) | **Deutsch** | [Français](./README.fr.md)

Eine portable Sammlung benutzerdefinierter Skills für KI-Coding-Agenten, gebaut, um ohne host-spezifische Anpassungen über mehrere Agent-Hosts hinweg geteilt zu werden.

## Überblick

Jeder im Plugin enthaltene Skill liegt in einem eigenen Ordner unter `skills/` und ist in sich geschlossen.
Skills außerhalb des Plugins liegen unter `standalone-skills/`.
Dieselbe `SKILL.md` funktioniert unverändert auf jedem unterstützten Host.

## Unterstützte Hosts

- Claude Code
- Codex
- OpenCode (über das [Oh My OpenAgent](https://github.com/code-yeongyu/oh-my-openagent)-Plugin)

## Struktur

```
hei5enbug-agent-setup/
├── .agents/plugins/marketplace.json
├── .claude-plugin/
│   ├── marketplace.json
│   └── plugin.json
├── .codex-plugin/plugin.json
├── .github/workflows/validate.yml
├── LICENSE
├── pyproject.toml
├── standalone-agents/
│   ├── scout.md
│   └── codex-explorer.toml
├── standalone-skills/
│   └── omo-model-config/
└── skills/
    ├── decision-navigator/
    ├── deep-interview/
    ├── flowchart-design/
    ├── humanize-korean/
    ├── markdown-to-confluence/
    ├── skill-builder/
    ├── suggest-commit/
    ├── technical-design-writer/
    └── tiki-taka/
```

Jeder Plugin-Skill-Ordner enthält seine eigene `SKILL.md` sowie alle benötigten Referenzen oder Skripte.
Die Plugin-Manifeste paketieren dasselbe Verzeichnis `skills/` für Codex und Claude Code, ohne Skills in host-spezifische Verzeichnisse zu kopieren.
Das Verzeichnis `standalone-skills/` gehört zu keinem Skill-Suchpfad der beiden Plugins.

Das Verzeichnis `standalone-agents/` enthält die Subagent-Definitionen, auf die `CLAUDE.md` und `AGENTS.md` namentlich verweisen.
Kopiere `scout.md` von Hand nach `~/.claude/agents/`. Kopiere `codex-explorer.toml` nach `~/.codex/agents/explorer.toml`;
sie überschreibt den eingebauten Codex-`explorer`, sodass Reasoning-Aufwand und Nur-Lese-Sandbox festgelegt sind. Sie legt kein Modell fest
und erbt daher das Standardmodell des Hosts, während `scout` auf Claude Code eines fest vorgibt.
Beide bleiben außerhalb des Plugin-Bundles, damit die Installation des Plugins niemals einen Subagenten hinzufügt.

## Plugin installieren

Installiere das Bundle einmal aus dem GitHub-Repository.

### Codex

```bash
codex plugin marketplace add hei5enbug/hei5enbug-agent-setup --ref main
codex plugin add hei5enbug-agent-setup@hei5enbug
```

### Claude Code

```bash
claude plugin marketplace add hei5enbug/hei5enbug-agent-setup
claude plugin install hei5enbug-agent-setup@hei5enbug
```

## Plugin aktualisieren

Beide Plugin-Manifeste und `pyproject.toml` tragen dieselbe semantische Version, derzeit `0.2.0`. Erhöhe die Version vor einem
Release gemeinsam in `.codex-plugin/plugin.json`, `.claude-plugin/plugin.json` und `pyproject.toml`, und erst, nachdem die
Entwicklungsprüfungen unten bestanden sind.

Aktualisiere Codex, sobald das Release verfügbar ist:

```bash
codex plugin marketplace upgrade hei5enbug
codex plugin add hei5enbug-agent-setup@hei5enbug
```

Aktualisiere Claude Code, sobald das Release verfügbar ist:

```bash
claude plugin marketplace update hei5enbug
claude plugin update hei5enbug-agent-setup@hei5enbug
```

Starte nach dem Update einen neuen Codex-Thread oder Claude Code neu, damit der Host die neuen Skill-Versionen lädt.

## Entwicklungsprüfungen

Die mitgelieferten Skripte benötigen Python 3.12 oder neuer mit PyYAML, die Node-Tests benötigen Node.js.
Führe mit denselben Befehlen die drei Prüfungen aus, die `.github/workflows/validate.yml` unter macOS und Linux ausführt:

```bash
python3 -m pip install -e ".[dev]"
for skill in skills/*/ standalone-skills/*/; do python3 skills/skill-builder/scripts/quick_validate.py "$skill"; done
python3 -m pytest
node --test skills/markdown-to-confluence/tests/test_render_diagrams.mjs
```

## Sprache der Anweisungen

Ausführbare Skill-Anweisungen sind auf Englisch geschrieben. Eine `README.ko.md` in einem Skill-Verzeichnis ist eine nicht
maßgebliche koreanische Übersetzung, die mit ihrem englischen Dokument synchron gehalten wird. Sie ist für menschliche Leser
bestimmt und darf von einem Agenten während der Skill-Ausführung nicht geladen oder verwendet werden. Koreanischer Text bleibt in
ausführbaren Dateien nur dann, wenn er Zielsprachen-Daten ist, etwa Auslösephrasen, Beispiele, verpflichtende Ausgabe-Labels oder Evaluationsdaten.

## Skills

| Skill | Was er tut |
|---|---|
| [`decision-navigator`](skills/decision-navigator/SKILL.md) | Zerlegt ein Vorhaben über mehrere Sitzungen in Entscheidungs-Tickets und löst sie einzeln, bis der Implementierungsweg klar ist. |
| [`deep-interview`](skills/deep-interview/SKILL.md) | Führt ein sokratisches Interview, das die Mehrdeutigkeit der Anforderung nach jeder Antwort bewertet, und geht erst zur Ausführung über, wenn der Wert unter den Schwellenwert fällt. [Koreanische Anleitung](skills/deep-interview/README.ko.md) |
| [`flowchart-design`](skills/flowchart-design/SKILL.md) | Ein gemeinsamer Design-Standard, damit Flussdiagramme aus SVG, HTML/CSS, Figma oder draw.io wie ein einheitliches Designsystem wirken. |
| [`humanize-korean`](skills/humanize-korean/SKILL.md) | Schreibt KI-klingenden koreanischen Text so um, dass er natürlich und menschlich wirkt, ohne den Inhalt zu verändern. [Koreanische Anleitung](skills/humanize-korean/README.ko.md) |
| [`markdown-to-confluence`](skills/markdown-to-confluence/SKILL.md) | Veröffentlicht ein Markdown-Dokument als Confluence-Seite und hält die Seite bei späteren Änderungen korrekt: Inhaltsverzeichnis-Makro, eingebettete Bilder, Anhänge und als Bild gerenderte Diagramme. |
| [`skill-builder`](skills/skill-builder/SKILL.md) | Erstellt, testet und verpackt Agenten-Skills in einem Zyklus aus Entwurf → Test → Review → Verbesserung. |
| [`suggest-commit`](skills/suggest-commit/SKILL.md) | Liest gestagte und ungestagte Änderungen zusammen, oder den von dir genannten Bereich, samt jüngster Commit-Historie und schlägt fünf Commit-Nachrichten im Stil des Repositorys vor. |
| [`technical-design-writer`](skills/technical-design-writer/SKILL.md) | Regeln und ein fünfstufiger Prozess, der das Inhaltsverzeichnis schrittweise eingrenzt, zum Schreiben oder Überarbeiten technischer Design-Dokumente. [Koreanische Anleitung](skills/technical-design-writer/README.ko.md) |
| [`tiki-taka`](skills/tiki-taka/SKILL.md) | Führt eine auf Runden begrenzte Debatte zwischen dem aktuellen Agenten und einer gegenüberliegenden Claude/Codex-Sitzung, um Probleme aufzudecken und zu klären. [Koreanische Anleitung](skills/tiki-taka/README.ko.md) |

## Verwandte Links

- [`omo-model-config`](standalone-skills/omo-model-config/SKILL.md) bleibt als eigenständiger Quellcode
  erhalten und ist nicht Teil der Skill-Liste des Plugins.
- [Oh My OpenAgent](https://github.com/code-yeongyu/oh-my-openagent) — Plugin-System, dessen Modell-Routing
  der eigenständige Skill aktualisiert

## Lizenz

Dieses Repository steht unter der Apache License 2.0. Den vollständigen Text findest du in [`LICENSE`](./LICENSE).
