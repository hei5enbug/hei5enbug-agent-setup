import { expect, test } from "claude-code/testing";

const REFUSAL = "GPT 요청을 처리할 수 없습니다. 호스트에 완전한 도구 입력 스키마가 없고 재개 후 고정된 시스템 프롬프트 접근도 미검증이므로 GPT 연결이 비활성화되어 있습니다. Claude Code를 업데이트해도 이 경로는 자동으로 활성화되지 않습니다.";

test("고정된 GPT 모델의 메인 요청은 모델을 부르지 않고 거부 문구로 끝난다", async ($) => {
  // given
  const models = ["gpt-6.1-sol", "gpt-6-luna"];

  for (const model of models) {
    const stream = $.turn.step({ turnId: "turn-test", index: 0, model, messageCount: 1 });
    const chunks = [];

    // when
    for await (const chunk of stream) chunks.push(chunk);

    // then
    expect(chunks).toEqual([
      { kind: "text", index: 0, text: REFUSAL },
      { kind: "stop", stopReason: "refusal", usage: null },
    ]);
  }
});

test("Claude 요청과 하위 에이전트의 GPT 요청은 거부하지 않고 다음 핸들러로 전달한다", {
  plugins: [{
    name: "gpt-route-test-sink",
    tier: "append",
    register(on) {
      on("turn.step", async function* (_$, event) {
        const answer = `passed:${event.model}:${event.agentId ?? "main"}`;
        yield { kind: "text", index: 0, text: answer };
        yield { kind: "stop", stopReason: "end_turn", usage: null };
        return {
          turnId: event.turnId,
          index: event.index,
          answer,
          toolUses: [],
          stopReason: "end_turn",
          usage: null,
        };
      });
    },
  }],
}, async ($) => {
  // given
  const requests = [
    { turnId: "claude-turn", index: 0, model: "claude-sonnet-4-5", messageCount: 1 },
    { turnId: "agent-turn", index: 0, model: "gpt-6-luna", messageCount: 1, agentId: "agent-test" },
  ];

  // when
  const answers = [];
  for (const request of requests) {
    const stream = $.turn.step(request);
    const chunks = [];
    for await (const chunk of stream) chunks.push(chunk);
    answers.push(chunks);
  }

  // then
  expect(answers.map(chunks => chunks.find(chunk => chunk.kind === "text")?.text)).toEqual([
    "passed:claude-sonnet-4-5:main",
    "passed:gpt-6-luna:agent-test",
  ]);
  expect(answers.map(chunks => chunks.at(-1)?.stopReason)).toEqual(["end_turn", "end_turn"]);
});

test("모든 기능 옵션을 꺼도 고정된 GPT 모델의 메인 요청은 계속 거부한다", {
  options: { agent_guard: false, session_approval: false, role_pinning: false, language_guard: false, datagrip_guard: false },
}, async ($) => {
  // given
  const stream = $.turn.step({ turnId: "turn-off", index: 0, model: "gpt-6-luna", messageCount: 1 });
  const chunks = [];

  // when
  for await (const chunk of stream) chunks.push(chunk);

  // then
  expect(chunks.at(-1)).toEqual({ kind: "stop", stopReason: "refusal", usage: null });
  expect(chunks[0]?.text).toContain("GPT 요청을 처리할 수 없습니다");
});
