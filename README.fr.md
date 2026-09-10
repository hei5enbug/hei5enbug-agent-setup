# hei5enbug-agent-setup

[English](./README.md) | [한국어](./README.ko.md) | [日本語](./README.ja.md) | [简体中文](./README.zh-CN.md) | [Español](./README.es.md) | [Deutsch](./README.de.md) | **Français**

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

Chaque dossier de skill du plugin contient son propre `SKILL.md` ainsi que les références ou scripts dont il a besoin.
Les manifestes du plugin empaquettent le même répertoire `skills/` pour Codex et Claude Code sans copier les skills dans des répertoires propres à chaque host.
Le répertoire `standalone-skills/` ne fait partie du chemin de découverte des skills d'aucun des deux plugins.

Le répertoire `standalone-agents/` contient les définitions de sous-agents que `CLAUDE.md` et `AGENTS.md` désignent par leur nom.
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

## Mise à jour du plugin

Les deux manifestes du plugin et `pyproject.toml` portent la même version sémantique, actuellement `0.2.0`. Avant de publier
une version, vérifiez que les contrôles de développement ci-dessous passent, puis augmentez la version en même temps dans
`.codex-plugin/plugin.json`, `.claude-plugin/plugin.json` et `pyproject.toml`.

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

Après la mise à jour, ouvrez un nouveau fil Codex ou redémarrez Claude Code pour que le host charge les nouvelles versions des skills.

## Contrôles de développement

Les scripts fournis nécessitent Python 3.12 ou plus récent avec PyYAML, et les tests Node nécessitent Node.js.
Exécutez avec les mêmes commandes les trois contrôles que `.github/workflows/validate.yml` exécute sous macOS et Linux :

```bash
python3 -m pip install -e ".[dev]"
for skill in skills/*/ standalone-skills/*/; do python3 skills/skill-builder/scripts/quick_validate.py "$skill"; done
python3 -m pytest
node --test skills/markdown-to-confluence/tests/test_render_diagrams.mjs
```

## Langue des instructions

Les instructions exécutables des skills sont rédigées en anglais. Un `README.ko.md` dans un répertoire de skill est une traduction
coréenne non officielle maintenue synchronisée avec son document anglais. Elle s'adresse aux lecteurs humains et un agent ne doit
ni la charger ni l'utiliser pendant l'exécution du skill. Le texte coréen ne reste dans les fichiers exécutables que lorsqu'il constitue
une donnée de la langue cible, comme des phrases de déclenchement, des exemples, des libellés de sortie obligatoires ou des données d'évaluation.

## Skills

| Skill | Ce qu'il fait |
|---|---|
| [`decision-navigator`](skills/decision-navigator/SKILL.md) | Découpe un chantier qui s'étend sur plusieurs sessions en tickets de décision et les résout un par un jusqu'à ce que la route d'implémentation soit claire. |
| [`deep-interview`](skills/deep-interview/SKILL.md) | Mène un entretien socratique qui note l'ambiguïté des exigences après chaque réponse et ne passe à l'exécution que lorsque ce score descend sous le seuil fixé. [Guide en coréen](skills/deep-interview/README.ko.md) |
| [`flowchart-design`](skills/flowchart-design/SKILL.md) | Un standard de design partagé pour que les diagrammes de flux réalisés en SVG, HTML/CSS, Figma ou draw.io paraissent issus d'un même système de design. |
| [`humanize-korean`](skills/humanize-korean/SKILL.md) | Réécrit un texte coréen qui sonne « IA » pour qu'il paraisse naturel et humain, sans en changer le sens. [Guide en coréen](skills/humanize-korean/README.ko.md) |
| [`markdown-to-confluence`](skills/markdown-to-confluence/SKILL.md) | Publie un document Markdown en page Confluence et garde la page correcte lors des modifications ultérieures : macro de sommaire, images en ligne, pièces jointes et diagrammes rendus en images. |
| [`skill-builder`](skills/skill-builder/SKILL.md) | Crée, teste et empaquette des skills d'agent via une boucle brouillon → test → revue → amélioration. |
| [`suggest-commit`](skills/suggest-commit/SKILL.md) | Lit ensemble les changements indexés et non indexés, ou le périmètre que vous indiquez, avec l'historique récent des commits, puis propose cinq messages de commit conformes au style du dépôt. |
| [`technical-design-writer`](skills/technical-design-writer/SKILL.md) | Règles et processus en cinq étapes qui restreint progressivement le plan, pour rédiger ou nettoyer des documents de conception technique. [Guide en coréen](skills/technical-design-writer/README.ko.md) |
| [`tiki-taka`](skills/tiki-taka/SKILL.md) | Mène un débat à nombre d'échanges limité entre l'agent actuel et une session Claude/Codex adverse afin de faire émerger puis de résoudre les points de désaccord. [Guide en coréen](skills/tiki-taka/README.ko.md) |

## Liens associés

- [`omo-model-config`](standalone-skills/omo-model-config/SKILL.md) reste disponible comme source autonome
  et ne fait pas partie de la liste des skills du plugin.
- [Oh My OpenAgent](https://github.com/code-yeongyu/oh-my-openagent) — système de plugins dont le routage de
  modèles est mis à jour par le skill autonome

## Licence

Ce dépôt est publié sous la licence Apache License 2.0. Le texte complet se trouve dans [`LICENSE`](./LICENSE).
