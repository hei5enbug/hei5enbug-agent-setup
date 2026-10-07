const HIDDEN_AGENTS = /^(general-purpose|explore|plan|claude)$/i;
const FORK_DENIAL =
  "Forking the current conversation is disabled while hei5enbug-agent-setup is installed. Use `hei5enbug-agent-setup:scout` or `hei5enbug-agent-setup:worker`, another defined agent, or the main session.";

const ROLE_PINS = Object.freeze({
  "hei5enbug-agent-setup:worker": { role: "worker", model: "claude-sonnet-5-5", effort: "high" },
  "hei5enbug-agent-setup:scout": { role: "scout", model: "claude-sonnet-5-5", effort: "medium" },
  "hei5enbug-agent-setup:researcher": { role: "researcher", model: "claude-sonnet-5-5", effort: "medium" },
  "hei5enbug-agent-setup:designer": { role: "designer", model: "claude-opus-5-5", effort: "xhigh" },
});

const BUILT_IN_DENIAL =
  "The built-in agent is disabled while hei5enbug-agent-setup is installed. Use `hei5enbug-agent-setup:scout` or `hei5enbug-agent-setup:worker`, another defined agent, or the main session.";

const RETENTION_MS = 7 * 24 * 60 * 60 * 1000;
const STORE_KEY = "roles";
const CONTEXT_BLOCK = { name: "hei5enbugAgentSetupMod", text: "hei5enbug-agent-setup mod: role pinning active" };
const REFUSAL_TEXT =
  "This subagent ran on a model other than its pinned model, so hei5enbug-agent-setup stopped it. Its result must not be accepted.";
const TOOL_DENIAL =
  "This subagent ran on a model other than its pinned model, so hei5enbug-agent-setup denies its tool calls.";
const RESULT_WARNING =
  "Warning: this subagent ran on an unexpected model instead of its pinned model. Do not accept its result; redo the work through another allowed path.";

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

export function registerAgentGuard(on) {
  on("agent.offer", { agent: HIDDEN_AGENTS }, () => ({ isOffered: false })).catch(($, e, next) => next(e));

  on("agent.spawn", { fork: true }, () => ({ deny: FORK_DENIAL })).catch(($, e, next) => next(e));

  on("agent.spawn", { subagentType: HIDDEN_AGENTS }, () => ({ deny: BUILT_IN_DENIAL })).catch(($, e, next) => next(e));
}

export function registerRolePinning(on) {
  on("agent.spawn", { subagentType: ["hei5enbug-agent-setup:worker", "hei5enbug-agent-setup:scout", "hei5enbug-agent-setup:researcher", "hei5enbug-agent-setup:designer"] }, async ($, e, next) => {
    const pin = ROLE_PINS[e.subagentType];
    const result = await next({ ...e, model: pin.model });
    if (result.deny !== undefined || result.agentId === undefined) return result;
    await recordRole($, {
      agentId: result.agentId,
      role: pin.role,
      model: pin.model,
      effort: pin.effort,
      toolUseId: e.tool_use_id,
    });
    return result;
  }).catch(($, e, next) => next(e));

  on("turn.step", async function* ($, e, next) {
    if (e.agentId === undefined) return yield* next(e);
    const entry = await findByAgent($, e.agentId);
    if (entry === undefined) return yield* next(e);
    if (entry.mismatch === true) {
      yield { kind: "text", index: 0, text: REFUSAL_TEXT };
      yield { kind: "stop", stopReason: "refusal", usage: null };
      return { turnId: e.turnId, index: e.index, answer: REFUSAL_TEXT, toolUses: [], stopReason: "refusal", usage: null };
    }
    const response = yield* next({ ...e, model: entry.model, effort: entry.effort });
    if (response.usage !== null && response.usage.model !== entry.model) {
      await markMismatch($, e.agentId);
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
    return entry?.mismatch === true ? replacedAgentResult(result) : result;
  }).catch(($, e, next) => next(e));

  on("prompt.context", async ($, e, next) => {
    const context = await next(e);
    return { ...context, blocks: [...context.blocks, CONTEXT_BLOCK] };
  });
}
