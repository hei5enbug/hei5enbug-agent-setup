# hei5enbug-agent-setup

[English](./README.md) | [한국어](./README.ko.md) | [日本語](./README.ja.md) | [简体中文](./README.zh-CN.md) | [Español](./README.es.md) | **Deutsch** | [Français](./README.fr.md)

Eine portable Sammlung benutzerdefinierter Skills für KI-Coding-Agenten, gebaut, um ohne host-spezifische Anpassungen über mehrere Agent-Hosts hinweg geteilt zu werden.

## Überblick

Jeder im Plugin enthaltene Skill liegt in einem eigenen Ordner unter `skills/`.
Skills außerhalb des Plugins liegen unter `standalone-skills/`.
Dieselbe `SKILL.md` funktioniert unverändert auf jedem unterstützten Host.

## Unterstützte Hosts

- Claude Code
- Codex
- OpenCode (über das [Oh My OpenAgent](https://github.com/code-yeongyu/oh-my-openagent)-Plugin)

## Struktur

```
hei5enbug-agent-setup/
├── standalone-skills/
│   ├── omo-model-config/
│   └── portable-opencode-setup/
└── skills/
    ├── deep-interview/
    ├── flowchart-design/
    ├── humanize-korean/
    ├── markdown-to-confluence/
    ├── skill-builder/
    ├── suggest-commit/
    ├── technical-design-writer/
    └── tiki-taka/
```

Jeder Ordner enthält seine eigene `SKILL.md` sowie alle benötigten Referenzen oder Skripte.
Das Plugin erkennt nur `skills/`, nicht `standalone-skills/`.

## Skills

| Skill | Was er tut |
|---|---|
| [`deep-interview`](skills/deep-interview/SKILL.md) | Führt ein sokratisches Interview, das die Mehrdeutigkeit der Anforderung nach jeder Antwort bewertet, und geht erst zur Ausführung über, wenn der Wert unter den Schwellenwert fällt. |
| [`flowchart-design`](skills/flowchart-design/SKILL.md) | Ein gemeinsamer Design-Standard, damit Flussdiagramme aus SVG, HTML/CSS, Figma oder draw.io wie ein einheitliches Designsystem wirken. |
| [`humanize-korean`](skills/humanize-korean/SKILL.md) | Schreibt KI-klingenden koreanischen Text so um, dass er natürlich und menschlich wirkt, ohne den Inhalt zu verändern. |
| [`markdown-to-confluence`](skills/markdown-to-confluence/SKILL.md) | Veröffentlicht ein Markdown-Dokument als Confluence-Seite und hält die Seite bei späteren Änderungen korrekt: Inhaltsverzeichnis-Makro, eingebettete Bilder, Anhänge und als Bild gerenderte Diagramme. |
| [`skill-builder`](skills/skill-builder/SKILL.md) | Erstellt, testet und verpackt Agenten-Skills in einem Zyklus aus Entwurf → Test → Review → Verbesserung. |
| [`suggest-commit`](skills/suggest-commit/SKILL.md) | Liest den aktuellen Diff und die jüngste Commit-Historie und schlägt fünf Commit-Nachrichten im Stil des Repositorys vor. |
| [`technical-design-writer`](skills/technical-design-writer/SKILL.md) | Regeln und ein fünfstufiger Prozess, der das Inhaltsverzeichnis schrittweise eingrenzt, zum Schreiben oder Überarbeiten technischer Design-Dokumente. |
| [`tiki-taka`](skills/tiki-taka/SKILL.md) | Führt eine auf Runden begrenzte Debatte zwischen dem aktuellen Agenten und einer gegenüberliegenden Claude/Codex-Sitzung, um Probleme aufzudecken und zu klären. |

## Verwandte Links

- [`omo-model-config`](standalone-skills/omo-model-config/SKILL.md) und
  [`portable-opencode-setup`](standalone-skills/portable-opencode-setup/SKILL.md) bleiben als eigenständiger
  Quellcode erhalten und sind nicht Teil der Skill-Liste des Plugins.
- [Oh My OpenAgent](https://github.com/code-yeongyu/oh-my-openagent) — Plugin-System, das die eigenständigen
  OpenCode-Skills konfigurieren
