import { expect, test } from "claude-code/testing";
import { responseLanguage } from "./language.js";
import { riskLevel } from "./risk.js";

const PLUGIN = "hei5enbug-agent-setup";
const SESSION = "session-test";
const RISK_FILE = `/home/test/.local/state/hei5enbug-agent-setup/approvals/risk/claude-${SESSION}.json`;
const ENV = { HOME: "/home/test" };
const RECORDS = {
  "echo write": { kind: "write", critical: false },
  "echo request": { kind: "request", critical: false },
  "echo always": { kind: "always", critical: false },
  "echo critical": { kind: "write", critical: true },
  "echo read": { kind: "read", critical: false },
};

function guardWorld(on, records, world = {}) {
  const calls = [];
  const ids = [];
  const runs = [];
  const reads = [];
  on("env.get", (_$, e) => ({ value: ENV[e.name] }));
  on("session.id", () => ({ value: SESSION }));
  on("session.cwd", () => ({ value: "/work" }));
  on("settings.read", () => ({ value: world.settings ?? {} }));
  on("classic.PreToolUse", (_$, e) => {
    const record = records[e.tool_input?.command ?? e.command];
    if (record !== undefined) calls.push({ id: e.tool_use_id, ...record });
    return {};
  });
  on("fs.read", (_$, e) => {
    reads.push(e.path);
    if (e.path === RISK_FILE && world.guardOn !== false) return { value: JSON.stringify({ calls }) };
    throw new Error(`no such file: ${e.path}`);
  });
  on("process.run", (_$, e) => {
    runs.push(e.argv);
    return { value: { exitCode: 0, stdout: world.stdout ?? "", stderr: "", isStdoutTruncated: false, isStderrTruncated: false } };
  });
  on("tool.call", (_$, e) => {
    ids.push(e.tool_use_id);
    return { result: { stdout: "", stderr: "" }, text: "" };
  });
  on("ui.render", () => ({ type: "Text", props: {}, children: ["engine row"] }));
  return { ids, runs, reads };
}

function toolUse(requestId, surface = "terminal") {
  return {
    plugin: PLUGIN,
    component: "ToolUse",
    surface,
    requestId,
    props: { tool_use_id: requestId, tool: "Bash", input: {}, isRunning: false, isErrored: false, isInterrupted: false },
  } as const;
}

