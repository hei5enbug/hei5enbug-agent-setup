import { atom, memberOf, read, update } from "claude-code";
import { impactOf } from "./impact.js";
import { responseLanguage } from "./language.js";

const GUARD_TOOLS = /^(Bash|Read|Edit|Write|MultiEdit|NotebookEdit|apply_patch|mcp__.*)$/;
const LABELS = {
  English: { critical: "irreversible", always: "asks every time", write: "write" },
  Korean: { critical: "되돌릴 수 없음", always: "매번 확인", write: "쓰기" },
};
const COLORS = { critical: "error", always: "error", write: "warning" };
const SEVERITY = ["critical", "always", "write"];
const riskMarks = atom({ plugin: "hei5enbug-agent-setup", key: "riskMarks" }, null);

let language;

function isRecord(value) {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

export function riskLevel(record) {
  if (!isRecord(record)) return undefined;
  if (record.critical === true) return "critical";
  if (record.kind === "always") return "always";
  return record.kind === "write" || record.kind === "request" ? "write" : undefined;
}

async function guardRecord($, toolUseId) {
  try {
    const state = (await $.env.get("XDG_STATE_HOME")) || `${(await $.env.get("HOME")) ?? ""}/.local/state`;
    const data = JSON.parse(await $.fs.read(`${state}/hei5enbug-agent-setup/approvals/risk/claude-${await $.session.id()}.json`));
    return Array.isArray(data?.calls) ? data.calls.find((call) => isRecord(call) && call.id === toolUseId) : undefined;
  } catch {
    return undefined;
  }
}

async function capture($, e) {
  const mark = memberOf(riskMarks, { requestId: e.tool_use_id });
  if ((await read($, mark)) !== null) return;
  const level = riskLevel(await guardRecord($, e.tool_use_id));
  if (level === undefined) return;
  language ??= await responseLanguage($);
  const impact = level === "write" ? undefined : await impactOf($, e.tool, e.input, language);
  await update($, mark, () => ({ level, label: LABELS[language][level], impact: impact ?? null }));
}

function badge($, e, theirs, mark) {
  const { Box, Text } = $.ui.resolve(e);
  const color = COLORS[mark.level];
  const label = Box({ flexShrink: 0, children: [Text({ color, wrap: "truncate-end", children: [`[${mark.label}]`] })] });
  const head = Box({ flexDirection: "row", columnGap: 1, children: [theirs, label] });
  const impact = mark.impact === null ? [] : [Text({ color, wrap: "truncate-end", children: [`  ${mark.impact}`] })];
  return Box({ flexDirection: "column", children: [head, ...impact] });
}

export function registerRiskHighlight(on) {
  on("tool.check", { tool: GUARD_TOOLS }, async ($, e, next) => {
    const decided = await next(e);
    if (typeof e.tool_use_id === "string") await capture($, e);
    return decided;
  }).catch(($, e, next) => next(e));

  on("ui.render", { component: "ToolUse" }, async ($, e, next) => {
    const mark = await read($, memberOf(riskMarks, e));
    return mark === null ? next(e) : badge($, e, await next(e), mark);
  });

  on("ui.render", { component: "ToolGroup" }, async ($, e, next) => {
    if (e.props.isExpanded) return next(e);
    const ids = e.props.calls.map((call) => call.tool_use_id).filter((id) => typeof id === "string");
    const found = (await Promise.all(ids.map((id) => read($, memberOf(riskMarks, { requestId: id }))))).filter(Boolean);
    const mark = SEVERITY.map((level) => found.find((item) => item.level === level)).find(Boolean);
    return mark === undefined ? next(e) : badge($, e, await next(e), mark);
  });
}
