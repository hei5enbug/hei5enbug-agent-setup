import { expect, mock, test } from "claude-code/testing";
import { enabled } from "./register.js";

const WORKER = "hei5enbug-agent-setup:worker";
const SCOUT = "hei5enbug-agent-setup:scout";
const RESEARCHER = "hei5enbug-agent-setup:researcher";
const PINNED = "claude-sonnet-5-5";
const SESSION = "session-test";
const DAY = 24 * 60 * 60 * 1000;
const NOW = 10 * DAY;

function environment(on, roles = undefined) {
  const data = roles === undefined ? {} : { roles };
  on("store.get", (_$, e) => ({ value: data[e.key] }));
  on("store.set", (_$, e) => {
    data[e.key] = JSON.parse(JSON.stringify(e.value));
    return { value: undefined };
  });
  on("session.id", () => ({ value: SESSION }));
  mock.clock(on, { now: NOW });
  return data;
}

function spawnInput(subagentType, extra = {}) {
  return {
    tool_use_id: "toolu_spawn",
    prompt: "작업",
    description: "작업",
    subagentType,
    provider: { plugin: "hei5enbug-agent-setup", tier: "user" },
    parentModel: "claude-opus-5-5",
    background: false,
    fork: false,
    ...extra,
  };
}

function offerInput(agent, source = "plugin") {
  return { agent, description: "설명", source, provider: { plugin: "engine", tier: "core" } };
}

function entry(agentId, extra = {}) {
  return { agentId, role: "worker", model: PINNED, effort: "high", toolUseId: "toolu_main", time: NOW, ...extra };
}

function stepSink(on, seen, usageModel = PINNED) {
  on("turn.step", async function* (_$, e) {
    seen.push({ model: e.model, effort: e.effort, agentId: e.agentId });
    yield { kind: "text", index: 0, text: "완료" };
    const usage = usageModel === null ? null : { input_tokens: 1, output_tokens: 1, cache_read_input_tokens: 0, cache_creation_input_tokens: 0, model: usageModel };
    yield { kind: "stop", stopReason: "end_turn", usage };
    return { turnId: e.turnId, index: e.index, answer: "완료", toolUses: [], stopReason: "end_turn", usage };
  });
}

async function step($, request) {
  const chunks = [];
  const stream = $.turn.step({ turnId: "turn-1", index: 0, messageCount: 1, model: "claude-opus-5-5", ...request });
  for (;;) {
    const next = await stream.next();
    if (next.done) return { chunks, result: next.value };
    chunks.push(next.value);
  }
}

test("내장 에이전트 네 종류는 제안 목록에서 숨기고 나머지는 그대로 제안한다", async ($, on) => {
  // given
  on("agent.offer", () => ({ isOffered: true }));
  const hidden = ["general-purpose", "Explore", "Plan", "claude", "explore", "PLAN"];
  const offered = ["claude-code-guide", "statusline-setup", SCOUT, "tradlinx-agent-setup:pr-review-gate-reader", "reviewer"];

  // when
  const hiddenResults = [];
  for (const agent of hidden) hiddenResults.push(await $.agent.offer(offerInput(agent, "built-in")));
  const offeredResults = [];
  for (const agent of offered) offeredResults.push(await $.agent.offer(offerInput(agent)));

  // then
  expect(hiddenResults.map((result) => result.isOffered)).toEqual(hidden.map(() => false));
  expect(offeredResults.map((result) => result.isOffered)).toEqual(offered.map(() => true));
});

test("fork 호출은 거부하고 fork가 아닌 호출은 그대로 시작한다", async ($, on) => {
  // given
  environment(on);
  on("agent.spawn", () => ({ model: "inherited", agentId: "agent-1" }));

  // when
  const forked = await $.agent.spawn(spawnInput("fork", { fork: true }));
  const plain = await $.agent.spawn(spawnInput("reviewer"));

  // then
  expect(typeof forked.deny).toBe("string");
  expect(forked.agentId).toBeUndefined();
  expect(plain).toEqual({ model: "inherited", agentId: "agent-1" });
});

test("내장 에이전트 이름으로 해석된 시작은 대소문자와 관계없이 거부한다", async ($, on) => {
  // given
  environment(on);
  on("agent.spawn", () => ({ model: "inherited", agentId: "agent-1" }));
  const names = ["general-purpose", "Explore", "Plan", "claude", "EXPLORE"];

  // when
  const denied = [];
  for (const name of names) denied.push(await $.agent.spawn(spawnInput(name)));
  const allowed = [];
  for (const name of ["claude-code-guide", "statusline-setup", "reviewer"]) allowed.push(await $.agent.spawn(spawnInput(name)));

  // then
  for (const result of denied) {
    expect(result.agentId).toBeUndefined();
    expect(result.deny).toContain("disabled while hei5enbug-agent-setup is installed");
    expect(result.deny).toContain("hei5enbug-agent-setup:scout");
  }
  expect(allowed.map((result) => result.agentId)).toEqual(["agent-1", "agent-1", "agent-1"]);
});

