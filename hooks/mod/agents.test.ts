import { expect, mock, test } from "claude-code/testing";
import { enabled } from "./register.js";
import { resetClaudeRolePins } from "./registry.js";

const WORKER = "hei5enbug-agent-setup:worker";
const SONNET_WORKER = "hei5enbug-agent-setup:sonnet-worker";
const SCOUT = "hei5enbug-agent-setup:scout";
const DESIGNER = "hei5enbug-agent-setup:designer";
const REVIEWER = "hei5enbug-agent-setup:reviewer";
const EXAMPLE_SCOUT = "example-plugin:scout";
const EXAMPLE_LINTER = "example-plugin:linter";
const PINNED = "claude-sonnet-5-5";
const WORKER_PINNED = "claude-haiku-5-5";
const SESSION = "session-test";
const CONFIG = "/config";
const EXAMPLE_PATH = "/plugins/example-plugin";
const AGENT_ID = "abc123";
const ENV = { CLAUDE_CONFIG_DIR: CONFIG, HOME: "/home/test" };
const DAY = 24 * 60 * 60 * 1000;
const NOW = 10 * DAY;
const REGISTRY = JSON.stringify({
  pins: { "claude-sonnet": PINNED, "claude-haiku": WORKER_PINNED, "claude-opus": "claude-opus-5-5", "gpt-luna": "gpt-5.6-luna" },
  efforts: ["low", "medium", "high", "xhigh", "max"],
  claude_agents: {
    "hei5enbug-agent-setup:worker": { role: "worker", model: WORKER_PINNED, effort: "high", access: "write" },
    "hei5enbug-agent-setup:sonnet-worker": { role: "worker", model: PINNED, effort: "high", access: "write" },
    "hei5enbug-agent-setup:scout": { role: "scout", model: PINNED, effort: "medium", access: "read", fallback: { model: WORKER_PINNED, effort: "medium" } },
    "hei5enbug-agent-setup:designer": { role: "designer", model: "claude-opus-5-5", effort: "xhigh", access: "write" },
    "hei5enbug-agent-setup:reviewer": { role: "reviewer", model: "claude-opus-5-5", effort: "high", access: "read" },
  },
  effort_rules: { "gpt-5.6-luna": ["high", "xhigh"] },
});
const MANIFEST = JSON.stringify({
  userConfig: {
    worker_model: { options: ["claude-fable-5-1", "claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-5-5"] },
    worker_effort: { options: ["low", "medium", "high", "xhigh", "max"] },
  },
});
const EXAMPLE_ROLES = {
  version: 1,
  agents: {
    "example-plugin:scout": { model: PINNED, effort: "medium", fallback: { model: WORKER_PINNED, effort: "medium" } },
    "example-plugin:linter": { model: PINNED, effort: "high" },
  },
};

function environment(on, roles = undefined, world = {}) {
  const data = roles === undefined ? {} : { roles };
  const files = world.files ?? {};
  const unreadable = world.unreadable ?? [];
  on("fs.read", (_$, e) => {
    if (e.path.endsWith("config/model-registry.json")) return { value: world.registry ?? REGISTRY };
    if (e.path.endsWith(".claude-plugin/plugin.json")) {
      if (world.manifest === null) throw new Error(`no such file: ${e.path}`);
      return { value: world.manifest ?? MANIFEST };
    }
    if (e.path in files) return { value: files[e.path] };
    throw new Error(`no such file: ${e.path}`);
  });
  on("fs.exists", (_$, e) => ({ value: e.path in files || unreadable.includes(e.path) }));
  on("env.get", (_$, e) => ({ value: ENV[e.name] }));
  on("store.get", (_$, e) => ({ value: data[e.key] }));
  on("store.set", (_$, e) => {
    data[e.key] = JSON.parse(JSON.stringify(e.value));
    return { value: undefined };
  });
  on("session.id", () => ({ value: world.sessionId?.() ?? SESSION }));
  mock.clock(on, { now: NOW });
  resetClaudeRolePins();
  return data;
}

function pluginsWorld(installs) {
  const plugins = {};
  const files = {};
  for (const { key, installPath, roles } of installs) {
    plugins[key] = [{ scope: "user", installPath }];
    if (roles !== undefined) {
      files[`${installPath}/.claude-plugin/model-roles.json`] = typeof roles === "string" ? roles : JSON.stringify(roles);
    }
  }
  files[`${CONFIG}/plugins/installed_plugins.json`] = JSON.stringify({ version: 2, plugins });
  return { files };
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
  return { agentId, role: "worker", model: WORKER_PINNED, effort: "high", toolUseId: "toolu_main", time: NOW, ...extra };
}

function stepSink(on, seen, usageModel = WORKER_PINNED) {
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
  const offered = ["claude-code-guide", "statusline-setup", SCOUT, "example-plugin:reader", "reviewer"];

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
  for (const [index, type] of [WORKER, SONNET_WORKER, SCOUT, DESIGNER, REVIEWER].entries()) {
    results.push(await $.agent.spawn(spawnInput(type, { model: "haiku", tool_use_id: `toolu_${index}` })));
  }

  // then
  expect(received.map((item) => item.model)).toEqual([
    WORKER_PINNED,
    PINNED,
    PINNED,
    "claude-opus-5-5",
    "claude-opus-5-5",
  ]);
  expect(results.map((result) => result.agentId)).toEqual(["agent-1", "agent-2", "agent-3", "agent-4", "agent-5"]);
  expect(data.roles[SESSION]).toEqual([
    { agentId: "agent-1", agent: WORKER, role: "worker", model: WORKER_PINNED, effort: "high", toolUseId: "toolu_0", time: NOW },
    { agentId: "agent-2", agent: SONNET_WORKER, role: "worker", model: PINNED, effort: "high", toolUseId: "toolu_1", time: NOW },
    { agentId: "agent-3", agent: SCOUT, role: "scout", model: PINNED, effort: "medium", toolUseId: "toolu_2", time: NOW },
    { agentId: "agent-4", agent: DESIGNER, role: "designer", model: "claude-opus-5-5", effort: "xhigh", toolUseId: "toolu_3", time: NOW },
    { agentId: "agent-5", agent: REVIEWER, role: "reviewer", model: "claude-opus-5-5", effort: "high", toolUseId: "toolu_4", time: NOW },
  ]);
});

test("designer를 시작하면 Opus 모델과 xhigh를 고정하고 요청마다 같은 값으로 보낸다", async ($, on) => {
  // given
  const data = environment(on);
  const received = [];
  on("agent.spawn", (_$, e) => {
    received.push(e.model);
    return { model: e.model, agentId: "agent-design" };
  });
  const seen = [];
  stepSink(on, seen, "claude-opus-5-5");

  // when
  const spawn = await $.agent.spawn(spawnInput(DESIGNER, { model: "haiku", tool_use_id: "toolu_design" }));
  const first = await step($, { agentId: "agent-design", model: "claude-sonnet-5-5", effort: "low" });

  // then
  expect(spawn).toEqual({ model: "claude-opus-5-5", agentId: "agent-design" });
  expect(received).toEqual(["claude-opus-5-5"]);
  expect(data.roles[SESSION]).toEqual([
    { agentId: "agent-design", agent: DESIGNER, role: "designer", model: "claude-opus-5-5", effort: "xhigh", toolUseId: "toolu_design", time: NOW },
  ]);
  expect(seen).toEqual([{ model: "claude-opus-5-5", effort: "xhigh", agentId: "agent-design" }]);
  expect(first.result.stopReason).toBe("end_turn");
  expect(data.roles[SESSION][0].mismatch).toBeUndefined();
});

