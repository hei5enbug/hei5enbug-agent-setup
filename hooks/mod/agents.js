import { atom, read, update } from "claude-code";
import { claudeRolePins, configuredWorkerPin } from "./registry.js";

const WORKER_AGENT = "hei5enbug-agent-setup:worker";
const HIDDEN_AGENTS = /^(general-purpose|explore|plan|claude)$/i;
const FORK_DENIAL =
  "Forking the current conversation is disabled while hei5enbug-agent-setup is installed. Use `hei5enbug-agent-setup:scout` or `hei5enbug-agent-setup:worker`, another defined agent, or the main session.";

const BUILT_IN_DENIAL =
  "The built-in agent is disabled while hei5enbug-agent-setup is installed. Use `hei5enbug-agent-setup:scout` or `hei5enbug-agent-setup:worker`, another defined agent, or the main session.";

const PLUGIN_AGENT = /^[^:]+:/;
const RETENTION_MS = 7 * 24 * 60 * 60 * 1000;
const STORE_KEY = "roles";
const MARKER = "hei5enbug-agent-setup mod: role pinning active";
const markerSession = atom({ plugin: "hei5enbug-agent-setup", key: "roleMarkerSession" }, null);
const REFUSAL_TEXT =
  "This subagent ran on a model other than its pinned model, so hei5enbug-agent-setup stopped it. Its result must not be accepted.";
const TOOL_DENIAL =
  "This subagent ran on a model other than its pinned model, so hei5enbug-agent-setup denies its tool calls.";
const RESULT_WARNING =
  "Warning: this subagent ran on a model other than its pinned model. Do not accept its result; redo the work through another allowed path.";

let storeQueue = Promise.resolve();

