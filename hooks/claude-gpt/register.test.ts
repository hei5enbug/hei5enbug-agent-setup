import { expect, test } from "claude-code/testing";

test("GPT 주 요청은 추론하지 않고 호스트 지원 오류로 끝난다", async ($) => {
  // given
  const request = { turnId: "turn-test", index: 0, model: "gpt-6-luna", messageCount: 1 };
  const stream = $.turn.step(request);
  const chunks = [];

  // when
  for await (const chunk of stream) chunks.push(chunk);

  // then
  expect(chunks).toEqual([
    { kind: "text", index: 0, text: "GPT 요청을 처리할 수 없습니다. 호스트에 완전한 도구 입력 스키마가 없고 재개 후 고정된 시스템 프롬프트 접근도 미검증이므로 GPT 연결이 비활성화되어 있습니다. Claude Code를 업데이트해도 이 경로는 자동으로 활성화되지 않습니다." },
    { kind: "stop", stopReason: "refusal", usage: null },
  ]);
  expect(chunks.at(-1)).toEqual({ kind: "stop", stopReason: "refusal", usage: null });
});

test("Claude 요청과 하위 에이전트의 GPT 요청은 다음 핸들러로 전달된다", {
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
