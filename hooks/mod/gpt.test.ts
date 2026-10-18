import { expect, test } from "claude-code/testing";
import { registerGpt } from "./gpt.js";

const GPT_MODELS = ["gpt-6.1-sol", "gpt-5.6-luna"];
const REGISTRY = JSON.stringify({
  pins: { "gpt-luna": "gpt-5.6-luna", "gpt-sol": "gpt-6.1-sol" },
  claude_agents: {},
  effort_rules: { "gpt-5.6-luna": ["high", "xhigh"] },
  gpt_gateway_models: ["gpt-6.1-sol", "gpt-5.6-luna"],
});
const REGISTRY_CONTEXT = { plugin: { root: "/plugin" }, fs: { read: async () => REGISTRY } };

function registryFiles(on) {
  on("fs.read", () => ({ value: REGISTRY }));
}
const LAUNCHER_COMMAND =
  "uv run --extra claude-gpt python scripts/claude_gpt.py launch --profile <profile-id> -- <Claude arguments>";

function registeredGpt() {
  let handler;
  let errorHandler;
  const on = (_event, _options, callback) => {
    handler = callback;
    return {
      catch(callback) {
        errorHandler = callback;
        return this;
      },
    };
  };
  registerGpt(on);
  return { handler, errorHandler };
}

async function collect(stream) {
  const chunks = [];
  while (true) {
    const item = await stream.next();
    if (item.done) return { chunks, result: item.value };
    chunks.push(item.value);
  }
}

function gatewayContext(values) {
  return { env: { get: async (name) => values[name] } };
}

async function invoke(context, event, { fail = false } = {}) {
  const { handler, errorHandler } = registeredGpt();
  const $ = { ...REGISTRY_CONTEXT, ...context };
  const calls = [];
  const next = (forwardedEvent) => {
    calls.push(forwardedEvent);
    return (async function* () {
      if (fail) throw new Error("gateway failure");
      const answer = `passed:${forwardedEvent.model}:${forwardedEvent.agentId ?? "main"}`;
      yield { kind: "text", index: 0, text: answer };
      yield { kind: "stop", stopReason: "end_turn", usage: null };
      return {
        turnId: forwardedEvent.turnId,
        index: forwardedEvent.index,
        answer,
        toolUses: [],
        stopReason: "end_turn",
        usage: null,
      };
    })();
  };

  try {
    return { ...(await collect(handler($, event, next))), calls };
  } catch {
    return { ...(await collect(errorHandler($, event, next))), calls };
  }
}

test("런처 URL이 없거나 다르면 두 GPT 모델을 거부하고 같으면 한 번 전달한다", async () => {
  // given
  const environments = [
    ["없음", undefined, false],
    ["gateway만 있음", { HEI5ENBUG_GPT_GATEWAY_URL: "http://127.0.0.1/gpt" }, false],
    ["Anthropic URL만 있음", { ANTHROPIC_BASE_URL: "http://127.0.0.1/gpt" }, false],
    ["서로 다름", {
      HEI5ENBUG_GPT_GATEWAY_URL: "http://127.0.0.1/gpt",
      ANTHROPIC_BASE_URL: "http://127.0.0.1/other",
    }, false],
    ["gateway URL이 비어 있음", {
      HEI5ENBUG_GPT_GATEWAY_URL: "",
      ANTHROPIC_BASE_URL: "",
    }, false],
    ["같음", {
      HEI5ENBUG_GPT_GATEWAY_URL: "http://127.0.0.1/gpt",
      ANTHROPIC_BASE_URL: "http://127.0.0.1/gpt",
    }, true],
  ];
  const results = [];

  // when
  for (const model of GPT_MODELS) {
    for (const [name, values, allowed] of environments) {
      const event = { turnId: `${model}-${name}`, index: 0, model };
      const run = await invoke(values === undefined ? {} : gatewayContext(values), event);
      results.push({
        model,
        environment: name,
        allowed,
        calls: run.calls.length,
        stopReason: run.result.stopReason,
        text: run.chunks[0]?.text,
      });
    }
  }

  // then
  for (const result of results) {
    expect(result.calls).toEqual(result.allowed ? 1 : 0);
    expect(result.stopReason).toEqual(result.allowed ? "end_turn" : "refusal");
    if (!result.allowed) expect(result.text).toContain(LAUNCHER_COMMAND);
  }
});

test("환경 API가 없거나 사용할 수 없으면 두 고정 GPT 모델을 전달하지 않고 거부한다", async () => {
  // given
  const contexts = [
    {},
    { env: {} },
    { env: { get: undefined } },
    { env: { get: () => { throw new Error("unavailable"); } } },
    { env: { get: async () => { throw new Error("unavailable"); } } },
  ];
  const results = [];

  // when
  for (const context of contexts) {
    for (const model of GPT_MODELS) {
      const run = await invoke(context, { turnId: model, index: 0, model });
      results.push(run);
    }
  }

  // then
  for (const result of results) {
    expect(result.calls).toEqual([]);
    expect(result.result.stopReason).toEqual("refusal");
  }
});

test("모든 기능 옵션을 꺼도 런처 URL이 없으면 메인 GPT 요청을 거부한다", {
  options: { agent_guard: false, role_pinning: false, language_guard: false, datagrip_guard: false },
}, async ($, on) => {
  // given
  registryFiles(on);
  on("env.get", () => ({ value: undefined }));
  const stream = $.turn.step({ turnId: "turn-off", index: 0, model: "gpt-5.6-luna", messageCount: 1 });
  const chunks = [];

  // when
  for await (const chunk of stream) chunks.push(chunk);

  // then
  expect(chunks.at(-1)).toEqual({ kind: "stop", stopReason: "refusal", usage: null });
  expect(chunks[0]?.text).toContain(LAUNCHER_COMMAND);
});

