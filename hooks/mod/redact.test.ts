import { expect, test } from "claude-code/testing";
import { carriesPlaceholder, compilePatterns, maskText, resetSecretPatterns } from "./redact.js";

const PATTERNS_FILE = "config/secret-patterns.json";
const ALNUM = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789";
const PATTERNS = JSON.stringify({
  placeholder: "(.)\\1{9}",
  patterns: [
    { name: "github-token", pattern: "\\bgh[pousr]_[A-Za-z0-9]{36,}", placeholder: true },
    {
      name: "bearer-token",
      pattern: "(\\bAuthorization\\s*:\\s*Bearer\\s+)((?=[A-Za-z0-9._~+/=-]*[0-9])[A-Za-z0-9._~+/=-]{16,})()",
      flags: "i",
      partial: true,
      placeholder: true,
    },
  ],
});

function fake(length: number, seed = 1) {
  return Array.from({ length }, (_, index) => ALNUM[(index * 7 + seed * 13 + Math.floor(index / 5)) % ALNUM.length]).join("");
}

const TOKEN = `ghp_${fake(36)}`;
const MASK = "[REDACTED:github-token]";

function world(on, options: { patterns?: string | null; answer?: (e: any) => any } = {}) {
  const logs: string[] = [];
  const seen: any[] = [];
  resetSecretPatterns();
  on("fs.read", (_$, e) => {
    if (e.path.endsWith(PATTERNS_FILE) && options.patterns !== null) return { value: options.patterns ?? PATTERNS };
    throw new Error(`no such file: ${e.path}`);
  });
  on("ui.log", (_$, e) => {
    logs.push(e.text);
    return { value: undefined };
  });
  on("tool.call", (_$, e) => {
    seen.push(e);
    return options.answer?.(e) ?? { ref: 7, result: { stdout: "", stderr: "" }, text: "" };
  });
  return { logs, seen };
}

test("Bash 결과는 stdout과 stderr의 토큰만 종류가 보이게 가리고 나머지 필드와 모양은 그대로 둔다", async ($, on) => {
  // given
  const { logs } = world(on, {
    answer: () => ({
      ref: 7,
      isReadOnly: true,
      result: { stdout: `token ${TOKEN} end\nAuthorization: Bearer ${fake(24)}9`, stderr: `warn ${TOKEN}`, interrupted: false, isImage: false },
      text: `token ${TOKEN}`,
    }),
  });

  // when
  const answer = await $.tool.call({ tool: "Bash", command: "cat .env" });

  // then
  expect(answer.result).toEqual({
    stdout: `token ${MASK} end\nAuthorization: Bearer [REDACTED:bearer-token]`,
    stderr: `warn ${MASK}`,
    interrupted: false,
    isImage: false,
  });
  expect(answer.ref).toBeUndefined();
  expect(answer.text).toBeUndefined();
  expect(logs).toHaveLength(1);
  expect(logs[0]).toContain("masked 3 secret values");
  expect(logs[0]).not.toContain(TOKEN);
});

test("도구에 넘기는 인자는 건드리지 않는다", async ($, on) => {
  // given
  const { seen } = world(on);
  const command = `curl -H 'Authorization: Bearer ${fake(24)}9' https://example.com && echo ${TOKEN}`;

  // when
  await $.tool.call({ tool: "Bash", command });

  // then
  expect(seen[0].command).toBe(command);
});

test("Read 텍스트 결과는 file.content만 가리고 경로와 줄 수는 그대로 둔다", async ($, on) => {
  // given
  world(on, {
    answer: () => ({
      result: { type: "text", file: { filePath: `/work/${TOKEN}.txt`, content: `a=${TOKEN}\nb=2`, numLines: 2, startLine: 1, totalLines: 2 } },
    }),
  });

  // when
  const answer = await $.tool.call({ tool: "Read", file_path: "/work/a.txt" });

  // then
  expect(answer.result).toEqual({
    type: "text",
    file: { filePath: `/work/${TOKEN}.txt`, content: `a=${MASK}\nb=2`, numLines: 2, startLine: 1, totalLines: 2 },
  });
});

