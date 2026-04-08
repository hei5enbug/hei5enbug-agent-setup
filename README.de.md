# hei5enbug-agent-setup

[English](./README.md) | [한국어](./README.ko.md) | [日本語](./README.ja.md) | [简体中文](./README.zh-CN.md) | [Español](./README.es.md) | **Deutsch** | [Français](./README.fr.md)

Modell- und Variant-Konfiguration für einen AI-Agent-Harness, zugewiesen passend zur Rolle jedes Agenten.

## Überblick

Jeder Agent in einem Harness erfordert unterschiedliche Fähigkeiten. Diese Konfiguration optimiert `model`, `variant` und Fallback-Ketten pro Agentenrolle und Aufgabenkategorie.

## Unterstützte Tools

- [OpenCode](https://github.com/code-yeongyu/oh-my-openagent) (über das [Oh My OpenAgent](https://github.com/code-yeongyu/oh-my-openagent)-Plugin)

## Struktur

```
hei5enbug-agent-setup/
├── oh-my-openagent.json       # Konfigurationsdatei, die vom Skill gelesen und bearbeitet wird
├── available-models.json     # Allowlist, die vom Skill zur Validierung von Modelländerungen verwendet wird
└── .opencode/
    └── skills/
        └── omo-model-config/ # Benutzerdefinierter Skill für sichere Konfigurationsbearbeitung
            └── SKILL.md
```

## Benutzerdefinierte Skills

### omo-model-config

Ein Workflow zur sicheren Bearbeitung von Agenten-Modellzuweisungen. Er wendet folgende Regeln an:

- **GitHub-first-Auflösung** — die Upstream-Dokumentation von [oh-my-openagent](https://github.com/code-yeongyu/oh-my-openagent) ist die primäre Autorität für das Modell-Rollen-Matching
- **Verfügbarkeits-Gate** — jedes Modell muss in der Allowlist von `available-models.json` vorhanden sein
- **Provider-Diversitäts-Gate** — erforderliche Provider müssen in der Fallback-Kette jedes Agenten abgedeckt sein
- **Begrenzter Bearbeitungsumfang** — nur die Felder `model`, `variant` und `fallback_models` werden geändert; alles andere bleibt erhalten

Details unter [`.opencode/skills/omo-model-config/SKILL.md`](.opencode/skills/omo-model-config/SKILL.md).

## Verwendung

Als Projektstamm in einem unterstützten Agenten-Tool öffnen. Die Konfiguration wird beim Sitzungsstart automatisch geladen.

```bash
cd hei5enbug-agent-setup
opencode
```

### Modellzuweisungen ändern

Den `omo-model-config`-Skill innerhalb der Agentensitzung aufrufen:

```
/omo-model-config
```

Oder den Agenten direkt bitten:

```
"Ändere das primary model von Oracle zu claude-opus-4-6"
"Füge gpt-5.4 zum Fallback von Librarian hinzu"
```

Der Skill validiert Änderungen gegen die Allowlist und stellt sicher, dass die Provider-Diversitätsregeln eingehalten werden, bevor er sie anwendet.

## Einstellungen

| Schlüssel | Wert | Beschreibung |
|---|---|---|
| `runtime_fallback` | `true` | Wechselt automatisch zum nächsten Modell, wenn das primäre nicht verfügbar ist |
| `disabled_hooks` | `["no-sisyphus-gpt"]` | Erlaubt die Verwendung von GPT-Modellen im Sisyphus-Agenten |

## Verwandte Links

- [Oh My OpenAgent](https://github.com/code-yeongyu/oh-my-openagent) — Plugin-System, das die Konfiguration antreibt
- [oh-my-openagent docs](https://github.com/code-yeongyu/oh-my-openagent) — Upstream-Dokumentation und Modell-Matching-Leitfäden