test("subagent_type을 생략한 호출은 general-purpose로 해석되어 시작 단계에서 거부한다", async ($, on) => {
  // given
  environment(on);
  on("agent.spawn", () => ({ model: "inherited", agentId: "agent-1" }));
  const resolved = spawnInput("general-purpose", { description: "종류를 생략한 호출" });

  // when
  const result = await $.agent.spawn(resolved);

  // then
  expect(result.agentId).toBeUndefined();
  expect(result.deny).toContain("built-in agent is disabled");
});

test("agent_guard 옵션이 꺼지면 내장 에이전트를 숨기지도 fork를 거부하지도 않는다", { options: { agent_guard: false } }, async ($, on) => {
  // given
  environment(on);
  on("agent.offer", () => ({ isOffered: true }));
  on("agent.spawn", () => ({ model: "inherited", agentId: "agent-1" }));

  // when
  const offer = await $.agent.offer(offerInput("Plan", "built-in"));
  const spawn = await $.agent.spawn(spawnInput("fork", { fork: true }));
  const builtIn = await $.agent.spawn(spawnInput("general-purpose"));

  // then
  expect(offer.isOffered).toBe(true);
  expect(spawn.agentId).toBe("agent-1");
  expect(builtIn.agentId).toBe("agent-1");
});

test("agent_guard 옵션이 켜져 있어도 role_pinning 옵션이 꺼지면 모델 고정만 빠진다", { options: { role_pinning: false } }, async ($, on) => {
  // given
  const data = environment(on);
  on("agent.offer", () => ({ isOffered: true }));
  on("agent.spawn", (_$, e) => ({ model: e.model ?? "inherited", agentId: "agent-1" }));

  // when
  const offer = await $.agent.offer(offerInput("Plan", "built-in"));
  const forked = await $.agent.spawn(spawnInput("fork", { fork: true }));
  const spawn = await $.agent.spawn(spawnInput(WORKER));

  // then
  expect(offer.isOffered).toBe(false);
  expect(typeof forked.deny).toBe("string");
  expect(spawn.model).toBe("inherited");
  expect(data.roles).toBeUndefined();
});

test("토글 값은 undefined와 true만 켜짐이고 false, 0, off, no는 대소문자와 공백을 무시하고 꺼짐이다", async () => {
  // given
  const on = [undefined, null, true, "", "on", "true", "1", "yes", "maybe"];
  const off = [false, 0, "false", "FALSE", "0", "off", "Off", " no ", "NO"];

  // when
  const onResults = on.map((value) => enabled(value));
  const offResults = off.map((value) => enabled(value));

  // then
  expect(onResults).toEqual(on.map(() => true));
  expect(offResults).toEqual(off.map(() => false));
});

test("고정 역할을 시작하면 모델을 고정해 넘기고 에이전트 기록을 세션별로 남긴다", async ($, on) => {
  // given
  const data = environment(on);
  const received = [];
  on("agent.spawn", (_$, e) => {
    received.push({ type: e.subagentType, model: e.model });
    return { model: e.model, agentId: `agent-${received.length}` };
  });

  // when
  const results = [];
  for (const [index, type] of [WORKER, SCOUT, RESEARCHER].entries()) {
    results.push(await $.agent.spawn(spawnInput(type, { model: "haiku", tool_use_id: `toolu_${index}` })));
  }

  // then
  expect(received.map((item) => item.model)).toEqual([PINNED, PINNED, PINNED]);
  expect(results.map((result) => result.agentId)).toEqual(["agent-1", "agent-2", "agent-3"]);
  expect(data.roles[SESSION]).toEqual([
    { agentId: "agent-1", role: "worker", model: PINNED, effort: "high", toolUseId: "toolu_0", time: NOW },
    { agentId: "agent-2", role: "scout", model: PINNED, effort: "medium", toolUseId: "toolu_1", time: NOW },
    { agentId: "agent-3", role: "researcher", model: PINNED, effort: "medium", toolUseId: "toolu_2", time: NOW },
  ]);
});

