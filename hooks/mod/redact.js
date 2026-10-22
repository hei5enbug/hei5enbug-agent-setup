const RESULT_TOOLS = /^(Bash|Read|Grep|mcp__.+)$/;
const WRITE_TOOLS = /^(Edit|Write|MultiEdit|NotebookEdit)$/;
const SCAN_LIMIT = 4 * 1024 * 1024;
const MAX_DEPTH = 8;
const SKIPPED_KEYS = new Set(["base64", "type", "mimeType", "mediaType", "filePath", "rawOutputPath", "backgroundOutputPath", "outputDir"]);
const PLACEHOLDER_MARK = "[REDACTED:";
const DENY_REASON =
  "This text contains a [REDACTED:...] placeholder, which marks a secret that was masked when it was read. Writing it would replace the real value. Edit around the masked span without rewriting it.";
let compiled;

function isRecord(value) {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

export function compilePatterns(source) {
  const data = typeof source === "string" ? JSON.parse(source) : source;
  if (!isRecord(data) || !Array.isArray(data.patterns)) throw new Error("secret patterns are missing");
  const placeholder = typeof data.placeholder === "string" ? new RegExp(data.placeholder) : null;
  return data.patterns.map((entry) => {
    if (!isRecord(entry) || typeof entry.name !== "string" || typeof entry.pattern !== "string") throw new Error("secret pattern is malformed");
    return {
      name: entry.name,
      regex: new RegExp(entry.pattern, `g${entry.flags ?? ""}`),
      partial: entry.partial === true,
      placeholder: entry.placeholder === true ? placeholder : null,
    };
  });
}

export function maskText(text, patterns, budget = { left: SCAN_LIMIT }) {
  if (typeof text !== "string" || text === "" || budget.left <= 0) return { text, count: 0 };
  const head = text.length > budget.left ? text.slice(0, budget.left) : text;
  budget.left -= head.length;
  let masked = head;
  let count = 0;
  for (const { name, regex, partial, placeholder } of patterns) {
    const label = `[REDACTED:${name}]`;
    masked = masked.replace(regex, (...found) => {
      const secret = partial ? found[2] : found[0];
      if (placeholder !== null && placeholder.test(secret)) return found[0];
      count += 1;
      return partial ? `${found[1]}${label}${found[3]}` : label;
    });
  }
  return count === 0 ? { text, count } : { text: masked + text.slice(head.length), count };
}

export function maskValue(value, patterns, budget = { left: SCAN_LIMIT }, depth = 0) {
  if (typeof value === "string") return maskText(value, patterns, budget);
  if (depth >= MAX_DEPTH || value === null || typeof value !== "object") return { text: value, count: 0 };
  const array = Array.isArray(value);
  if (!array && !isRecord(value)) return { text: value, count: 0 };
  let count = 0;
  const copy = array ? [] : {};
  for (const [key, item] of Object.entries(value)) {
    const inner = !array && SKIPPED_KEYS.has(key) ? { text: item, count: 0 } : maskValue(item, patterns, budget, depth + 1);
    copy[key] = inner.text;
    count += inner.count;
  }
  return count === 0 ? { text: value, count } : { text: copy, count };
}

export function maskedAnswer(answer, patterns) {
  if (answer.deny !== undefined) return { answer, count: 0 };
  const budget = { left: SCAN_LIMIT };
  const result = maskValue(answer.result, patterns, budget);
  const text = answer.isError === true ? maskText(answer.text, patterns, budget) : { text: undefined, count: 0 };
  const count = result.count + text.count;
  if (count === 0) return { answer, count };
  const { ref: _ref, text: _text, isReadOnly: _readOnly, ...rest } = answer;
  return { answer: { ...rest, result: result.text, ...(answer.isError === true ? { text: text.text } : {}) }, count };
}

export function carriesPlaceholder(e) {
  const texts = [e.new_string, e.content, e.new_source];
  if (Array.isArray(e.edits)) for (const edit of e.edits) texts.push(edit?.new_string);
  return texts.some((text) => typeof text === "string" && text.includes(PLACEHOLDER_MARK));
}

async function patternsOf($) {
  if (compiled === undefined) {
    const pending = $.fs.read(`${$.plugin.root}/config/secret-patterns.json`).then(compilePatterns);
    compiled = pending;
    pending.catch(() => {
      if (compiled === pending) compiled = undefined;
    });
  }
  return compiled;
}

export function resetSecretPatterns() {
  compiled = undefined;
}

export function registerSecretRedaction(on) {
  on("tool.call", { tool: WRITE_TOOLS }, ($, e, next) => (carriesPlaceholder(e) ? { deny: DENY_REASON } : next(e))).catch(($, e, next) =>
    next(e),
  );

  on("tool.call", { tool: RESULT_TOOLS }, async ($, e, next) => {
    const answer = await next(e);
    try {
      const { answer: masked, count } = maskedAnswer(answer, await patternsOf($));
      if (count > 0) $.ui.log(`${$.plugin.name}: masked ${count} secret ${count === 1 ? "value" : "values"} in the ${e.tool} result`);
      return masked;
    } catch {
      return answer;
    }
  }).catch(($, e, next) => next(e));
}
