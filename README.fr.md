# hei5enbug-agent-setup

[English](./README.md) | [한국어](./README.ko.md) | [日本語](./README.ja.md) | [简体中文](./README.zh-CN.md) | [Español](./README.es.md) | [Deutsch](./README.de.md) | **Français**

Une collection portable de skills personnalisés pour agents de codage IA, conçue pour être partagée entre plusieurs agent hosts sans réécriture spécifique à chacun.

## Présentation

Chaque skill inclus dans le plugin vit dans son propre dossier sous `skills/`.
Les skills hors du plugin vivent sous `standalone-skills/`.
Le même `SKILL.md` fonctionne sans modification sur chaque host compatible.

## Hosts compatibles

- Claude Code
- Codex
- OpenCode (via le plugin [Oh My OpenAgent](https://github.com/code-yeongyu/oh-my-openagent))

## Structure

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

Chaque dossier contient son propre `SKILL.md` ainsi que les références ou scripts dont il a besoin.
Le plugin ne découvre que `skills/`, pas `standalone-skills/`.

## Skills

| Skill | Ce qu'il fait |
|---|---|
| [`deep-interview`](skills/deep-interview/SKILL.md) | Mène un entretien socratique qui note l'ambiguïté des exigences après chaque réponse et ne passe à l'exécution que lorsque ce score descend sous le seuil fixé. |
| [`flowchart-design`](skills/flowchart-design/SKILL.md) | Un standard de design partagé pour que les diagrammes de flux réalisés en SVG, HTML/CSS, Figma ou draw.io paraissent issus d'un même système de design. |
| [`humanize-korean`](skills/humanize-korean/SKILL.md) | Réécrit un texte coréen qui sonne « IA » pour qu'il paraisse naturel et humain, sans en changer le sens. |
| [`markdown-to-confluence`](skills/markdown-to-confluence/SKILL.md) | Publie un document Markdown en page Confluence et garde la page correcte lors des modifications ultérieures : macro de sommaire, images en ligne, pièces jointes et diagrammes rendus en images. |
| [`skill-builder`](skills/skill-builder/SKILL.md) | Crée, teste et empaquette des skills d'agent via une boucle brouillon → test → revue → amélioration. |
| [`suggest-commit`](skills/suggest-commit/SKILL.md) | Lit le diff actuel et l'historique récent des commits, puis propose cinq messages de commit conformes au style du dépôt. |
| [`technical-design-writer`](skills/technical-design-writer/SKILL.md) | Règles et processus en cinq étapes qui restreint progressivement le plan, pour rédiger ou nettoyer des documents de conception technique. |
| [`tiki-taka`](skills/tiki-taka/SKILL.md) | Mène un débat à nombre d'échanges limité entre l'agent actuel et une session Claude/Codex adverse afin de faire émerger puis de résoudre les points de désaccord. |

## Liens associés

- [`omo-model-config`](standalone-skills/omo-model-config/SKILL.md) et
  [`portable-opencode-setup`](standalone-skills/portable-opencode-setup/SKILL.md) restent disponibles comme
  sources autonomes et ne font pas partie de la liste des skills du plugin.
- [Oh My OpenAgent](https://github.com/code-yeongyu/oh-my-openagent) — système configuré par les skills
  OpenCode autonomes
