import { expect, mock, test } from "claude-code/testing";
import { forecast, hitRate, normalizedPath, roughly } from "./board.js";

const PLUGIN = "hei5enbug-agent-setup";
const HOUR = 60 * 60 * 1000;
const DAY = 24 * HOUR;
const NOW = Date.parse("2026-10-22T00:00:00Z");
const CWD = "/work";
const PANE = {
  plugin: PLUGIN,
  component: "Pane",
  requestId: "work-board",
  props: { title: "Work board", isFocused: false, bodyColumns: 60, placement: "dock", scroll: { offset: 0, bodyRows: 30 }, view: {} },
} as const;
const BAND = {
  plugin: PLUGIN,
  component: "AbovePrompt",
  requestId: "above-prompt",
  props: { hasSurvey: false, isWorking: true, maxRows: 10, bodyColumns: 80, scroll: { offset: 0, bodyRows: 10 }, view: {} },
} as const;

function iso(ms) {
  return new Date(ms).toISOString();
}

function agent(id, status = "running", type = "hei5enbug-agent-setup:worker") {
  return { id, status, type, description: `task ${id}` };
}

function boardWorld(on, world = {}) {
  const toasts = [];
  const registered = [];
  const runs = [];
  const state = { agents: world.agents ?? [], panes: [{ id: "work-board", title: "Work board", isShown: true, isFocused: false, isPlaced: true }], lists: 0 };
  const clock = mock.clock(on, { now: NOW });
  on("agent.list", () => {
    state.lists += 1;
    return { value: state.agents };
  });
  on("store.get", () => ({ value: undefined }));
  on("fs.stat", (_$, e) => ({ value: { kind: "file", size: 1, mtimeMs: 0, isLink: false, realPath: world.realPaths?.[e.path] ?? e.path } }));
  on("session.id", () => ({ value: "session-test" }));
  on("session.cwd", () => ({ value: CWD }));
  on("session.usage", () => (world.usage === undefined ? { deny: "no usage" } : { value: world.usage }));
  on("ui.toast", (_$, e) => {
    toasts.push(e.text);
    return { value: undefined };
  });
  on("ui.open", () => ({ value: { isPlaced: true } }));
  on("ui.panes", () => ({ value: state.panes }));
  on("session.measure", (_$, e) => ({ changed: e.changed }));
  on("classic.SessionStart", () => ({}));
  on("command.register", (_$, e) => {
    registered.push(e.name);
    return { value: undefined };
  });
  on("process.run", (_$, e) => {
    runs.push(e.argv);
    return { value: { exitCode: 0, stdout: world.codex ?? "", stderr: "", isStdoutTruncated: false, isStderrTruncated: false } };
  });
  on("session.start", (_$, e) => ({ cwd: e.cwd }));
  on("turn.start", (_$, e) => ({ turnId: e.turnId }));
  on("turn.complete", () => ({ text: "" }));
  on("command.run", () => ({ text: "engine command" }));
  on("tool.call", () => ({ result: { type: "update", filePath: "", content: "" }, text: "ok" }));
  on("ui.render", () => ({ type: "Text", props: {}, children: ["engine band"] }));
  return { toasts, registered, runs, state, clock };
}

function turnEnd(turnId, agentId = undefined, usage = null) {
  return { turnId, answer: "", durationMs: 1, isAborted: false, reason: "answer", usage, ...(agentId === undefined ? {} : { agentId }) };
}

function usageOf(read, creation, input) {
  return { input_tokens: input, output_tokens: 1, cache_read_input_tokens: read, cache_creation_input_tokens: creation, model: "claude-opus-5-5" };
}

async function texts($, target) {
  const ui = await $.ui.mount({ ...target, surface: "terminal" });
  const found = await ui.findAll({ type: "Text" });
  await ui.unmount();
  return found;
}

