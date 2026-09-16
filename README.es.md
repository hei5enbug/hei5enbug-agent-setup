# hei5enbug-agent-setup

[English](./README.md) | [한국어](./README.ko.md) | [日本語](./README.ja.md) | [简体中文](./README.zh-CN.md) | **Español** | [Deutsch](./README.de.md) | [Français](./README.fr.md)

Una colección portátil de skills personalizados para agentes de codificación con IA, pensada para compartirse entre varios agent hosts sin reescrituras específicas de cada uno.

## Descripción general

Cada skill incluido en el plugin vive en su propia carpeta dentro de `skills/` y es autocontenido.
Los skills que no forman parte del plugin viven en `standalone-skills/`.
El mismo `SKILL.md` funciona sin modificaciones en cada host compatible.

## Hosts compatibles

- Claude Code
- Codex
- OpenCode (mediante el plugin [Oh My OpenAgent](https://github.com/code-yeongyu/oh-my-openagent))

## Estructura

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
├── agents/
│   ├── ko/scout.ko.md
│   └── scout.md
├── standalone-agents/
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

Cada carpeta de skill del plugin contiene su propio `SKILL.md` junto con las referencias o scripts que necesita.
Los manifiestos del plugin empaquetan el mismo directorio `skills/` para Codex y Claude Code sin copiar skills a directorios específicos de cada host.
El directorio `standalone-skills/` no forma parte de la ruta de descubrimiento de skills de ningún plugin.

El directorio `agents/` se distribuye con el plugin de Claude Code, así que instalar el paquete añade el
subagente `hei5enbug-agent-setup:scout`. No hace falta copiar nada a mano.

Codex solo busca subagentes en `~/.codex/agents/` y `.codex/agents/`, por lo que un plugin no puede registrar uno.
En su lugar, el hook de sesión escribe `standalone-agents/codex-explorer.toml` en `~/.codex/agents/explorer.toml`
cuando ese archivo no existe; sustituye al `explorer` integrado de Codex para fijar su esfuerzo de razonamiento y su
sandbox de solo lectura. Un `explorer.toml` existente nunca se sobrescribe, y el agente queda disponible en la
siguiente sesión de Codex. No indica ningún modelo, así que hereda el predeterminado del host, a diferencia de
`scout`, que fija uno en Claude Code.

## Instalación del plugin

Instala el paquete una vez desde el repositorio de GitHub.

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

## Instrucciones automáticas

En macOS y Linux, los hooks combinan `instructions/session/common.md` con `codex.md` o `claude-code.md` para el host actual.
Se ejecutan al iniciar o reanudar una sesión, al limpiar o compactar el contexto y al iniciar un subagente.
Los detalles de `instructions/` se leen solo antes de la acción correspondiente.
Se requiere Python 3.12 o superior como `python3`, hooks habilitados y aprobación de confianza en Codex.
Tras actualizar el plugin, inicia una sesión nueva.
Consulta las referencias, los errores y los límites en la
[sección en inglés](README.md#automatic-instructions).

## Actualización del plugin

Los dos manifiestos del plugin, `pyproject.toml` y `uv.lock` deben usar la misma versión semántica.
Actualízalos juntos después de que pasen las verificaciones de desarrollo y antes de publicar una versión.

Actualiza Codex cuando la versión esté disponible:

```bash
codex plugin marketplace upgrade hei5enbug
codex plugin add hei5enbug-agent-setup@hei5enbug
```

Actualiza Claude Code cuando la versión esté disponible:

```bash
claude plugin marketplace update hei5enbug
claude plugin update hei5enbug-agent-setup@hei5enbug
```

Tras actualizar, inicia un hilo nuevo de Codex o reinicia Claude Code para que el host cargue los nuevos skills y las instrucciones.

## Verificaciones de desarrollo

Los scripts incluidos necesitan Python 3.12 o superior con PyYAML, y las pruebas de Node necesitan Node.js.
Ejecuta con los mismos comandos las tres verificaciones que `.github/workflows/validate.yml` ejecuta en macOS y Linux:

```bash
python3 -m pip install -e ".[dev]"
for skill in skills/*/ standalone-skills/*/; do python3 skills/skill-builder/scripts/quick_validate.py "$skill"; done
python3 -m pytest
node --test skills/document-to-confluence/tests/test_render_diagrams.mjs
```

## Idioma de las instrucciones

Los archivos en inglés son las fuentes ejecutables canónicas de skills, referencias, agentes e instrucciones de sesión.
Cada archivo Markdown en inglés para lectura humana tiene al lado una traducción coreana `.ko.md` con el mismo significado.
Las traducciones no son autoritativas y no se cargan durante la ejecución. La fuente y su traducción se modifican, mueven
o eliminan juntas. El código, los esquemas, los datos de prueba, los artefactos generados y los documentos que no están
en inglés no necesitan copia coreana. El coreano puede permanecer como dato del idioma objetivo.

## Skills

| Skill | Qué hace |
|---|---|
| [`decision-navigator`](skills/decision-navigator/SKILL.md) | Convierte un trabajo que abarca varias sesiones en tickets de decisión y los resuelve uno a uno hasta que la ruta de implementación queda clara. |
| [`deep-interview`](skills/deep-interview/SKILL.md) | Realiza una entrevista socrática que puntúa la ambigüedad del requisito tras cada respuesta y no avanza a la ejecución hasta que baja del umbral. [Guía en coreano](skills/deep-interview/SKILL.ko.md) |
| [`flowchart-design`](skills/flowchart-design/SKILL.md) | Un estándar de diseño compartido para que los diagramas de flujo hechos en SVG, HTML/CSS, Figma o draw.io se vean como parte de un mismo sistema de diseño. |
| [`humanize-korean`](skills/humanize-korean/SKILL.md) | Reescribe texto en coreano con apariencia de IA para que suene natural y humano, sin cambiar su significado. [Guía en coreano](skills/humanize-korean/SKILL.ko.md) |
| [`document-to-confluence`](skills/document-to-confluence/SKILL.md) | Convierte contenido de Markdown, HTML, PDF, DOCX y Google Docs en páginas de Confluence, conserva la estructura y los adjuntos y sincroniza cambios posteriores de la fuente. |
| [`skill-builder`](skills/skill-builder/SKILL.md) | Crea, prueba y empaqueta skills de agente mediante un ciclo de borrador → prueba → revisión → mejora. |
| [`suggest-commit`](skills/suggest-commit/SKILL.md) | Lee juntos los cambios preparados y sin preparar, o el alcance que indiques, junto con el historial reciente de commits, y sugiere cinco mensajes de commit acordes al estilo del repositorio. |
| [`technical-design-writer`](skills/technical-design-writer/SKILL.md) | Reglas y un proceso de cinco pasos que va acotando el índice para escribir o depurar documentos de diseño técnico. [Guía en coreano](skills/technical-design-writer/SKILL.ko.md) |
| [`tiki-taka`](skills/tiki-taka/SKILL.md) | Ejecuta un debate con número de turnos limitado entre el agente actual y una sesión opuesta de Claude/Codex para sacar a la luz y resolver problemas. [Guía en coreano](skills/tiki-taka/SKILL.ko.md) |

## Enlaces relacionados

- [`omo-model-config`](standalone-skills/omo-model-config/SKILL.md) se conserva como código independiente
  y no forma parte de la lista de skills del plugin.
- [Oh My OpenAgent](https://github.com/code-yeongyu/oh-my-openagent) — sistema de plugins cuyo enrutado de
  modelos actualiza el skill independiente

## Licencia

Este repositorio se distribuye bajo la Apache License 2.0. El texto completo está en [`LICENSE`](./LICENSE).
