const RESULT_TOOLS = /^(Bash|Read|Grep|mcp__.+)$/;
const WRITE_TOOLS = /^(Edit|Write|MultiEdit|NotebookEdit)$/;
const SCAN_LIMIT = 4 * 1024 * 1024;
const MAX_NODES = 1_000_000;
const BINARY_TYPE = /^(?:(?:image|audio|video)(?:\/|$)|application\/(?:pdf|octet-stream)|pdf$)/i;
const BASE64_BLOB = /^[A-Za-z0-9+/=\r\n]{64,}$/;
const PLACEHOLDER_MARK = "[REDACTED:";
const ISSUED_MARKER = /\[REDACTED:[^\]\s:]+:([0-9a-f]{6})\]/g;
const DENY_REASON =
  "This text contains a [REDACTED:...] placeholder, which marks a secret that was masked when it was read. Writing it would replace the real value. Edit around the masked span without rewriting it.";
const CONTEXT_DENY_REASON =
  "The result is withheld because text a hook attached to it holds a secret that cannot be masked. Run the call again after removing that source, or read the value another way.";
const ISSUED = { plugin: "hei5enbug-agent-setup", key: "redactIds" };
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

function fingerprint(text) {
  let first = 0xdeadbeef;
  let second = 0x41c6ce57;
  for (let index = 0; index < text.length; index += 1) {
    const code = text.charCodeAt(index);
    first = Math.imul(first ^ code, 2654435761);
    second = Math.imul(second ^ code, 1597334677);
  }
  first = Math.imul(first ^ (first >>> 16), 2246822507) ^ Math.imul(second ^ (second >>> 13), 3266489909);
  second = Math.imul(second ^ (second >>> 16), 2246822507) ^ Math.imul(first ^ (first >>> 13), 3266489909);
  return (4294967296 * (2097151 & second) + (first >>> 0)).toString(36);
}

function randomId() {
  return Math.floor(Math.random() * 0x1000000).toString(16).padStart(6, "0");
}

export function createIssuer(known = {}) {
  const taken = new Set(Object.keys(known));
  const byPrint = new Map();
  for (const [id, print] of Object.entries(known)) if (!byPrint.has(print)) byPrint.set(print, id);
  const fresh = {};
  return {
    fresh,
    issue(kind, secret) {
      const print = fingerprint(`${kind}\0${secret}`);
      let id = byPrint.get(print);
      if (id === undefined) {
        do id = randomId();
        while (taken.has(id));
        taken.add(id);
        byPrint.set(print, id);
        fresh[id] = print;
      }
      return id;
    },
  };
}

export function maskText(text, patterns, budget = { left: SCAN_LIMIT }, issuer = null) {
  if (typeof text !== "string" || text === "" || budget.left <= 0) return { text, count: 0 };
  const head = text.length > budget.left ? text.slice(0, budget.left) : text;
  budget.left -= head.length;
  let masked = head;
  let count = 0;
  for (const { name, regex, partial, placeholder } of patterns) {
    masked = masked.replace(regex, (...found) => {
      const secret = partial ? found[2] : found[0];
      if (placeholder !== null && placeholder.test(secret)) return found[0];
      count += 1;
      const label = issuer === null ? `[REDACTED:${name}]` : `[REDACTED:${name}:${issuer.issue(name, secret)}]`;
      return partial ? `${found[1]}${label}${found[3]}` : label;
    });
  }
  return count === 0 ? { text, count } : { text: masked + text.slice(head.length), count };
}

function isContainer(value) {
  if (value === null || typeof value !== "object") return false;
  if (Array.isArray(value)) return true;
  const prototype = Object.getPrototypeOf(value);
  return prototype === Object.prototype || prototype === null;
}

function isBinary(object) {
  return [object.type, object.mimeType, object.mediaType].some((kind) => typeof kind === "string" && BINARY_TYPE.test(kind));
}

function define(target, key, value) {
  Object.defineProperty(target, key, { value, enumerable: true, writable: true, configurable: true });
}

function emptyLike(value) {
  return Array.isArray(value) ? [] : Object.create(Object.getPrototypeOf(value));
}