test("designer가 고정 모델이 아닌 모델로 응답하면 고정 실패로 기록하고 이후 요청을 거절한다", async ($, on) => {
  // given
  const data = environment(on, { [SESSION]: [entry("agent-design", { role: "designer", model: "claude-opus-5-5", effort: "xhigh" })] });
  stepSink(on, [], PINNED);

  // when
  await step($, { agentId: "agent-design" });
  const second = await step($, { agentId: "agent-design", index: 1 });

  // then
  expect(data.roles[SESSION][0].mismatch).toBe(true);
  expect(second.result.stopReason).toBe("refusal");
});

test("나란히 시작한 고정 역할의 기록은 서로 덮어쓰지 않는다", async ($, on) => {
  // given
  const data = environment(on);
  let count = 0;
  on("agent.spawn", (_$, e) => ({ model: e.model, agentId: `agent-${++count}` }));

  // when
  await Promise.all([WORKER, SCOUT, WORKER, DESIGNER].map((type, index) => $.agent.spawn(spawnInput(type, { tool_use_id: `toolu_${index}` }))));

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

test("선언된 역할은 설치된 플러그인의 model-roles.json에서 읽어 고정하고 기록에 고정 경로를 남긴다", async ($, on) => {
  // given
  const data = environment(on, undefined, pluginsWorld([{ key: "example-plugin@market", installPath: EXAMPLE_PATH, roles: EXAMPLE_ROLES }]));
  const received = [];
  on("agent.spawn", (_$, e) => {
    received.push(e.model);
    return { model: e.model, agentId: "agent-example" };
  });

  // when
  const spawn = await $.agent.spawn(spawnInput(EXAMPLE_SCOUT, { model: "haiku", tool_use_id: "toolu_example" }));

  // then
  expect(received).toEqual([PINNED]);
  expect(spawn).toEqual({ model: PINNED, agentId: "agent-example" });
  expect(data.roles[SESSION]).toEqual([
    { agentId: "agent-example", agent: EXAMPLE_SCOUT, role: "scout", model: PINNED, effort: "medium", toolUseId: "toolu_example", time: NOW },
  ]);
});

test("어느 플러그인도 선언하지 않은 에이전트는 모델을 바꾸지 않고 시작한다", async ($, on) => {
  // given
  environment(on, undefined, pluginsWorld([{ key: "example-plugin@market", installPath: EXAMPLE_PATH, roles: EXAMPLE_ROLES }]));
  const received = [];
  on("agent.spawn", (_$, e) => {
    received.push(e.model);
    return { model: e.model ?? "inherited", agentId: "agent-free" };
  });

  // when
  const spawn = await $.agent.spawn(spawnInput("other-plugin:scout", { model: "haiku" }));

  // then
  expect(received).toEqual(["haiku"]);
  expect(spawn.agentId).toBe("agent-free");
});

test("유효하지 않은 역할 파일은 그 파일이 이름 붙인 모든 에이전트를 거부하고 읽을 수 없는 파일은 플러그인의 모든 에이전트를 거부한다", async ($, on) => {
  // given
  const broken = {
    version: 1,
    agents: {
      "broken-plugin:worker": { model: "claude-haiku-4-5", effort: "high" },
      "broken-plugin:scout": { model: PINNED, effort: "medium" },
    },
  };
  environment(on, undefined, pluginsWorld([
    { key: "broken-plugin@market", installPath: "/plugins/broken-plugin", roles: broken },
    { key: "unreadable@market", installPath: "/plugins/unreadable", roles: "{not json" },
  ]));
  const received = [];
  on("agent.spawn", (_$, e) => {
    received.push(e.subagentType);
    return { model: e.model, agentId: "agent-x" };
  });

  // when
  const worker = await $.agent.spawn(spawnInput("broken-plugin:worker"));
  const scout = await $.agent.spawn(spawnInput("broken-plugin:scout"));
  const unreadable = await $.agent.spawn(spawnInput("unreadable:worker"));

  // then
  expect(worker.deny).toContain("claude-haiku-4-5 is not a pinned model");
  expect(scout.deny).toContain("broken-plugin:worker");
  expect(unreadable.deny).toContain("not valid JSON");
  expect(received).toEqual([]);
});

test("유효하지 않은 두 번째 설치의 선언은 첫 번째 설치가 고정한 같은 이름도 거부한다", async ($, on) => {
  // given
  const invalid = { version: 1, agents: { "example-plugin:scout": { model: "claude-haiku-4-5", effort: "medium" } } };
  environment(on, undefined, pluginsWorld([
    { key: "example-plugin@market", installPath: EXAMPLE_PATH, roles: EXAMPLE_ROLES },
    { key: "example-plugin@beta", installPath: "/plugins/example-plugin-beta", roles: invalid },
  ]));
  on("agent.spawn", (_$, e) => ({ model: e.model, agentId: "agent-dup" }));

  // when
  const spawn = await $.agent.spawn(spawnInput(EXAMPLE_SCOUT));

  // then
  expect(spawn.agentId).toBeUndefined();
  expect(spawn.deny).toContain("claude-haiku-4-5 is not a pinned model");
});

test("플러그인이 선언한 파일은 레지스트리에 있는 역할의 고정값을 바꾸지 못한다", async ($, on) => {
  // given
  const override = { version: 1, agents: { "hei5enbug-agent-setup:worker": { model: PINNED, effort: "high" } } };
  environment(on, undefined, pluginsWorld([{ key: "hei5enbug-agent-setup@hei5enbug", installPath: "/plugins/own", roles: override }]));
  const received = [];
  on("agent.spawn", (_$, e) => {
    received.push(e.model);
    return { model: e.model, agentId: "agent-worker" };
  });

  // when
  await $.agent.spawn(spawnInput(WORKER));

  // then
  expect(received).toEqual([WORKER_PINNED]);
});

test("고정 실패 뒤의 다음 시작은 한 번 거부하고 러너 대체 명령을 알리며, 그다음 시작은 기본 고정을 쓴다", async ($, on) => {
  // given
  const data = environment(on, undefined, pluginsWorld([{ key: "example-plugin@market", installPath: EXAMPLE_PATH, roles: EXAMPLE_ROLES }]));
  const received = [];
  on("agent.spawn", (_$, e) => {
    received.push(e.model);
    return { model: e.model, agentId: `agent-${received.length}` };
  });
  stepSink(on, [], "claude-opus-5-5");

  // when
  const first = await $.agent.spawn(spawnInput(EXAMPLE_SCOUT, { tool_use_id: "toolu_1" }));
  await step($, { agentId: "agent-1" });
  const second = await $.agent.spawn(spawnInput(EXAMPLE_SCOUT, { tool_use_id: "toolu_2" }));
  const third = await $.agent.spawn(spawnInput(EXAMPLE_SCOUT, { tool_use_id: "toolu_3" }));

  // then
  expect(received).toEqual([PINNED, PINNED]);
  expect(first.agentId).toBe("agent-1");
  expect(second.agentId).toBeUndefined();
  expect(second.deny).toContain("role_runner.py agent --name example-plugin:scout --fallback");
  expect(third.agentId).toBe("agent-2");
  expect(data.roles[SESSION].map((item) => [item.agentId, item.mismatch, item.retryNoticeIssued])).toEqual([
    ["agent-1", true, true],
    ["agent-2", undefined, undefined],
  ]);
});

test("고정 실패한 실행은 대체 안내 뒤에도 mismatch가 남아 그 실행의 도구 호출을 계속 거부한다", async ($, on) => {
  // given
  environment(on, undefined, pluginsWorld([{ key: "example-plugin@market", installPath: EXAMPLE_PATH, roles: EXAMPLE_ROLES }]));
  let spawned = 0;
  on("agent.spawn", (_$, e) => {
    spawned += 1;
    return { model: e.model, agentId: `agent-${spawned}` };
  });
  on("tool.call", () => ({ result: { stdout: "ok", stderr: "" }, text: "ok" }));
  stepSink(on, [], "claude-opus-5-5");
  await $.agent.spawn(spawnInput(EXAMPLE_SCOUT, { tool_use_id: "toolu_1" }));
  await step($, { agentId: "agent-1" });
  const denied = await $.agent.spawn(spawnInput(EXAMPLE_SCOUT, { tool_use_id: "toolu_2" }));

  // when
  const call = await $.tool.call({ tool: "Bash", command: "echo hi", agentId: "agent-1" });
  const restarted = await $.agent.spawn(spawnInput(EXAMPLE_SCOUT, { tool_use_id: "toolu_3" }));
  const again = await $.tool.call({ tool: "Bash", command: "echo hi", agentId: "agent-1" });

  // then
  expect(denied.deny).toContain("role_runner.py agent --name example-plugin:scout --fallback");
  expect(typeof call.deny).toBe("string");
  expect(restarted.agentId).toBe("agent-2");
  expect(typeof again.deny).toBe("string");
});

test("선언된 역할의 대체 안내는 access를 따른다: 쓰기 역할은 --add-dir을 덧붙이고 access가 없는 역할은 읽기로 본다", async ($, on) => {
  // given
  const roles = {
    version: 1,
    agents: {
      "example-plugin:editor": { model: PINNED, effort: "high", access: "write" },
      "example-plugin:scout": { model: PINNED, effort: "medium" },
    },
  };
  environment(on, undefined, pluginsWorld([{ key: "example-plugin@market", installPath: EXAMPLE_PATH, roles }]));
  let spawned = 0;
  on("agent.spawn", (_$, e) => {
    spawned += 1;
    return { model: e.model, agentId: `agent-${spawned}` };
  });
  stepSink(on, [], "claude-opus-5-5");
  await $.agent.spawn(spawnInput("example-plugin:editor", { tool_use_id: "toolu_editor" }));
  await step($, { agentId: "agent-1" });
  await $.agent.spawn(spawnInput(EXAMPLE_SCOUT, { tool_use_id: "toolu_reader" }));
  await step($, { agentId: "agent-2" });

  // when
  const editor = await $.agent.spawn(spawnInput("example-plugin:editor", { tool_use_id: "toolu_editor_2" }));
  const reader = await $.agent.spawn(spawnInput("example-plugin:scout", { tool_use_id: "toolu_reader_2" }));

  // then
  expect(editor.deny).toContain("--name example-plugin:editor --fallback");
  expect(editor.deny).toContain("--add-dir <dir>");
  expect(reader.deny).toContain("--name example-plugin:scout --fallback");
  expect(reader.deny).not.toContain("--add-dir");
});

test("대체 고정이 없는 역할도 첫 고정 실패 뒤의 시작을 한 번 거부하고 다음 시작은 기본 고정을 쓴다", async ($, on) => {
  // given
  environment(on, undefined, pluginsWorld([{ key: "example-plugin@market", installPath: EXAMPLE_PATH, roles: EXAMPLE_ROLES }]));
  const received = [];
  on("agent.spawn", (_$, e) => {
    received.push(e.model);
    return { model: e.model, agentId: `agent-linter-${received.length}` };
  });
  stepSink(on, [], "claude-opus-5-5");

  // when
  await $.agent.spawn(spawnInput(EXAMPLE_LINTER, { tool_use_id: "toolu_linter" }));
  await step($, { agentId: "agent-linter-1" });
  const second = await $.agent.spawn(spawnInput(EXAMPLE_LINTER, { tool_use_id: "toolu_linter_2" }));
  const third = await $.agent.spawn(spawnInput(EXAMPLE_LINTER, { tool_use_id: "toolu_linter_3" }));

  // then
  expect(second.agentId).toBeUndefined();
  expect(second.deny).toContain("role_runner.py agent --name example-plugin:linter --fallback");
  expect(third.agentId).toBe("agent-linter-2");
  expect(received).toEqual([PINNED, PINNED]);
});

test("쓰기 접근 에이전트의 대체 안내는 --add-dir과 --mcp 지침을 덧붙이고 읽기 접근 에이전트의 안내에는 덧붙이지 않는다", async ($, on) => {
  // given
  environment(on);
  let spawned = 0;
  on("agent.spawn", (_$, e) => {
    spawned += 1;
    return { model: e.model, agentId: `agent-${spawned}` };
  });
  stepSink(on, [], "claude-opus-5-5");
  await $.agent.spawn(spawnInput(SONNET_WORKER, { tool_use_id: "toolu_writer" }));
  await step($, { agentId: "agent-1" });
  await $.agent.spawn(spawnInput(SCOUT, { tool_use_id: "toolu_reader" }));
  await step($, { agentId: "agent-2" });

  // when
  const writer = await $.agent.spawn(spawnInput(SONNET_WORKER, { tool_use_id: "toolu_writer_2" }));
  const reader = await $.agent.spawn(spawnInput(SCOUT, { tool_use_id: "toolu_reader_2" }));

  // then
  expect(writer.deny).toContain(`--name ${SONNET_WORKER} --fallback`);
  expect(writer.deny).toContain("--add-dir <dir>");
  expect(writer.deny).toContain("--mcp");
  expect(reader.deny).toContain(`--name ${SCOUT} --fallback`);
  expect(reader.deny).not.toContain("--mcp");
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
  environment(on, { [SESSION]: [entry("agent-1"), entry("agent-2", { role: "scout", model: PINNED, effort: "medium" })] });
  const seen = [];
  stepSink(on, seen);

  // when
  const first = await step($, { agentId: "agent-1", model: "claude-opus-5-5", effort: "max" });
  const second = await step($, { agentId: "agent-2", model: "claude-haiku-4-5" });

  // then
  expect(seen).toEqual([
    { model: WORKER_PINNED, effort: "high", agentId: "agent-1" },
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
    { model: WORKER_PINNED, effort: "high", agentId: "agent-1" },
  ]);
});

test("응답 모델이 고정값과 문자열까지 같지 않으면 날짜가 붙은 이름도 고정 실패로 기록한다", async ($, on) => {
  // given
  const data = environment(on, { [SESSION]: [entry("agent-1")] });
  const seen = [];
  stepSink(on, seen, `${WORKER_PINNED}-20260101`);

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
  stepSink(on, seen, WORKER_PINNED);

  // when
  await step($, { agentId: "agent-1" });
  await step($, { agentId: "agent-1", index: 1 });

  // then
  expect(seen.length).toBe(2);
  expect(data.roles[SESSION][0].mismatch).toBeUndefined();
});

test("응답에 사용량이 없으면 고정 실패로 기록한다", async ($, on) => {
  // given
  const data = environment(on, { [SESSION]: [entry("agent-1")] });
  stepSink(on, [], null);

  // when
  await step($, { agentId: "agent-1" });

  // then
  expect(data.roles[SESSION][0].mismatch).toBe(true);
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

test("고정 실패한 에이전트를 시작한 Agent 호출의 결과는 다른 모델 경고로 바뀐다", async ($, on) => {
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
  expect(replaced.result.content[0].text).toContain("ran on a model other than its pinned model");
  expect(replaced.result.content[0].text).toContain("Do not accept");
  expect(replaced.result.agentId).toBe("agent-1");
  expect(replaced.context[0]).toContain("ran on a model other than its pinned model");
});

test("턴이 아직 없는 백그라운드 시작의 Agent 호출 결과는 실패로 기록하지 않고 전사본을 읽지 않은 채 그대로 둔다", async ($, on) => {
  // given
  const data = environment(on, {});
  const original = { status: "async_launched", agentId: AGENT_ID, content: [{ type: "text", text: "백그라운드 시작" }], prompt: "작업" };
  on("tool.call", (_$, e) => {
    if (e.tool === "Agent") data.roles[SESSION] = [entry(AGENT_ID, { agent: SCOUT, role: "scout", model: PINNED, effort: "medium", toolUseId: e.tool_use_id })];
    return { result: e.tool === "Agent" ? original : { stdout: "ok", stderr: "" }, text: "백그라운드 시작" };
  });

  // when
  const agent = await $.tool.call({ tool: "Agent", prompt: "작업", description: "작업", subagent_type: SCOUT, run_in_background: true });
  const other = await $.tool.call({ tool: "Bash", command: "echo hi" });

  // then
  expect(agent.result).toEqual(original);
  expect(data.roles[SESSION][0].mismatch).toBeUndefined();
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
  expect(seen).toEqual([{ model: WORKER_PINNED, effort: "high", agentId: "agent-1" }]);
  expect(pinned.result.stopReason).toBe("end_turn");
  expect(refused.result.stopReason).toBe("refusal");
  expect(data.roles[SESSION].length).toBe(2);
});

const MARKER = "hei5enbug-agent-setup mod: role pinning active";

function submitSink(on, seen) {
  on("prompt.submit", (_$, e) => {
    seen.push(e);
    return { text: e.text };
  });
  on("session.end", (_$, e) => ({ sessionId: e.sessionId ?? SESSION }));
}

test("프롬프트 컨텍스트 훅은 등록하지 않아 엔진의 컨텍스트 블록을 그대로 둔다", async ($, on) => {
  // given
  environment(on);
  on("prompt.context", (_$, e) => ({ blocks: e.blocks }));

  // when
  const context = await $.prompt.context({ blocks: [{ name: "currentDate", text: "2026-10-07" }] });

  // then
  expect(context.blocks).toEqual([{ name: "currentDate", text: "2026-10-07" }]);
});

test("역할 고정 안내는 첫 메인 프롬프트의 추가 컨텍스트에 한 번만 붙고 기존 컨텍스트와 본문을 유지한다", async ($, on) => {
  // given
  environment(on);
  const seen = [];
  submitSink(on, seen);

  // when
  await $.prompt.submit({ text: "first", context: ["earlier hook"] });
  await $.prompt.submit({ text: "second" });
  await $.prompt.submit({ text: "third" });

  // then
  expect(seen.map((e) => e.text)).toEqual(["first", "second", "third"]);
  expect(seen[0].context).toEqual(["earlier hook", MARKER]);
  expect(seen[1].context).toBeUndefined();
  expect(seen[2].context).toBeUndefined();
});

test("역할 고정 안내는 /clear와 /resume 뒤 첫 프롬프트에 다시 붙고 그 밖의 종료 사유에는 붙지 않는다", async ($, on) => {
  // given
  environment(on);
  const seen = [];
  submitSink(on, seen);
  await $.prompt.submit({ text: "p1" });

  // when
  await $.session.end({ reason: "clear" });
  await $.prompt.submit({ text: "p2" });
  await $.prompt.submit({ text: "p3" });
  await $.session.end({ reason: "resume" });
  await $.prompt.submit({ text: "p4" });
  await $.session.end({ reason: "other" });
  await $.prompt.submit({ text: "p5" });

  // then
  expect(seen.map((e) => e.context ?? [])).toEqual([[MARKER], [MARKER], [], [MARKER], []]);
});

test("새 세션은 이전 세션이 안내를 붙였어도 첫 프롬프트에 다시 붙인다", async ($, on) => {
  // given
  const ids = ["session-one", "session-two"];
  environment(on, undefined, { sessionId: () => ids[0] });
  const seen = [];
  submitSink(on, seen);
  await $.prompt.submit({ text: "p1" });

  // when
  ids.shift();
  await $.prompt.submit({ text: "p2" });

  // then
  expect(seen.map((e) => e.context ?? [])).toEqual([[MARKER], [MARKER]]);
});

test("뒤쪽 훅이 프롬프트를 버리면 안내를 기록하지 않아 다음에 받아들여진 프롬프트에 한 번만 붙는다", async ($, on) => {
  // given
  environment(on);
  const seen = [];
  let drops = 1;
  on("prompt.submit", (_$, e) => {
    seen.push(e);
    if (drops > 0) {
      drops -= 1;
      return { drop: "later hook refused" };
    }
    return { text: e.text };
  });

  // when
  const dropped = await $.prompt.submit({ text: "first" });
  await $.prompt.submit({ text: "second" });
  await $.prompt.submit({ text: "third" });

  // then
  expect(dropped.drop).toBe("later hook refused");
  expect(seen.map((e) => e.context ?? [])).toEqual([[MARKER], [MARKER], []]);
});

test("하위 에이전트의 프롬프트에는 안내를 붙이지 않고 메인 프롬프트의 몫도 쓰지 않는다", async ($, on) => {
  // given
  environment(on);
  const seen = [];
  submitSink(on, seen);

  // when
  await $.prompt.submit({ text: "sub", agentId: AGENT_ID });
  await $.prompt.submit({ text: "main" });

  // then
  expect(seen[0].context).toBeUndefined();
  expect(seen[1].context).toEqual([MARKER]);
});

test("role_pinning 옵션이 꺼지면 프롬프트에 안내를 붙이지 않는다", { options: { role_pinning: false } }, async ($, on) => {
  // given
  const seen = [];
  submitSink(on, seen);

  // when
  await $.prompt.submit({ text: "first" });
  await $.session.end({ reason: "clear" });
  await $.prompt.submit({ text: "second" });

  // then
  expect(seen.map((e) => e.context)).toEqual([undefined, undefined]);
});

test("저장소 기록을 읽지 못하면 고정 역할의 시작을 거부하고 호스트의 결과를 넘기지 않는다", async ($, on) => {
  // given
  on("fs.read", () => ({ value: REGISTRY }));
  on("env.get", (_$, e) => ({ value: ENV[e.name] }));
  on("store.get", () => { throw new Error("저장소 오류"); });
  on("session.id", () => ({ value: SESSION }));
  mock.clock(on, { now: NOW });
  resetClaudeRolePins();
  on("agent.spawn", (_$, e) => ({ model: e.model, agentId: "agent-1" }));

  // when
  const spawn = await $.agent.spawn(spawnInput(WORKER));

  // then
  expect(spawn.agentId).toBeUndefined();
  expect(spawn.deny).toContain("the role pin check failed");
});

test("고정 역할의 기록을 쓰지 못하면 시작은 넘기되 그 서브에이전트의 모든 턴을 거절한다", async ($, on) => {
  // given
  on("fs.read", () => ({ value: REGISTRY }));
  on("env.get", (_$, e) => ({ value: ENV[e.name] }));
  on("store.get", () => ({ value: {} }));
  on("store.set", () => { throw new Error("저장소 쓰기 오류"); });
  on("session.id", () => ({ value: SESSION }));
  mock.clock(on, { now: NOW });
  resetClaudeRolePins();
  on("agent.spawn", (_$, e) => ({ model: e.model, agentId: "agent-1" }));
  const seen = [];
  stepSink(on, seen, WORKER_PINNED);

  // when
  const spawn = await $.agent.spawn(spawnInput(WORKER));
  const turn = await step($, { agentId: "agent-1" });

  // then
  expect(spawn.agentId).toBe("agent-1");
  expect(seen).toEqual([]);
  expect(turn.result.stopReason).toBe("refusal");
});

test("설치 목록을 읽을 수 없으면 플러그인 접두사의 에이전트를 거부하고 레지스트리 역할과 접두사 없는 에이전트는 그대로 시작한다", async ($, on) => {
  // given
  environment(on, undefined, { files: { [`${CONFIG}/plugins/installed_plugins.json`]: "{not json" } });
  const received = [];
  on("agent.spawn", (_$, e) => {
    received.push(e.subagentType);
    return { model: e.model ?? "inherited", agentId: `agent-${received.length}` };
  });

  // when
  const linter = await $.agent.spawn(spawnInput(EXAMPLE_LINTER));
  const worker = await $.agent.spawn(spawnInput(WORKER));
  const plain = await $.agent.spawn(spawnInput("reviewer"));

  // then
  expect(linter.deny).toContain("its installed plugins file cannot be parsed");
  expect(worker.model).toBe(WORKER_PINNED);
  expect(plain.agentId).toBe("agent-2");
  expect(received).toEqual([WORKER, "reviewer"]);
});

test("설치된 플러그인의 역할 파일이 있는데 읽을 수 없으면 그 플러그인의 에이전트를 거부하고 다른 역할은 고정한다", async ($, on) => {
  // given
  environment(on, undefined, {
    ...pluginsWorld([{ key: "unreadable@market", installPath: "/plugins/unreadable" }]),
    unreadable: ["/plugins/unreadable/.claude-plugin/model-roles.json"],
  });
  const received = [];
  on("agent.spawn", (_$, e) => {
    received.push(e.subagentType);
    return { model: e.model, agentId: "agent-x" };
  });

  // when
  const denied = await $.agent.spawn(spawnInput("unreadable:worker"));
  const pinned = await $.agent.spawn(spawnInput(WORKER));

  // then
  expect(denied.deny).toContain("its model roles file cannot be read");
  expect(pinned.model).toBe(WORKER_PINNED);
  expect(received).toEqual([WORKER]);
});

test("턴 기록에 실패한 서브에이전트의 남은 턴은 모델을 부르지 않고 거절한다", async ($, on) => {
  // given
  on("store.get", () => ({ value: { [SESSION]: [entry("agent-1")] } }));
  on("store.set", () => { throw new Error("저장소 쓰기 오류"); });
  on("session.id", () => ({ value: SESSION }));
  mock.clock(on, { now: NOW });
  const seen = [];
  stepSink(on, seen, "claude-opus-5-5");

  // when
  const first = await step($, { agentId: "agent-1" });
  const second = await step($, { agentId: "agent-1", index: 1 });

  // then
  expect(seen).toEqual([{ model: WORKER_PINNED, effort: "high", agentId: "agent-1" }]);
  expect(first.result.stopReason).toBe("end_turn");
  expect(second.result.stopReason).toBe("refusal");
  expect(second.chunks[0].text).toContain("must not be accepted");
});

test("응답 사용량에 모델 이름이 없어도 고정 실패로 기록한다", async ($, on) => {
  // given
  const data = environment(on, { [SESSION]: [entry("agent-1")] });
  const usage = { input_tokens: 1, output_tokens: 1, cache_read_input_tokens: 0, cache_creation_input_tokens: 0 };
  on("turn.step", async function* (_$, e) {
    yield { kind: "stop", stopReason: "end_turn", usage };
    return { turnId: e.turnId, index: e.index, answer: "완료", toolUses: [], stopReason: "end_turn", usage };
  });

  // when
  await step($, { agentId: "agent-1" });

  // then
  expect(data.roles[SESSION][0].mismatch).toBe(true);
});

test("Agent 호출이 오류로 끝나면 그 고정 실행을 실패로 기록해 다음 시작은 러너 대체 안내로 한 번 거부하고 오류 결과는 그대로 둔다", async ($, on) => {
  // given
  const data = environment(on, { [SESSION]: [entry("agent-1", { agent: SCOUT, role: "scout", model: PINNED, effort: "medium" })] });
  on("tool.call", (_$, e) => {
    data.roles[SESSION][0].toolUseId = e.tool_use_id;
    return { isError: true, result: "실패", text: "작업 실패" };
  });
  const received = [];
  on("agent.spawn", (_$, e) => {
    received.push(e.model);
    return { model: e.model, agentId: "agent-2" };
  });

  // when
  const failed = await $.tool.call({ tool: "Agent", prompt: "작업", description: "작업", subagent_type: SCOUT });
  const denied = await $.agent.spawn(spawnInput(SCOUT, { tool_use_id: "toolu_next" }));
  const failureAfterDenial = data.roles[SESSION][0].mismatch;
  const noticeAfterDenial = data.roles[SESSION][0].retryNoticeIssued;
  const restarted = await $.agent.spawn(spawnInput(SCOUT, { tool_use_id: "toolu_after" }));

  // then
  expect(failed.isError).toBe(true);
  expect(failed.text).toBe("작업 실패");
  expect(denied.deny).toContain(`--name ${SCOUT} --fallback`);
  expect(failureAfterDenial).toBe(true);
  expect(noticeAfterDenial).toBe(true);
  expect(received).toEqual([PINNED]);
  expect(restarted.agentId).toBe("agent-2");
});

test("서브에이전트의 마지막 턴이 오류로 끝나면 그 실행을 고정 실패로 기록하고 정상 종료는 기록하지 않는다", async ($, on) => {
  // given
  const data = environment(on, { [SESSION]: [entry("agent-1", { agent: SCOUT }), entry("agent-2", { agent: SCOUT })] });
  on("turn.complete", () => ({ text: "" }));
  const finished = { answer: "", durationMs: 1, isAborted: false, turnId: "turn-1" };

  // when
  await $.turn.complete({ ...finished, agentId: "agent-1", reason: "error" });
  await $.turn.complete({ ...finished, agentId: "agent-2", reason: "answer" });

  // then
  expect(data.roles[SESSION].find((item) => item.agentId === "agent-1").mismatch).toBe(true);
  expect(data.roles[SESSION].find((item) => item.agentId === "agent-2").mismatch).toBeUndefined();
});

test("worker는 /config에서 고른 모델과 effort로 시작하고 기록과 요청에 같은 값을 쓴다", { options: { worker_model: "claude-opus-5-5", worker_effort: "xhigh" } }, async ($, on) => {
  // given
  const data = environment(on);
  const received = [];
  on("agent.spawn", (_$, e) => {
    received.push(e.model);
    return { model: e.model, agentId: "agent-worker" };
  });
  const seen = [];
  stepSink(on, seen, "claude-opus-5-5");

  // when
  const spawn = await $.agent.spawn(spawnInput(WORKER, { model: "haiku", tool_use_id: "toolu_worker" }));
  const turn = await step($, { agentId: "agent-worker", model: "claude-sonnet-5-5", effort: "low" });

  // then
  expect(received).toEqual(["claude-opus-5-5"]);
  expect(spawn.agentId).toBe("agent-worker");
  expect(data.roles[SESSION]).toEqual([
    { agentId: "agent-worker", agent: WORKER, role: "worker", model: "claude-opus-5-5", effort: "xhigh", toolUseId: "toolu_worker", time: NOW },
  ]);
  expect(seen).toEqual([{ model: "claude-opus-5-5", effort: "xhigh", agentId: "agent-worker" }]);
  expect(turn.result.stopReason).toBe("end_turn");
  expect(data.roles[SESSION][0].mismatch).toBeUndefined();
});

test("worker 옵션이 없으면 레지스트리의 고정값으로 시작한다", async ($, on) => {
  // given
  const data = environment(on);
  const received = [];
  on("agent.spawn", (_$, e) => {
    received.push(e.model);
    return { model: e.model, agentId: "agent-worker" };
  });

  // when
  await $.agent.spawn(spawnInput(WORKER, { tool_use_id: "toolu_worker" }));

  // then
  expect(received).toEqual([WORKER_PINNED]);
  expect(data.roles[SESSION][0].model).toBe(WORKER_PINNED);
  expect(data.roles[SESSION][0].effort).toBe("high");
});

const INVALID_WORKER_OPTIONS = [
  { worker_model: "gpt-6.1-sol", worker_effort: "high" },
  { worker_model: "claude-unknown-9", worker_effort: "high" },
  { worker_model: 5, worker_effort: "high" },
];

for (const options of INVALID_WORKER_OPTIONS) {
  test(`worker 옵션 ${JSON.stringify(options)}이 유효하지 않으면 거부하지 않고 레지스트리의 고정값으로 시작한다`, { options }, async ($, on) => {
    // given
    const data = environment(on);
    const received = [];
    on("agent.spawn", (_$, e) => {
      received.push(e.model);
      return { model: e.model, agentId: "agent-worker" };
    });

    // when
    const spawn = await $.agent.spawn(spawnInput(WORKER, { tool_use_id: "toolu_worker" }));

    // then
    expect(spawn.deny).toBeUndefined();
    expect(received).toEqual([WORKER_PINNED]);
    expect(data.roles[SESSION][0].model).toBe(WORKER_PINNED);
    expect(data.roles[SESSION][0].effort).toBe("high");
  });
}

const UNUSABLE_MANIFESTS = {
  "없는": null,
  "JSON이 아닌": "{not json",
  "선택지가 줄어든": JSON.stringify({ userConfig: { worker_model: { options: ["claude-haiku-5-5"] }, worker_effort: { options: ["high"] } } }),
  "userConfig가 없는": JSON.stringify({ name: "hei5enbug-agent-setup" }),
};

for (const [label, manifest] of Object.entries(UNUSABLE_MANIFESTS)) {
  test(`${label} 매니페스트면 worker는 거부하지 않고 레지스트리의 고정값으로 시작한다`, { options: { worker_model: "claude-opus-5-5", worker_effort: "xhigh" } }, async ($, on) => {
    // given
    const data = environment(on, undefined, { manifest });
    const received = [];
    on("agent.spawn", (_$, e) => {
      received.push(e.model);
      return { model: e.model, agentId: "agent-worker" };
    });

    // when
    const spawn = await $.agent.spawn(spawnInput(WORKER, { tool_use_id: "toolu_worker" }));

    // then
    expect(spawn.deny).toBeUndefined();
    expect(received).toEqual([WORKER_PINNED]);
    expect([data.roles[SESSION][0].model, data.roles[SESSION][0].effort]).toEqual([WORKER_PINNED, "high"]);
  });
}

test("레지스트리의 effort 규칙이 금지한 조합이면 worker는 레지스트리의 고정값으로 시작한다", { options: { worker_model: "claude-opus-5-5", worker_effort: "max" } }, async ($, on) => {
  // given
  const registry = JSON.parse(REGISTRY);
  registry.effort_rules["claude-opus-5-5"] = ["high", "xhigh"];
  environment(on, undefined, { registry: JSON.stringify(registry) });
  const received = [];
  on("agent.spawn", (_$, e) => {
    received.push(e.model);
    return { model: e.model, agentId: "agent-worker" };
  });

  // when
  const spawn = await $.agent.spawn(spawnInput(WORKER));

  // then
  expect(spawn.deny).toBeUndefined();
  expect(received).toEqual([WORKER_PINNED]);
});

test("sonnet-worker와 다른 역할은 worker 옵션을 무시한다", { options: { worker_model: "claude-opus-5-5", worker_effort: "xhigh" } }, async ($, on) => {
  // given
  const data = environment(on);
  const received = [];
  on("agent.spawn", (_$, e) => {
    received.push(e.model);
    return { model: e.model, agentId: `agent-${received.length}` };
  });

  // when
  for (const [index, type] of [SONNET_WORKER, SCOUT, REVIEWER].entries()) {
    await $.agent.spawn(spawnInput(type, { tool_use_id: `toolu_${index}` }));
  }

  // then
  expect(received).toEqual([PINNED, PINNED, "claude-opus-5-5"]);
  expect(data.roles[SESSION].map((item) => [item.model, item.effort])).toEqual([
    [PINNED, "high"],
    [PINNED, "medium"],
    ["claude-opus-5-5", "high"],
  ]);
});

const OPUS = "claude-opus-5-5";
const HAIKU = "claude-haiku-5-5";

function requestWorld(extra = {}) {
  return { sessionId: () => SESSION, ...extra };
}

function requestSinks(on) {
  const received = [];
  on("agent.spawn", (_$, e) => {
    received.push(e.model);
    return { model: e.model, agentId: `agent-${received.length}` };
  });
  on("prompt.submit", (_$, e) => ({ text: e.text }));
  return received;
}

test("사용자가 모델과 effort를 직접 말하면 같은 모델을 넘긴 호출은 그 모델과 effort로 시작하고 기록한다", async ($, on) => {
  // given
  const data = environment(on, undefined, requestWorld());
  const received = requestSinks(on);
  const seen = [];
  stepSink(on, seen, OPUS);
  await $.prompt.submit({ text: "이 변경을 claude-opus-5-5 모델로 max effort로 검토해줘" });

  // when
  const spawn = await $.agent.spawn(spawnInput(SCOUT, { model: "opus", tool_use_id: "toolu_req" }));
  const first = await step($, { agentId: "agent-1", model: PINNED, effort: "low" });

  // then
  expect(received).toEqual([OPUS]);
  expect(spawn).toEqual({ model: OPUS, agentId: "agent-1" });
  expect(data.roles[SESSION]).toEqual([
    { agentId: "agent-1", agent: SCOUT, role: "scout", model: OPUS, effort: "max", requested: true, toolUseId: "toolu_req", time: NOW },
  ]);
  expect(seen).toEqual([{ model: OPUS, effort: "max", agentId: "agent-1" }]);
  expect(first.result.stopReason).toBe("end_turn");
});

test("프롬프트에 별칭만 말해도 레지스트리 고정 모델로 풀어 요청한 모델로 시작하고 effort는 역할 고정값을 둔다", async ($, on) => {
  // given
  const data = environment(on, undefined, requestWorld());
  const received = requestSinks(on);
  await $.prompt.submit({ text: "Please run the reviewer on Haiku." });

  // when
  await $.agent.spawn(spawnInput(REVIEWER, { model: "haiku" }));
  await $.agent.spawn(spawnInput(REVIEWER, { model: HAIKU, tool_use_id: "toolu_full" }));

  // then
  expect(received).toEqual([HAIKU, HAIKU]);
  expect(data.roles[SESSION].map((item) => [item.model, item.effort, item.requested])).toEqual([
    [HAIKU, "high", true],
    [HAIKU, "high", true],
  ]);
});

test("사용자가 말하지 않은 모델을 호출이 넘기면 무시하고 역할 고정 모델로 시작한다", async ($, on) => {
  // given
  const data = environment(on, undefined, requestWorld());
  const received = requestSinks(on);
  await $.prompt.submit({ text: "워커로 구현해줘. sonnet 말고 다른 건 쓰지 마." });

  // when
  await $.agent.spawn(spawnInput(WORKER, { model: "opus" }));
  await $.agent.spawn(spawnInput(WORKER, { model: "fable", tool_use_id: "toolu_two" }));

  // then
  expect(received).toEqual([WORKER_PINNED, WORKER_PINNED]);
  expect(data.roles[SESSION].every((item) => item.requested === undefined)).toBe(true);
});

test("요청이 없던 세션에서 호출이 모델을 넘겨도 지금처럼 역할 고정 모델과 effort로 시작한다", async ($, on) => {
  // given
  const data = environment(on, undefined, requestWorld());
  const received = requestSinks(on);
  await $.prompt.submit({ text: "범위를 정리해줘" });

  // when
  await $.agent.spawn(spawnInput(SCOUT, { model: "opus" }));

  // then
  expect(received).toEqual([PINNED]);
  expect(data.roles[SESSION][0]).toEqual(expect.objectContaining({ model: PINNED, effort: "medium" }));
});

test("요청한 다음의 새 메인 프롬프트가 요청 없이 오면 다음 위임은 역할 고정값으로 돌아간다", async ($, on) => {
  // given
  const data = environment(on, undefined, requestWorld());
  const received = requestSinks(on);
  await $.prompt.submit({ text: "opus 모델 max effort로 검토해줘" });
  await $.agent.spawn(spawnInput(SCOUT, { model: "opus", tool_use_id: "toolu_a" }));

  // when
  await $.prompt.submit({ text: "이어서 진행해줘" });
  await $.agent.spawn(spawnInput(SCOUT, { model: "opus", tool_use_id: "toolu_b" }));

  // then
  expect(received).toEqual([OPUS, PINNED]);
  expect(data.roles[SESSION].map((item) => [item.model, item.effort])).toEqual([
    [OPUS, "max"],
    [PINNED, "medium"],
  ]);
});

test("붙여넣은 블록과 코드 블록 안의 모델 이름은 요청으로 세지 않는다", async ($, on) => {
  // given
  environment(on, undefined, requestWorld());
  const received = requestSinks(on);
  const pasted = '로그를 봐줘 <pasted_content id="1">use claude-opus-5-5 at max, opus</pasted_content> 끝';
  const fenced = "예시:\n```\nmodel: opus\neffort: max\n```\n이 설정은 쓰지 마.";
  const unterminated = "예시:\n```\nmodel: claude-opus-5-5";

  // when
  const results = [];
  for (const text of [pasted, fenced, unterminated]) {
    await $.prompt.submit({ text });
    await $.agent.spawn(spawnInput(SCOUT, { model: "opus" }));
    results.push(received.at(-1));
  }

  // then
  expect(results).toEqual([PINNED, PINNED, PINNED]);
});

test("물결표 울타리와 더 긴 백틱 울타리 블록 안의 모델 이름은 요청으로 세지 않고 울타리 밖 요청은 센다", async ($, on) => {
  // given
  environment(on, undefined, requestWorld());
  const received = requestSinks(on);
  const tilde = "예시:\n~~~\nmodel: opus\neffort: max\n~~~\n이 설정은 쓰지 마.";
  const longTilde = "예시:\n~~~~\n~~~\nmodel: opus\neffort: max\n~~~~\n끝";
  const longBacktick = "예시:\n````\n```\nmodel: opus\neffort: max\n````\n끝";
  const unterminatedTilde = "예시:\n~~~\nmodel: claude-opus-5-5";
  const outside = "```\nx\n```\nopus 모델 max effort로 검토해줘";

  // when
  const results = [];
  for (const text of [tilde, longTilde, longBacktick, unterminatedTilde, outside]) {
    await $.prompt.submit({ text });
    await $.agent.spawn(spawnInput(SCOUT, { model: "opus" }));
    results.push(received.at(-1));
  }

  // then
  expect(results).toEqual([PINNED, PINNED, PINNED, PINNED, OPUS]);
});

test("백틱으로 감싼 모델 ID와 effort도 사용자의 요청으로 센다", async ($, on) => {
  // given
  const data = environment(on, undefined, requestWorld());
  const received = requestSinks(on);
  await $.prompt.submit({ text: "Review this with `claude-opus-5-5` at `max`" });

  // when
  await $.agent.spawn(spawnInput(SCOUT, { model: "opus" }));

  // then
  expect(received).toEqual([OPUS]);
  expect(data.roles[SESSION][0]).toEqual(expect.objectContaining({ model: OPUS, effort: "max", requested: true }));
});

test("effort만 말한 요청은 호출이 역할 고정 모델의 별칭을 넘길 때 고정 모델과 그 effort로 시작하고 기록한다", async ($, on) => {
  // given
  const data = environment(on, undefined, requestWorld());
  const received = requestSinks(on);
  const seen = [];
  stepSink(on, seen, PINNED);
  await $.prompt.submit({ text: "max effort로 검토해줘" });

  // when
  await $.agent.spawn(spawnInput(SCOUT, { model: "sonnet", tool_use_id: "toolu_alias" }));
  await $.agent.spawn(spawnInput(SCOUT, { model: PINNED, tool_use_id: "toolu_full" }));
  await step($, { agentId: "agent-1", effort: "low" });

  // then
  expect(received).toEqual([PINNED, PINNED]);
  expect(data.roles[SESSION].map((item) => [item.model, item.effort, item.requested])).toEqual([
    [PINNED, "max", true],
    [PINNED, "max", true],
  ]);
  expect(seen).toEqual([{ model: PINNED, effort: "max", agentId: "agent-1" }]);
});

test("effort만 말한 요청이라도 effort를 말하지 않았거나 여러 개 말했거나 모델 없는 호출이면 고정 effort를 둔다", async ($, on) => {
  // given
  const data = environment(on, undefined, requestWorld());
  requestSinks(on);

  // when
  await $.prompt.submit({ text: "검토해줘" });
  await $.agent.spawn(spawnInput(SCOUT, { model: "sonnet", tool_use_id: "toolu_none" }));
  await $.prompt.submit({ text: "low 나 max effort로 해줘" });
  await $.agent.spawn(spawnInput(SCOUT, { model: "sonnet", tool_use_id: "toolu_two" }));
  await $.prompt.submit({ text: "max effort로 해줘" });
  await $.agent.spawn(spawnInput(SCOUT, { tool_use_id: "toolu_bare" }));

  // then
  expect(data.roles[SESSION].map((item) => [item.model, item.effort, item.requested])).toEqual([
    [PINNED, "medium", undefined],
    [PINNED, "medium", undefined],
    [PINNED, "medium", undefined],
  ]);
});

test("effort만 말한 요청에서 역할 고정 모델이 아닌 모델을 넘긴 호출은 무시하고 고정값으로 시작한다", async ($, on) => {
  // given
  const data = environment(on, undefined, requestWorld());
  const received = requestSinks(on);
  await $.prompt.submit({ text: "max effort로 해줘" });

  // when
  await $.agent.spawn(spawnInput(SCOUT, { model: "opus" }));

  // then
  expect(received).toEqual([PINNED]);
  expect(data.roles[SESSION][0]).toEqual(expect.objectContaining({ model: PINNED, effort: "medium" }));
  expect(data.roles[SESSION][0].requested).toBeUndefined();
});

test("effort만 말한 요청도 레지스트리 effort 규칙이 모델에 허용하지 않으면 고정 effort를 둔다", async ($, on) => {
  // given
  const restricted = JSON.stringify({ ...JSON.parse(REGISTRY), effort_rules: { "gpt-5.6-luna": ["high", "xhigh"], [PINNED]: ["medium", "high"] } });
  const data = environment(on, undefined, requestWorld({ registry: restricted }));
  requestSinks(on);
  await $.prompt.submit({ text: "max effort로 해줘" });

  // when
  await $.agent.spawn(spawnInput(SCOUT, { model: "sonnet" }));

  // then
  expect(data.roles[SESSION][0]).toEqual(expect.objectContaining({ model: PINNED, effort: "medium" }));
  expect(data.roles[SESSION][0].requested).toBeUndefined();
});

test("레지스트리 effort 규칙이 허용하지 않거나 여러 effort를 말하면 모델만 따르고 고정 effort를 둔다", async ($, on) => {
  // given
  const restricted = JSON.stringify({ ...JSON.parse(REGISTRY), effort_rules: { "gpt-5.6-luna": ["high", "xhigh"], [OPUS]: ["high", "xhigh"] } });
  const data = environment(on, undefined, requestWorld({ registry: restricted }));
  requestSinks(on);

  // when
  await $.prompt.submit({ text: "opus 모델 max effort로 검토해줘" });
  await $.agent.spawn(spawnInput(REVIEWER, { model: "opus", tool_use_id: "toolu_rule" }));
  await $.prompt.submit({ text: "opus 모델로 low 아니면 xhigh로 검토해줘" });
  await $.agent.spawn(spawnInput(REVIEWER, { model: "opus", tool_use_id: "toolu_two" }));

  // then
  expect(data.roles[SESSION].map((item) => [item.model, item.effort])).toEqual([
    [OPUS, "high"],
    [OPUS, "high"],
  ]);
});

test("GPT 모델을 말한 요청은 플러그인 에이전트에 적용하지 않고 고정 모델로 시작한다", async ($, on) => {
  // given
  environment(on, undefined, requestWorld());
  const received = requestSinks(on);
  await $.prompt.submit({ text: "gpt-5.6-luna 모델 high로 돌려줘" });

  // when
  await $.agent.spawn(spawnInput(SCOUT, { model: "gpt-5.6-luna" }));

  // then
  expect(received).toEqual([PINNED]);
});

test("하위 에이전트 프롬프트와 사용자 입력이 아닌 프롬프트는 요청을 만들거나 지우지 않는다", async ($, on) => {
  // given
  environment(on, undefined, requestWorld());
  const received = requestSinks(on);
  await $.prompt.submit({ text: "sub opus max", agentId: AGENT_ID });
  await $.prompt.submit({ text: "notify opus max", origin: { kind: "task-notification" } });
  await $.agent.spawn(spawnInput(SCOUT, { model: "opus", tool_use_id: "toolu_a" }));
  await $.prompt.submit({ text: "opus 모델 max effort로 검토해줘", origin: { kind: "composer" } });

  // when
  await $.prompt.submit({ text: "작업이 끝났다는 알림", origin: { kind: "task-notification" } });
  await $.agent.spawn(spawnInput(SCOUT, { model: "opus", tool_use_id: "toolu_b" }));

  // then
  expect(received).toEqual([PINNED, OPUS]);
});

test("요청한 모델과 다른 모델로 응답하면 고정 실패로 기록하고 이후 요청을 거절한다", async ($, on) => {
  // given
  const data = environment(on, undefined, requestWorld());
  requestSinks(on);
  stepSink(on, [], PINNED);
  await $.prompt.submit({ text: "opus 모델로 검토해줘" });
  await $.agent.spawn(spawnInput(SCOUT, { model: "opus" }));

  // when
  await step($, { agentId: "agent-1" });
  const second = await step($, { agentId: "agent-1", index: 1 });

  // then
  expect(data.roles[SESSION][0]).toEqual(expect.objectContaining({ model: OPUS, mismatch: true }));
  expect(second.result.stopReason).toBe("refusal");
});

test("role_pinning 옵션이 꺼지면 프롬프트 요청도 기록하지 않는다", { options: { role_pinning: false } }, async ($, on) => {
  // given
  const data = environment(on, undefined, requestWorld());
  on("prompt.submit", (_$, e) => ({ text: e.text }));

  // when
  await $.prompt.submit({ text: "opus max" });

  // then
  expect(data.requests).toBeUndefined();
});
