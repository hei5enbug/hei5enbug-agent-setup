const DATAGRIP_TOOL = "mcp__datagrip__execute_sql_query";
const STORE_KEY = "approvals";
const RETENTION_MS = 7 * 24 * 60 * 60 * 1000;
const LOOKUP_TIMEOUT_MS = 3000;

export const DESTRUCTIVE_REASON = "Always asks: this action cannot be undone.";
export const UNVERIFIABLE_REASON = "Contains a command the session approval cannot verify.";

const TOOL_MATCHER = /^(Bash|mcp__.*)$/;
const SEPARATORS = new Set(["&&", "||", ";", "|", "|&", "&"]);
const PUNCTUATION = new Set("();<>|&");
const OPAQUE_COMMAND =
  /\$\(|`|<<|\beval\b|\bxargs\b|\b(?:bash|sh|zsh|dash|ksh)\s+-[A-Za-z]*c\b|\\\n/;
const SCAN_KEYS = [
  ["git tag", "git:tag"],
  ["git push", "git:push-tag"],
  ["gh release", "gh:release"],
];
const SCAN_DESTRUCTIVE =
  /\bgh\s+(?:release|repo)\s+delete|\bgit\s+tag\b[^;&|]*\s(?:-d|--delete|-f|--force)\b|\bgit\s+push\b[^;&|]*\s(?:-[A-Za-z]*[fd][A-Za-z]*|--force\S*|--delete|--mirror|--prune|\+\S+|:\S+)(?:\s|$)/;
const EXPANSION_TOKEN = /[${}`!\\]|^~/;
const GLOB_TOKEN = /[*?[\]]/;
const RISKY_CONFIG_KEY =
  /ssh|hook|fsmonitor|pager|editor|helper|alias|insteadof|pushurl|proxy|include|exec|program|askpass|command|gpg|filter|textconv|url/iu;
const TAG_VALUE_OPTIONS = new Set(["-m", "-F", "-u", "--message", "--file", "--local-user", "--cleanup"]);
const TAG_LONG_VALUE_OPTIONS = new Set(["--message", "--file", "--local-user", "--cleanup"]);
const TAG_LIST_OPTIONS =
  /^(?:-l|--list|-n\p{Nd}*|-v|--verify|--contains(?:=.*)?|--no-contains(?:=.*)?|--points-at(?:=.*)?|--merged(?:=.*)?|--no-merged(?:=.*)?|--sort(?:=.*)?|--format(?:=.*)?|--column(?:=.*)?|--no-column)$/u;
const PUSH_DESTRUCTIVE_OPTIONS = new Set(["--force", "--force-if-includes", "--delete", "--mirror", "--prune"]);
const PUSH_BENIGN_OPTIONS = new Set([
  "-u", "--set-upstream", "-v", "--verbose", "-q", "--quiet", "-n", "--dry-run", "--no-verify", "--atomic",
  "--progress", "--no-progress", "--thin", "--no-thin",
]);
const SINGLE_DASH_CLUSTER = /^-[A-Za-z0-9]+$/;
const RELEASE_VALUE_FLAGS = new Set(["--title", "-t", "--notes", "-n", "--target"]);
const RELEASE_SWITCH_FLAGS = new Set([
  "--generate-notes", "--notes-from-tag", "--latest", "--draft", "--prerelease", "--verify-tag",
]);
export const READ_VERBS = new Set([
  "get", "list", "search", "read", "fetch", "query", "find", "lookup", "describe", "show", "view", "check",
  "count", "browse", "download", "export", "preview", "introspect", "analyze", "explain",
]);
export const DESTRUCTIVE_WORDS = new Set([
  "delete", "trash", "remove", "destroy", "purge", "drop", "unshare", "revoke",
]);
export const WRITE_WORDS = new Set([
  "send", "post", "reply", "create", "update", "edit", "add", "write", "upsert", "transition", "schedule",
  "share", "copy", "move", "upload", "comment", "label", "unlabel", "mark", "unmark", "forward", "apply", "set",
  "rename", "link", "react", "reaction", "publish", "merge", "close", "reopen", "assign", "invite", "patch",
]);