async function badgeOf($, requestId, surface = "terminal") {
  const ui = await $.ui.mount(toolUse(requestId, surface));
  const badge = await ui.find({ type: "Text", text: /^\[/ });
  const engine = await ui.find({ type: "Text", text: "engine row" });
  await ui.unmount();
  return { badge, engine };
}

test("가드 기록의 kind와 critical만으로 빨간 표시, 노란 표시, 표시 없음을 고른다", () => {
  // given
  const records = [
    { kind: "always", critical: false },
    { kind: "always", critical: true },
    { kind: "write", critical: true },
    { kind: "write", critical: false },
    { kind: "request", critical: false },
    { kind: "read", critical: false },
    { kind: "pass", critical: false },
    { kind: "sensitive", critical: false },
    undefined,
    "write",
  ];

  // when
  const levels = records.map((record) => riskLevel(record));

  // then
  expect(levels).toEqual(["always", "critical", "critical", "write", "write", undefined, undefined, undefined, undefined, undefined]);
});

test("ToolUse 행은 엔진 행을 그대로 두고 옆에 쓰기는 노란 write, 매번 확인은 빨간 asks every time, 치명은 빨간 irreversible 표시를 붙인다", async ($, on) => {
  // given
  const { ids } = guardWorld(on, RECORDS);
  const commands = ["echo write", "echo request", "echo always", "echo critical"];
  for (const command of commands) await $.tool.call({ tool: "Bash", command });

  // when
  const drawn = [];
  for (const surface of ["terminal", "desktop"] as const) {
    for (const id of ids) drawn.push(await badgeOf($, id, surface));
  }

  // then
  const expected = [["[write]", "warning"], ["[write]", "warning"], ["[asks every time]", "error"], ["[irreversible]", "error"]];
  expect(drawn.map(({ badge }) => [badge?.text, badge?.props.color])).toEqual([...expected, ...expected]);
  expect(drawn.every(({ engine }) => engine !== undefined)).toBe(true);
});

test("가드 기록이 없거나 읽기로 기록된 호출, 가드가 꺼진 세션의 호출에는 표시를 붙이지 않는다", async ($, on) => {
  // given
  const { ids } = guardWorld(on, RECORDS);
  await $.tool.call({ tool: "Bash", command: "echo read" });
  await $.tool.call({ tool: "Bash", command: "ls" });

  // when
  const drawn = [await badgeOf($, ids[0]), await badgeOf($, ids[1]), await badgeOf($, "toolu_unknown")];

  // then
  expect(drawn.map(({ badge }) => badge)).toEqual([undefined, undefined, undefined]);
  expect(drawn.every(({ engine }) => engine !== undefined)).toBe(true);
});

test("승인 가드가 꺼져 기록 파일이 없으면 빨간 호출에도 표시를 붙이지 않는다", async ($, on) => {
  // given
  const { ids } = guardWorld(on, RECORDS, { guardOn: false });
  await $.tool.call({ tool: "Bash", command: "echo always" });

  // when
  const { badge, engine } = await badgeOf($, ids[0]);

  // then
  expect(badge).toBeUndefined();
  expect(engine).toBeDefined();
});

test("응답 언어 설정이 한국어면 표시 문구를 한국어로 쓴다", async ($, on) => {
  // given
  const { ids } = guardWorld(on, RECORDS, { settings: { language: "ko-KR" } });
  for (const command of ["echo write", "echo always", "echo critical"]) await $.tool.call({ tool: "Bash", command });

  // when
  const drawn = [await badgeOf($, ids[0]), await badgeOf($, ids[1]), await badgeOf($, ids[2])];

  // then
  expect(drawn.map(({ badge }) => badge?.text)).toEqual(["[쓰기]", "[매번 확인]", "[되돌릴 수 없음]"]);
});

test("응답 언어는 한국어를 뜻하는 설정값만 한국어로 읽고 그 밖의 값과 읽기 실패는 영어로 읽는다", async () => {
  // given
  const settings = (read) => ({ settings: { read } });
  const values = ["Korean", " ko ", "ko-KR", "ko_KR", "한국어", "english", "en-US", "", undefined, 3];

  // when
  const languages = [];
  for (const language of values) languages.push(await responseLanguage(settings(async () => ({ language }))));
  const failed = await responseLanguage(settings(async () => {
    throw new Error("no settings");
  }));

  // then
  expect(languages).toEqual(["Korean", "Korean", "Korean", "Korean", "Korean", "English", "English", "English", "English", "English"]);
  expect(failed).toBe("English");
});

test("접힌 ToolGroup은 표시된 호출 중 가장 위험한 표시를 붙이고 펼친 그룹은 각 행에 맡긴다", async ($, on) => {
  // given
  const { ids } = guardWorld(on, RECORDS);
  for (const command of ["echo read", "echo write", "echo always", "echo critical"]) await $.tool.call({ tool: "Bash", command });
  const calls = ids.map((id) => ({ tool_use_id: id, tool: "Bash", input: {}, isRunning: false, isErrored: false, isInterrupted: false }));
  const group = { plugin: PLUGIN, component: "ToolGroup", surface: "terminal", requestId: ids[0] } as const;

  // when
  const folded = await $.ui.mount({ ...group, props: { calls, isActive: false, isExpanded: false } });
  const foldedBadge = await folded.find({ type: "Text", text: /^\[/ });
  await folded.unmount();
  const withoutCritical = await $.ui.mount({ ...group, props: { calls: calls.slice(0, 3), isActive: false, isExpanded: false } });
  const alwaysBadge = await withoutCritical.find({ type: "Text", text: /^\[/ });
  await withoutCritical.unmount();
  const expanded = await $.ui.mount({ ...group, props: { calls, isActive: false, isExpanded: true } });
  const expandedBadge = await expanded.find({ type: "Text", text: /^\[/ });
  await expanded.unmount();

  // then
  expect([foldedBadge?.text, foldedBadge?.props.color]).toEqual(["[irreversible]", "error"]);
  expect([alwaysBadge?.text, alwaysBadge?.props.color]).toEqual(["[asks every time]", "error"]);
  expect(expandedBadge).toBeUndefined();
});

test("빨간 git reset --hard 호출은 읽기 전용 git diff로 버려질 변경을 표시 안에 보여준다", async ($, on) => {
  // given
  const { ids, runs } = guardWorld(on, { "git reset --hard": { kind: "always", critical: true } }, {
    stdout: "5\t1\ta.txt\n-\t-\tlogo.png\n",
  });
  await $.tool.call({ tool: "Bash", command: "git reset --hard" });

  // when
  const { badge } = await badgeOf($, ids[0]);

  // then
  expect(runs).toEqual([["git", "diff", "--numstat", "HEAD"], ["git", "diff", "--numstat", "--cached", "HEAD"]]);
  expect(badge?.text).toBe("[irreversible · discards 2 files (+5/-1)]");
});

test("치명은 아니지만 매번 묻는 git clean 호출도 빨간 asks every time 표시 안에 지울 경로를 보여준다", async ($, on) => {
  // given
  const { ids, runs } = guardWorld(on, { "git clean -fd": { kind: "always", critical: false } }, { stdout: "Would remove a.log\n" });
  await $.tool.call({ tool: "Bash", command: "git clean -fd" });

  // when
  const { badge } = await badgeOf($, ids[0]);

  // then
  expect(runs).toEqual([["git", "clean", "-n", "-d"]]);
  expect([badge?.text, badge?.props.color]).toEqual(["[asks every time · removes 1 path: a.log]", "error"]);
});

test("빨간 표시가 아닌 호출은 영향 미리보기 명령을 실행하지 않는다", async ($, on) => {
  // given
  const { ids, runs } = guardWorld(on, { "git reset --hard": { kind: "write", critical: false } });

  // when
  await $.tool.call({ tool: "Bash", command: "git reset --hard" });
  const { badge } = await badgeOf($, ids[0]);

  // then
  expect(runs).toEqual([]);
  expect(badge?.text).toBe("[write]");
});

test("risk_highlight 옵션이 꺼지면 기록을 읽지 않고 표시도 붙이지 않는다", { options: { risk_highlight: false } }, async ($, on) => {
  // given
  const { ids, reads } = guardWorld(on, RECORDS);
  await $.tool.call({ tool: "Bash", command: "echo always" });

  // when
  const { badge, engine } = await badgeOf($, ids[0]);

  // then
  expect(badge).toBeUndefined();
  expect(engine).toBeDefined();
  expect(reads.filter((path) => path === RISK_FILE)).toEqual([]);
});