export function maskValue(value, patterns, budget = { left: SCAN_LIMIT }, issuer = null) {
  if (typeof value === "string") return maskText(value, patterns, budget, issuer);
  if (!isContainer(value)) return { text: value, count: 0 };
  let count = 0;
  let nodes = 0;
  const root = emptyLike(value);
  const path = new Set([value]);
  const stack = [{ source: value, copy: root, entries: Object.entries(value), at: 0, binary: isBinary(value) }];
  while (stack.length > 0) {
    const frame = stack[stack.length - 1];
    if (frame.at >= frame.entries.length) {
      path.delete(frame.source);
      stack.pop();
      continue;
    }
    const [key, item] = frame.entries[frame.at];
    frame.at += 1;
    if (typeof item === "string") {
      const inner = frame.binary && BASE64_BLOB.test(item) ? { text: item, count: 0 } : maskText(item, patterns, budget, issuer);
      define(frame.copy, key, inner.text);
      count += inner.count;
    } else if (isContainer(item) && !path.has(item) && nodes < MAX_NODES) {
      nodes += 1;
      const copy = emptyLike(item);
      define(frame.copy, key, copy);
      path.add(item);
      stack.push({ source: item, copy, entries: Object.entries(item), at: 0, binary: frame.binary || isBinary(item) });
    } else {
      define(frame.copy, key, item);
    }
  }
  return count === 0 ? { text: value, count } : { text: root, count };
}

export function maskedAnswer(answer, patterns, issuer = null) {
  if (answer.deny !== undefined) return { answer, count: 0 };
  const budget = { left: SCAN_LIMIT };
  const failed = answer.isError === true;
  const context = Array.isArray(answer.context) ? answer.context.reduce((total, entry) => total + maskText(entry, patterns, budget).count, 0) : 0;
  if (context > 0) return { answer: { deny: CONTEXT_DENY_REASON }, count: context, withheld: true };
  const text = failed ? maskText(answer.text, patterns, budget, issuer) : { text: undefined, count: 0 };
  const result = maskValue(answer.result, patterns, budget, issuer);
  const derived = failed ? 0 : maskText(answer.text, patterns, budget).count;
  const count = result.count + text.count;
  if (count + derived === 0) return { answer, count: 0 };
  const { ref: _ref, text: _text, isReadOnly: _readOnly, ...rest } = answer;
  return { answer: { ...rest, result: result.text, ...(failed ? { text: text.text } : {}) }, count: count || derived };
}

export function markerIds(e) {
  const texts = [e.new_string, e.content, e.new_source];
  if (Array.isArray(e.edits)) for (const edit of e.edits) texts.push(edit?.new_string);
  const ids = [];
  for (const text of texts) {
    if (typeof text !== "string" || !text.includes(PLACEHOLDER_MARK)) continue;
    for (const found of text.matchAll(ISSUED_MARKER)) ids.push(found[1]);
  }
  return ids;
}

export function carriesIssuedPlaceholder(e, issued) {
  return markerIds(e).some((id) => Object.hasOwn(issued, id));
}

async function recordIds($, fresh) {
  for (let attempt = 0; attempt < 5; attempt += 1) {
    const { value, version } = await $.state.get(ISSUED);
    const done = await $.state.set(ISSUED, { ...(isRecord(value) ? value : {}), ...fresh }, { ifVersion: version });
    if (done.isSet) return;
  }
}

async function knownIds($) {
  try {
    const { value } = await $.state.get(ISSUED);
    return isRecord(value) ? value : {};
  } catch {
    return {};
  }
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
  on("tool.call", { tool: WRITE_TOOLS }, async ($, e, next) => {
    if (markerIds(e).length === 0) return next(e);
    return carriesIssuedPlaceholder(e, await knownIds($)) ? { deny: DENY_REASON } : next(e);
  }).catch(($, e, next) => next(e));

  on("tool.call", { tool: RESULT_TOOLS }, async ($, e, next) => {
    const answer = await next(e);
    try {
      const issuer = createIssuer(await knownIds($));
      const { answer: masked, count, withheld } = maskedAnswer(answer, await patternsOf($), issuer);
      if (Object.keys(issuer.fresh).length > 0) {
        try {
          await recordIds($, issuer.fresh);
        } catch {}
      }
      if (count > 0) {
        const noun = count === 1 ? "value" : "values";
        $.ui.log(`${$.plugin.name}: ${withheld ? `withheld the ${e.tool} result, hook context held ${count} secret ${noun}` : `masked ${count} secret ${noun} in the ${e.tool} result`}`);
      }
      return masked;
    } catch {
      return answer;
    }
  }).catch(($, e, next) => next(e));
}