test("한도 소진 예측은 사용률을 경과한 창 비율과 비교해 재설정 전에 100%에 닿을 때만 남은 시간을 낸다", () => {
  // given
  const weekly = { kind: "seven_day", percentUsed: 80, resetsAt: iso(NOW + 3.5 * DAY) };
  const fiveHour = { kind: "five_hour", percentUsed: 10, resetsAt: iso(NOW + 4 * HOUR) };
  const unknown = [{ kind: "spend_limit", percentUsed: 50, resetsAt: iso(NOW + HOUR) }, { kind: "seven_day", percentUsed: 50 }];

  // when
  const runsOut = forecast(weekly, NOW);
  const onTrack = forecast(fiveHour, NOW);
  const skipped = unknown.map((limit) => forecast(limit, NOW));

  // then
  expect(runsOut).toEqual({ isOnTrack: false, runsOutInMs: 21 * HOUR });
  expect(roughly(runsOut.runsOutInMs)).toBe("~21h");
  expect(onTrack).toEqual({ isOnTrack: true });
  expect(skipped).toEqual([undefined, undefined]);
});

test("캐시 적중률은 cache_read를 cache_read, cache_creation, input의 합으로 나눈 백분율이고 토큰이 없으면 없다", () => {
  // given
  const totals = [{ read: 900, creation: 60, input: 40 }, { read: 0, creation: 0, input: 0 }];

  // when
  const rates = totals.map((value) => hitRate(value));

  // then
  expect(rates).toEqual([90, undefined]);
});

test("서로 다른 두 하위 에이전트가 같은 파일을 고치면 파일을 빨갛게 표시하고 그 파일마다 토스트를 한 번 띄운다", async ($, on) => {
  // given
  const { toasts } = boardWorld(on, { agents: [agent("a1"), agent("a2", "running", "hei5enbug-agent-setup:sonnet-worker")] });
  await $.tool.call({ tool: "Edit", file_path: `${CWD}/src/app.ts`, old_string: "a", new_string: "b", agentId: "a1" });
  await $.tool.call({ tool: "Write", file_path: `${CWD}/src/only-a1.ts`, content: "x", agentId: "a1" });

  // when
  await $.tool.call({ tool: "Edit", file_path: `${CWD}/src/app.ts`, old_string: "b", new_string: "c", agentId: "a2" });
  await $.tool.call({ tool: "Edit", file_path: `${CWD}/src/app.ts`, old_string: "c", new_string: "d", agentId: "a1" });
  const pane = await texts($, PANE);
  const band = await texts($, BAND);

  // then
  expect(toasts).toEqual(["Edit conflict: src/app.ts (hei5enbug-agent-setup:worker, hei5enbug-agent-setup:sonnet-worker)"]);
  expect(pane.filter((item) => item.text.includes("(conflict)")).map((item) => [item.text, item.props.color])).toEqual([
    ["  src/app.ts (conflict)", "error"],
    ["  src/app.ts (conflict)", "error"],
  ]);
  expect(pane.some((item) => item.text === "  src/only-a1.ts")).toBe(true);
  expect(band.map((item) => item.text)).toEqual(["parallel 2", " · conflict 1", "engine band"]);
});

test("파일 경로는 작업 폴더 기준 절대 경로로 바꾸고 . 과 .. 을 접는다", () => {
  // given
  const paths = ["src/app.ts", "/work/./lib/../src/app.ts", "../other/x.ts", "/a//b/./c"];

  // when
  const normalized = paths.map((path) => normalizedPath(path, CWD));

  // then
  expect(normalized).toEqual(["/work/src/app.ts", "/work/src/app.ts", "/other/x.ts", "/a/b/c"]);
});

test("상대 경로, . 과 .. 이 섞인 경로, 심볼릭 링크 경로도 같은 파일이면 같은 파일로 보고 충돌을 찾는다", async ($, on) => {
  // given
  const { toasts } = boardWorld(on, {
    agents: [agent("a1"), agent("a2"), agent("a3")],
    realPaths: { "/work/link/app.ts": "/work/src/app.ts" },
  });
  await $.tool.call({ tool: "Edit", file_path: "src/app.ts", old_string: "a", new_string: "b", agentId: "a1" });

  // when
  await $.tool.call({ tool: "Edit", file_path: "/work/./lib/../src/app.ts", old_string: "b", new_string: "c", agentId: "a2" });
  await $.tool.call({ tool: "Write", file_path: "/work/link/app.ts", content: "x", agentId: "a3" });
  const pane = await texts($, PANE);

  // then
  expect(toasts).toEqual(["Edit conflict: src/app.ts (hei5enbug-agent-setup:worker, hei5enbug-agent-setup:worker)"]);
  expect(pane.filter((item) => item.text === "  src/app.ts (conflict)").length).toBe(3);
});