test("나란히 시작한 고정 역할의 기록은 서로 덮어쓰지 않는다", async ($, on) => {
  // given
  const data = environment(on);
  let count = 0;
  on("agent.spawn", (_$, e) => ({ model: e.model, agentId: `agent-${++count}` }));

  // when
  await Promise.all([WORKER, SCOUT, WORKER, RESEARCHER].map((type, index) => $.agent.spawn(spawnInput(type, { tool_use_id: `toolu_${index}` }))));

  // then
  expect(data.roles[SESSION].map((item) => item.toolUseId).sort()).toEqual(["toolu_0", "toolu_1", "toolu_2", "toolu_3"]);
});

test("고정하지 않는 에이전트와 거부된 시작은 모델도 기록도 바꾸지 않는다", async ($, on) => {
  // given
  const data = environment(on);
  const received = [];
  on("agent.spawn", (_$, e) => {
    received.push(e.model);
    return e.subagentType === "denied" ? { deny: "거부" } : { model: e.model ?? "inherited", agentId: "agent-x" };
  });

  // when
  const custom = await $.agent.spawn(spawnInput("reviewer", { model: "haiku" }));
  const denied = await $.agent.spawn(spawnInput("denied"));

  // then
  expect(received).toEqual(["haiku", undefined]);
  expect(custom.agentId).toBe("agent-x");
  expect(denied.deny).toBe("거부");
  expect(data.roles).toBeUndefined();
});

test("기록은 7일이 지난 항목만 정리하고 다른 세션의 최근 기록은 남긴다", async ($, on) => {
  // given
  const data = environment(on, {
    [SESSION]: [entry("old", { time: NOW - 7 * DAY - 1 }), entry("recent", { time: NOW - 7 * DAY })],
    "other-session": [entry("other-old", { time: NOW - 8 * DAY })],
    "other-recent": [entry("other-recent", { time: NOW - DAY })],
  });
  on("agent.spawn", (_$, e) => ({ model: e.model, agentId: "agent-new" }));

  // when
  await $.agent.spawn(spawnInput(WORKER));

  // then
  expect(data.roles[SESSION].map((item) => item.agentId)).toEqual(["recent", "agent-new"]);
  expect(data.roles["other-session"]).toBeUndefined();
  expect(data.roles["other-recent"].map((item) => item.agentId)).toEqual(["other-recent"]);
});

test("role_pinning 옵션이 꺼지면 모델을 고정하지 않고 기록도 남기지 않는다", { options: { role_pinning: false } }, async ($, on) => {
  // given
  const data = environment(on);
  on("agent.spawn", (_$, e) => ({ model: e.model ?? "inherited", agentId: "agent-1" }));
  const seen = [];
  stepSink(on, seen);

  // when
  const spawn = await $.agent.spawn(spawnInput(WORKER));
  await step($, { agentId: "agent-1", model: "claude-opus-5-5", effort: "max" });

  // then
  expect(spawn.model).toBe("inherited");
  expect(data.roles).toBeUndefined();
  expect(seen).toEqual([{ model: "claude-opus-5-5", effort: "max", agentId: "agent-1" }]);
});

test("기록된 에이전트의 요청은 모델과 effort를 고정값으로 바꿔 보낸다", async ($, on) => {
  // given
  environment(on, { [SESSION]: [entry("agent-1"), entry("agent-2", { role: "scout", effort: "medium" })] });
  const seen = [];
  stepSink(on, seen);

  // when
  const first = await step($, { agentId: "agent-1", model: "claude-opus-5-5", effort: "max" });
  const second = await step($, { agentId: "agent-2", model: "claude-haiku-4-5" });

  // then
  expect(seen).toEqual([
    { model: PINNED, effort: "high", agentId: "agent-1" },
    { model: PINNED, effort: "medium", agentId: "agent-2" },
  ]);
  expect(first.result.stopReason).toBe("end_turn");
  expect(second.result.answer).toBe("완료");
});

test("메인 요청과 기록에 없는 에이전트의 요청은 그대로 보낸다", async ($, on) => {
  // given
  environment(on, { [SESSION]: [entry("agent-1")] });
  const seen = [];
  stepSink(on, seen);

  // when
  await step($, { model: "claude-opus-5-5", effort: "max" });
  await step($, { agentId: "agent-unknown", model: "claude-opus-5-5", effort: "low" });
  await step($, { agentId: "agent-1", model: "claude-opus-5-5", effort: "low" });

  // then
  expect(seen).toEqual([
    { model: "claude-opus-5-5", effort: "max", agentId: undefined },
    { model: "claude-opus-5-5", effort: "low", agentId: "agent-unknown" },
    { model: PINNED, effort: "high", agentId: "agent-1" },
  ]);
});

