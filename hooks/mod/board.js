import { atom, read, update } from "claude-code";

const PANE = "work-board";
const MAIN = "main";
const EDIT_TOOLS = ["Edit", "Write", "NotebookEdit"];
const ACTIVE = new Set(["pending", "running", "waiting"]);
const STATUS_COLORS = { pending: "subtle", running: "suggestion", waiting: "warning", idle: "inactive", completed: "success", failed: "error", killed: "error" };
const SECOND = 1000;
const MINUTE = 60 * SECOND;
const HOUR = 60 * MINUTE;
const DAY = 24 * HOUR;
const TICK_MS = 5 * SECOND;
const CODEX_TTL_MS = 5 * MINUTE;
const WINDOWS = {
  five_hour: { name: "Claude 5h", short: "5h", ms: 5 * HOUR },
  seven_day: { name: "Claude weekly", short: "wk", ms: 7 * DAY },
};
const PANE_COLUMNS = 40;
const SEPARATOR = " · ";
const KEEP_ORDER = ["conflict", "parallel", "ctx", "5h", "wk", "Codex", "cache"];

const edits = atom({ plugin: "hei5enbug-agent-setup", key: "boardEdits" }, {});
const agentTimes = atom({ plugin: "hei5enbug-agent-setup", key: "boardAgents" }, {});
const announced = atom({ plugin: "hei5enbug-agent-setup", key: "boardAnnounced" }, []);
const cacheTotals = atom({ plugin: "hei5enbug-agent-setup", key: "boardCache" }, { read: 0, creation: 0, input: 0 });
const usageFigures = atom({ plugin: "hei5enbug-agent-setup", key: "boardUsage" }, null);
const codexUsage = atom({ plugin: "hei5enbug-agent-setup", key: "boardCodex" }, { at: null, percent: null });
const ticks = atom({ plugin: "hei5enbug-agent-setup", key: "boardTick" }, 0);
const mainActive = atom({ plugin: "hei5enbug-agent-setup", key: "boardMainActive" }, false);
const usageStale = atom({ plugin: "hei5enbug-agent-setup", key: "boardUsageStale" }, true);

let ticker;
let codexPending = false;

export function forecast(limit, now) {
  const window = WINDOWS[limit?.kind]?.ms;
  const resetsAt = Date.parse(limit?.resetsAt ?? "");
  const used = limit?.percentUsed;
  if (window === undefined || typeof used !== "number" || !Number.isFinite(resetsAt) || resetsAt <= now) return undefined;
  const elapsed = window - (resetsAt - now);
  if (elapsed <= 0) return undefined;
  if (used >= 100) return { isOnTrack: false, runsOutInMs: 0 };
  const runsOutInMs = used > 0 ? ((100 - used) * elapsed) / used : Infinity;
  return now + runsOutInMs < resetsAt ? { isOnTrack: false, runsOutInMs } : { isOnTrack: true };
}

export function hitRate(totals) {
  const total = totals.read + totals.creation + totals.input;
  return total > 0 ? Math.round((100 * totals.read) / total) : undefined;
}

export function roughly(ms) {
  if (ms < HOUR) return `~${Math.max(1, Math.round(ms / MINUTE))}m`;
  return ms < 2 * DAY ? `~${Math.round(ms / HOUR)}h` : `~${Math.round(ms / DAY)}d`;
}