test("메인 대화는 턴이 도는 동안에만 활성 소유자라서 턴 중 겹친 편집만 충돌이고 턴이 끝난 뒤 백그라운드 편집은 충돌이 아니다", async ($, on) => {
  // given
  const { toasts } = boardWorld(on, { agents: [agent("a1")] });
  await $.turn.start({ turnId: "main-1", text: "go" });
  await $.tool.call({ tool: "Edit", file_path: `${CWD}/during.ts`, old_string: "a", new_string: "b" });
  await $.tool.call({ tool: "Write", file_path: `${CWD}/after.ts`, content: "x" });

  // when
  await $.tool.call({ tool: "Edit", file_path: `${CWD}/during.ts`, old_string: "b", new_string: "c", agentId: "a1" });
  const duringTurn = await texts($, BAND);
  await $.turn.complete(turnEnd("main-1"));
  await $.tool.call({ tool: "Edit", file_path: `${CWD}/after.ts`, old_string: "x", new_string: "y", agentId: "a1" });
  const afterTurn = await texts($, BAND);

  // then
  expect(toasts).toEqual(["Edit conflict: during.ts (main, hei5enbug-agent-setup:worker)"]);
  expect(duringTurn.map((item) => item.text)).toEqual(["parallel 1", " · conflict 1", "engine band"]);
  expect(afterTurn.map((item) => item.text)).toEqual(["parallel 1", "engine band"]);
});

test("끝난 하위 에이전트가 고친 파일은 충돌로 보지 않는다", async ($, on) => {
  // given
  const { toasts } = boardWorld(on, { agents: [agent("a1", "completed"), agent("a2")] });
  await $.tool.call({ tool: "Edit", file_path: `${CWD}/src/app.ts`, old_string: "a", new_string: "b", agentId: "a1" });

  // when
  await $.tool.call({ tool: "Edit", file_path: `${CWD}/src/app.ts`, old_string: "b", new_string: "c", agentId: "a2" });
  const band = await texts($, BAND);

  // then
  expect(toasts).toEqual([]);
  expect(band.map((item) => item.text)).toEqual(["parallel 1", "engine band"]);
});

test("하위 에이전트의 턴 시작과 끝은 메인 대화가 고친 파일과 캐시 적중률을 바꾸지 않고 메인 턴 시작만 메인 목록을 비운다", async ($, on) => {
  // given
  boardWorld(on, { agents: [agent("a1")] });
  await $.session.measure({ context: { window: 200000, tokens: 24000, percent: 12 }, rateLimits: [], changed: ["context"] });
  await $.turn.complete(turnEnd("main-1", undefined, usageOf(80, 10, 10)));
  await $.tool.call({ tool: "Edit", file_path: `${CWD}/README.md`, old_string: "a", new_string: "b" });

  // when
  await $.turn.start({ turnId: "sub-1", text: "", agentId: "a1" });
  await $.turn.complete(turnEnd("sub-1", "a1", usageOf(0, 500, 500)));
  const afterSubagent = await texts($, PANE);
  await $.turn.start({ turnId: "main-2", text: "next" });
  const afterMain = await texts($, PANE);

  // then
  expect(afterSubagent.some((item) => item.text === "  README.md")).toBe(true);
  expect(afterSubagent[0].text).toBe("context 12% · cache hit 80%");
  expect(afterMain.some((item) => item.text === "  README.md")).toBe(false);
});

test("하위 에이전트가 없고 충돌도 없으면 띠에는 다른 Mod의 출력만 남긴다", async ($, on) => {
  // given
  boardWorld(on, { agents: [agent("a1", "completed")] });

  // when
  const band = await texts($, BAND);

  // then
  expect(band.map((item) => item.text)).toEqual(["engine band"]);
});