test("응답 모델이 고정값과 문자열까지 같지 않으면 날짜가 붙은 이름도 고정 실패로 기록한다", async ($, on) => {
  // given
  const data = environment(on, { [SESSION]: [entry("agent-1")] });
  const seen = [];
  stepSink(on, seen, `${PINNED}-20260101`);

  // when
  await step($, { agentId: "agent-1" });
  const second = await step($, { agentId: "agent-1", index: 1 });

  // then
  expect(seen.length).toBe(1);
  expect(data.roles[SESSION][0].mismatch).toBe(true);
  expect(second.result.stopReason).toBe("refusal");
});

test("응답 모델이 고정값과 정확히 같으면 고정 실패로 기록하지 않는다", async ($, on) => {
  // given
  const data = environment(on, { [SESSION]: [entry("agent-1")] });
  const seen = [];
  stepSink(on, seen, PINNED);

  // when
  await step($, { agentId: "agent-1" });
  await step($, { agentId: "agent-1", index: 1 });

  // then
  expect(seen.length).toBe(2);
  expect(data.roles[SESSION][0].mismatch).toBeUndefined();
});

test("응답에 사용량이 없으면 고정 실패로 기록하지 않는다", async ($, on) => {
  // given
  const data = environment(on, { [SESSION]: [entry("agent-1")] });
  stepSink(on, [], null);

  // when
  await step($, { agentId: "agent-1" });

  // then
  expect(data.roles[SESSION][0].mismatch).toBeUndefined();
});

test("응답 모델이 고정값과 다르면 그 에이전트를 고정 실패로 기록한다", async ($, on) => {
  // given
  const data = environment(on, { [SESSION]: [entry("agent-1"), entry("agent-2")] });
  stepSink(on, [], "claude-opus-5-5");

  // when
  await step($, { agentId: "agent-1" });

  // then
  expect(data.roles[SESSION].find((item) => item.agentId === "agent-1").mismatch).toBe(true);
  expect(data.roles[SESSION].find((item) => item.agentId === "agent-2").mismatch).toBeUndefined();
});

test("고정 실패한 에이전트의 이후 요청은 모델을 부르지 않고 거절 텍스트로 끝난다", async ($, on) => {
  // given
  environment(on, { [SESSION]: [entry("agent-1", { mismatch: true })] });
  const seen = [];
  stepSink(on, seen);

  // when
  const { chunks, result } = await step($, { agentId: "agent-1", index: 3 });

  // then
  expect(seen).toEqual([]);
  expect(chunks.map((chunk) => chunk.kind)).toEqual(["text", "stop"]);
  expect(chunks[1]).toEqual({ kind: "stop", stopReason: "refusal", usage: null });
  expect(result).toEqual({ turnId: "turn-1", index: 3, answer: chunks[0].text, toolUses: [], stopReason: "refusal", usage: null });
  expect(chunks[0].text).toContain("must not be accepted");
});

test("고정 실패한 에이전트의 도구 호출은 모두 거부하고 정상 에이전트와 메인은 통과시킨다", async ($, on) => {
  // given
  environment(on, { [SESSION]: [entry("bad", { mismatch: true }), entry("good")] });
  on("tool.call", () => ({ result: { stdout: "ok", stderr: "" }, text: "ok" }));

  // when
  const bad = await $.tool.call({ tool: "Bash", command: "echo hi", agentId: "bad" });
  const badRead = await $.tool.call({ tool: "Read", file_path: "/tmp/x", agentId: "bad" });
  const good = await $.tool.call({ tool: "Bash", command: "echo hi", agentId: "good" });
  const unknown = await $.tool.call({ tool: "Bash", command: "echo hi", agentId: "unknown" });
  const main = await $.tool.call({ tool: "Bash", command: "echo hi" });

  // then
  expect(typeof bad.deny).toBe("string");
  expect(typeof badRead.deny).toBe("string");
  expect(good.text).toBe("ok");
  expect(unknown.text).toBe("ok");
  expect(main.text).toBe("ok");
});

