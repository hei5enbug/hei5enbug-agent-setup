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
│   ├── datagrip_guard.py
│   ├── language_guard.py
│   ├── session_approval_guard.py
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

### Langue de réponse

Un garde de langue, `scripts/language_guard.py`, vérifie que chaque réponse et chaque message d'avancement sont
rédigés dans la langue de réponse. Claude Code tire la langue du paramètre `language`, lu dans les paramètres locaux
du projet, puis ceux du projet, puis ceux de l'utilisateur ; sans ce paramètre, rien n'est imposé. Codex lit
`HEI5ENBUG_RESPONSE_LANGUAGE` et utilise le coréen si elle n'est pas définie. Seules les langues dotées d'une écriture
distinctive sont vérifiées : coréen, japonais, chinois, russe, ukrainien, grec, arabe, hébreu, thaï et hindi. Pour
toute autre langue, comme l'anglais ou le français, seule l'instruction s'applique.

La vérification ignore le code, les citations et les URL. Un texte réussit lorsqu'au moins 30 % de ses lettres
relèvent de l'écriture cible, et un texte très court réussit toujours. Un hook `Stop` demande une réécriture
lorsqu'une réponse échoue, au plus 3 fois par tour. Un hook `PostToolUse` ajoute un rappel après un message
d'avancement dans une autre langue. Placez le texte que l'utilisateur demande dans une autre langue dans un bloc de
code ou une citation en bloc.

### Garde de requêtes DataGrip

Un hook `PreToolUse` et un hook `PermissionRequest`, tous deux `scripts/datagrip_guard.py`, s'exécutent avant l'outil
MCP DataGrip `execute_sql_query`. Le garde lit la connexion dans `.idea/dataSources.xml` du projet DataGrip que
désigne `projectPath`. Une connexion dont le nom contient `승인` demande toujours une approbation. Les lectures
PostgreSQL et SQL Server s'exécutent sans approbation, celles de PostgreSQL dans une transaction en lecture seule. Les
écritures, les requêtes que le garde ne peut pas classer, les connexions inconnues et les autres types de base de
données demandent toujours une approbation. Le garde ne refuse jamais un appel. Dans Codex, approuvez le hook dans
`/hooks`.

Facultativement, installez une fois l'analyseur `pglast` :

```bash
uv venv --python 3.12 "${XDG_STATE_HOME:-$HOME/.local/state}/hei5enbug-agent-setup/sql-parser"
uv pip install --python "${XDG_STATE_HOME:-$HOME/.local/state}/hei5enbug-agent-setup/sql-parser/bin/python" pglast==8.4
```

Sans lui, PostgreSQL se rabat sur une vérification textuelle plus stricte, qui peut demander plus souvent une
approbation mais ne laisse jamais passer une écriture sans approbation.

### Approbations de session

Sur Claude Code uniquement, un garde d'approbations de session, `scripts/session_approval_guard.py`, permet
d'approuver une seule fois par session certaines écritures visibles de l'extérieur. Il couvre la création de tags git,
le push de tags vers un remote configuré, `gh release create` et `gh release edit` avec seulement le tag et les
options `--title`, `--notes`, `--target`, `--generate-notes`, `--notes-from-tag`, `--latest`, `--draft`,
`--prerelease`, `--verify-tag`, et les outils MCP dont le nom contient un verbe d'écriture. Les outils MCP dont le nom
commence par un verbe de lecture, comme get, list, search, read, fetch, query ou download, ne sont jamais couverts et
gardent le flux de permissions normal. Après une approbation, le même type d'action s'exécute sans demande pour le
reste de la session. Chaque type d'outil ou de commande est approuvé séparément.

Les actions destructrices demandent toujours une approbation : les push forcés, la suppression de branches distantes
ou de tags, la suppression d'un tag, `gh release delete`, `gh repo delete` et les outils MCP qui suppriment, mettent à
la corbeille ou retirent, même si le nom commence par un verbe de lecture. `gh release upload` demande aussi toujours
une approbation, car il peut publier n'importe quel fichier local. Il en va de même pour un push de tag vers une URL,
un remote non listé ou avec `--repo`, pour un push `--tags` auquel se mêle une branche, et pour un `gh release create`
ou `gh release edit` avec des fichiers joints, `--notes-file` ou toute autre option. Une commande composée qui
contient quelque chose que le garde ne peut pas vérifier demande aussi toujours une approbation. Un simple `echo` avec
du texte littéral après une commande couverte, par exemple `git tag v1 && echo done`, n'empêche pas l'approbation de
s'appliquer ; un `echo` avec une variable, une substitution de commande, un glob, une redirection ou un tube demande
toujours une approbation. Les sous-agents n'héritent d'aucune approbation. Les approbations expirent avec la session
et sont stockées dans le répertoire de données du plugin. Les push ordinaires et toutes les autres commandes gardent
le flux de permissions normal.

N'ajoutez pas de règles `permissions.ask` pour ces actions, car une règle ask demande à chaque fois, même après une
approbation de session.

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
Après chaque appel d'outil et à la fin de chaque réponse, le garde de langue s'exécute aussi via `PostToolUse` et
`Stop`.
Le garde de requêtes DataGrip s'exécute avant `execute_sql_query` via `PreToolUse` et `PermissionRequest`.
Sur Claude Code, le garde d'approbations de session s'exécute pour Bash et les outils MCP via `PreToolUse` et
`PostToolUse`.
Python 3.12 ou plus récent doit être disponible via `python3` ; les hooks doivent être activés et approuvés dans Codex.
Un hook ajouté par une mise à jour, comme le garde d'agents, le garde de langue ou le garde de requêtes DataGrip,
reste ignoré dans Codex tant que vous ne l'avez pas approuvé dans `/hooks`.
Le garde d'approbations de session ne s'exécute que sur Claude Code ; cette étape de confiance ne le concerne donc pas.
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