test("Read 이미지 결과는 base64에 토큰 모양이 있어도 그대로 둔다", async ($, on) => {
  // given
  const result = { type: "image", file: { base64: `${TOKEN}`, type: "image/png", originalSize: 40 } };
  const { logs } = world(on, { answer: () => ({ ref: 3, result, text: "image" }) });

  // when
  const answer = await $.tool.call({ tool: "Read", file_path: "/work/a.png" });

  // then
  expect(answer.result).toEqual(result);
  expect(answer.ref).toBe(3);
  expect(logs).toEqual([]);
});

test("MCP 결과는 content 블록의 text만 가리고 블록 모양과 isError를 그대로 둔다", async ($, on) => {
  // given
  world(on, {
    answer: () => ({
      result: { content: [{ type: "text", text: `key ${TOKEN}` }, { type: "image", data: "AAAA", mimeType: "image/png" }], isError: false, structuredContent: { note: `n ${TOKEN}`, count: 2 } },
    }),
  });

  // when
  const answer = await $.tool.call({ tool: "mcp__demo__fetch", id: "1" });

  // then
  expect(answer.result).toEqual({
    content: [{ type: "text", text: `key ${MASK}` }, { type: "image", data: "AAAA", mimeType: "image/png" }],
    isError: false,
    structuredContent: { note: `n ${MASK}`, count: 2 },
  });
});

test("문자열 결과와 Grep 결과도 같은 모양으로 가린다", async ($, on) => {
  // given
  world(on, {
    answer: (e) => ({ result: e.tool === "Grep" ? { mode: "content", content: `src/a.ts:1:${TOKEN}`, numLines: 1 } : `plain ${TOKEN}` }),
  });

  // when
  const grep = await $.tool.call({ tool: "Grep", pattern: "ghp_" });
  const text = await $.tool.call({ tool: "mcp__demo__echo" });

  // then
  expect(grep.result).toEqual({ mode: "content", content: `src/a.ts:1:${MASK}`, numLines: 1 });
  expect(text.result).toBe(`plain ${MASK}`);
});

test("오류 결과는 text와 result를 모두 가리고 호스트 기록을 가리키는 ref는 버린다", async ($, on) => {
  // given
  world(on, { answer: () => ({ isError: true, ref: 9, result: `Exit code 1\n${TOKEN}`, text: `Exit code 1\n${TOKEN}` }) });

  // when
  const answer = await $.tool.call({ tool: "Bash", command: "false" });

  // then
  expect(answer.isError).toBe(true);
  expect(answer.result).toBe(`Exit code 1\n${MASK}`);
  expect(answer.text).toBe(`Exit code 1\n${MASK}`);
  expect(answer.ref).toBeUndefined();
});

test("가릴 값이 없으면 결과를 그대로 돌려주고 로그를 남기지 않는다", async ($, on) => {
  // given
  const { logs } = world(on, {
    answer: () => ({ ref: 4, isReadOnly: true, result: { stdout: `api_key = config.get('api_key')\nTOKEN=\nid ghp_${fake(35)}`, stderr: "", interrupted: false }, text: "kept" }),
  });

  // when
  const answer = await $.tool.call({ tool: "Bash", command: "cat settings.py" });

  // then
  expect(answer.ref).toBe(4);
  expect(answer.text).toBe("kept");
  expect(answer.isReadOnly).toBe(true);
  expect(answer.result.stdout).toContain("api_key = config.get('api_key')");
  expect(logs).toEqual([]);
});

test("패턴 파일을 읽지 못하면 결과를 바꾸지 않는다", async ($, on) => {
  // given
  const { logs } = world(on, { patterns: null, answer: () => ({ ref: 4, result: { stdout: TOKEN, stderr: "" }, text: TOKEN }) });

  // when
  const answer = await $.tool.call({ tool: "Bash", command: "echo" });

  // then
  expect(answer.result.stdout).toBe(TOKEN);
  expect(answer.ref).toBe(4);
  expect(logs).toEqual([]);
});