test("호스트 환경 API가 같은 런처 URL을 반환하면 메인 GPT 요청을 한 번 전달한다", async ($, on) => {
  // given
  registryFiles(on);
  const names = [];
  const forwarded = [];
  on("env.get", (_$, event) => {
    names.push(event.name);
    return { value: "http://127.0.0.1/gateway" };
  });
  on("turn.step", async function* (_$, event) {
    forwarded.push(event);
    yield { kind: "text", index: 0, text: "완료" };
    yield { kind: "stop", stopReason: "end_turn", usage: null };
    return { turnId: event.turnId, index: event.index, answer: "완료", toolUses: [], stopReason: "end_turn", usage: null };
  });

  // when
  const result = await collect($.turn.step({ turnId: "turn-gateway", index: 0, model: "gpt-6.1-sol", messageCount: 1 }));

  // then
  expect(names).toEqual(["HEI5ENBUG_GPT_GATEWAY_URL", "ANTHROPIC_BASE_URL"]);
  expect(forwarded.length).toEqual(1);
  expect(result.result.stopReason).toEqual("end_turn");
  expect(result.chunks[0]?.text).toEqual("완료");
});

test("Claude 요청은 그대로 전달하고 하위 Luna 요청은 xhigh로 전달한다", async () => {
  // given
  const events = [
    { turnId: "claude-turn", index: 0, model: "claude-sonnet-5-5" },
    { turnId: "agent-turn", index: 0, model: "gpt-5.6-luna", agentId: "agent-test" },
  ];
  const results = [];

  // when
  for (const event of events) results.push(await invoke({}, event));

  // then
  expect(results.map((run) => run.calls)).toEqual([[events[0]], [{ ...events[1], effort: "xhigh" }]]);
  expect(results.map((run) => run.result.stopReason)).toEqual(["end_turn", "end_turn"]);
});

test("다른 Luna 버전은 메인과 하위 에이전트에서 모두 실행 전에 거부한다", async () => {
  // given
  const events = ["gpt-6-luna", "gpt-5.5-luna"].flatMap((model) => [
    { turnId: "main-luna", index: 0, model },
    { turnId: "agent-luna", index: 0, model, agentId: "agent-test" },
  ]);

  // when
  const results = await Promise.all(events.map((event) => invoke({}, event)));

  // then
  for (const run of results) {
    expect(run.calls).toEqual([]);
    expect(run.result.stopReason).toEqual("refusal");
    expect(run.chunks[0]?.text).toContain("gpt-5.6-luna");
  }
});

test("실제 Mod 필터에서도 이전 Luna 요청을 다음 핸들러로 전달하지 않는다", async ($, on) => {
  // given
  registryFiles(on);
  const forwarded = [];
  on("turn.step", async function* (_$, event) {
    forwarded.push(event);
    yield { kind: "text", index: 0, text: "실행됨" };
    yield { kind: "stop", stopReason: "end_turn", usage: null };
    return { turnId: event.turnId, index: event.index, answer: "실행됨", toolUses: [], stopReason: "end_turn", usage: null };
  });

  // when
  const run = await collect($.turn.step({ turnId: "old-luna-filter", index: 0, model: "gpt-6-luna", messageCount: 1 }));

  // then
  expect(forwarded).toEqual([]);
  expect(run.result.stopReason).toEqual("refusal");
  expect(run.chunks[0]?.text).toContain("gpt-5.6-luna");
});

test("Luna의 요청 추론 강도가 high나 xhigh면 그대로 두고 없거나 다르면 xhigh로 한 번 전달한다", async () => {
  // given
  const context = gatewayContext({
    HEI5ENBUG_GPT_GATEWAY_URL: "http://127.0.0.1/gpt",
    ANTHROPIC_BASE_URL: "http://127.0.0.1/gpt",
  });
  const events = [undefined, "low", "medium", "high", "xhigh", "max"].map((effort) => ({
    turnId: "pinned-luna", index: 0, model: "gpt-5.6-luna", effort,
  }));

  // when
  const results = await Promise.all(events.map((event) => invoke(context, event)));

  // then
  for (let index = 0; index < events.length; index++) {
    const effort = ["high", "xhigh"].includes(events[index].effort) ? events[index].effort : "xhigh";
    expect(results[index].calls).toEqual([{ ...events[index], effort }]);
    expect(results[index].result.stopReason).toEqual("end_turn");
  }
});

test("게이트웨이가 실패한 메인 GPT 요청은 다시 전달하지 않는다", async () => {
  // given
  const context = gatewayContext({
    HEI5ENBUG_GPT_GATEWAY_URL: "http://127.0.0.1/gpt",
    ANTHROPIC_BASE_URL: "http://127.0.0.1/gpt",
  });
  const event = { turnId: "failed-turn", index: 0, model: "gpt-6.1-sol" };

  // when
  const run = await invoke(context, event, { fail: true });

  // then
  expect(run.calls).toEqual([event]);
  expect(run.result.stopReason).toEqual("refusal");
  expect(run.chunks[0]?.text).toContain("GPT 요청을 전달하는 중 오류가 발생해 중단했습니다");
});

test("레지스트리를 읽지 못하면 GPT 요청을 전달하지 않고 중단한다", async () => {
  // given
  const context = {
    plugin: { root: "/missing" },
    fs: { read: async () => { throw new Error("registry missing"); } },
  };
  const event = { turnId: "no-registry", index: 0, model: "gpt-6.1-sol" };

  // when
  const run = await invoke(context, event);

  // then
  expect(run.calls).toEqual([]);
  expect(run.result.stopReason).toEqual("refusal");
  expect(run.chunks[0]?.text).toContain("GPT 요청을 전달하는 중 오류가 발생해 중단했습니다");
});
