export const UNSUPPORTED_HOST_MESSAGE =
  "GPT 요청을 처리할 수 없습니다. 이 플러그인은 Claude Code에서 GPT 모델을 실행하지 않습니다. `/model claude-opus-5-5`로 Claude 모델을 선택하세요.";

async function* refusal(event, message) {
  yield { kind: "text", index: 0, text: message };
  yield { kind: "stop", stopReason: "refusal", usage: null };
  return {
    turnId: event.turnId,
    index: event.index,
    answer: message,
    toolUses: [],
    stopReason: "refusal",
    usage: null,
  };
}

export function registerGpt(on) {
  on("turn.step", { model: /^gpt-/ }, async function* ($, event, next) {
    if (event.agentId !== undefined) return yield* next(event);
    return yield* refusal(event, UNSUPPORTED_HOST_MESSAGE);
  }).catch(async function* ($, event, next) {
    return yield* next(event);
  });
}