function isRecord(value) {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function prunedRoles(stored, now) {
  const roles = {};
  if (!isRecord(stored)) return roles;
  for (const [sessionId, entries] of Object.entries(stored)) {
    if (!Array.isArray(entries)) continue;
    const kept = entries.filter((entry) => isRecord(entry) && typeof entry.time === "number" && entry.time >= now - RETENTION_MS);
    if (kept.length > 0) roles[sessionId] = kept;
  }
  return roles;
}

function updateRoles($, change) {
  const run = storeQueue.then(async () => {
    const now = await $.clock.now();
    const sessionId = await $.session.id();
    const roles = prunedRoles(await $.store.get(STORE_KEY), now);
    roles[sessionId] = change(roles[sessionId] ?? [], now);
    await $.store.set(STORE_KEY, roles);
  });
  storeQueue = run.catch(() => undefined);
  return run;
}

async function sessionEntries($) {
  const stored = await $.store.get(STORE_KEY);
  const entries = isRecord(stored) ? stored[await $.session.id()] : undefined;
  return Array.isArray(entries) ? entries.filter(isRecord) : [];
}

async function findByAgent($, agentId) {
  return (await sessionEntries($)).find((entry) => entry.agentId === agentId);
}

async function findByToolUse($, toolUseId) {
  return (await sessionEntries($)).find((entry) => entry.toolUseId === toolUseId);
}

function markMismatch($, agentId) {
  return updateRoles($, (entries) => entries.map((entry) => (entry.agentId === agentId ? { ...entry, mismatch: true } : entry)));
}

function recordRole($, entry) {
  return updateRoles($, (entries, now) => [...entries.filter((item) => item.agentId !== entry.agentId), { ...entry, time: now }]);
}

function replacedAgentResult(result) {
  const record = isRecord(result.result) ? result.result : {};
  return {
    result: { ...record, content: [{ type: "text", text: RESULT_WARNING }] },
    context: [RESULT_WARNING],
  };
}

function unpinnedDenial(name, reason) {
  return `hei5enbug-agent-setup could not verify the model pin for ${name} (${reason}), so it did not start the agent. Use another defined agent or the main session.`;
}

function prefixReason(table, name) {
  if (table.installsUnusable !== undefined && PLUGIN_AGENT.test(name) && !table.registryNames.has(name)) {
    return table.installsUnusable;
  }
  return table.prefixes.find((item) => name.startsWith(item.prefix))?.reason;
}

function pinnedOrCovered(table, name) {
  return table.pins.has(name) || table.denials.has(name) || prefixReason(table, name) !== undefined;
}

function fallbackDenial(root, name, access) {
  const writes = access === "write" ? " --add-dir <dir> for each directory it may write" : "";
  const mcp = access === "write" ? " Add --mcp only when the assignment needs MCP tools or network." : "";
  return (
    `${name} failed model verification, so hei5enbug-agent-setup denied this spawn once. Run its fallback through the role runner: ` +
    `python3 ${root}/scripts/role_runner.py agent --name ${name} --fallback --assignment <file> --result <file>${writes}.${mcp}`
  );
}

async function consumeRetryNotice($, name) {
  const last = (await sessionEntries($)).filter((entry) => entry.agent === name).at(-1);
  if (last?.mismatch !== true || last.retryNoticeIssued === true) return false;
  await updateRoles($, (entries) => entries.map((entry) => (entry.agentId === last.agentId ? { ...entry, retryNoticeIssued: true } : entry)));
  return true;
}

export function registerAgentGuard(on) {
  on("agent.offer", { agent: HIDDEN_AGENTS }, () => ({ isOffered: false })).catch(($, e, next) => next(e));

  on("agent.spawn", { fork: true }, () => ({ deny: FORK_DENIAL })).catch(($, e, next) => next(e));

  on("agent.spawn", { subagentType: HIDDEN_AGENTS }, () => ({ deny: BUILT_IN_DENIAL })).catch(($, e, next) => next(e));
}

async function pinSpawn($, e, next, unrecorded, options) {
  const table = await claudeRolePins($);
  const reason = table.denials.get(e.subagentType) ?? prefixReason(table, e.subagentType);
  if (reason !== undefined) return { deny: unpinnedDenial(e.subagentType, reason) };
  const pinned = table.pins.get(e.subagentType);
  if (pinned === undefined) return next(e);
  const configured = e.subagentType === WORKER_AGENT ? await configuredWorkerPin($, options) : undefined;
  const declared = configured === undefined ? pinned : { ...pinned, primary: configured };
  if (await consumeRetryNotice($, e.subagentType)) {
    return { deny: fallbackDenial($.plugin.root, e.subagentType, declared.access) };
  }
  const result = await next({ ...e, model: declared.primary.model });
  if (result.deny !== undefined || result.agentId === undefined) return result;
  try {
    await recordRole($, {
      agentId: result.agentId,
      agent: e.subagentType,
      role: declared.role,
      model: declared.primary.model,
      effort: declared.primary.effort,
      toolUseId: e.tool_use_id,
    });
  } catch {
    unrecorded.add(result.agentId);
  }
  return result;
}

export function registerRolePinning(on, options) {
  const unrecorded = new Set();

  on("agent.spawn", async ($, e, next) => {
    if (typeof e.subagentType !== "string") return next(e);
    try {
      return await pinSpawn($, e, next, unrecorded, options);
    } catch (error) {
      if (pinnedOrCovered(await claudeRolePins($), e.subagentType)) {
        return { deny: unpinnedDenial(e.subagentType, "the role pin check failed") };
      }
      throw error;
    }
  }).catch(($, e, next) => next(e));

  on("turn.step", async function* ($, e, next) {
    if (e.agentId === undefined) return yield* next(e);
    const entry = unrecorded.has(e.agentId) ? { mismatch: true } : await findByAgent($, e.agentId);
    if (entry === undefined) return yield* next(e);
    if (entry.mismatch === true) {
      yield { kind: "text", index: 0, text: REFUSAL_TEXT };
      yield { kind: "stop", stopReason: "refusal", usage: null };
      return { turnId: e.turnId, index: e.index, answer: REFUSAL_TEXT, toolUses: [], stopReason: "refusal", usage: null };
    }
    const response = yield* next({ ...e, model: entry.model, effort: entry.effort });
    if (response.usage?.model !== entry.model) {
      try {
        await markMismatch($, e.agentId);
      } catch {
        unrecorded.add(e.agentId);
      }
    }
    return response;
  }).catch(async function* ($, e, next) {
    return yield* next(e);
  });

  on("tool.call", async ($, e, next) => {
    if (e.agentId !== undefined) {
      const entry = await findByAgent($, e.agentId);
      return entry?.mismatch === true ? { deny: TOOL_DENIAL } : next(e);
    }
    if (e.tool !== "Agent") return next(e);
    const result = await next(e);
    if (result.deny !== undefined) return result;
    const entry = await findByToolUse($, e.tool_use_id);
    if (result.isError === true) {
      if (entry !== undefined) await markMismatch($, entry.agentId);
      return result;
    }
    if (entry?.mismatch !== true) return result;
    return replacedAgentResult(result);
  }).catch(($, e, next) => next(e));

  on("turn.complete", async ($, e, next) => {
    if (e.agentId !== undefined && e.reason === "error" && (await findByAgent($, e.agentId)) !== undefined) {
      await markMismatch($, e.agentId);
    }
    return next(e);
  }).catch(($, e, next) => next(e));

  on("session.end", { reason: ["clear", "resume"] }, async ($, e, next) => {
    await update($, markerSession, () => null);
    return next(e);
  }).catch(($, e, next) => next(e));

  on("prompt.submit", async ($, e, next) => {
    if (e.agentId !== undefined) return next(e);
    const sessionId = await $.session.id();
    if ((await read($, markerSession)) === sessionId) return next(e);
    const result = await next({ ...e, context: [...(e.context ?? []), MARKER] });
    if (result?.drop === undefined) await update($, markerSession, () => sessionId);
    return result;
  }).catch(($, e, next) => next(e));
}
