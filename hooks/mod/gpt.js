const GPT_MODELS = Object.freeze(["gpt-6.1-sol", "gpt-6-luna"]);

export const UNSUPPORTED_HOST_MESSAGE =
  "GPT 요청을 처리할 수 없습니다. 호스트에 완전한 도구 입력 스키마가 없고 재개 후 고정된 시스템 프롬프트 접근도 미검증이므로 GPT 연결이 비활성화되어 있습니다. Claude Code를 업데이트해도 이 경로는 자동으로 활성화되지 않습니다.";

export function isPinnedGptModel(model) {
  return typeof model === "string" && GPT_MODELS.includes(model);
}

export function registerGpt(on) {
  on("turn.step", { model: ["gpt-6.1-sol", "gpt-6-luna"] }, async function* ($, event, next) {
    if (event.agentId !== undefined || !isPinnedGptModel(event.model)) {
      return yield* next(event);
    }

    yield { kind: "text", index: 0, text: UNSUPPORTED_HOST_MESSAGE };
    yield { kind: "stop", stopReason: "refusal", usage: null };
    return {
      turnId: event.turnId,
      index: event.index,
      answer: UNSUPPORTED_HOST_MESSAGE,
      toolUses: [],
      stopReason: "refusal",
      usage: null,
    };
  }).catch(async function* ($, event, next) {
    return yield* next(event);
  });
}
