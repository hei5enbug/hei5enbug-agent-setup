import { expect, test } from "claude-code/testing";
import { nativeChunksFromRecords, parseHelperLine } from "./protocol.js";

const completed = toolCalls => ({
  protocol_version: 1,
  type: "completed",
  response_id: "resp-test",
  model: "gpt-6-luna",
  provider_reported_effort: "high",
  usage: { input_tokens: 12, cached_input_tokens: 3, output_tokens: 7, reasoning_tokens: 2 },
  tool_calls: toolCalls,
});

async function collect(records, options) {
  const chunks = [];
  let error = null;
  let value;
  try {
    const iterator = nativeChunksFromRecords(records, { turnId: "turn-test", index: 0, ...options });
    while (true) {
      const step = await iterator.next();
      if (step.done) {
        value = step.value;
        break;
      }
      chunks.push(step.value);
    }
  } catch (caught) {
    error = String(caught);
  }
  return { chunks, error, value };
}

test("완료 레코드와 헬퍼 종료를 확인한 뒤 도구 호출을 전달한다", async ($) => {
  // given
  const records = [
    { protocol_version: 1, type: "text_delta", text: "안녕" },
    completed([{ id: "call-1", name: "Read", arguments: { file_path: "a.md" } }]),
  ];

  // when
  const result = await collect(records, { model: "gpt-6-luna", allowedToolNames: ["Read"] });

  // then
  expect(result.error).toBe(null);
  expect(result.chunks).toEqual([
    { kind: "text", index: 0, text: "안녕" },
    { kind: "tool", index: 1, id: "call-1", name: "Read" },
    { kind: "input", index: 1, json: "{\"file_path\":\"a.md\"}" },
    { kind: "stop", stopReason: "tool_use", usage: {
      input_tokens: 9,
      output_tokens: 7,
      cache_read_input_tokens: 3,
      cache_creation_input_tokens: 0,
      model: "gpt-6-luna",
    } },
  ]);
  expect(result.value).toEqual({
    turnId: "turn-test",
    index: 0,
    answer: "안녕",
    toolUses: [{ name: "Read", input: { file_path: "a.md" } }],
    stopReason: "tool_use",
    usage: { input_tokens: 9, output_tokens: 7, cache_read_input_tokens: 3, cache_creation_input_tokens: 0, model: "gpt-6-luna" },
  });
});

test("잘못된 종료나 헬퍼 오류가 있으면 도구 호출을 내보내지 않는다", async ($) => {
  // given
  const calls = [{ id: "call-1", name: "Read", arguments: { file_path: "a.md" } }];
  const cases = [
    [completed(calls), { protocol_version: 1, type: "text_delta", text: "늦은 데이터" }],
    [completed(calls)],
    [{ protocol_version: 1, type: "error", code: "provider_failed" }],
  ];

  // when
  const results = [];
  for (const records of cases) {
    results.push(await collect(records, {
      model: "gpt-6-luna",
      allowedToolNames: ["Read"],
      processResult: Promise.resolve({ code: records.length === 1 && records[0].type === "completed" ? 1 : 0, signal: null }),
    }));
  }

  // then
  for (const result of results) {
    expect(result.error).toBeTruthy();
    expect(result.chunks.some(chunk => chunk.kind === "tool" || chunk.kind === "input")).toBe(false);
  }
});

test("알 수 없는 도구와 중복 호출 ID는 거부한다", async ($) => {
  // given
  const unknown = completed([{ id: "call-1", name: "Bash", arguments: { command: "true" } }]);
  const duplicate = completed([
    { id: "call-1", name: "Read", arguments: { file_path: "a.md" } },
    { id: "call-1", name: "Read", arguments: { file_path: "b.md" } },
  ]);

  // when
  const results = await Promise.all([
    collect([unknown], { model: "gpt-6-luna", allowedToolNames: ["Read"] }),
    collect([duplicate], { model: "gpt-6-luna", allowedToolNames: ["Read"] }),
  ]);

  // then
  expect(results.every(result => result.error !== null)).toBe(true);
  expect(results.every(result => !result.chunks.some(chunk => chunk.kind === "tool"))).toBe(true);
});

test("잘못된 버전과 잘린 JSON 줄을 프로토콜 오류로 처리한다", async ($) => {
  // given
  const lines = ["{\"protocol_version\":2,\"type\":\"completed\"}", "{\"protocol_version\":1"];

  // when
  const errors = lines.map(line => {
    try {
      parseHelperLine(line);
      return null;
    } catch (error) {
      return String(error);
    }
  });

  // then
  expect(errors.every(error => error !== null)).toBe(true);
});
