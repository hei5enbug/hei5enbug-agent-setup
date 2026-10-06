import { isPinnedGptModel, UNSUPPORTED_HOST_MESSAGE } from "./protocol.js";

export function register(on) {
  on("turn.step", async function* ($, event, next) {
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
  });
}
