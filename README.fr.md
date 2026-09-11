# hei5enbug-agent-setup

[English](./README.md) | [한국어](./SKILL.ko.md) | [日本語](./README.ja.md) | [简体中文](./README.zh-CN.md) | [Español](./README.es.md) | [Deutsch](./README.de.md) | **Français**

Une collection portable de skills personnalisés pour agents de codage IA, conçue pour être partagée entre plusieurs agent hosts sans réécriture spécifique à chacun.

## Présentation

Chaque skill inclus dans le plugin vit dans son propre dossier sous `skills/` et est autonome.
Les skills hors du plugin vivent sous `standalone-skills/`.
Le même `SKILL.md` fonctionne sans modification sur chaque host compatible.

## Hosts compatibles

- Claude Code
- Codex
- OpenCode (via le plugin [Oh My OpenAgent](https://github.com/code-yeongyu/oh-my-openagent))

## Structure

```
hei5enbug-agent-setup/
├── .agents/plugins/marketplace.json
├── .claude-plugin/
│   ├── marketplace.json
│   └── plugin.json
├── .codex-plugin/plugin.json
├── .github/workflows/validate.yml
├── AGENTS.md
├── AGENTS.ko.md
├── CLAUDE.md
├── CLAUDE.ko.md
├── hooks/hooks.json
├── instructions/
│   ├── claude-agents.md
│   ├── codex-agents.md
│   ├── confluence.md
│   ├── documentation.md
│   ├── protected-values.md
│   ├── services.md
│   └── session/
│       ├── claude-code.md
│       ├── codex.md
│       └── common.md
├── scripts/session_context.py
├── tests/
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
    ├── document-to-confluence/
    ├── skill-builder/
    ├── suggest-commit/
    ├── technical-design-writer/
    └── tiki-taka/
```

Chaque dossier de skill du plugin contient son propre `SKILL.md` ainsi que les références ou scripts dont il a besoin.
Les manifestes du plugin empaquettent le même répertoire `skills/` pour Codex et Claude Code sans copier les skills dans des répertoires propres à chaque host.
Le répertoire `standalone-skills/` ne fait partie du chemin de découverte des skills d'aucun des deux plugins.

Le répertoire `standalone-agents/` contient les définitions de sous-agents utilisées par les instructions propres à chaque host.
Copiez `scout.md` à la main dans `~/.claude/agents/`. Copiez `codex-explorer.toml` vers `~/.codex/agents/explorer.toml` ;
il remplace l'`explorer` intégré de Codex afin de fixer son effort de raisonnement et son bac à sable en lecture seule. Il ne précise aucun modèle,
il hérite donc du modèle par défaut du host, contrairement à `scout`, qui en fixe un sur Claude Code.
Ils restent hors du paquet du plugin, si bien qu'installer le plugin n'ajoute jamais de sous-agent.

## Installation du plugin

Installez le paquet une seule fois depuis le dépôt GitHub.

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

## Instructions automatiques

Sous macOS et Linux, les hooks combinent `instructions/session/common.md` avec `codex.md` ou `claude-code.md` selon le host.
Ils s'exécutent au démarrage ou à la reprise d'une session, après son effacement ou sa compression,
et au démarrage d'un sous-agent.
Les détails dans `instructions/` sont lus uniquement avant l'action correspondante.
Python 3.12 ou plus récent doit être disponible via `python3` ; les hooks doivent être activés et approuvés dans Codex.
Après une mise à jour du plugin, ouvrez une nouvelle session.
Les références, erreurs et limites sont décrites dans la
[section en anglais](README.md#automatic-instructions).

## Mise à jour du plugin

Les deux manifestes du plugin, `pyproject.toml` et `uv.lock` doivent utiliser la même version sémantique.
Mettez-les à jour ensemble après la réussite des contrôles de développement et avant de publier une version.

Mettez à jour Codex une fois la version disponible :

```bash
codex plugin marketplace upgrade hei5enbug
codex plugin add hei5enbug-agent-setup@hei5enbug
```

Mettez à jour Claude Code une fois la version disponible :

```bash
claude plugin marketplace update hei5enbug
claude plugin update hei5enbug-agent-setup@hei5enbug
```

Après la mise à jour, ouvrez un nouveau fil Codex ou redémarrez Claude Code pour que le host charge les nouveaux skills et les instructions.

## Contrôles de développement

Les scripts fournis nécessitent Python 3.12 ou plus récent avec PyYAML, et les tests Node nécessitent Node.js.
Exécutez avec les mêmes commandes les trois contrôles que `.github/workflows/validate.yml` exécute sous macOS et Linux :

```bash
python3 -m pip install -e ".[dev]"
for skill in skills/*/ standalone-skills/*/; do python3 skills/skill-builder/scripts/quick_validate.py "$skill"; done
python3 -m pytest
node --test skills/document-to-confluence/tests/test_render_diagrams.mjs
```

## Langue des instructions

Les fichiers anglais sont les sources exécutables canoniques des skills, références, agents et instructions de session.
Chaque fichier Markdown anglais destiné aux humains possède à côté une traduction coréenne `.ko.md` de même sens.
Ces traductions ne font pas autorité et ne sont pas chargées pendant l'exécution. La source et sa traduction sont modifiées,
déplacées ou supprimées ensemble. Le code, les schémas, les données de test, les artefacts générés et les documents non
anglais n'exigent pas de copie coréenne. Le coréen peut rester dans une source comme donnée de langue cible.

## Skills

| Skill | Ce qu'il fait |
|---|---|
| [`decision-navigator`](skills/decision-navigator/SKILL.md) | Découpe un chantier qui s'étend sur plusieurs sessions en tickets de décision et les résout un par un jusqu'à ce que la route d'implémentation soit claire. |
| [`deep-interview`](skills/deep-interview/SKILL.md) | Mène un entretien socratique qui note l'ambiguïté des exigences après chaque réponse et ne passe à l'exécution que lorsque ce score descend sous le seuil fixé. [Guide en coréen](skills/deep-interview/SKILL.ko.md) |
| [`flowchart-design`](skills/flowchart-design/SKILL.md) | Un standard de design partagé pour que les diagrammes de flux réalisés en SVG, HTML/CSS, Figma ou draw.io paraissent issus d'un même système de design. |
| [`humanize-korean`](skills/humanize-korean/SKILL.md) | Réécrit un texte coréen qui sonne « IA » pour qu'il paraisse naturel et humain, sans en changer le sens. [Guide en coréen](skills/humanize-korean/SKILL.ko.md) |
| [`document-to-confluence`](skills/document-to-confluence/SKILL.md) | Convertit les contenus Markdown, HTML, PDF, DOCX et Google Docs en pages Confluence, conserve la structure et les pièces jointes et synchronise les révisions ultérieures. |
| [`skill-builder`](skills/skill-builder/SKILL.md) | Crée, teste et empaquette des skills d'agent via une boucle brouillon → test → revue → amélioration. |
| [`suggest-commit`](skills/suggest-commit/SKILL.md) | Lit ensemble les changements indexés et non indexés, ou le périmètre que vous indiquez, avec l'historique récent des commits, puis propose cinq messages de commit conformes au style du dépôt. |
| [`technical-design-writer`](skills/technical-design-writer/SKILL.md) | Règles et processus en cinq étapes qui restreint progressivement le plan, pour rédiger ou nettoyer des documents de conception technique. [Guide en coréen](skills/technical-design-writer/SKILL.ko.md) |
| [`tiki-taka`](skills/tiki-taka/SKILL.md) | Mène un débat à nombre d'échanges limité entre l'agent actuel et une session Claude/Codex adverse afin de faire émerger puis de résoudre les points de désaccord. [Guide en coréen](skills/tiki-taka/SKILL.ko.md) |

## Liens associés

- [`omo-model-config`](standalone-skills/omo-model-config/SKILL.md) reste disponible comme source autonome
  et ne fait pas partie de la liste des skills du plugin.
- [Oh My OpenAgent](https://github.com/code-yeongyu/oh-my-openagent) — système de plugins dont le routage de
  modèles est mis à jour par le skill autonome

## Licence

Ce dépôt est publié sous la licence Apache License 2.0. Le texte complet se trouve dans [`LICENSE`](./LICENSE).
