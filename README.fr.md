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
├── scripts/
│   ├── agent_guard.py
│   └── session_context.py
├── tests/
├── LICENSE
├── pyproject.toml
├── agents/
│   ├── ko/
│   │   ├── scout.ko.md
│   │   └── worker.ko.md
│   ├── scout.md
│   └── worker.md
├── standalone-agents/
│   ├── codex-scout.toml
│   └── codex-worker.toml
├── standalone-skills/
│   └── omo-model-config/
└── skills/
    ├── decision-navigator/
    ├── deep-interview/
    ├── flowchart-design/
    ├── docs-rewrite/
    ├── document-to-confluence/
    ├── orca-plugin-refresh/
    ├── skill-builder/
    ├── suggest-commit/
    ├── technical-design-writer/
    └── tiki-taka/
```

Chaque dossier de skill du plugin contient son propre `SKILL.md` ainsi que les références ou scripts dont il a besoin.
Les manifestes du plugin empaquettent le même répertoire `skills/` pour Codex et Claude Code sans copier les skills dans des répertoires propres à chaque host.
Le répertoire `standalone-skills/` ne fait partie du chemin de découverte des skills d'aucun des deux plugins.

Le répertoire `agents/` est livré avec le plugin Claude Code : installer le paquet ajoute donc les sous-agents
`hei5enbug-agent-setup:scout` et `hei5enbug-agent-setup:worker`. Aucune copie manuelle n'est nécessaire. Le manifeste
ne liste que ces deux définitions en anglais ; les traductions coréennes de `agents/ko/` ne sont donc pas
enregistrées comme sous-agents.

Codex ne cherche les sous-agents que dans `~/.codex/agents/` et `.codex/agents/` ; un plugin ne peut donc pas en
enregistrer. À la place, le hook de session copie `standalone-agents/codex-scout.toml` et
`standalone-agents/codex-worker.toml` vers `~/.codex/agents/scout.toml` et `~/.codex/agents/worker.toml` lorsque
chaque fichier est absent. Ils définissent les agents `scout` et `worker`, aux mêmes noms que sur Claude Code, avec
un effort de raisonnement et un bac à sable fixes. Le `worker` du plugin remplace le `worker` intégré de Codex, et
`scout` ne touche pas à l'`explorer` intégré. Un fichier que vous avez modifié n'est jamais écrasé, et les agents
sont disponibles à la session Codex suivante. Comme une copie modifiée ne change jamais, les fichiers ne précisent
aucun modèle ; les instructions Codex transmettent le modèle épinglé à chaque lancement. Le hook supprime aussi un
`explorer.toml` et remplace un `worker.toml` écrits par une version antérieure, mais seulement tant que le fichier
est identique octet par octet à celui livré par cette version ; une copie que vous avez modifiée est conservée.
Lorsque le plugin est désactivé, le rôle `worker` installé agit comme un worker d'implémentation ordinaire au lieu
de refuser de modifier.

Un hook `PreToolUse`, `scripts/agent_guard.py`, écarte les sous-agents intégrés sur les deux hosts. Sur Claude Code,
il refuse un type de sous-agent omis et tout type intégré : `general-purpose`, `Explore`, `Plan`, `claude` et les
forks. Les types intégrés à usage restreint `claude-code-guide` et `statusline-setup` passent, tout comme les agents
de plugin et les définitions issues de toute source utilisateur, projet, CLI ou gérée. Sur Codex, il refuse un type
omis, `default`, `explorer` et tout type sans fichier de rôle, y compris le `worker` intégré tant que le rôle du
plugin manque. Les skills qui demandent un worker indépendant en lecture seule utilisent `scout`, et ceux qui écrivent
des sorties d'essai lancent un processus `claude -p` ou `codex exec` distinct.

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
Un hook ajouté par une mise à jour reste ignoré dans Codex tant que vous ne l'avez pas approuvé dans `/hooks`.
Après une mise à jour du plugin, ouvrez une nouvelle session.
Les références, erreurs et limites sont décrites dans la
[section en anglais](README.md#automatic-instructions).

## Mise à jour du plugin

Les deux manifestes du plugin, `pyproject.toml` et `uv.lock` doivent utiliser la même version sémantique.
Le tag `v<version>` le plus récent accessible depuis `HEAD` est la base de release. Le premier changement qui la suit
fixe la prochaine version dans ces fichiers au sein du même commit. Une version présente uniquement dans ces fichiers
est la prochaine version planifiée, même si elle est déjà sur `main` ; regroupez-y donc tous les changements non
publiés suivants au lieu d'incrémenter à nouveau. Une release n'ajoute aucun commit : une fois les contrôles de
développement ci-dessous réussis sur `HEAD`, taguez `HEAD` `v<version>` et poussez le tag.

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

Les tests qui nécessitent la CLI Orca sont ignorés lorsqu'elle n'est pas installée, si bien que la CI réussit sans
Orca. Après avoir installé Orca, relancez `python3 -m pytest` pour les couvrir.

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
| [`docs-rewrite`](skills/docs-rewrite/SKILL.md) | Réécrit un texte existant pour qu'il se lise naturellement en gardant identiques chaque affirmation, chiffre et degré de certitude, et corrige le coréen qui sonne « IA ». [Guide en coréen](skills/docs-rewrite/SKILL.ko.md) |
| [`document-to-confluence`](skills/document-to-confluence/SKILL.md) | Convertit les contenus Markdown, HTML, PDF, DOCX et Google Docs en pages Confluence, conserve la structure et les pièces jointes et synchronise les révisions ultérieures. |
| [`skill-builder`](skills/skill-builder/SKILL.md) | Crée, teste et empaquette des skills d'agent via une boucle brouillon → test → revue → amélioration. |
| [`suggest-commit`](skills/suggest-commit/SKILL.md) | Lit ensemble les changements indexés et non indexés, ou le périmètre que vous indiquez, avec l'historique récent des commits, puis propose cinq messages de commit conformes au style du dépôt. Si vous lui demandez de committer, il crée directement le commit avec le sujet le plus adapté. |
| [`technical-design-writer`](skills/technical-design-writer/SKILL.md) | Règles et processus en cinq étapes qui restreint progressivement le plan, pour rédiger ou nettoyer des documents de conception technique. [Guide en coréen](skills/technical-design-writer/SKILL.ko.md) |
| [`tiki-taka`](skills/tiki-taka/SKILL.md) | Mène un débat à nombre d'échanges limité entre l'agent actuel et une session Claude/Codex adverse afin de faire émerger puis de résoudre les points de désaccord. [Guide en coréen](skills/tiki-taka/SKILL.ko.md) |

## Liens associés

- [`omo-model-config`](standalone-skills/omo-model-config/SKILL.md) reste disponible comme source autonome
  et ne fait pas partie de la liste des skills du plugin.
- [Oh My OpenAgent](https://github.com/code-yeongyu/oh-my-openagent) — système de plugins dont le routage de
  modèles est mis à jour par le skill autonome

## Licence

Ce dépôt est publié sous la licence Apache License 2.0. Le texte complet se trouve dans [`LICENSE`](./LICENSE).
