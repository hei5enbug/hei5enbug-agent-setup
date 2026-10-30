const REQUIRED_SECTIONS = ["pins", "claude_agents", "effort_rules"];
const PLUGIN_PREFIX = "hei5enbug-agent-setup:";
const PLUGINS_FILE = "plugins/installed_plugins.json";
const ROLES_FILE = ".claude-plugin/model-roles.json";
const MANIFEST_FILE = ".claude-plugin/plugin.json";
const loaded = new Map();
const manifests = new Map();
let pinTable;

function parseRegistry(text) {
  const registry = JSON.parse(text);
  const complete = registry !== null && typeof registry === "object"
    && REQUIRED_SECTIONS.every((key) => registry[key] !== undefined);
  if (!complete) throw new Error("model registry is missing a required section");
  return registry;
}

async function readRegistry($, path) {
  return parseRegistry(await $.fs.read(path));
}

export async function modelRegistry($) {
  const path = `${$.plugin.root}/config/model-registry.json`;
  if (!loaded.has(path)) {
    const pending = readRegistry($, path);
    loaded.set(path, pending);
    pending.catch(() => loaded.delete(path));
  }
  return loaded.get(path);
}

function isRecord(value) {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

async function readManifest($, path) {
  return JSON.parse(await $.fs.read(path));
}

async function pluginManifest($) {
  const path = `${$.plugin.root}/${MANIFEST_FILE}`;
  if (!manifests.has(path)) {
    const pending = readManifest($, path);
    manifests.set(path, pending);
    pending.catch(() => manifests.delete(path));
  }
  return manifests.get(path);
}

export async function configuredWorkerPin($, options) {
  const model = options?.worker_model;
  const effort = options?.worker_effort;
  if (typeof model !== "string" || typeof effort !== "string") return undefined;
  try {
    const { userConfig } = await pluginManifest($);
    if (!userConfig.worker_model.options.includes(model) || !userConfig.worker_effort.options.includes(effort)) return undefined;
    const allowed = (await modelRegistry($)).effort_rules?.[model];
    if (Array.isArray(allowed) && !allowed.includes(effort)) return undefined;
    return { model, effort };
  } catch {
    return undefined;
  }
}

export async function claudeConfigDir($) {
  const configured = await $.env.get("CLAUDE_CONFIG_DIR");
  return configured || `${(await $.env.get("HOME")) ?? ""}/.claude`;
}

function entryProblem(registry, entry) {
  if (registry === undefined) return "the model registry is unavailable";
  if (!isRecord(entry)) return "an entry is not an object";
  if (!Object.values(registry.pins).includes(entry.model)) return `${entry.model} is not a pinned model`;
  if (!(registry.efforts ?? []).includes(entry.effort)) return `${entry.effort} is not a known effort`;
  const allowed = registry.effort_rules?.[entry.model];
  if (Array.isArray(allowed) && !allowed.includes(entry.effort)) return `${entry.effort} is not allowed for ${entry.model}`;
  return undefined;
}

function declarationProblem(agents, plugin, registry) {
  for (const [name, entry] of Object.entries(agents)) {
    if (!name.startsWith(`${plugin}:`)) return `${name} is not named by ${plugin}`;
    const problem = entryProblem(registry, entry) ?? (entry.fallback === undefined ? undefined : entryProblem(registry, entry.fallback));
    if (problem !== undefined) return `${name}: ${problem}`;
  }
  return undefined;
}

function addDeclarations(table, plugin, text, registry) {
  let parsed;
  try {
    parsed = JSON.parse(text);
  } catch {
    table.prefixes.push({ prefix: `${plugin}:`, reason: "its model roles file is not valid JSON" });
    return;
  }
  if (!isRecord(parsed) || parsed.version !== 1 || !isRecord(parsed.agents)) {
    table.prefixes.push({ prefix: `${plugin}:`, reason: "its model roles file has no version 1 agents object" });
    return;
  }
  const problem = declarationProblem(parsed.agents, plugin, registry);
  for (const name of Object.keys(parsed.agents)) {
    if (table.registryNames.has(name)) continue;
    if (problem !== undefined) {
      table.pins.delete(name);
      table.denials.set(name, problem);
      continue;
    }
    if (table.denials.has(name) || table.pins.has(name)) continue;
    const entry = parsed.agents[name];
    table.pins.set(name, {
      role: name.slice(plugin.length + 1),
      primary: { model: entry.model, effort: entry.effort },
      access: entry.access ?? "read",
    });
  }
}

async function readText($, path) {
  try {
    return await $.fs.read(path);
  } catch {
    return undefined;
  }
}

async function exists($, path) {
  try {
    return await $.fs.exists(path);
  } catch {
    return true;
  }
}

async function installedPlugins($, config) {
  const path = `${config}/${PLUGINS_FILE}`;
  const text = await readText($, path);
  if (text === undefined) return { plugins: {}, unusable: await exists($, path) };
  try {
    const parsed = JSON.parse(text);
    return { plugins: isRecord(parsed) && isRecord(parsed.plugins) ? parsed.plugins : {}, unusable: false };
  } catch {
    return { plugins: {}, unusable: true };
  }
}

async function buildPinTable($) {
  const table = { pins: new Map(), denials: new Map(), prefixes: [], registryNames: new Set(), complete: true, installsUnusable: undefined };
  let registry;
  try {
    registry = await modelRegistry($);
    for (const [name, pin] of Object.entries(registry.claude_agents)) {
      table.registryNames.add(name);
      table.pins.set(name, {
        role: pin.role,
        primary: { model: pin.model, effort: pin.effort },
        access: pin.access,
      });
    }
  } catch {
    table.complete = false;
    table.prefixes.push({ prefix: PLUGIN_PREFIX, reason: "the model registry is unavailable" });
  }
  try {
    const { plugins, unusable } = await installedPlugins($, await claudeConfigDir($));
    if (unusable) table.installsUnusable = "its installed plugins file cannot be parsed";
    for (const [key, installs] of Object.entries(plugins)) {
      if (!Array.isArray(installs)) continue;
      const plugin = key.split("@")[0];
      for (const install of installs) {
        if (!isRecord(install) || typeof install.installPath !== "string") continue;
        const path = `${install.installPath}/${ROLES_FILE}`;
        const text = await readText($, path);
        if (text !== undefined) addDeclarations(table, plugin, text, registry);
        else if (await exists($, path)) table.prefixes.push({ prefix: `${plugin}:`, reason: "its model roles file cannot be read" });
      }
    }
  } catch {
    table.complete = false;
    table.prefixes.push({ prefix: "", reason: "the installed plugins could not be read" });
  }
  return table;
}

export async function claudeRolePins($) {
  if (pinTable !== undefined) return pinTable;
  const table = await buildPinTable($);
  if (table.complete) pinTable = table;
  return table;
}

export function resetClaudeRolePins() {
  pinTable = undefined;
  manifests.clear();
}

const CLAUDE_PREFIX = "claude-";
const QUOTED_TEXT = [
  /<pasted_content\b[^>]*>[\s\S]*?<\/pasted_content>/gi,
  /<pasted_content\b[^>]*\/>/gi,
  /(?<!`)(`{3,})(?!`)[\s\S]*?(?:\1|$)/g,
  /(?<!~)(~{3,})(?!~)[\s\S]*?(?:\1|$)/g,
];

function textWithoutQuotes(text) {
  return QUOTED_TEXT.reduce((rest, pattern) => rest.replace(pattern, " "), text);
}

function escaped(value) {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function claudeAliases(registry) {
  return Object.keys(registry.pins).filter((key) => key.startsWith(CLAUDE_PREFIX)).map((key) => key.slice(CLAUDE_PREFIX.length));
}

export function claudeModelId(registry, value) {
  if (typeof value !== "string") return undefined;
  const name = value.trim().toLowerCase();
  if (Object.values(registry.pins).includes(name) && name.startsWith(CLAUDE_PREFIX)) return name;
  const pinned = registry.pins[`${CLAUDE_PREFIX}${name}`];
  return typeof pinned === "string" && pinned.startsWith(CLAUDE_PREFIX) ? pinned : undefined;
}

function namedIn(text, words, boundary) {
  return words.filter((word) => new RegExp(`${boundary.before}${escaped(word)}${boundary.after}`, "i").test(text));
}

const ID_BOUNDARY = { before: "(?<![\\w.-])", after: "(?![\\w-]|\\.\\d)" };
const WORD_BOUNDARY = { before: "(?<![\\w-])", after: "(?![\\w-])" };

export function userRequest(registry, text) {
  const body = textWithoutQuotes(typeof text === "string" ? text : "");
  const ids = namedIn(body, Object.values(registry.pins), ID_BOUNDARY);
  const aliases = namedIn(body, claudeAliases(registry), WORD_BOUNDARY).map((alias) => registry.pins[`${CLAUDE_PREFIX}${alias}`]);
  const models = [...new Set([...ids, ...aliases])].filter((model) => model.startsWith(CLAUDE_PREFIX));
  const efforts = namedIn(body, registry.efforts ?? [], WORD_BOUNDARY);
  return { models, efforts };
}

function effortAllowed(registry, model, effort) {
  const allowed = registry.effort_rules?.[model];
  return (registry.efforts ?? []).includes(effort) && (!Array.isArray(allowed) || allowed.includes(effort));
}

export function requestedPin(registry, callModel, request, declared) {
  const model = claudeModelId(registry, callModel);
  if (model === undefined) return undefined;
  const named = request.efforts.length === 1 ? request.efforts[0] : undefined;
  if (!request.models.includes(model)) {
    const effortOnly = model === declared.model && named !== undefined && effortAllowed(registry, model, named);
    return effortOnly ? { model, effort: named } : undefined;
  }
  const effort = named !== undefined && effortAllowed(registry, model, named) ? named : declared.effort;
  return effortAllowed(registry, model, effort) ? { model, effort } : undefined;
}