const CODEX_VALUE_OPTIONS = new Set([
  "-c", "--config", "-C", "--cd", "--add-dir", "-s", "--sandbox", "-m", "--model", "-o", "--output-last-message",
  "--output-schema", "-p", "--profile", "-i", "--image", "--color", "-a", "--ask-for-approval", "--enable",
  "--disable", "--local-provider",
]);
const CODEX_DANGEROUS_FLAGS = new Set([
  "--dangerously-bypass-approvals-and-sandbox",
  "--dangerously-bypass-hook-trust",
]);
const CODEX_DANGEROUS_SANDBOX = "danger-full-access";
const CODEX_SANDBOX_CONFIG_KEY = /^\s*["']?sandbox/i;

const LEX_WHITESPACE = " \t\r\n";
const LEX_QUOTES = "'\"";
const LEX_ESCAPE = "\\";
const LEX_PUNCTUATION = "();<>|&";

function outcome(keys, destructive, known, mustAsk = false) {
  return { keys: new Set(keys), destructive, known, mustAsk };
}

function expands(token) {
  return EXPANSION_TOKEN.test(token);
}

function unsafe(token) {
  return expands(token) || GLOB_TOKEN.test(token);
}

function beforeEquals(text) {
  const index = text.indexOf("=");
  return index < 0 ? text : text.slice(0, index);
}

export function lex(command) {
  const text = Array.from(command.replace(/\r\n|\n|\r/g, " ; "));
  const pushedBack = [];
  const tokens = [];
  let position = 0;
  let state = " ";

  function read() {
    if (pushedBack.length > 0) return pushedBack.pop();
    return position < text.length ? text[position++] : "";
  }

  while (true) {
    let token = "";
    let quoted = false;
    let escapedState = " ";
    while (true) {
      const next = read();
      if (state === null) {
        token = "";
        break;
      }
      if (state === " ") {
        if (!next) {
          state = null;
          break;
        }
        if (LEX_WHITESPACE.includes(next)) {
          if (token || quoted) break;
          continue;
        }
        if (next === LEX_ESCAPE) {
          escapedState = "a";
          state = next;
        } else if (LEX_PUNCTUATION.includes(next)) {
          token = next;
          state = "c";
        } else if (LEX_QUOTES.includes(next)) {
          state = next;
        } else {
          token = next;
          state = "a";
        }
      } else if (state === "'" || state === '"') {
        quoted = true;
        if (!next) throw new Error("No closing quotation");
        if (next === state) {
          state = "a";
        } else if (next === LEX_ESCAPE && state === '"') {
          escapedState = state;
          state = next;
        } else {
          token += next;
        }
      } else if (state === LEX_ESCAPE) {
        if (!next) throw new Error("No escaped character");
        if (LEX_QUOTES.includes(escapedState) && next !== state && next !== escapedState) token += state;
        token += next;
        state = escapedState;
      } else {
        if (!next) {
          state = null;
          break;
        }
        if (LEX_WHITESPACE.includes(next)) {
          state = " ";
          if (token || quoted) break;
          continue;
        }
        if (state === "c") {
          if (LEX_PUNCTUATION.includes(next)) {
            token += next;
          } else {
            pushedBack.push(next);
            state = " ";
            break;
          }
        } else if (LEX_QUOTES.includes(next)) {
          state = next;
        } else if (next === LEX_ESCAPE) {
          escapedState = "a";
          state = next;
        } else if (LEX_PUNCTUATION.includes(next)) {
          pushedBack.push(next);
          state = " ";
          if (token || quoted) break;
        } else {
          token += next;
        }
      }
    }
    if (!quoted && token === "") break;
    tokens.push(token);
  }
  return tokens;
}

function splitSubcommands(tokens) {
  const commands = [[]];
  for (const token of tokens) {
    if (SEPARATORS.has(token)) commands.push([]);
    else commands[commands.length - 1].push(token);
  }
  return commands.filter(words => words.length > 0);
}

function scanOpaque(command) {
  const keys = SCAN_KEYS.filter(([needle]) => command.includes(needle)).map(([, key]) => key);
  return outcome(keys, SCAN_DESTRUCTIVE.test(command), false);
}

function joinDirectory(base, argument) {
  if (base === null || !argument || unsafe(argument)) return null;
  const joined = argument.startsWith("/") ? argument : `${base}/${argument}`;
  const absolute = joined.startsWith("/");
  const parts = [];
  for (const part of joined.split("/")) {
    if (part === "" || part === ".") continue;
    if (part === "..") {
      if (parts.length > 0 && parts[parts.length - 1] !== "..") parts.pop();
      else if (!absolute) parts.push(part);
      continue;
    }
    parts.push(part);
  }
  const path = parts.join("/");
  return absolute ? `/${path}` : path || ".";
}

async function tagExists($, directory, name) {
  if (directory === null || !name || name.startsWith("-") || unsafe(name)) return false;
  try {
    const completed = await $.process.run(
      ["git", "-C", directory, "rev-parse", "-q", "--verify", `refs/tags/${name}`],
      { timeoutMs: LOOKUP_TIMEOUT_MS },
    );
    return completed.exitCode === 0;
  } catch {
    return false;
  }
}

async function gitRemotes($, directory) {
  if (directory === null) return null;
  try {
    const completed = await $.process.run(["git", "-C", directory, "remote"], { timeoutMs: LOOKUP_TIMEOUT_MS });
    if (completed.exitCode !== 0) return null;
    return new Set((completed.stdout || "").split(/\s+/).filter(Boolean));
  } catch {
    return null;
  }
}

function classifyTag(args, state) {
  const positionals = [];
  let destructive = false;
  let listing = false;
  let unknown = false;
  let index = 0;
  while (index < args.length) {
    const arg = args[index];
    index += 1;
    if (TAG_VALUE_OPTIONS.has(arg)) {
      index += 1;
      continue;
    }
    if (arg.startsWith("--") && TAG_LONG_VALUE_OPTIONS.has(beforeEquals(arg))) continue;
    if (arg === "-d" || arg === "--delete" || arg === "-f" || arg === "--force") {
      destructive = true;
    } else if (SINGLE_DASH_CLUSTER.test(arg) && /[df]/.test(arg.slice(1)) && !TAG_LIST_OPTIONS.test(arg)) {
      destructive = true;
    } else if (TAG_LIST_OPTIONS.test(arg)) {
      listing = true;
    } else if (arg.startsWith("-")) {
      if (unsafe(arg)) unknown = true;
    } else {
      positionals.push(arg);
      if (expands(arg)) unknown = true;
    }
  }
  if (destructive) return outcome([], true, true);
  if (unknown) return outcome([], false, false);
  if (!listing && positionals.some(item => unsafe(item))) return outcome([], false, false);
  if (listing || args.length === 0) return outcome([], false, true);
  if (positionals.length > 0) state.created.add(positionals[0]);
  return outcome(["git:tag"], false, true);
}

async function classifyPush($, args, state, directory) {
  const positionals = [];
  let tagFlag = false;
  let destructive = false;
  let unknown = false;
  for (const arg of args) {
    if (PUSH_DESTRUCTIVE_OPTIONS.has(arg) || arg.startsWith("--force-with-lease")) {
      destructive = true;
    } else if (SINGLE_DASH_CLUSTER.test(arg) && /[fd]/.test(arg.slice(1))) {
      destructive = true;
    } else if (arg === "--tags" || arg === "--follow-tags") {
      tagFlag = true;
    } else if (PUSH_BENIGN_OPTIONS.has(arg)) {
      continue;
    } else if (arg.startsWith("-")) {
      unknown = true;
    } else {
      positionals.push(arg);
    }
  }
  if (positionals.some(item => item.startsWith("+") || item.startsWith(":") || item.startsWith("-"))) {
    destructive = true;
  }
  if (destructive) return outcome([], true, true);
  const refspecs = positionals.slice(1);
  const plain = !unknown && !positionals.some(item => unsafe(item));
  let isTagPush = tagFlag || refspecs.some(item => item.startsWith("refs/tags/"));
  if (!isTagPush && plain && refspecs.length > 0) {
    isTagPush = true;
    for (const item of refspecs) {
      if (state.created.has(item)) continue;
      if (!(await tagExists($, directory, item))) {
        isTagPush = false;
        break;
      }
    }
  }
  if (!isTagPush) return outcome([], false, false);
  let remoteKnown = positionals.length === 0;
  if (!remoteKnown && plain) {
    const remotes = (await gitRemotes($, directory)) ?? new Set();
    remoteKnown = remotes.has(positionals[0]);
  }
  const known = plain && remoteKnown && !(tagFlag && refspecs.length > 0);
  return outcome(["git:push-tag"], false, known);
}

async function classifyGit($, words, state) {
  let directory = state.dir;
  let index = 1;
  while (index < words.length) {
    const word = words[index];
    if (word === "-C" && index + 1 < words.length) {
      directory = joinDirectory(directory, words[index + 1]);
      index += 2;
    } else if (word === "-c" && index + 1 < words.length) {
      const key = beforeEquals(words[index + 1]);
      if (RISKY_CONFIG_KEY.test(key) || unsafe(words[index + 1])) return outcome([], false, false);
      index += 2;
    } else if (word.startsWith("--git-dir=") || word.startsWith("--work-tree=")) {
      if (unsafe(word)) return outcome([], false, false);
      directory = null;
      index += 1;
    } else if (word === "--no-pager" || word === "-P") {
      index += 1;
    } else {
      break;
    }
  }
  if (index >= words.length) return outcome([], false, false);
  const subcommand = words[index];
  const args = words.slice(index + 1);
  if (subcommand === "tag") return classifyTag(args, state);
  if (subcommand === "push") return classifyPush($, args, state, directory);
  return outcome([], false, false);
}

function releaseWriteIsKnown(args) {
  let positionals = 0;
  let index = 0;
  while (index < args.length) {
    const arg = args[index];
    index += 1;
    const name = beforeEquals(arg);
    if (arg.startsWith("-")) {
      if (RELEASE_VALUE_FLAGS.has(name)) {
        if (!arg.includes("=")) {
          if (index >= args.length) return false;
          index += 1;
        }
      } else if (!RELEASE_SWITCH_FLAGS.has(name)) {
        return false;
      }
    } else {
      positionals += 1;
      if (unsafe(arg)) return false;
    }
  }
  return positionals === 1;
}

function classifyGh(words) {
  if (words.length < 3 || words.slice(1, 3).some(word => unsafe(word) || word.startsWith("-"))) {
    return outcome([], false, false);
  }
  const area = words[1];
  const action = words[2];
  if (area === "repo" && action.startsWith("delete")) return outcome([], true, true);
  if (area === "release") {
    if (action.startsWith("delete")) return outcome([], true, true);
    if (action === "create" || action === "edit") {
      return outcome(["gh:release"], false, releaseWriteIsKnown(words.slice(3)));
    }
    if (action === "upload") return outcome(["gh:release"], false, false);
  }
  return outcome([], false, false);
}

function codexSubcommand(args) {
  let index = 0;
  while (index < args.length) {
    const arg = args[index];
    index += 1;
    if (arg.startsWith("-") && arg !== "-") {
      if (CODEX_VALUE_OPTIONS.has(arg)) index += 1;
    } else {
      return arg;
    }
  }
  return null;
}

function optionValues(args, short, longs) {
  const values = [];
  let index = 0;
  while (index < args.length) {
    const arg = args[index];
    index += 1;
    if ((short !== null && arg === `-${short}`) || longs.includes(arg)) {
      values.push(index < args.length ? args[index] : null);
      index += 1;
    } else if (arg.startsWith("--")) {
      const name = longs.find(item => arg.startsWith(`${item}=`));
      if (name !== undefined) values.push(arg.slice(name.length + 1));
    } else if (short !== null && arg.length > 2 && arg.startsWith(`-${short}`)) {
      const rest = arg.slice(2);
      values.push(rest.startsWith("=") ? rest.slice(1) : rest);
    }
  }
  return values;
}

function codexIsDangerous(args) {
  if (args.some(arg => CODEX_DANGEROUS_FLAGS.has(arg))) return true;
  if (optionValues(args, "s", ["--sandbox"]).includes(CODEX_DANGEROUS_SANDBOX)) return true;
  return optionValues(args, "c", ["--config"]).some(
    value => typeof value === "string" && CODEX_SANDBOX_CONFIG_KEY.test(value),
  );
}

function codexDirectory(state, argument) {
  if (typeof argument !== "string") return null;
  const resolved = joinDirectory(argument.startsWith("/") ? "/" : state.dir, argument);
  return resolved !== null && resolved.startsWith("/") ? resolved : null;
}

function classifyCodex(words, state) {
  const args = words.slice(1);
  if (codexSubcommand(args) !== "exec") return null;
  if (codexIsDangerous(args)) return outcome([], true, true);
  const root = joinDirectory(state.root, ".");
  const prefix = root === "/" ? "/" : `${root}/`;
  const targets = optionValues(args, null, ["--add-dir"]);
  const workdirs = optionValues(args, "C", ["--cd"]);
  const keys = new Set();
  let unverifiable = false;
  if (workdirs.length > 0) targets.push(...workdirs);
  else if (state.dir !== state.root) targets.push(state.dir);
  for (const target of targets) {
    const resolved = codexDirectory(state, target);
    if (resolved === null || root === null || !root.startsWith("/")) {
      unverifiable = true;
    } else if (resolved !== root && !resolved.startsWith(prefix)) {
      keys.add(`codex-dir:${resolved}`);
    }
  }
  return outcome(keys, false, keys.size > 0 && !unverifiable, unverifiable);
}

function isPunctuation(word) {
  return Boolean(word) && Array.from(word).every(char => PUNCTUATION.has(char));
}

function codexInputRedirect(words) {
  const marks = words.flatMap((word, index) => (isPunctuation(word) ? [index] : []));
  if (marks.length !== 1 || words[marks[0]] !== "<") return null;
  const at = marks[0];
  const path = words[at + 1];
  if (typeof path !== "string" || path === "") return null;
  if (unsafe(path)) return { stripped: null };
  return { stripped: [...words.slice(0, at), ...words.slice(at + 2)] };
}

async function classifySubcommand($, words, state) {
  const punctuated = words.some(isPunctuation);
  if (words[0] === "codex") {
    const redirect = punctuated ? codexInputRedirect(words) : null;
    const reads = redirect !== null && redirect.stripped !== null;
    const codex = classifyCodex(reads ? redirect.stripped : words, state);
    if (codex !== null) {
      if (!punctuated || reads) return codex;
      const expanded = redirect !== null;
      return outcome(codex.keys, codex.destructive, false, codex.mustAsk || (expanded && !codex.destructive));
    }
  }
  if (punctuated) return outcome([], false, false);
  const head = words[0];
  if (head === "echo") return outcome([], false, !words.slice(1).some(word => unsafe(word)));
  if (head === "cd") {
    if (words.length === 2) {
      state.dir = joinDirectory(state.dir, words[1]);
      return outcome([], false, true);
    }
    return outcome([], false, false);
  }
  if (head === "git") return classifyGit($, words, state);
  if (head === "gh") return classifyGh(words);
  return outcome([], false, false);
}

async function sessionDirectory($) {
  try {
    const directory = await $.session.cwd();
    return typeof directory === "string" && directory ? directory : ".";
  } catch {
    return ".";
  }
}

async function classifyBash($, command) {
  if (typeof command !== "string" || !command.trim()) return outcome([], false, false);
  if (OPAQUE_COMMAND.test(command)) return scanOpaque(command);
  let subcommands;
  try {
    subcommands = splitSubcommands(lex(command));
  } catch {
    return scanOpaque(command);
  }
  const root = await sessionDirectory($);
  const state = { dir: root, root, created: new Set() };
  const keys = new Set();
  let destructive = false;
  let known = true;
  let mustAsk = false;
  for (const words of subcommands) {
    const sub = await classifySubcommand($, words, state);
    for (const key of sub.keys) keys.add(key);
    destructive = destructive || sub.destructive;
    known = known && (sub.known || sub.destructive);
    mustAsk = mustAsk || sub.mustAsk;
  }
  return outcome(keys, destructive, known, mustAsk);
}

export function toolWordList(toolPart) {
  const spaced = toolPart
    .replace(/([a-z0-9])([A-Z])/g, "$1_$2")
    .replace(/([A-Z]+)([A-Z][a-z])/g, "$1_$2");
  return spaced
    .toLowerCase()
    .split(/[_\-\s]+/)
    .filter(Boolean);
}

export function toolWords(toolPart) {
  return new Set(toolWordList(toolPart));
}

function mcpToolPart(toolName) {
  const first = toolName.indexOf("__");
  if (first < 0) return null;
  const second = toolName.indexOf("__", first + 2);
  if (second < 0) return null;
  return toolName.slice(second + 2);
}

function classifyMcp(toolName) {
  if (toolName === DATAGRIP_TOOL) return outcome([], false, false);
  const toolPart = mcpToolPart(toolName);
  if (toolPart === null) return outcome([], false, false);
  const ordered = toolWordList(toolPart);
  if (ordered.some(word => DESTRUCTIVE_WORDS.has(word))) return outcome([`mcp:${toolName}`], true, true);
  if (ordered.length > 0 && READ_VERBS.has(ordered[0])) return outcome([], false, false);
  if (ordered.some(word => WRITE_WORDS.has(word))) return outcome([`mcp:${toolName}`], false, true);
  return outcome([], false, false);
}

export async function classify($, tool, input) {
  if (tool === "Bash") {
    const isRecord = input !== null && typeof input === "object" && !Array.isArray(input);
    return classifyBash($, isRecord ? input.command : undefined);
  }
  if (typeof tool === "string" && tool.startsWith("mcp__")) return classifyMcp(tool);
  return outcome([], false, false);
}

function validEntry(entry, now) {
  return (
    entry !== null &&
    typeof entry === "object" &&
    !Array.isArray(entry) &&
    Number.isFinite(entry.time) &&
    entry.time >= now - RETENTION_MS &&
    Array.isArray(entry.keys)
  );
}

function storedEntries(state, now) {
  if (state === null || typeof state !== "object" || Array.isArray(state)) return [];
  return Object.entries(state).filter(([, entry]) => validEntry(entry, now));
}

async function sessionId($) {
  const id = await $.session.id();
  return typeof id === "string" && id ? id : null;
}

async function approvedKeys($) {
  try {
    const id = await sessionId($);
    if (id === null) return new Set();
    const now = await $.clock.now();
    const entries = storedEntries(await $.store.get(STORE_KEY), now);
    const found = entries.find(([key]) => key === id);
    if (found === undefined) return new Set();
    return new Set(found[1].keys.filter(key => typeof key === "string"));
  } catch {
    return new Set();
  }
}

async function recordKeys($, keys) {
  const id = await sessionId($);
  if (id === null) return;
  const now = await $.clock.now();
  const entries = storedEntries(await $.store.get(STORE_KEY), now);
  const found = entries.find(([key]) => key === id);
  const existing = found === undefined ? [] : found[1].keys.filter(key => typeof key === "string");
  const kept = entries.filter(([key]) => key !== id);
  kept.push([id, { time: now, keys: [...new Set([...existing, ...keys])].sort() }]);
  await $.store.set(STORE_KEY, Object.fromEntries(kept));
}

function isDeny(result) {
  return typeof result?.deny === "string";
}

export function registerApproval(on) {
  on("tool.check", { tool: TOOL_MATCHER }, async ($, e, next) => {
    const decided = await next(e);
    if (decided.decision === "deny") return decided;
    const { keys, destructive, known, mustAsk } = await classify($, e.tool, e.input);
    if (destructive) return { decision: "ask", reason: DESTRUCTIVE_REASON };
    if (mustAsk) return { decision: "ask", reason: UNVERIFIABLE_REASON };
    if (keys.size === 0) return decided;
    if (!known) return { decision: "ask", reason: UNVERIFIABLE_REASON };
    const listed = [...keys].sort().join(", ");
    if (!e.agentId) {
      const approved = await approvedKeys($);
      if ([...keys].every(key => approved.has(key))) {
        return { decision: "allow", reason: `Approved earlier in this session: ${listed}` };
      }
    }
    return {
      decision: "ask",
      reason: `First time in this session: approving it allows ${listed} for the rest of the session.`,
    };
  }).catch(($, e, next) => next(e));

  on("tool.call", { tool: TOOL_MATCHER }, async ($, e, next) => {
    const result = await next(e);
    if (e.agentId || isDeny(result) || result?.isError) return result;
    const { keys, destructive } = await classify($, e.tool, e);
    if (destructive || keys.size === 0) return result;
    await recordKeys($, keys);
    return result;
  }).catch(($, e, next) => next(e));
}