test("/work-board는 창을 열고 에이전트 상태와 경과 시간, Claude 한도 예측, Codex 주간 사용률, 캐시 적중률을 보여준다", async ($, on) => {
  // given
  const usage = {
    startedAt: NOW,
    context: { window: 200000, tokens: 24000, percent: 12 },
    rateLimits: [
      { kind: "five_hour", percentUsed: 10, resetsAt: iso(NOW + 4 * HOUR) },
      { kind: "seven_day", percentUsed: 80, resetsAt: iso(NOW + 3.5 * DAY) },
    ],
  };
  const { registered, runs, clock } = boardWorld(on, { agents: [agent("a1"), agent("a2", "failed")], usage, codex: '{"weekly_used_percent": 42.4}' });
  await $.session.start({ cwd: CWD, surface: "terminal", isInteractive: true });
  await $.turn.complete(turnEnd("main-1", undefined, usageOf(300, 50, 50)));
  await $.turn.start({ turnId: "sub-1", text: "", agentId: "a1" });
  await clock.advance(65 * 1000);

  // when
  const answer = await $.command.run({ command: "work-board", args: "" });
  const pane = await texts($, PANE);

  // then
  expect(registered).toEqual(["work-board"]);
  expect(answer.text).toBeUndefined();
  expect(runs.length).toBe(1);
  expect([runs[0][0], runs[0][1].endsWith("/scripts/hook_python.sh"), runs[0][2]]).toEqual(["sh", true, "codex_usage.py"]);
  expect(pane.map((item) => [item.text, item.props.color ?? (item.props.dimColor ? "dim" : undefined)]).slice(0, 3)).toEqual([
    ["context 12% · cache hit 75% · Codex weekly 42%", undefined],
    ["Claude 5h 10% · on track", "dim"],
    ["Claude weekly 80% · runs out in ~21h, before reset", "warning"],
  ]);
  expect(pane.map((item) => item.text)).toContain("1m 05s");
  expect(pane.filter((item) => ["running", "failed"].includes(item.text)).map((item) => [item.text, item.props.color])).toEqual([
    ["running", "suggestion"],
    ["failed", "error"],
  ]);
});

test("열린 창은 다시 마운트하지 않아도 상태가 바뀌면 새 편집 파일을 그린다", async ($, on) => {
  // given
  boardWorld(on, { agents: [agent("a1")] });
  const ui = await $.ui.mount({ ...PANE, surface: "terminal" });
  const before = await ui.find({ type: "Text", text: "src/new.ts" });

  // when
  await $.tool.call({ tool: "Write", file_path: `${CWD}/src/new.ts`, content: "x", agentId: "a1" });
  const after = await ui.find({ type: "Text", text: "src/new.ts" });
  await ui.unmount();

  // then
  expect(before).toBeUndefined();
  expect(after?.text).toBe("  src/new.ts");
});

test("5초 갱신은 창이 열려 있고 활성 하위 에이전트가 있을 때만 경과 시간을 다시 그리고 창이 닫히면 멈춘다", async ($, on) => {
  // given
  const { state, clock } = boardWorld(on, { agents: [agent("a1")], codex: '{"weekly_used_percent": 10}' });
  await $.turn.start({ turnId: "sub-1", text: "", agentId: "a1" });
  await $.command.run({ command: "work-board", args: "" });
  const ui = await $.ui.mount({ ...PANE, surface: "terminal" });
  const first = await ui.find({ type: "Text", text: /^\d+s$/ });

  // when
  await clock.advance(5000);
  const second = await ui.find({ type: "Text", text: /^\d+s$/ });
  state.panes = [];
  await clock.advance(5000);
  const listsAfterClose = state.lists;
  await clock.advance(20000);
  await ui.unmount();

  // then
  expect([first?.text, second?.text]).toEqual(["0s", "5s"]);
  expect(state.lists).toBe(listsAfterClose);
});

test("/clear 뒤에는 초기화된 상태에 Claude 한도와 예측을 다시 채운다", async ($, on) => {
  // given
  const usage = { startedAt: NOW, context: { window: 200000 }, rateLimits: [{ kind: "five_hour", percentUsed: 10, resetsAt: iso(NOW + 4 * HOUR) }] };
  boardWorld(on, { usage });

  // when
  await $.classic.SessionStart({ source: "clear" });
  const pane = await texts($, PANE);

  // then
  expect(pane[0].text).toBe("Claude 5h 10% · on track");
});

test("work_board 옵션이 꺼지면 명령을 등록하지 않고 하위 에이전트가 돌아도 띠를 그리지 않는다", { options: { work_board: false } }, async ($, on) => {
  // given
  const { registered } = boardWorld(on, { agents: [agent("a1")] });

  // when
  await $.session.start({ cwd: CWD, surface: "terminal", isInteractive: true });
  const answer = await $.command.run({ command: "work-board", args: "" });
  const band = await texts($, BAND);

  // then
  expect(registered).toEqual([]);
  expect(answer.text).toBe("engine command");
  expect(band.map((item) => item.text)).toEqual(["engine band"]);
});
