# hei5enbug-agent-setup

[English](./README.md) | [한국어](./README.ko.md) | [日本語](./README.ja.md) | [简体中文](./README.zh-CN.md) | **Español** | [Deutsch](./README.de.md) | [Français](./README.fr.md)

Una colección portátil de skills personalizados para agentes de codificación con IA, pensada para compartirse entre varios agent hosts sin reescrituras específicas de cada uno.

## Descripción general

Cada skill vive en su propia carpeta dentro de `skills/` y es autocontenido: sus instrucciones, referencias y scripts viajan juntos. El mismo `SKILL.md` funciona sin modificaciones en cada host compatible.

## Hosts compatibles

- Claude Code
- Codex
- OpenCode (mediante el plugin [Oh My OpenAgent](https://github.com/code-yeongyu/oh-my-openagent))

## Estructura

```
hei5enbug-agent-setup/
└── skills/
    ├── deep-interview/
    ├── flowchart-design/
    ├── humanize-korean/
    ├── markdown-to-confluence/
    ├── omo-model-config/
    ├── portable-opencode-setup/
    ├── skill-builder/
    ├── suggest-commit/
    ├── technical-design-writer/
    └── tiki-taka/
```

Cada carpeta contiene su propio `SKILL.md` junto con las referencias o scripts que necesita. No hay configuración compartida en el nivel superior: cada skill es autocontenido.

## Skills

| Skill | Qué hace |
|---|---|
| [`deep-interview`](skills/deep-interview/SKILL.md) | Realiza una entrevista socrática que puntúa la ambigüedad del requisito tras cada respuesta y no avanza a la ejecución hasta que baja del umbral. |
| [`flowchart-design`](skills/flowchart-design/SKILL.md) | Un estándar de diseño compartido para que los diagramas de flujo hechos en SVG, HTML/CSS, Figma o draw.io se vean como parte de un mismo sistema de diseño. |
| [`humanize-korean`](skills/humanize-korean/SKILL.md) | Reescribe texto en coreano con apariencia de IA para que suene natural y humano, sin cambiar su significado. |
| [`markdown-to-confluence`](skills/markdown-to-confluence/SKILL.md) | Publica un documento Markdown como página de Confluence y mantiene la página correcta en ediciones posteriores: macro de índice, imágenes en línea, adjuntos y diagramas renderizados como imágenes. |
| [`omo-model-config`](skills/omo-model-config/SKILL.md) | Edita de forma segura el model routing de OpenCode/oh-my-openagent (`model`, `variant`, `fallback_models`) contra una allowlist upstream. |
| [`portable-opencode-setup`](skills/portable-opencode-setup/SKILL.md) | Añade las piezas que falten de la configuración de OpenCode/oh-my-openagent en una máquina nueva, de forma solo aditiva, sin tocar los ajustes existentes. |
| [`skill-builder`](skills/skill-builder/SKILL.md) | Crea, prueba y empaqueta skills de agente mediante un ciclo de borrador → prueba → revisión → mejora. |
| [`suggest-commit`](skills/suggest-commit/SKILL.md) | Lee el diff actual y el historial reciente de commits, y sugiere cinco mensajes de commit acordes al estilo del repositorio. |
| [`technical-design-writer`](skills/technical-design-writer/SKILL.md) | Reglas y un proceso de cinco pasos que va acotando el índice para escribir o depurar documentos de diseño técnico. |
| [`tiki-taka`](skills/tiki-taka/SKILL.md) | Ejecuta un debate con número de turnos limitado entre el agente actual y una sesión opuesta de Claude/Codex para sacar a la luz y resolver problemas. |

## Enlaces relacionados

- [Oh My OpenAgent](https://github.com/code-yeongyu/oh-my-openagent) — sistema de plugins que `omo-model-config` y `portable-opencode-setup` configuran
