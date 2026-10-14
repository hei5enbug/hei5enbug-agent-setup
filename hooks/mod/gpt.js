const GPT_MODELS = Object.freeze(["gpt-6.1-sol", "gpt-5.6-luna"]);

export const UNSUPPORTED_HOST_MESSAGE =
  "GPT 요청을 처리할 수 없습니다. 이 플러그인 버전과 일치하는 활성 설치본을 사용하고, 소스 체크아웃에서 `uv run --extra claude-gpt python scripts/claude_gpt.py launch --profile <profile-id> -- <Claude arguments>`로 Claude Code를 시작하세요. `/model` 선택기에서 `s`를 누르면 새 세션 기본값은 바뀌지 않습니다. `Enter` 또는 `/model <name>`은 사용자 기본값을 저장합니다. 일반 Claude 세션에서 거부되면 `/model claude-opus-5-5`를 입력해 기본값을 복구하세요. Mod는 기본 모델을 설정할 수 없습니다.";

const GPT_FAILURE_MESSAGE =
  "GPT 요청을 전달하는 중 오류가 발생해 중단했습니다.";
const LUNA_PIN_MESSAGE = "GPT Luna는 gpt-5.6-luna와 xhigh로만 실행할 수 있습니다.";

function isLunaModel(model) {
  return typeof model === "string" && /^gpt-.*-luna$/.test(model);
}

export function isPinnedGptModel(model) {
  return typeof model === "string" && GPT_MODELS.includes(model);
}

function isMainGptTurn(event) {
  return event?.agentId === undefined && isPinnedGptModel(event?.model);
}

export async function hasMatchingGptGateway($) {
  try {
    const gatewayUrl = await $.env.get("HEI5ENBUG_GPT_GATEWAY_URL");
    const anthropicBaseUrl = await $.env.get("ANTHROPIC_BASE_URL");
    return typeof gatewayUrl === "string" && gatewayUrl.length > 0 && gatewayUrl === anthropicBaseUrl;
  } catch {
    return false;
  }
}

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
  on("turn.step", { model: /^gpt-.*-(?:sol|luna)$/ }, async function* ($, event, next) {
    if (isLunaModel(event.model) && event.model !== "gpt-5.6-luna") {
      return yield* refusal(event, LUNA_PIN_MESSAGE);
    }
    const pinnedEvent = isLunaModel(event.model) ? { ...event, effort: "xhigh" } : event;
    if (!isMainGptTurn(event)) {
      return yield* next(pinnedEvent);
    }

    if (!(await hasMatchingGptGateway($))) {
      return yield* refusal(event, UNSUPPORTED_HOST_MESSAGE);
    }

    return yield* next(pinnedEvent);
  }).catch(async function* ($, event, next) {
    if (isMainGptTurn(event) || isLunaModel(event?.model)) {
      return yield* refusal(event, GPT_FAILURE_MESSAGE);
    }

    return yield* next(event);
  });
}
