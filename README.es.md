# hei5enbug-agent-setup

[English](./README.md) | [한국어](./README.ko.md) | [日本語](./README.ja.md) | [简体中文](./README.zh-CN.md) | **Español** | [Deutsch](./README.de.md) | [Français](./README.fr.md)

Configuración de modelos y variants para un AI agent harness, asignados según el rol de cada agente.

## Descripción general

Cada agente en un harness requiere capacidades distintas. Esta configuración optimiza `model`, `variant` y cadenas de fallback por rol de agente y categoría de tarea.

## Herramientas compatibles

- [OpenCode](https://github.com/code-yeongyu/oh-my-opencode) (mediante el plugin [Oh My OpenCode](https://github.com/code-yeongyu/oh-my-opencode))

## Estructura

```
hei5enbug-agent-setup/
├── oh-my-opencode.json       # Archivo de configuración leído y modificado por el skill
├── available-models.json     # Allowlist utilizada por el skill para validar cambios de modelo
└── .opencode/
    └── skills/
        └── omo-model-config/ # Skill personalizado para edición segura de configuración
            └── SKILL.md
```

## Skills personalizados

### omo-model-config

Un flujo de trabajo para editar de forma segura las asignaciones de modelo de los agentes. Aplica las siguientes reglas:

- **Resolución GitHub-first** — la documentación upstream de [oh-my-openagent](https://github.com/code-yeongyu/oh-my-openagent) es la autoridad principal para el matching modelo-rol
- **Gate de disponibilidad** — todo modelo debe estar en la allowlist de `available-models.json`
- **Gate de diversidad de proveedores** — los proveedores requeridos deben estar cubiertos en la cadena de fallback de cada agente
- **Edición limitada** — solo se modifican los campos `model`, `variant` y `fallback_models`; todo lo demás se preserva

Consulta [`.opencode/skills/omo-model-config/SKILL.md`](.opencode/skills/omo-model-config/SKILL.md) para más detalles.

## Uso

Abre como raíz de proyecto en una herramienta de agente compatible. La configuración se carga automáticamente al iniciar la sesión.

```bash
cd hei5enbug-agent-setup
opencode
```

### Cambiar asignaciones de modelo

Invoca el skill `omo-model-config` desde la sesión del agente:

```
/omo-model-config
```

O solicítalo directamente al agente:

```
"Cambia el primary model de Oracle a claude-opus-4-6"
"Añade gpt-5.4 al fallback de Librarian"
```

El skill valida los cambios contra la allowlist y verifica las reglas de diversidad de proveedores antes de aplicarlos.

## Configuración

| Clave | Valor | Descripción |
|---|---|---|
| `runtime_fallback` | `true` | Cambia automáticamente al siguiente modelo si el principal no está disponible |
| `disabled_hooks` | `["no-sisyphus-gpt"]` | Permite el uso de modelos GPT en el agente Sisyphus |

## Enlaces relacionados

- [Oh My OpenCode](https://github.com/code-yeongyu/oh-my-opencode) — sistema de plugins que impulsa la configuración
- [oh-my-openagent docs](https://github.com/code-yeongyu/oh-my-openagent) — documentación upstream y guías de matching de modelos
