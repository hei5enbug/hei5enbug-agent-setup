# hei5enbug-agent-setup

[English](./README.md) | [한국어](./README.ko.md) | [日本語](./README.ja.md) | [简体中文](./README.zh-CN.md) | [Español](./README.es.md) | [Deutsch](./README.de.md) | **Français**

Configuration de modèles et de variants pour un AI agent harness, attribués selon le rôle de chaque agent.

## Présentation

Chaque agent dans un harness requiert des capacités différentes. Cette configuration optimise `model`, `variant` et les chaînes de fallback par rôle d'agent et catégorie de tâche.

## Outils compatibles

- [OpenCode](https://github.com/code-yeongyu/oh-my-openagent) (via le plugin [Oh My OpenAgent](https://github.com/code-yeongyu/oh-my-openagent))

## Structure

```
hei5enbug-agent-setup/
├── oh-my-openagent.json       # Fichier de configuration lu et modifié par le skill
├── available-models.json     # Allowlist utilisée par le skill pour valider les changements de modèle
└── .opencode/
    └── skills/
        └── omo-model-config/ # Skill personnalisé pour l'édition sécurisée de la configuration
            └── SKILL.md
```

## Skills personnalisés

### omo-model-config

Un workflow pour éditer en toute sécurité les attributions de modèles des agents. Il applique les règles suivantes :

- **Résolution GitHub-first** — la documentation upstream de [oh-my-openagent](https://github.com/code-yeongyu/oh-my-openagent) est l'autorité principale pour le matching modèle-rôle
- **Gate de disponibilité** — chaque modèle doit figurer dans l'allowlist de `available-models.json`
- **Gate de diversité des fournisseurs** — les fournisseurs requis doivent être couverts dans la chaîne de fallback de chaque agent
- **Portée d'édition limitée** — seuls les champs `model`, `variant` et `fallback_models` sont modifiés ; tout le reste est préservé

Consultez [`.opencode/skills/omo-model-config/SKILL.md`](.opencode/skills/omo-model-config/SKILL.md) pour plus de détails.

## Utilisation

Ouvrir comme racine de projet dans un outil d'agent compatible. La configuration est chargée automatiquement au démarrage de la session.

```bash
cd hei5enbug-agent-setup
opencode
```

### Modifier les attributions de modèles

Invoquer le skill `omo-model-config` depuis la session de l'agent :

```
/omo-model-config
```

Ou demander directement à l'agent :

```
"Change le primary model d'Oracle en claude-opus-4-6"
"Ajoute gpt-5.4 au fallback de Librarian"
```

Le skill valide les changements contre l'allowlist et vérifie les règles de diversité des fournisseurs avant de les appliquer.

## Paramètres

| Clé | Valeur | Description |
|---|---|---|
| `runtime_fallback` | `true` | Bascule automatiquement vers le modèle suivant si le principal est indisponible |
| `disabled_hooks` | `["no-sisyphus-gpt"]` | Autorise l'utilisation des modèles GPT dans l'agent Sisyphus |

## Liens associés

- [Oh My OpenAgent](https://github.com/code-yeongyu/oh-my-openagent) — système de plugins qui alimente la configuration
- [oh-my-openagent docs](https://github.com/code-yeongyu/oh-my-openagent) — documentation upstream et guides de matching de modèles