test("고정 실패한 에이전트를 시작한 Agent 호출의 결과는 불일치 경고로 바뀐다", async ($, on) => {
  // given
  let toolUseId = "";
  on("store.get", () => ({ value: { [SESSION]: [entry("agent-1", { mismatch: true, toolUseId })] } }));
  on("store.set", () => ({ value: undefined }));
  on("session.id", () => ({ value: SESSION }));
  mock.clock(on, { now: NOW });
  const original = {
    status: "completed",
    agentId: "agent-1",
    content: [{ type: "text", text: "신뢰할 수 없는 결과" }],
    totalToolUseCount: 0,
    totalDurationMs: 1,
    totalTokens: 1,
    prompt: "작업",
  };
  on("tool.call", (_$, e) => {
    toolUseId = e.tool_use_id;
    return { result: original, text: "신뢰할 수 없는 결과" };
  });

  // when
  const replaced = await $.tool.call({ tool: "Agent", prompt: "작업", description: "작업", subagent_type: WORKER });

  // then
  expect(replaced.result.content).toHaveLength(1);
  expect(replaced.result.content[0].text).toContain("unexpected model");
  expect(replaced.result.content[0].text).toContain("Do not accept");
  expect(replaced.result.agentId).toBe("agent-1");
  expect(replaced.context[0]).toContain("unexpected model");
});

test("고정 실패하지 않은 에이전트의 Agent 호출 결과와 다른 도구 결과는 그대로 둔다", async ($, on) => {
  // given
  let toolUseId = "";
  on("store.get", () => ({ value: { [SESSION]: [entry("agent-1", { toolUseId })] } }));
  on("session.id", () => ({ value: SESSION }));
  const original = { status: "completed", agentId: "agent-1", content: [{ type: "text", text: "정상 결과" }], totalToolUseCount: 0, totalDurationMs: 1, totalTokens: 1, prompt: "작업" };
  on("tool.call", (_$, e) => {
    toolUseId = e.tool_use_id;
    return { result: e.tool === "Agent" ? original : { stdout: "ok", stderr: "" }, text: "정상 결과" };
  });

  // when
  const agent = await $.tool.call({ tool: "Agent", prompt: "작업", description: "작업", subagent_type: WORKER });
  const other = await $.tool.call({ tool: "Bash", command: "echo hi" });

  // then
  expect(agent.result.content[0].text).toBe("정상 결과");
  expect(other.result).toEqual({ stdout: "ok", stderr: "" });
});

test("플러그인을 다시 불러와도 저장소의 고정 기록으로 고정이 유지된다", async ($, on) => {
  // given
  const data = environment(on, { [SESSION]: [entry("agent-1"), entry("agent-2", { mismatch: true })] });
  const seen = [];
  stepSink(on, seen);

  // when
  const pinned = await step($, { agentId: "agent-1", model: "claude-opus-5-5" });
  const refused = await step($, { agentId: "agent-2", model: "claude-opus-5-5" });

  // then
  expect(seen).toEqual([{ model: PINNED, effort: "high", agentId: "agent-1" }]);
  expect(pinned.result.stopReason).toBe("end_turn");
  expect(refused.result.stopReason).toBe("refusal");
  expect(data.roles[SESSION].length).toBe(2);
});

test("프롬프트 컨텍스트에 역할 고정 안내 한 줄을 덧붙이고 기존 블록을 유지한다", async ($, on) => {
  // given
  on("prompt.context", (_$, e) => ({ blocks: e.blocks }));

  // when
  const context = await $.prompt.context({ blocks: [{ name: "currentDate", text: "2026-10-07" }] });

  // then
  expect(context.blocks[0]).toEqual({ name: "currentDate", text: "2026-10-07" });
  expect(context.blocks.filter((block) => block.text.includes("hei5enbug-agent-setup mod: role pinning active"))).toHaveLength(1);
  expect(context.blocks).toHaveLength(2);
});

test("role_pinning 옵션이 꺼지면 프롬프트 컨텍스트를 바꾸지 않는다", { options: { role_pinning: false } }, async ($, on) => {
  // given
  on("prompt.context", (_$, e) => ({ blocks: e.blocks }));

  // when
  const context = await $.prompt.context({ blocks: [{ name: "currentDate", text: "2026-10-07" }] });

  // then
  expect(context.blocks).toEqual([{ name: "currentDate", text: "2026-10-07" }]);
});

test("저장소 기록이 실패해도 고정 역할의 시작은 막히지 않고 호스트의 결과를 그대로 받는다", async ($, on) => {
  // given
  on("store.get", () => { throw new Error("저장소 오류"); });
  on("session.id", () => ({ value: SESSION }));
  mock.clock(on, { now: NOW });
  on("agent.spawn", (_$, e) => ({ model: e.model, agentId: "agent-1" }));

  // when
  const spawn = await $.agent.spawn(spawnInput(WORKER));

  // then
  expect(spawn).toEqual({ model: PINNED, agentId: "agent-1" });
});
