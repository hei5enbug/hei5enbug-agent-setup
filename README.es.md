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

Cada carpeta de skill del plugin contiene su propio `SKILL.md` junto con las referencias o scripts que necesita.
Los manifiestos del plugin empaquetan el mismo directorio `skills/` para Codex y Claude Code sin copiar skills a directorios específicos de cada host.
El directorio `standalone-skills/` no forma parte de la ruta de descubrimiento de skills de ningún plugin.

El directorio `agents/` se distribuye con el plugin de Claude Code, así que instalar el paquete añade los
subagentes `hei5enbug-agent-setup:scout` y `hei5enbug-agent-setup:worker`. No hace falta copiar nada a mano. El
manifiesto solo enumera estas dos definiciones en inglés, así que las traducciones al coreano de `agents/ko/` no se
registran como subagentes.

Codex solo busca subagentes en `~/.codex/agents/` y `.codex/agents/`, por lo que un plugin no puede registrar uno.
En su lugar, el hook de sesión copia `standalone-agents/codex-scout.toml` y `standalone-agents/codex-worker.toml` en
`~/.codex/agents/scout.toml` y `~/.codex/agents/worker.toml` cuando cada archivo no existe. Definen los agentes
`scout` y `worker`, con los mismos nombres que en Claude Code, un esfuerzo de razonamiento fijo y un sandbox fijo.
El `worker` del plugin sustituye al `worker` integrado de Codex, y `scout` no modifica el `explorer` integrado. Un
archivo que usted haya editado nunca se sobrescribe, y los agentes quedan disponibles en la siguiente sesión de Codex.
Como una copia editada nunca cambia, los archivos no indican ningún modelo; en su lugar, las instrucciones de Codex
pasan el modelo fijado en cada creación. El hook también elimina un `explorer.toml` y sustituye un `worker.toml`
escritos por una versión anterior, pero solo mientras el archivo sea idéntico byte a byte al que distribuyó esa
versión; una copia que usted haya editado se conserva. Con el plugin desactivado, el rol `worker` instalado actúa
como un worker de implementación normal en lugar de negarse a editar.

Un hook `PreToolUse`, `scripts/agent_guard.py`, mantiene fuera los subagentes integrados en ambos hosts. En Claude
Code rechaza un tipo de subagente omitido y todo tipo integrado: `general-purpose`, `Explore`, `Plan`, `claude` y las
bifurcaciones. Los tipos integrados de propósito acotado `claude-code-guide` y `statusline-setup` pasan, igual que los
agentes de plugin y las definiciones de cualquier origen de usuario, proyecto, CLI o gestionado. En Codex rechaza un
tipo omitido, `default`, `explorer` y todo tipo sin archivo de rol, incluido el `worker` integrado mientras falte el
rol del plugin. Los skills que piden un worker independiente de solo lectura usan `scout`, y los que escriben salidas
de prueba ejecutan un proceso `claude -p` o `codex exec` aparte.

### Idioma de respuesta

Un guardián de idioma, `scripts/language_guard.py`, comprueba que cada respuesta y cada aviso de progreso estén
escritos en el idioma de respuesta. Claude Code toma el idioma del ajuste `language`, que lee de la configuración
local del proyecto, luego de la del proyecto y luego de la del usuario; sin ese ajuste, no se impone nada. Codex lee
`HEI5ENBUG_RESPONSE_LANGUAGE` y usa coreano si no está definida. Solo se comprueban los idiomas con una escritura
distintiva: coreano, japonés, chino, ruso, ucraniano, griego, árabe, hebreo, tailandés e hindi. Con cualquier otro
idioma, como inglés o francés, solo se aplica la instrucción.

La comprobación ignora el código, las citas y las URL. Un texto pasa cuando al menos el 30 % de sus letras pertenecen
a la escritura del idioma, y un texto muy corto siempre pasa. Un hook `Stop` pide reescribir una respuesta que no
pasa, como máximo 3 veces por turno. Un hook `PostToolUse` añade un recordatorio tras un aviso de progreso en otro
idioma. Coloque el texto que el usuario pida en otro idioma en un bloque de código o una cita en bloque.

### Guardián de consultas de DataGrip

Un hook `PreToolUse` y un hook `PermissionRequest`, ambos `scripts/datagrip_guard.py`, se ejecutan antes de la
herramienta MCP de DataGrip `execute_sql_query`. El guardián lee la conexión de `.idea/dataSources.xml` en el proyecto
de DataGrip que indica `projectPath`. Una conexión cuyo nombre contiene `승인` siempre pide aprobación. Las lecturas de
PostgreSQL y SQL Server se ejecutan sin aprobación, y las de PostgreSQL se ejecutan dentro de una transacción de solo
lectura. Las escrituras, las consultas que el guardián no puede clasificar, las conexiones desconocidas y los demás
tipos de base de datos siempre piden aprobación. El guardián nunca deniega una llamada. En Codex, apruebe el hook en
`/hooks`.

De forma opcional, instale el analizador `pglast` una vez:

```bash
uv venv --python 3.12 "${XDG_STATE_HOME:-$HOME/.local/state}/hei5enbug-agent-setup/sql-parser"
uv pip install --python "${XDG_STATE_HOME:-$HOME/.local/state}/hei5enbug-agent-setup/sql-parser/bin/python" pglast==8.4
```

Sin él, PostgreSQL recurre a una comprobación de texto más estricta que puede pedir aprobación con más frecuencia,
pero nunca deja pasar una escritura sin aprobación.

### Aprobaciones de sesión

