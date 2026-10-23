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
  const opens = [];
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
  on("ui.open", (_$, e) => {
    opens.push(e);
    return { value: { isPlaced: true } };
  });
  on("ui.panes", () => ({ value: state.panes }));
  on("session.measure", (_$, e) => ({ changed: e.changed }));
  on("classic.SessionStart", () => ({}));
  on("session.end", (_$, e) => ({ sessionId: e.sessionId ?? "session-test" }));
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
  return { toasts, registered, runs, opens, state, clock };
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

test("/clear와 /resume 뒤에는 캐시 적중률과 사용량을 비우고 다음 메인 턴 시작에 한도와 예측을 다시 채운다", async ($, on) => {
  // given
  const before = { startedAt: NOW, context: { window: 200000, tokens: 24000, percent: 12 }, rateLimits: [{ kind: "five_hour", percentUsed: 40, resetsAt: iso(NOW + 4 * HOUR) }] };
  const after = { startedAt: NOW, context: { window: 200000, tokens: 2000, percent: 1 }, rateLimits: [{ kind: "five_hour", percentUsed: 10, resetsAt: iso(NOW + 4 * HOUR) }] };
  const world = { usage: before as any };
  boardWorld(on, world);
  await $.session.start({ cwd: CWD, surface: "terminal", isInteractive: true });
  await $.turn.complete(turnEnd("main-1", undefined, usageOf(80, 10, 10)));
  const seeded = await texts($, PANE);

  // when
  world.usage = after;
  await $.session.end({ reason: "clear" });
  const cleared = await texts($, PANE);
  await $.turn.start({ turnId: "sub-1", text: "", agentId: "a1" });
  const afterSubagent = await texts($, PANE);
  await $.turn.start({ turnId: "main-2", text: "next" });
  const reseeded = await texts($, PANE);
  world.usage = before;
  await $.session.end({ reason: "resume" });
  await $.turn.start({ turnId: "main-3", text: "next" });
  const resumed = await texts($, PANE);

  // then
  expect(seeded[0].text).toBe("context 12% · cache hit 80%");
  expect(cleared[0].text).toBe("No subagents in this session.");
  expect(afterSubagent[0].text).toBe("No subagents in this session.");
  expect(reseeded[0].text).toBe("context 1%");
  expect(reseeded[1].text).toBe("Claude 5h 10% · on track");
  expect(resumed[0].text).toBe("context 12%");
});

test("session.end가 다른 사유로 오면 사용량을 비우지 않고 session.start가 처음 사용량을 채운다", async ($, on) => {
  // given
  const usage = { startedAt: NOW, context: { window: 200000, tokens: 24000, percent: 12 }, rateLimits: [] };
  boardWorld(on, { usage });
  await $.session.start({ cwd: CWD, surface: "terminal", isInteractive: true });

  // when
  await $.session.end({ reason: "logout" });
  const pane = await texts($, PANE);

  // then
  expect(pane[0].text).toBe("context 12%");
});

test("사용량을 읽지 못해도 시작과 메인 턴 시작은 실패하지 않고 읽을 수 있게 되면 다음 메인 턴 시작에 채운다", async ($, on) => {
  // given
  const world = { usage: undefined as any };
  boardWorld(on, world);
  await $.session.start({ cwd: CWD, surface: "terminal", isInteractive: true });
  await $.turn.start({ turnId: "main-1", text: "go" });
  const missing = await texts($, PANE);

  // when
  world.usage = { startedAt: NOW, context: { window: 200000, tokens: 24000, percent: 12 }, rateLimits: [] };
  await $.turn.start({ turnId: "main-2", text: "go" });
  const found = await texts($, PANE);

  // then
  expect(missing[0].text).toBe("No subagents in this session.");
  expect(found[0].text).toBe("context 12%");
});

test("classic.SessionStart 훅은 등록하지 않아 /clear 뒤에도 엔진 이벤트만 지나간다", async ($, on) => {
  // given
  const usage = { startedAt: NOW, context: { window: 200000, tokens: 24000, percent: 12 }, rateLimits: [] };
  boardWorld(on, { usage });

  // when
  const answer = await $.classic.SessionStart({ source: "clear" });
  const pane = await texts($, PANE);

  // then
  expect(answer).toEqual({});
  expect(pane[0].text).toBe("No subagents in this session.");
});

test("/work-board는 창 너비를 40칸으로 요청하고 다른 크기 옵션은 넘기지 않는다", async ($, on) => {
  // given
  const { opens } = boardWorld(on);

  // when
  await $.command.run({ command: "work-board", args: "" });

  // then
  expect(opens).toEqual([{ id: "work-board", title: "Work board", columns: 40 }]);
});

test("띠는 평소에도 컨텍스트, 캐시, Claude 5시간과 주간, Codex 사용률을 한 줄로 보이고 예측이 막히는 한도만 경고 색으로 칠한다", async ($, on) => {
  // given
  const usage = {
    startedAt: NOW,
    context: { window: 200000, tokens: 24000, percent: 34 },
    rateLimits: [
      { kind: "five_hour", percentUsed: 10, resetsAt: iso(NOW + 4 * HOUR) },
      { kind: "seven_day", percentUsed: 80, resetsAt: iso(NOW + 3.5 * DAY) },
      { kind: "spend_limit", percentUsed: 50, resetsAt: iso(NOW + HOUR) },
    ],
  };
  const { clock } = boardWorld(on, { usage, codex: '{"weekly_used_percent": 51.2}' });
  await $.session.start({ cwd: CWD, surface: "terminal", isInteractive: true });
  await $.turn.complete(turnEnd("main-1", undefined, usageOf(920, 40, 40)));
  await clock.settle();

  // when
  const band = await texts($, BAND);

  // then
  expect(band.map((item) => [item.text, item.props.color])).toEqual([
    ["ctx 34%", undefined],
    [" · cache 92%", undefined],
    [" · 5h 10%", undefined],
    [" · wk 80%", "warning"],
    [" · Codex 51%", undefined],
    ["engine band", undefined],
  ]);
  expect(band.slice(0, 5).map((item) => item.text).join("").length).toBeLessThan(60);
});