test("4MB 뒤의 토큰은 훑지 않고 그 앞의 토큰은 가린다", async ($, on) => {
  // given
  const filler = "x ".repeat(2 * 1024 * 1024 + 8);
  world(on, { answer: () => ({ result: { stdout: `${TOKEN}\n${filler}${TOKEN}`, stderr: TOKEN, interrupted: false } }) });

  // when
  const answer = await $.tool.call({ tool: "Bash", command: "cat big.log" });

  // then
  expect(answer.result.stdout.startsWith(`${MASK}\n`)).toBe(true);
  expect(answer.result.stdout.endsWith(TOKEN)).toBe(true);
  expect(answer.result.stderr).toBe(TOKEN);
});

test("마스킹 도우미는 자리표시자와 한 글자 반복 값을 가리지 않는다", () => {
  // given
  const patterns = compilePatterns(PATTERNS);

  // when
  const kept = maskText(`ghp_${"a".repeat(36)} Authorization: Bearer ${"0".repeat(20)}`, patterns);
  const masked = maskText(`ghp_${fake(36)}`, patterns, { left: 1000 });
  const spent = maskText(`ghp_${fake(36)}`, patterns, { left: 0 });

  // then
  expect(kept.count).toBe(0);
  expect(masked).toEqual({ text: MASK, count: 1 });
  expect(spent.count).toBe(0);
});

test("가려진 자리표시자가 새 내용에 들어 있으면 Edit, Write, MultiEdit, NotebookEdit을 거부하고 도구는 실행하지 않는다", async ($, on) => {
  // given
  const { seen } = world(on);
  const calls = [
    { tool: "Edit", file_path: "/work/a.env", old_string: "a", new_string: `KEY=${MASK}` },
    { tool: "Write", file_path: "/work/a.env", content: `KEY=[REDACTED:aws-access-key-id]` },
    { tool: "MultiEdit", file_path: "/work/a.env", edits: [{ old_string: "a", new_string: "b" }, { old_string: "c", new_string: "[REDACTED:jwt]" }] },
    { tool: "NotebookEdit", notebook_path: "/work/a.ipynb", new_source: `x = "${MASK}"` },
  ];

  // when
  const answers = [];
  for (const call of calls) answers.push(await $.tool.call(call));

  // then
  for (const answer of answers) {
    expect(answer.deny).toContain("[REDACTED:");
    expect(answer.deny).toContain("Edit around the masked span");
  }
  expect(seen).toEqual([]);
});

test("자리표시자가 없는 쓰기와 이전 내용에만 있는 자리표시자는 막지 않는다", async ($, on) => {
  // given
  const { seen } = world(on);

  // when
  const edit = await $.tool.call({ tool: "Edit", file_path: "/work/a.md", old_string: MASK, new_string: "removed" });
  const write = await $.tool.call({ tool: "Write", file_path: "/work/a.md", content: "plain [REDACTED] text" });

  // then
  expect(edit.deny).toBeUndefined();
  expect(write.deny).toBeUndefined();
  expect(seen).toHaveLength(2);
  expect(carriesPlaceholder({ new_string: "a", edits: [null, {}] })).toBe(false);
});

test("secret_redaction 옵션이 꺼지면 결과를 가리지도 쓰기를 막지도 않는다", { options: { secret_redaction: false } }, async ($, on) => {
  // given
  const { logs } = world(on, { answer: () => ({ ref: 4, result: { stdout: TOKEN, stderr: "" }, text: TOKEN }) });

  // when
  const read = await $.tool.call({ tool: "Bash", command: "echo" });
  const write = await $.tool.call({ tool: "Write", file_path: "/work/a.md", content: MASK });

  // then
  expect(read.result.stdout).toBe(TOKEN);
  expect(write.deny).toBeUndefined();
  expect(logs).toEqual([]);
});