function clockText(ms) {
  const seconds = Math.max(0, Math.floor(ms / SECOND));
  const pad = (value) => String(value).padStart(2, "0");
  if (seconds < 60) return `${seconds}s`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ${pad(seconds % 60)}s`;
  return `${Math.floor(seconds / 3600)}h ${pad(Math.floor(seconds / 60) % 60)}m`;
}

function tokens(value) {
  return typeof value === "number" && Number.isFinite(value) ? value : 0;
}

function shortPath(path, cwd) {
  return cwd && path.startsWith(`${cwd}/`) ? path.slice(cwd.length + 1) : path;
}

function figures(usage) {
  return {
    contextPercent: typeof usage.context?.percent === "number" ? usage.context.percent : null,
    rateLimits: (usage.rateLimits ?? []).map((limit) => ({ kind: limit.kind, percentUsed: limit.percentUsed, resetsAt: limit.resetsAt ?? null })),
  };
}

export function normalizedPath(path, cwd) {
  const parts = [];
  for (const part of (path.startsWith("/") ? path : `${cwd}/${path}`).split("/")) {
    if (part === "..") parts.pop();
    else if (part !== "" && part !== ".") parts.push(part);
  }
  return `/${parts.join("/")}`;
}

async function fileIdentity($, path, cwd) {
  const plain = normalizedPath(path, cwd);
  try {
    return (await $.fs.stat(plain, { resolve: true })).realPath ?? plain;
  } catch {
    return plain;
  }
}

function isActive(agent, times) {
  return ACTIVE.has(agent.status) && typeof times[agent.id]?.endedAt !== "number";
}

async function ownership($) {
  const [agents, files, times, isMainActive] = await Promise.all([$.agent.list(), read($, edits), read($, agentTimes), read($, mainActive)]);
  return { agents, files, times, isMainActive };
}

function owners(path, view) {
  const active = new Set(view.agents.filter((agent) => isActive(agent, view.times)).map((agent) => agent.id));
  return Object.entries(view.files)
    .filter(([owner, paths]) => paths.includes(path) && (owner === MAIN ? view.isMainActive : active.has(owner)))
    .map(([owner]) => owner);
}

function conflicts(view) {
  const paths = new Set(Object.values(view.files).flat());
  return new Set([...paths].filter((path) => owners(path, view).length > 1));
}

async function recordEdit($, owner, rawPath) {
  const cwd = await $.session.cwd();
  const path = await fileIdentity($, rawPath, cwd);
  if ((await read($, edits))[owner]?.includes(path)) return;
  const files = await update($, edits, (value) => ({ ...value, [owner]: [...(value[owner] ?? []).filter((item) => item !== path), path] }));
  const view = { ...(await ownership($)), files };
  const shared = owners(path, view);
  if (shared.length < 2 || (await read($, announced)).includes(path)) return;
  await update($, announced, (list) => (list.includes(path) ? list : [...list, path]));
  const names = shared.map((id) => (id === MAIN ? MAIN : view.agents.find((agent) => agent.id === id)?.type ?? id));
  $.ui.toast(`Edit conflict: ${shortPath(path, cwd)} (${names.join(", ")})`);
}

async function seedUsage($) {
  const usage = await $.session.usage().catch(() => undefined);
  if (usage === undefined) return false;
  await update($, usageFigures, () => figures(usage));
  await update($, usageStale, () => false);
  return true;
}

async function markTurn($, agentId, ended) {
  const now = await $.clock.now();
  await update($, agentTimes, (times) => ({
    ...times,
    [agentId]: { startedAt: times[agentId]?.startedAt ?? (ended ? null : now), endedAt: ended ? now : null },
  }));
}

async function refreshCodex($) {
  const now = await $.clock.now();
  const current = await read($, codexUsage);
  if (codexPending || (current.at !== null && now - current.at < CODEX_TTL_MS)) return;
  codexPending = true;
  let percent = null;
  try {
    const result = await $.process.run(["sh", `${$.plugin.root}/scripts/hook_python.sh`, "codex_usage.py"], { timeoutMs: 10 * SECOND });
    const value = JSON.parse(result.stdout).weekly_used_percent;
    percent = typeof value === "number" && Number.isFinite(value) ? value : null;
  } catch {
    percent = null;
  } finally {
    codexPending = false;
  }
  await update($, codexUsage, () => ({ at: now, percent }));
}

async function tick($) {
  try {
    if (!(await $.ui.panes()).some((pane) => pane.id === PANE)) {
      ticker?.cancel();
      ticker = undefined;
      return;
    }
    await refreshCodex($);
    const [agents, times] = await Promise.all([$.agent.list(), read($, agentTimes)]);
    if (agents.some((agent) => isActive(agent, times))) await update($, ticks, (count) => count + 1);
  } catch {
    return;
  }
}

function limitRow(Text, limit, now) {
  const window = WINDOWS[limit.kind];
  if (window === undefined || typeof limit.percentUsed !== "number") return [];
  const text = `${window.name} ${limit.percentUsed}%`;
  const outlook = forecast(limit, now);
  if (outlook === undefined) return [Text({ children: [text] })];
  if (outlook.isOnTrack) return [Text({ dimColor: true, children: [`${text} · on track`] })];
  const when = outlook.runsOutInMs > 0 ? `runs out in ${roughly(outlook.runsOutInMs)}, before reset` : "limit reached";
  return [Text({ color: "warning", children: [`${text} · ${when}`] })];
}

function usageRows(Text, usage, cache, codex, now) {
  const head = [];
  if (usage?.contextPercent !== null && usage?.contextPercent !== undefined) head.push(`context ${usage.contextPercent}%`);
  const rate = hitRate(cache);
  if (rate !== undefined) head.push(`cache hit ${rate}%`);
  if (codex.percent !== null) head.push(`Codex weekly ${Math.round(codex.percent)}%`);
  const limits = (usage?.rateLimits ?? []).flatMap((limit) => limitRow(Text, limit, now));
  return [...(head.length > 0 ? [Text({ children: [head.join(" · ")] })] : []), ...limits];
}

function compactParts(usage, cache, codex, running, conflicted, now) {
  const parts = [];
  if (typeof usage?.contextPercent === "number") parts.push({ id: "ctx", text: `ctx ${usage.contextPercent}%` });
  const rate = hitRate(cache);
  if (rate !== undefined) parts.push({ id: "cache", text: `cache ${rate}%` });
  for (const limit of usage?.rateLimits ?? []) {
    const window = WINDOWS[limit.kind];
    if (window === undefined || typeof limit.percentUsed !== "number") continue;
    const text = `${window.short} ${limit.percentUsed}%`;
    parts.push(forecast(limit, now)?.isOnTrack === false ? { id: window.short, text, color: "warning" } : { id: window.short, text });
  }
  if (typeof codex.percent === "number") parts.push({ id: "Codex", text: `Codex ${Math.round(codex.percent)}%` });
  if (running > 0) parts.push({ id: "parallel", text: `parallel ${running}` });
  if (conflicted > 0) parts.push({ id: "conflict", text: `conflict ${conflicted}`, color: "error" });
  return parts;
}

function lineWidth(parts) {
  return parts.reduce((total, part) => total + part.text.length, 0) + SEPARATOR.length * Math.max(0, parts.length - 1);
}

export function fitParts(parts, columns) {
  if (typeof columns !== "number" || !Number.isFinite(columns)) return parts;
  const kept = [...parts];
  const rank = (part) => KEEP_ORDER.indexOf(part.id);
  while (kept.length > 1 && lineWidth(kept) > columns) {
    const lowest = kept.reduce((worst, part) => (rank(part) > rank(worst) ? part : worst));
    kept.splice(kept.indexOf(lowest), 1);
  }
  return kept;
}

function truncating(Text) {
  return (props) => Text({ wrap: "truncate-end", ...props });
}

function agentRow(Box, Text, agent, times, now) {
  const { startedAt = null, endedAt = null } = times[agent.id] ?? {};
  const end = isActive(agent, times) ? now : endedAt ?? now;
  const cell = (flexShrink, props) => Box({ flexShrink, children: [Text(props)] });
  return Box({
    flexDirection: "row",
    columnGap: 1,
    children: [
      cell(1, { children: [`${agent.type} · ${agent.description}`] }),
      cell(0, { color: STATUS_COLORS[agent.status] ?? "text", children: [agent.status] }),
      ...(startedAt === null ? [] : [cell(0, { dimColor: true, children: [clockText(end - startedAt)] })]),
    ],
  });
}

export function registerWorkBoard(on) {
  on("session.start", async ($, e, next) => {
    await $.command.register({ name: "work-board", description: "Show subagents, the files they edit, edit conflicts, and usage in a pane", immediate: true });
    await seedUsage($).catch(() => undefined);
    return next(e);
  }).catch(($, e, next) => next(e));

  on("command.run", { command: "work-board" }, async ($) => {
    await $.ui.open({ id: PANE, title: "Work board", columns: PANE_COLUMNS });
    ticker ??= $.clock.every(TICK_MS, () => void tick($));
    await seedUsage($);
    await refreshCodex($);
    return {};
  });

  on("session.end", { reason: ["clear", "resume"] }, async ($, e, next) => {
    await update($, cacheTotals, () => ({ read: 0, creation: 0, input: 0 }));
    await update($, usageFigures, () => null);
    await update($, usageStale, () => true);
    return next(e);
  }).catch(($, e, next) => next(e));

  on("tool.call", { tool: EDIT_TOOLS }, async ($, e, next) => {
    const result = await next(e);
    const path = e.file_path ?? e.notebook_path;
    if (result.deny === undefined && result.isError !== true && typeof path === "string") await recordEdit($, e.agentId ?? MAIN, path);
    return result;
  }).catch(($, e, next) => next(e));

  on("turn.start", async ($, e, next) => {
    if (e.agentId !== undefined) await markTurn($, e.agentId, false);
    else {
      if (await read($, usageStale)) await seedUsage($).catch(() => undefined);
      if (Object.hasOwn(await read($, edits), MAIN)) await update($, edits, ({ [MAIN]: _, ...rest }) => rest);
      await update($, mainActive, () => true);
    }
    return next(e);
  });

  on("turn.complete", { turnId: /./ }, async ($, e, next) => {
    if (e.agentId !== undefined) await markTurn($, e.agentId, true);
    else {
      await update($, mainActive, () => false);
      void refreshCodex($).catch(() => undefined);
    }
    if (e.agentId === undefined && e.usage) {
      await update($, cacheTotals, (totals) => ({
        read: totals.read + tokens(e.usage.cache_read_input_tokens),
        creation: totals.creation + tokens(e.usage.cache_creation_input_tokens),
        input: totals.input + tokens(e.usage.input_tokens),
      }));
    }
    return next(e);
  });

  on("session.measure", async ($, e, next) => {
    await update($, usageFigures, () => figures(e));
    return next(e);
  });

  on("ui.render", { component: "AbovePrompt" }, async ($, e, next) => {
    if (e.props.hasSurvey) return next(e);
    const [view, cache, usage, codex, now] = await Promise.all([ownership($), read($, cacheTotals), read($, usageFigures), read($, codexUsage), $.clock.now()]);
    const running = view.agents.filter((agent) => isActive(agent, view.times)).length;
    const parts = fitParts(compactParts(usage, cache, codex, running, conflicts(view).size, now), e.props.bodyColumns);
    if (parts.length === 0) return next(e);
    const { Box, Text } = $.ui.resolve(e);
    const theirs = await next(e);
    const line = Box({
      flexDirection: "row",
      children: parts.map((part, index) =>
        Text({ wrap: "truncate-end", ...(part.color === undefined ? {} : { color: part.color }), children: [index === 0 ? part.text : `${SEPARATOR}${part.text}`] })),
    });
    return Box({ flexDirection: "column", children: theirs ? [line, theirs] : [line] });
  });

  on("ui.render", { component: "Pane", requestId: PANE }, async ($, e) => {
    const { Box, Text: plain } = $.ui.resolve(e);
    const Text = truncating(plain);
    const [view, cache, usage, codex, , now, cwd] = await Promise.all([
      ownership($),
      read($, cacheTotals),
      read($, usageFigures),
      read($, codexUsage),
      read($, ticks),
      $.clock.now(),
      $.session.cwd(),
    ]);
    const { agents, files, times } = view;
    const conflicted = conflicts(view);
    const fileRows = (owner) => (files[owner] ?? []).map((path) => (conflicted.has(path)
      ? Text({ color: "error", children: [`  ${shortPath(path, cwd)} (conflict)`] })
      : Text({ children: [`  ${shortPath(path, cwd)}`] })));
    const rows = usageRows(Text, usage, cache, codex, now);
    if (rows.length > 0) rows.push(Text({ children: [" "] }));
    if (files[MAIN] !== undefined) rows.push(Text({ children: [MAIN] }), ...fileRows(MAIN));
    for (const agent of agents) rows.push(agentRow(Box, Text, agent, times, now), ...fileRows(agent.id));
    if (agents.length === 0 && files[MAIN] === undefined) rows.push(Text({ dimColor: true, children: ["No subagents in this session."] }));
    return Box({ flexDirection: "column", children: rows });
  });
}