Solo en Claude Code, un guardián de aprobaciones de sesión, `scripts/session_approval_guard.py`, permite aprobar una
vez por sesión ciertas escrituras con efecto externo. Cubre la creación de etiquetas git, el envío de etiquetas a un
remoto configurado, `gh release create` y `gh release edit` solo con la etiqueta y las opciones `--title`, `--notes`,
`--target`, `--generate-notes`, `--notes-from-tag`, `--latest`, `--draft`, `--prerelease`, `--verify-tag`, y las
herramientas MCP cuyo nombre contiene un verbo de escritura. Tras aprobar una, el mismo tipo de acción se ejecuta sin
preguntar durante el resto de la sesión. Cada tipo de herramienta o de comando se aprueba por separado.

Las acciones destructivas siempre piden aprobación: los envíos forzados, borrar ramas remotas o etiquetas, borrar una
etiqueta, `gh release delete`, `gh repo delete` y las herramientas MCP que borran, envían a la papelera o eliminan.
`gh release upload` también pide siempre aprobación, porque puede publicar cualquier archivo local. Lo mismo ocurre
con el envío de una etiqueta a una URL, a un remoto no listado o con `--repo`, o que mezcla una rama en un envío con
`--tags`, y con un `gh release create` o `gh release edit` con archivos adjuntos, `--notes-file` o cualquier otra
opción. Un comando compuesto con algo que el guardián no puede verificar también pide siempre aprobación. Los
subagentes no heredan las aprobaciones. Las aprobaciones caducan con la sesión y se guardan en el directorio de datos
del plugin. Los envíos ordinarios y los demás comandos conservan el flujo de permisos normal.

No añada reglas `permissions.ask` para estas acciones, porque una regla ask pregunta cada vez, incluso después de una
aprobación de sesión.

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
Tras cada llamada a una herramienta y al terminar cada respuesta, el guardián de idioma también se ejecuta mediante
`PostToolUse` y `Stop`.
El guardián de consultas de DataGrip se ejecuta antes de `execute_sql_query` mediante `PreToolUse` y
`PermissionRequest`.
En Claude Code, el guardián de aprobaciones de sesión se ejecuta para Bash y las herramientas MCP mediante `PreToolUse`
y `PostToolUse`.
Se requiere Python 3.12 o superior como `python3`, hooks habilitados y aprobación de confianza en Codex.
Un hook que añade una actualización, como el guardián de agentes, el de idioma o el de consultas de DataGrip, queda
omitido en Codex hasta que lo apruebes en `/hooks`.
El guardián de aprobaciones de sesión solo se ejecuta en Claude Code, así que este paso de confianza no le afecta.
Tras actualizar el plugin, inicia una sesión nueva.
Consulta las referencias, los errores y los límites en la
[sección en inglés](README.md#automatic-instructions).

## Actualización del plugin

Los dos manifiestos del plugin, `pyproject.toml` y `uv.lock` deben usar la misma versión semántica.
La etiqueta `v<version>` más reciente alcanzable desde `HEAD` es la base de la versión publicada. El primer cambio
posterior fija la siguiente versión en estos archivos dentro del mismo commit. Una versión que solo aparece en estos
archivos es la próxima versión planificada, aunque ya esté en `main`, así que agrupa en ella todos los cambios no
publicados posteriores en lugar de subirla otra vez. Una versión publicada no añade ningún commit: cuando pasen las
verificaciones de desarrollo de abajo en `HEAD`, etiqueta `HEAD` con `v<version>` y sube la etiqueta.

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

Las pruebas que necesitan la CLI de Orca se omiten cuando no está instalada, así que la CI pasa sin Orca. Después de
instalar Orca, vuelva a ejecutar `python3 -m pytest` para cubrirlas.

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
| [`docs-rewrite`](skills/docs-rewrite/SKILL.md) | Reescribe un texto existente para que se lea con naturalidad manteniendo idénticas todas sus afirmaciones, cifras y grados de certeza, y corrige el coreano con apariencia de IA. [Guía en coreano](skills/docs-rewrite/SKILL.ko.md) |
| [`document-to-confluence`](skills/document-to-confluence/SKILL.md) | Convierte contenido de Markdown, HTML, PDF, DOCX y Google Docs en páginas de Confluence, conserva la estructura y los adjuntos y sincroniza cambios posteriores de la fuente. |
| [`skill-builder`](skills/skill-builder/SKILL.md) | Crea, prueba y empaqueta skills de agente mediante un ciclo de borrador → prueba → revisión → mejora. |
| [`suggest-commit`](skills/suggest-commit/SKILL.md) | Lee juntos los cambios preparados y sin preparar, o el alcance que indiques, junto con el historial reciente de commits, y sugiere cinco mensajes de commit acordes al estilo del repositorio. Si le pides que haga el commit, lo crea directamente con el asunto más adecuado. |
| [`technical-design-writer`](skills/technical-design-writer/SKILL.md) | Reglas y un proceso de cinco pasos que va acotando el índice para escribir o depurar documentos de diseño técnico. [Guía en coreano](skills/technical-design-writer/SKILL.ko.md) |
| [`tiki-taka`](skills/tiki-taka/SKILL.md) | Ejecuta un debate con número de turnos limitado entre el agente actual y una sesión opuesta de Claude/Codex para sacar a la luz y resolver problemas. [Guía en coreano](skills/tiki-taka/SKILL.ko.md) |

## Enlaces relacionados

- [`omo-model-config`](standalone-skills/omo-model-config/SKILL.md) se conserva como código independiente
  y no forma parte de la lista de skills del plugin.
- [Oh My OpenAgent](https://github.com/code-yeongyu/oh-my-openagent) — sistema de plugins cuyo enrutado de
  modelos actualiza el skill independiente

## Licencia

Este repositorio se distribuye bajo la Apache License 2.0. El texto completo está en [`LICENSE`](./LICENSE).
