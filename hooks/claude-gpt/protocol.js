export const GPT_MODELS = Object.freeze(["gpt-6.1-sol", "gpt-6-luna"]);

export const UNSUPPORTED_HOST_MESSAGE =
  "GPT 요청을 처리할 수 없습니다. 호스트에 완전한 도구 입력 스키마가 없고 재개 후 고정된 시스템 프롬프트 접근도 미검증이므로 GPT 연결이 비활성화되어 있습니다. Claude Code를 업데이트해도 이 경로는 자동으로 활성화되지 않습니다.";

const isObject = value => value !== null && typeof value === "object" && !Array.isArray(value);
const isSafeInteger = value => Number.isSafeInteger(value) && value >= 0;

export function isPinnedGptModel(model) {
  return typeof model === "string" && GPT_MODELS.includes(model);
}

function validateUsage(usage, model) {
  if (!isObject(usage)) throw new Error("헬퍼 응답의 사용량 데이터가 잘못되었습니다.");
  if (!isSafeInteger(usage.input_tokens) || !isSafeInteger(usage.output_tokens)) {
    throw new Error("헬퍼 응답의 사용량 데이터가 잘못되었습니다.");
  }
  if (usage.cached_input_tokens !== undefined && !isSafeInteger(usage.cached_input_tokens)) {
    throw new Error("헬퍼 응답의 사용량 데이터가 잘못되었습니다.");
  }
  if (usage.reasoning_tokens !== undefined && !isSafeInteger(usage.reasoning_tokens)) {
    throw new Error("헬퍼 응답의 사용량 데이터가 잘못되었습니다.");
  }
  if (usage.cached_input_tokens !== undefined && usage.cached_input_tokens > usage.input_tokens) {
    throw new Error("헬퍼 응답의 사용량 데이터가 잘못되었습니다.");
  }
  return {
    input_tokens: usage.input_tokens - (usage.cached_input_tokens ?? 0),
    output_tokens: usage.output_tokens,
    cache_read_input_tokens: usage.cached_input_tokens ?? 0,
    cache_creation_input_tokens: 0,
    model,
  };
}

function validateToolCall(call, allowedToolNames, seenIds) {
  if (!isObject(call) || typeof call.id !== "string" || !call.id ||
      typeof call.name !== "string" || !call.name || !allowedToolNames.has(call.name) ||
      !isObject(call.arguments)) {
    throw new Error("헬퍼가 제공한 도구 호출이 요청과 일치하지 않습니다.");
  }
  if (seenIds.has(call.id)) throw new Error("헬퍼가 중복 도구 호출 ID를 반환했습니다.");
  seenIds.add(call.id);
  return call;
}

export function parseHelperLine(line) {
  if (typeof line !== "string" || line.length === 0 || line.length > 1_048_576) {
    throw new Error("헬퍼 프로토콜 줄의 크기 또는 형식이 잘못되었습니다.");
  }
  let record;
  try {
    record = JSON.parse(line);
  } catch {
    throw new Error("헬퍼 프로토콜 JSON을 읽을 수 없습니다.");
  }
  if (!isObject(record) || record.protocol_version !== 1 || typeof record.type !== "string") {
    throw new Error("헬퍼 프로토콜 버전 또는 레코드가 잘못되었습니다.");
  }
  return record;
}

