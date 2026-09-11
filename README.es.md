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
├── LICENSE
├── pyproject.toml
├── standalone-agents/
│   ├── scout.md
│   └── codex-explorer.toml
├── standalone-skills/
│   └── omo-model-config/
└── skills/
    ├── confluence-ops/
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

Cada carpeta de skill del plugin contiene su propio `SKILL.md` junto con las referencias o scripts que necesita.
Los manifiestos del plugin empaquetan el mismo directorio `skills/` para Codex y Claude Code sin copiar skills a directorios específicos de cada host.
El directorio `standalone-skills/` no forma parte de la ruta de descubrimiento de skills de ningún plugin.

El directorio `standalone-agents/` contiene las definiciones de subagentes a las que `CLAUDE.md` y `AGENTS.md` se refieren por nombre.
Copia `scout.md` a mano en `~/.claude/agents/`. Copia `codex-explorer.toml` como `~/.codex/agents/explorer.toml`;
sustituye al `explorer` integrado de Codex para fijar su esfuerzo de razonamiento y su sandbox de solo lectura. No indica ningún modelo,
así que hereda el modelo predeterminado del host, a diferencia de `scout`, que fija uno en Claude Code.
Quedan fuera del paquete del plugin, de modo que instalarlo nunca añade un subagente.

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

## Actualización del plugin

Los dos manifiestos del plugin y `pyproject.toml` llevan la misma versión semántica, actualmente `0.2.0`. Antes de publicar
una versión, comprueba que pasan las verificaciones de desarrollo de abajo y sube la versión a la vez en
`.codex-plugin/plugin.json`, `.claude-plugin/plugin.json` y `pyproject.toml`.

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

Tras actualizar, inicia un hilo nuevo de Codex o reinicia Claude Code para que el host cargue las nuevas versiones de los skills.

## Verificaciones de desarrollo

Los scripts incluidos necesitan Python 3.12 o superior con PyYAML, y las pruebas de Node necesitan Node.js.
Ejecuta con los mismos comandos las tres verificaciones que `.github/workflows/validate.yml` ejecuta en macOS y Linux:

```bash
python3 -m pip install -e ".[dev]"
for skill in skills/*/ standalone-skills/*/; do python3 skills/skill-builder/scripts/quick_validate.py "$skill"; done
python3 -m pytest
node --test skills/markdown-to-confluence/tests/test_render_diagrams.mjs
```

## Idioma de las instrucciones

Las instrucciones ejecutables de los skills están escritas en inglés. Un `README.ko.md` dentro de un directorio de skill es una
traducción coreana no autoritativa que se mantiene sincronizada con su documento en inglés. Es para lectores humanos y un agente
no debe cargarla ni usarla durante la ejecución del skill. El texto en coreano solo permanece en archivos ejecutables cuando es
un dato del idioma objetivo, como frases de activación, ejemplos, etiquetas de salida obligatorias o datos de evaluación.

## Skills

| Skill | Qué hace |
|---|---|
| [`confluence-ops`](skills/confluence-ops/SKILL.md) | Reglas internas para trabajar con Confluence: prioriza `confluence-cli` sobre herramientas genéricas, mantiene las credenciales fuera de la línea de comandos y logra que el marcado de comentarios y las menciones funcionen bien. |
| [`decision-navigator`](skills/decision-navigator/SKILL.md) | Convierte un trabajo que abarca varias sesiones en tickets de decisión y los resuelve uno a uno hasta que la ruta de implementación queda clara. |
| [`deep-interview`](skills/deep-interview/SKILL.md) | Realiza una entrevista socrática que puntúa la ambigüedad del requisito tras cada respuesta y no avanza a la ejecución hasta que baja del umbral. [Guía en coreano](skills/deep-interview/README.ko.md) |
| [`flowchart-design`](skills/flowchart-design/SKILL.md) | Un estándar de diseño compartido para que los diagramas de flujo hechos en SVG, HTML/CSS, Figma o draw.io se vean como parte de un mismo sistema de diseño. |
| [`humanize-korean`](skills/humanize-korean/SKILL.md) | Reescribe texto en coreano con apariencia de IA para que suene natural y humano, sin cambiar su significado. [Guía en coreano](skills/humanize-korean/README.ko.md) |
| [`markdown-to-confluence`](skills/markdown-to-confluence/SKILL.md) | Publica un documento Markdown como página de Confluence y mantiene la página correcta en ediciones posteriores: macro de índice, imágenes en línea, adjuntos y diagramas renderizados como imágenes. |
| [`skill-builder`](skills/skill-builder/SKILL.md) | Crea, prueba y empaqueta skills de agente mediante un ciclo de borrador → prueba → revisión → mejora. |
| [`suggest-commit`](skills/suggest-commit/SKILL.md) | Lee juntos los cambios preparados y sin preparar, o el alcance que indiques, junto con el historial reciente de commits, y sugiere cinco mensajes de commit acordes al estilo del repositorio. |
| [`technical-design-writer`](skills/technical-design-writer/SKILL.md) | Reglas y un proceso de cinco pasos que va acotando el índice para escribir o depurar documentos de diseño técnico. [Guía en coreano](skills/technical-design-writer/README.ko.md) |
| [`tiki-taka`](skills/tiki-taka/SKILL.md) | Ejecuta un debate con número de turnos limitado entre el agente actual y una sesión opuesta de Claude/Codex para sacar a la luz y resolver problemas. [Guía en coreano](skills/tiki-taka/README.ko.md) |

## Enlaces relacionados

- [`omo-model-config`](standalone-skills/omo-model-config/SKILL.md) se conserva como código independiente
  y no forma parte de la lista de skills del plugin.
- [Oh My OpenAgent](https://github.com/code-yeongyu/oh-my-openagent) — sistema de plugins cuyo enrutado de
  modelos actualiza el skill independiente

## Licencia

Este repositorio se distribuye bajo la Apache License 2.0. El texto completo está en [`LICENSE`](./LICENSE).