test("띠는 알려진 값만 줄이고 parallel과 conflict는 0이 아닐 때만 덧붙이며 서베이 중에는 건드리지 않는다", async ($, on) => {
  // given
  const usage = { startedAt: NOW, context: { window: 200000, tokens: 1, percent: 5 }, rateLimits: [] };
  boardWorld(on, { usage, agents: [agent("a1"), agent("a2")] });
  await $.session.start({ cwd: CWD, surface: "terminal", isInteractive: true });
  await $.tool.call({ tool: "Edit", file_path: `${CWD}/src/app.ts`, old_string: "a", new_string: "b", agentId: "a1" });
  await $.tool.call({ tool: "Edit", file_path: `${CWD}/src/app.ts`, old_string: "b", new_string: "c", agentId: "a2" });

  // when
  const band = await texts($, BAND);
  const survey = await texts($, { ...BAND, props: { ...BAND.props, hasSurvey: true } });

  // then
  expect(band.map((item) => [item.text, item.props.color])).toEqual([
    ["ctx 5%", undefined],
    [" · parallel 2", undefined],
    [" · conflict 1", "error"],
    ["engine band", undefined],
  ]);
  expect(survey.map((item) => item.text)).toEqual(["engine band"]);
});

test("띠는 bodyColumns에 맞춰 우선순위가 낮은 항목부터 덜어내고 conflict와 parallel을 남기며 넓으면 모두 보인다", async ($, on) => {
  // given
  const usage = {
    startedAt: NOW,
    context: { window: 200000, tokens: 24000, percent: 34 },
    rateLimits: [
      { kind: "five_hour", percentUsed: 10, resetsAt: iso(NOW + 4 * HOUR) },
      { kind: "seven_day", percentUsed: 80, resetsAt: iso(NOW + 3.5 * DAY) },
    ],
  };
  const { clock } = boardWorld(on, { usage, codex: '{"weekly_used_percent": 51.2}', agents: [agent("a1"), agent("a2")] });
  await $.session.start({ cwd: CWD, surface: "terminal", isInteractive: true });
  await $.turn.complete(turnEnd("main-1", undefined, usageOf(920, 40, 40)));
  await clock.settle();
  await $.tool.call({ tool: "Edit", file_path: `${CWD}/src/app.ts`, old_string: "a", new_string: "b", agentId: "a1" });
  await $.tool.call({ tool: "Edit", file_path: `${CWD}/src/app.ts`, old_string: "b", new_string: "c", agentId: "a2" });
  const at = async (bodyColumns) => {
    const found = await texts($, { ...BAND, props: { ...BAND.props, bodyColumns } });
    return found.filter((item) => item.text !== "engine band");
  };

  // when
  const narrow = await at(30);
  const medium = await at(40);
  const wide = await at(80);

  // then
  const width = (items) => items.map((item) => item.text).join("").length;
  expect(narrow.map((item) => item.text)).toEqual(["parallel 2", " · conflict 1"]);
  expect(width(narrow)).toBeLessThanOrEqual(30);
  expect(medium.map((item) => item.text)).toEqual(["ctx 34%", " · parallel 2", " · conflict 1"]);
  expect(width(medium)).toBeLessThanOrEqual(40);
  expect(wide.map((item) => item.text)).toEqual(["ctx 34%", " · cache 92%", " · 5h 10%", " · wk 80%", " · Codex 51%", " · parallel 2", " · conflict 1"]);
  expect(narrow.every((item) => item.props.wrap === "truncate-end")).toBe(true);
});

test("표시할 값이 없으면 띠는 다른 Mod의 출력만 남긴다", async ($, on) => {
  // given
  boardWorld(on);

  // when
  const band = await texts($, BAND);

  // then
  expect(band.map((item) => item.text)).toEqual(["engine band"]);
});

test("메인 턴이 끝나면 Codex 사용률을 기다리지 않고 새로 읽되 하위 에이전트의 턴과 5분 안의 턴은 다시 읽지 않는다", async ($, on) => {
  // given
  const { runs, clock } = boardWorld(on, { codex: '{"weekly_used_percent": 30}' });

  // when
  await $.turn.complete(turnEnd("sub-1", "a1"));
  await clock.settle();
  const afterSubagent = runs.length;
  await $.turn.complete(turnEnd("main-1"));
  await clock.settle();
  const afterMain = runs.length;
  await $.turn.complete(turnEnd("main-2"));
  await clock.settle();
  const withinTtl = runs.length;
  await clock.advance(5 * 60 * 1000);
  await $.turn.complete(turnEnd("main-3"));
  await clock.settle();
  const band = await texts($, BAND);

  // then
  expect([afterSubagent, afterMain, withinTtl, runs.length]).toEqual([0, 1, 1, 2]);
  expect(band.map((item) => item.text)).toEqual(["Codex 30%", "engine band"]);
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
