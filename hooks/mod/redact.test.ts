import { expect, test } from "claude-code/testing";
import { carriesIssuedPlaceholder, compilePatterns, createIssuer, markerIds, maskText, maskValue, resetSecretPatterns } from "./redact.js";

const PATTERNS_FILE = "config/secret-patterns.json";
const ALNUM = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789";
const PATTERNS = JSON.stringify({
  placeholder: "(.)\\1{9}",
  patterns: [
    { name: "aws-access-key-id", pattern: "\\b(?:AKIA|ASIA)[0-9A-Z]{16}\\b", placeholder: true },
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
const KEY_ID = `AKIA${fake(16, 2).toUpperCase()}`;
const BLOB = `${fake(40, 3)}/${KEY_ID}/${fake(40, 4)}`;

const ID = /:[0-9a-f]{6}\]/g;

function plain<T>(value: T): T {
  return typeof value === "string" ? (value.replace(ID, "]") as T) : JSON.parse(JSON.stringify(value).replace(ID, "]"));
}

function world(on, options: { patterns?: string | null; answer?: (e: any) => any; language?: string } = {}) {
  const logs: string[] = [];
  const seen: any[] = [];
  resetSecretPatterns();
  if (options.language !== undefined) on("settings.read", () => ({ value: { language: options.language } }));
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
  expect(plain(answer.result)).toEqual({
    stdout: `token ${MASK} end\nAuthorization: Bearer [REDACTED:bearer-token]`,
    stderr: `warn ${MASK}`,
    interrupted: false,
    isImage: false,
  });
  expect(answer.ref).toBeUndefined();
  expect(answer.text).toBeUndefined();
  expect(logs).toEqual(["masked 3 secret values in the Bash result"]);
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

test("Read 텍스트 결과는 file.content의 토큰만 가리고 경로와 줄 수는 그대로 둔다", async ($, on) => {
  // given
  world(on, {
    answer: () => ({
      result: { type: "text", file: { filePath: "/work/a.txt", content: `a=${TOKEN}\nb=2`, numLines: 2, startLine: 1, totalLines: 2 } },
    }),
  });

  // when
  const answer = await $.tool.call({ tool: "Read", file_path: "/work/a.txt" });

  // then
  expect(plain(answer.result)).toEqual({
    type: "text",
    file: { filePath: "/work/a.txt", content: `a=${MASK}\nb=2`, numLines: 2, startLine: 1, totalLines: 2 },
  });
});

test("이미지와 PDF의 base64 덩어리는 같은 객체의 type이나 mime이 알려 줄 때만 건너뛴다", async ($, on) => {
  // given
  const image = { type: "image", file: { base64: BLOB, type: "image/png", originalSize: 40 } };
  const pdf = { type: "pdf", file: { filePath: "/work/a.pdf", base64: BLOB, originalSize: 40 } };
  const block = { content: [{ type: "image", data: BLOB, mimeType: "image/png" }] };
  const { logs } = world(on, { answer: (e) => ({ ref: 3, result: e.tool === "Read" ? (e.file_path.endsWith("png") ? image : pdf) : block, text: "binary" }) });

  // when
  const png = await $.tool.call({ tool: "Read", file_path: "/work/a.png" });
  const doc = await $.tool.call({ tool: "Read", file_path: "/work/a.pdf" });
  const mcp = await $.tool.call({ tool: "mcp__demo__shot" });

  // then
  expect(png.result).toEqual(image);
  expect(doc.result).toEqual(pdf);
  expect(mcp.result).toEqual(block);
  expect(png.ref).toBe(3);
  expect(logs).toEqual([]);
});

test("키 이름이 base64나 data여도 type과 mime이 이진을 가리키지 않으면 가린다", async ($, on) => {
  // given
  world(on, {
    answer: () => ({ result: { content: [{ type: "text", data: BLOB, base64: `${BLOB}` }], file: { base64: BLOB, filePath: `/x/${TOKEN}` } } }),
  });

  // when
  const answer = await $.tool.call({ tool: "mcp__demo__fetch" });

  // then
  const masked = plain(answer.result.content[0]);
  expect(masked.data).toContain("[REDACTED:aws-access-key-id]");
  expect(masked.base64).toContain("[REDACTED:aws-access-key-id]");
  expect(plain(answer.result.file.base64)).toContain("[REDACTED:aws-access-key-id]");
  expect(plain(answer.result.file.filePath)).toBe(`/x/${MASK}`);
});

test("MCP 결과는 키 이름과 상관없이 모든 문자열을 가리고 블록 모양과 isError를 그대로 둔다", async ($, on) => {
  // given
  world(on, {
    answer: () => ({
      result: { content: [{ type: "text", text: `key ${TOKEN}` }, { type: "image", data: "AAAA", mimeType: "image/png" }], isError: false, structuredContent: { note: `n ${TOKEN}`, count: 2, filePath: `https://example.com/${TOKEN}`, type: `t ${TOKEN}` } },
    }),
  });

  // when
  const answer = await $.tool.call({ tool: "mcp__demo__fetch", id: "1" });

  // then
  expect(plain(answer.result)).toEqual({
    content: [{ type: "text", text: `key ${MASK}` }, { type: "image", data: "AAAA", mimeType: "image/png" }],
    isError: false,
    structuredContent: { note: `n ${MASK}`, count: 2, filePath: `https://example.com/${MASK}`, type: `t ${MASK}` },
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
  expect(plain(grep.result)).toEqual({ mode: "content", content: `src/a.ts:1:${MASK}`, numLines: 1 });
  expect(plain(text.result)).toBe(`plain ${MASK}`);
});

test("오류 결과는 text와 result를 모두 가리고 호스트 기록을 가리키는 ref는 버린다", async ($, on) => {
  // given
  world(on, { answer: () => ({ isError: true, ref: 9, result: `Exit code 1\n${TOKEN}`, text: `Exit code 1\n${TOKEN}` }) });

  // when
  const answer = await $.tool.call({ tool: "Bash", command: "false" });

  // then
  expect(answer.isError).toBe(true);
  expect(plain(answer.result)).toBe(`Exit code 1\n${MASK}`);
  expect(plain(answer.text)).toBe(`Exit code 1\n${MASK}`);
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
  expect(plain(answer.result.stdout).startsWith(`${MASK}\n`)).toBe(true);
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

async function issue($, token = TOKEN, command = "cat .env") {
  const answer = await $.tool.call({ tool: "Bash", command: `${command} ${token.slice(-4)}` });
  const found = answer.result.stdout.match(/\[REDACTED:[a-z-]+:[0-9a-f]{6}\]/);
  return found[0] as string;
}

const secretOut = (token: string) => (e: any) => (e.tool === "Bash" ? { ref: 7, result: { stdout: `v=${token}`, stderr: "" }, text: "" } : undefined);

test("마스킹한 값마다 세션이 발급한 id가 붙고 같은 값은 같은 id를 다시 쓰고 다른 값은 다른 id를 받는다", async ($, on) => {
  // given
  const other = `ghp_${fake(36, 5)}`;
  const outputs = [TOKEN, TOKEN, other];
  world(on, { answer: () => ({ result: { stdout: `v=${outputs.shift()}`, stderr: "" } }) });

  // when
  const first = await issue($);
  const again = await issue($);
  const second = await issue($, other);

  // then
  expect(first).toMatch(/^\[REDACTED:github-token:[0-9a-f]{6}\]$/);
  expect(again).toBe(first);
  expect(second).not.toBe(first);
});

test("한 결과 안의 서로 다른 값은 서로 다른 id를 받고 같은 값은 같은 id를 받는다", async ($, on) => {
  // given
  const other = `ghp_${fake(36, 6)}`;
  world(on, { answer: () => ({ result: { stdout: `${TOKEN} ${other} ${TOKEN}`, stderr: "" } }) });

  // when
  const answer = await $.tool.call({ tool: "Bash", command: "cat .env" });

  // then
  const [one, two, three] = answer.result.stdout.split(" ");
  expect(one).toBe(three);
  expect(two).not.toBe(one);
  expect(markerIds({ content: answer.result.stdout })).toHaveLength(3);
});

test("발급한 id가 붙은 자리표시자를 쓰는 Edit, Write, MultiEdit, NotebookEdit은 거부하고 도구는 실행하지 않는다", async ($, on) => {
  // given
  const { seen } = world(on, { answer: secretOut(TOKEN) });
  const marker = await issue($);
  seen.length = 0;
  const calls = [
    { tool: "Edit", file_path: "/work/a.env", old_string: "a", new_string: `KEY=${marker}` },
    { tool: "Write", file_path: "/work/a.env", content: `KEY=${marker}` },
    { tool: "MultiEdit", file_path: "/work/a.env", edits: [{ old_string: "a", new_string: "b" }, { old_string: "c", new_string: `x ${marker}` }] },
    { tool: "NotebookEdit", notebook_path: "/work/a.ipynb", new_source: `x = "${marker}"` },
  ];

  // when
  const answers = [];
  for (const call of calls) answers.push(await $.tool.call(call));

  // then
  for (const answer of answers) {
    expect(answer.deny).toContain("[REDACTED:");
    expect(answer.deny).toContain("Leave the masked span out of what you write");
    expect(answer.deny).toContain("Writing it would save the marker, not the secret");
  }
  expect(seen).toEqual([]);
});

test("새 파일 쓰기와 기존 파일 편집의 거부 문구는 같고 기존 값을 덮어쓴다고 말하지 않는다", async ($, on) => {
  // given
  const { seen } = world(on, { answer: secretOut(TOKEN) });
  const marker = await issue($);
  seen.length = 0;

  // when
  const created = await $.tool.call({ tool: "Write", file_path: "/work/new.env", content: `KEY=${marker}` });
  const edited = await $.tool.call({ tool: "Edit", file_path: "/work/existing.env", old_string: "KEY=old", new_string: `KEY=${marker}` });

  // then
  expect(created.deny).toBe(edited.deny);
  expect(created.deny).toMatch(/^Blocked: /);
  expect(created.deny).not.toMatch(/replace|overwrite/i);
  expect(seen).toEqual([]);
});

test("응답 언어 설정이 한국어면 자리표시자 쓰기 거부와 훅 context 보류 문구를 한국어로 쓴다", async ($, on) => {
  // given
  const { seen } = world(on, {
    language: "ko-KR",
    answer: (e) => (e.tool === "Bash" && e.command.startsWith("ctx") ? { ref: 5, result: { stdout: "clean", stderr: "" }, text: "clean", context: [`note ${TOKEN}`] } : secretOut(TOKEN)(e)),
  });
  const marker = await issue($);
  seen.length = 0;

  // when
  const created = await $.tool.call({ tool: "Write", file_path: "/work/new.env", content: `KEY=${marker}` });
  const edited = await $.tool.call({ tool: "Edit", file_path: "/work/existing.env", old_string: "KEY=old", new_string: `KEY=${marker}` });
  const withheld = await $.tool.call({ tool: "Bash", command: "ctx" });

  // then
  expect(created.deny).toBe("차단됨: 이 텍스트에 가린 비밀 값의 [REDACTED:...] 표시가 있습니다. 그대로 쓰면 실제 값 대신 표시가 저장됩니다. 가린 부분은 쓰는 내용에서 빼세요.");
  expect(edited.deny).toBe(created.deny);
  expect(withheld.deny).toContain("보류했습니다");
  expect(withheld.deny).not.toContain(TOKEN);
});

test("응답 언어 설정이 영어이거나 읽을 수 없으면 영어 문구를 쓴다", async ($, on) => {
  // given
  world(on, { language: "English", answer: secretOut(TOKEN) });
  const marker = await issue($);

  // when
  const write = await $.tool.call({ tool: "Write", file_path: "/work/new.env", content: marker });

  // then
  expect(write.deny).toMatch(/^Blocked: /);
});

test("id가 없거나 이 세션이 발급하지 않은 자리표시자는 문서와 테스트 픽스처 쓰기를 막지 않는다", async ($, on) => {
  // given
  const { seen } = world(on, { answer: secretOut(TOKEN) });
  await issue($);
  seen.length = 0;
  const readme = "Each match becomes `[REDACTED:<kind>]` and `[REDACTED:<kind>:<id>]`.";
  const fixture = `expect(mask(token)).toBe("[REDACTED:github-token]")`;
  const calls = [
    { tool: "Edit", file_path: "/work/README.md", old_string: "a", new_string: readme },
    { tool: "Write", file_path: "/work/docs/redaction.md", content: "t=[REDACTED:jwt] and [REDACTED:aws-access-key-id]" },
    { tool: "Write", file_path: "/work/a.test.ts", content: fixture },
    { tool: "Write", file_path: "/work/b.md", content: "[REDACTED:jwt:ffffff] [REDACTED:jwt:abc] [REDACTED:jwt:7F3A9C]" },
    { tool: "MultiEdit", file_path: "/work/c.md", edits: [{ old_string: "a", new_string: "[REDACTED:jwt]" }] },
    { tool: "NotebookEdit", notebook_path: "/work/a.ipynb", new_source: `x = "${MASK}"` },
  ];

  // when
  const answers = [];
  for (const call of calls) answers.push(await $.tool.call(call));

  // then
  for (const answer of answers) expect(answer.deny).toBeUndefined();
  expect(seen).toHaveLength(calls.length);
});

test("자리표시자가 없는 쓰기와 이전 내용에만 있는 자리표시자는 막지 않는다", async ($, on) => {
  // given
  const { seen } = world(on, { answer: secretOut(TOKEN) });
  const marker = await issue($);
  seen.length = 0;

  // when
  const edit = await $.tool.call({ tool: "Edit", file_path: "/work/a.md", old_string: marker, new_string: "removed" });
  const write = await $.tool.call({ tool: "Write", file_path: "/work/a.md", content: "plain [REDACTED] text" });

  // then
  expect(edit.deny).toBeUndefined();
  expect(write.deny).toBeUndefined();
  expect(seen).toHaveLength(2);
  expect(markerIds({ new_string: "a", edits: [null, {}] })).toEqual([]);
  expect(carriesIssuedPlaceholder({ content: "[REDACTED:jwt:abcdef]" }, { abcdef: "x" })).toBe(true);
  expect(carriesIssuedPlaceholder({ content: "[REDACTED:jwt:abcdef]" }, {})).toBe(false);
});

test("모듈을 다시 불러와도 세션 state의 id가 남아 발급한 자리표시자를 계속 막고 같은 값은 같은 id를 쓴다", async ($, on) => {
  // given
  world(on, { answer: secretOut(TOKEN) });
  const marker = await issue($);

  // when
  resetSecretPatterns();
  const reread = await issue($);
  const write = await $.tool.call({ tool: "Write", file_path: "/work/a.env", content: `KEY=${marker}` });

  // then
  expect(reread).toBe(marker);
  expect(write.deny).toContain("[REDACTED:");
});

test("발급기는 알려진 id를 다시 쓰고 새 id만 fresh에 담으며 충돌하지 않는다", () => {
  // given
  const issuer = createIssuer({ aaaaaa: "print-a" });

  // when
  const ids = Array.from({ length: 300 }, (_, index) => issuer.issue("demo", `value-${index}`));

  // then
  expect(new Set(ids).size).toBe(300);
  expect(Object.keys(issuer.fresh)).toHaveLength(300);
  expect(Object.keys(issuer.fresh)).not.toContain("aaaaaa");
  expect(ids.every((id) => /^[0-9a-f]{6}$/.test(id))).toBe(true);
  expect(issuer.issue("demo", "value-7")).toBe(ids[7]);
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

test("훅이 붙인 context에 토큰이 있으면 고쳐 쓸 수 없으므로 결과를 보류한다", async ($, on) => {
  // given
  const { logs } = world(on, { answer: () => ({ ref: 5, result: { stdout: "clean", stderr: "" }, text: "clean", context: [`note ${TOKEN}`, "fine"] }) });

  // when
  const answer = await $.tool.call({ tool: "Bash", command: "echo clean" });

  // then
  expect(answer.deny).toContain("withheld");
  expect(answer.deny).not.toContain(TOKEN);
  expect(answer.result).toBeUndefined();
  expect(logs).toEqual(["withheld the Bash result, hook context held 1 secret value"]);
});

test("오류 결과의 context에 토큰이 있어도 보류하고 깨끗한 context는 그대로 둔다", async ($, on) => {
  // given
  world(on, { answer: (e) => ({ isError: true, ref: 5, result: "boom", text: "boom", context: [e.command === "dirty" ? `why ${TOKEN}` : "why not"] }) });

  // when
  const dirty = await $.tool.call({ tool: "Bash", command: "dirty" });
  const clean = await $.tool.call({ tool: "Bash", command: "clean" });

  // then
  expect(dirty.deny).toContain("withheld");
  expect(clean.context).toEqual(["why not"]);
  expect(clean.ref).toBe(5);
});

test("중첩이 깊은 결과도 끝까지 훑고 깊이 때문에 건너뛰지 않는다", () => {
  // given
  const patterns = compilePatterns(PATTERNS);
  let value: any = { leaf: `deep ${TOKEN}` };
  for (let level = 0; level < 3000; level += 1) value = level % 2 === 0 ? { next: value } : [value];

  // when
  const { text, count } = maskValue(value, patterns);

  // then
  let cursor = text;
  while (cursor.next !== undefined || Array.isArray(cursor)) cursor = Array.isArray(cursor) ? cursor[0] : cursor.next;
  expect(count).toBe(1);
  expect(plain(cursor)).toEqual({ leaf: `deep ${MASK}` });
  expect(value.next === undefined && Array.isArray(value)).toBe(true);
});

test("순환 참조는 무한히 돌지 않고 같은 객체를 두 번 가리키면 두 곳 모두 가린다", () => {
  // given
  const patterns = compilePatterns(PATTERNS);
  const shared = { note: TOKEN };
  const loop: any = { name: TOKEN };
  loop.self = loop;

  // when
  const twice = maskValue({ a: shared, b: shared }, patterns);
  const cyclic = maskValue(loop, patterns);

  // then
  expect(twice.text).toEqual({ a: { note: MASK }, b: { note: MASK } });
  expect(twice.count).toBe(2);
  expect(cyclic.text.name).toBe(MASK);
  expect(cyclic.text.self).toBe(loop);
});

test("소유한 __proto__ 키를 포함해 모든 키를 같은 모양으로 복사하고 프로토타입은 오염시키지 않는다", async ($, on) => {
  // given
  const result = JSON.parse(`{"__proto__": {"polluted": "${TOKEN}"}, "list": [{"__proto__": "${TOKEN}"}], "kept": 1}`);
  world(on, { answer: () => ({ result }) });

  // when
  const answer = await $.tool.call({ tool: "mcp__demo__fetch" });

  // then
  const copy = answer.result;
  expect(Object.keys(copy)).toEqual(["__proto__", "list", "kept"]);
  expect(plain(Object.getOwnPropertyDescriptor(copy, "__proto__")?.value)).toEqual({ polluted: MASK });
  expect(plain(Object.getOwnPropertyDescriptor(copy.list[0], "__proto__")?.value)).toBe(MASK);
  expect(Object.getPrototypeOf(copy)).toBe(Object.prototype);
  expect(({} as any).polluted).toBeUndefined();
  expect(copy.kept).toBe(1);
});