export async function* nativeChunksFromRecords(records, {
  model,
  turnId,
  index,
  allowedToolNames = [],
  priorCallIds = [],
  processResult = Promise.resolve({ code: 0, signal: null }),
}) {
  if (!isPinnedGptModel(model) || typeof turnId !== "string" || !turnId || !isSafeInteger(index)) {
    throw new Error("헬퍼 응답에 전달할 턴 ID, 순번 또는 GPT 모델 ID가 잘못되었습니다.");
  }
  if (!Array.isArray(allowedToolNames) || allowedToolNames.some(name => typeof name !== "string" || !name) ||
      new Set(allowedToolNames).size !== allowedToolNames.length) {
    throw new Error("요청에 허용된 도구 이름이 잘못되었습니다.");
  }
  const allowed = new Set(allowedToolNames);
  if (!Array.isArray(priorCallIds) || priorCallIds.some(id => typeof id !== "string" || !id)) {
    throw new Error("대화 기록에 도구 호출 ID가 잘못되었습니다.");
  }
  const seenIds = new Set(priorCallIds);
  if (seenIds.size !== priorCallIds.length) throw new Error("대화 기록에 중복 도구 호출 ID가 있습니다.");
  let terminal = null;
  let textSeen = false;
  let answer = "";
  let finalToolUses = [];
  let finalUsage = null;
  let deferred = [];

  for await (const record of records) {
    if (!isObject(record) || record.protocol_version !== 1 || typeof record.type !== "string") {
      throw new Error("헬퍼 프로토콜 버전 또는 레코드가 잘못되었습니다.");
    }
    if (terminal !== null) throw new Error("헬퍼가 종료 레코드 뒤에 데이터를 반환했습니다.");
    if (record.type === "text_delta") {
      if (Object.keys(record).sort().join(",") !== "protocol_version,text,type" ||
          typeof record.text !== "string" || record.text.length === 0) {
        throw new Error("헬퍼 텍스트 조각이 잘못되었습니다.");
      }
      textSeen = true;
      answer += record.text;
      yield { kind: "text", index: 0, text: record.text };
      continue;
    }
    if (record.type === "error") {
      if (Object.keys(record).sort().join(",") !== "code,protocol_version,type" ||
          typeof record.code !== "string" || !/^[a-z0-9_-]{1,80}$/.test(record.code)) {
        throw new Error("헬퍼 오류 레코드가 잘못되었습니다.");
      }
      terminal = { type: "error", code: record.code };
      continue;
    }
    if (record.type !== "completed" ||
        Object.keys(record).sort().join(",") !== "model,protocol_version,provider_reported_effort,response_id,tool_calls,type,usage" ||
        typeof record.response_id !== "string" ||
        record.response_id.length === 0 || record.model !== model ||
        !Array.isArray(record.tool_calls) ||
        (record.provider_reported_effort !== null &&
          (typeof record.provider_reported_effort !== "string" || !["low", "medium", "high", "xhigh", "max"].includes(record.provider_reported_effort)))) {
      throw new Error("헬퍼 완료 레코드가 잘못되었습니다.");
    }
    const usage = validateUsage(record.usage, model);
    const calls = record.tool_calls.map(call => validateToolCall(call, allowed, seenIds));
    finalToolUses = calls.map(call => ({ name: call.name, input: call.arguments }));
    finalUsage = usage;
    const toolOffset = textSeen ? 1 : 0;
    calls.forEach((call, offset) => {
      const index = toolOffset + offset;
      deferred.push({ kind: "tool", index, id: call.id, name: call.name });
      deferred.push({ kind: "input", index, json: JSON.stringify(call.arguments) });
    });
    deferred.push({ kind: "stop", stopReason: calls.length ? "tool_use" : "end_turn", usage });
    terminal = { type: "completed" };
  }

  if (terminal === null) throw new Error("헬퍼 스트림이 완료 또는 오류 없이 끝났습니다.");
  if (terminal.type === "error") throw new Error(`GPT 요청이 실패했습니다 (${terminal.code}).`);
  const result = await processResult;
  if (!isObject(result) || result.code !== 0 || result.signal !== null) {
    throw new Error("GPT 헬퍼가 정상 종료되지 않아 도구 호출을 전달하지 않았습니다.");
  }
  for (const chunk of deferred) yield chunk;
  return {
    turnId,
    index,
    answer,
    toolUses: finalToolUses,
    stopReason: finalToolUses.length ? "tool_use" : "end_turn",
    usage: finalUsage,
  };
}
