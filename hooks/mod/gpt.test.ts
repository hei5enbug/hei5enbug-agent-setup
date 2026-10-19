import { expect, test } from "claude-code/testing";
import { registerGpt, UNSUPPORTED_HOST_MESSAGE } from "./gpt.js";

function registeredGpt() {
  let options;
  let handler;
  let errorHandler;
  const on = (_event, registeredOptions, callback) => {
    options = registeredOptions;
    handler = callback;
    return {
      catch(callback) {
        errorHandler = callback;
        return this;
      },
    };
  };
  registerGpt(on);
  return { options, handler, errorHandler };
}

async function collect(stream) {
  const chunks = [];
  while (true) {
    const item = await stream.next();
    if (item.done) return { chunks, result: item.value };
    chunks.push(item.value);
  }
}

function forwarding(calls) {
  return (forwardedEvent) => {
    calls.push(forwardedEvent);
    return (async function* () {
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
}

test("메인 세션의 GPT 요청은 다음 핸들러로 전달하지 않고 안내 문구와 함께 거부한다", async () => {
  // given
  const { handler } = registeredGpt();
  const calls = [];
  const event = { turnId: "main-gpt", index: 2, model: "gpt-6.1-sol" };

  // when
  const run = await collect(handler({}, event, forwarding(calls)));

  // then
  expect(calls).toEqual([]);
  expect(run.chunks).toEqual([
    { kind: "text", index: 0, text: UNSUPPORTED_HOST_MESSAGE },
    { kind: "stop", stopReason: "refusal", usage: null },
  ]);
  expect(run.result).toEqual({
    turnId: "main-gpt",
    index: 2,
    answer: UNSUPPORTED_HOST_MESSAGE,
    toolUses: [],
    stopReason: "refusal",
    usage: null,
  });
  expect(UNSUPPORTED_HOST_MESSAGE).toContain("/model claude-opus-5-5");
});

test("하위 에이전트의 GPT 요청은 바꾸지 않고 그대로 전달한다", async () => {
  // given
  const { handler } = registeredGpt();
  const calls = [];
  const event = { turnId: "agent-gpt", index: 0, model: "gpt-5.6-luna", agentId: "agent-test" };

  // when
  const run = await collect(handler({}, event, forwarding(calls)));

  // then
  expect(calls).toEqual([event]);
  expect(run.result.stopReason).toEqual("end_turn");
  expect(run.chunks[0]?.text).toEqual("passed:gpt-5.6-luna:agent-test");
});

test("필터는 gpt-로 시작하는 모델만 고르고 Claude 요청은 처리 대상에서 제외한다", () => {
  // given
  const { options } = registeredGpt();
  const models = ["gpt-6.1-sol", "gpt-5.6-luna", "gpt-6-luna", "claude-sonnet-5-5", "claude-opus-5-5"];

  // when
  const matched = models.filter((model) => options.model.test(model));

  // then
  expect(matched).toEqual(["gpt-6.1-sol", "gpt-5.6-luna", "gpt-6-luna"]);
});

test("실제 Mod 필터에서 메인 Claude 요청은 그대로 다음 핸들러에 전달한다", async ($, on) => {
  // given
  const forwarded = [];
  on("turn.step", async function* (_$, event) {
    forwarded.push(event);
    yield { kind: "text", index: 0, text: "실행됨" };
    yield { kind: "stop", stopReason: "end_turn", usage: null };
    return { turnId: event.turnId, index: event.index, answer: "실행됨", toolUses: [], stopReason: "end_turn", usage: null };
  });

  // when
  const run = await collect($.turn.step({ turnId: "claude-turn", index: 0, model: "claude-sonnet-5-5", messageCount: 1 }));

  // then
  expect(forwarded.length).toEqual(1);
  expect(run.result.stopReason).toEqual("end_turn");
  expect(run.chunks[0]?.text).toEqual("실행됨");
});

test("실제 Mod 필터에서 메인 GPT 요청은 다음 핸들러에 전달하지 않고 거부한다", async ($, on) => {
  // given
  const forwarded = [];
  on("turn.step", async function* (_$, event) {
    forwarded.push(event);
    yield { kind: "stop", stopReason: "end_turn", usage: null };
    return { turnId: event.turnId, index: event.index, answer: "", toolUses: [], stopReason: "end_turn", usage: null };
  });

  // when
  const run = await collect($.turn.step({ turnId: "main-gpt-filter", index: 0, model: "gpt-5.6-luna", messageCount: 1 }));

  // then
  expect(forwarded).toEqual([]);
  expect(run.result.stopReason).toEqual("refusal");
  expect(run.chunks[0]?.text).toEqual(UNSUPPORTED_HOST_MESSAGE);
});

test("오류 경로는 요청을 거부하지 않고 다음 핸들러로 그대로 전달한다", async () => {
  // given
  const { errorHandler } = registeredGpt();
  const calls = [];
  const event = { turnId: "failed-turn", index: 0, model: "gpt-6.1-sol" };

  // when
  const run = await collect(errorHandler({}, event, forwarding(calls)));

  // then
  expect(calls).toEqual([event]);
  expect(run.result.stopReason).toEqual("end_turn");
});
