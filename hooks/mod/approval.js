import { modelRegistry } from "./registry.js";

const STORE_KEY = "approvals";
const SESSION_KEY = "write:session";
const RETENTION_MS = 7 * 24 * 60 * 60 * 1000;
const LOOKUP_TIMEOUT_MS = 3000;
const CLASSIFICATION_CACHE_LIMIT = 256;

export const DESTRUCTIVE_REASON = "Always asks: this action cannot be undone.";
export const UNVERIFIABLE_REASON = "Contains a command the session approval cannot verify.";

const TOOL_MATCHER = /^Bash$/;
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
const CODEX_WORD = /\bcodex\b/i;
const CODEX_DANGEROUS_TEXT =
  /danger-full-access|--dangerously-bypass-approvals-and-sandbox|--dangerously-bypass-hook-trust|(?:^|\s)(?:-c|--config)(?:\s+|=)?\s*["']?sandbox/i;

const ROLE_RUNNER_HEADS = new Set(["python3", "python"]);
const ROLE_RUNNER_SCRIPT = "/scripts/role_runner.py";
const ROLE_RUNNER_TEXT = /\bpython3?\s+[^\s;&|]*\/scripts\/role_runner\.py/;
const ROLE_RUNNER_ROLES = new Set(["scout", "researcher", "reviewer", "worker"]);
const ROLE_RUNNER_AGENT = "agent";
const ROLE_RUNNER_VALUE_OPTIONS = new Set([
  "--assignment", "--result", "--model", "--add-dir", "--timeout", "--host", "--instructions", "--resume", "--name",
]);
const ROLE_RUNNER_FLAG_OPTIONS = new Set(["--fallback", "--mcp"]);

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
  const codex = CODEX_WORD.test(command);
  const destructive = SCAN_DESTRUCTIVE.test(command) || (codex && CODEX_DANGEROUS_TEXT.test(command));
  return outcome(keys, destructive, false, (codex || ROLE_RUNNER_TEXT.test(command)) && !destructive);
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

async function realDirectory($, state, path) {
  if (state.real.has(path)) return state.real.get(path);
  let real = null;
  try {
    const completed = await $.process.run(["/bin/realpath", path], { timeoutMs: LOOKUP_TIMEOUT_MS });
    const text = completed.exitCode === 0 ? (completed.stdout || "").replace(/\r?\n$/, "") : "";
    real = text.startsWith("/") ? text : null;
  } catch {
    real = null;
  }
  state.real.set(path, real);
  return real;
}

async function outsideDirectories($, state, targets) {
  const root = joinDirectory(state.root, ".");
  const keys = new Set();
  let unverifiable = false;
  const realRoot = targets.length > 0 && root !== null && root.startsWith("/") ? await realDirectory($, state, root) : null;
  const prefix = realRoot === "/" ? "/" : `${realRoot}/`;
  for (const target of targets) {
    const resolved = codexDirectory(state, target);
    const real = resolved === null || realRoot === null ? null : await realDirectory($, state, resolved);
    if (real === null) {
      unverifiable = true;
    } else if (real !== realRoot && !real.startsWith(prefix)) {
      keys.add(`codex-dir:${real}`);
    }
  }
  return { keys, unverifiable };
}

async function classifyCodex($, words, state) {
  const args = words.slice(1);
  if (codexSubcommand(args) !== "exec") return null;
  if (codexIsDangerous(args)) return outcome([], true, true);
  if (args.some(unsafe)) return outcome([], false, false, true);
  const targets = optionValues(args, null, ["--add-dir"]);
  const workdirs = optionValues(args, "C", ["--cd"]);
  if (workdirs.length > 0) targets.push(...workdirs);
  else if (state.dir !== state.root) targets.push(state.dir);
  const { keys, unverifiable } = await outsideDirectories($, state, targets);
  return outcome(keys, false, keys.size > 0 && !unverifiable, unverifiable);
}

function isRoleRunner(words) {
  return ROLE_RUNNER_HEADS.has(words[0]) && words.length > 1 && words[1].endsWith(ROLE_RUNNER_SCRIPT);
}

function roleRunnerOptions(target, kind, args) {
  const addDirs = [];
  let name = null;
  let fallback = false;
  let index = 0;
  while (index < args.length) {
    const arg = args[index];
    index += 1;
    if (!arg.startsWith("--")) return null;
    const equals = arg.indexOf("=");
    const option = equals < 0 ? arg : arg.slice(0, equals);
    if (ROLE_RUNNER_FLAG_OPTIONS.has(option)) {
      if (equals >= 0 || kind === "role") return null;
      if (option === "--fallback") fallback = true;
      continue;
    }
    if (!ROLE_RUNNER_VALUE_OPTIONS.has(option)) return null;
    let value = equals < 0 ? undefined : arg.slice(equals + 1);
    if (value === undefined) {
      if (index >= args.length) return null;
      value = args[index];
      index += 1;
    }
    if (value === "" || value.startsWith("-")) return null;
    if (option === "--add-dir") {
      if (kind === "role" && target !== "worker") return null;
      addDirs.push(value);
    } else if (option === "--name") {
      if (kind !== "agent") return null;
      name = value;
    } else if (option === "--model" && target !== "reviewer") {
      return null;
    } else if (option === "--instructions" && kind !== "capability") {
      return null;
    }
  }
  return { addDirs, name, fallback };
}

async function runnerTargetKind($, target) {
  if (ROLE_RUNNER_ROLES.has(target)) return "role";
  if (target === ROLE_RUNNER_AGENT) return "agent";
  try {
    const names = Object.keys((await modelRegistry($)).capabilities);
    return names.includes(target) ? "capability" : null;
  } catch {
    return null;
  }
}

async function knownAgent($, name) {
  try {
    const registry = await modelRegistry($);
    const names = [...Object.keys(registry.claude_agents), ...Object.keys(registry.codex_agents ?? {})];
    return names.includes(name);
  } catch {
    return false;
  }
}

async function classifyRoleRunner($, words, state, punctuated) {
  const target = words[2];
  const args = words.slice(3);
  if (punctuated || words.some(unsafe)) return outcome([], false, false, true);
  const kind = await runnerTargetKind($, target);
  if (kind === null) return outcome([], false, false, true);
  const options = roleRunnerOptions(target, kind, args);
  if (options === null) return outcome([], false, false, true);
  if (kind === "agent" && (!options.fallback || !(await knownAgent($, options.name)))) return outcome([], false, false, true);
  if (kind === "role" && target !== "worker") return outcome([], false, false);
  const targets = [...options.addDirs];
  if (state.dir !== state.root) targets.push(state.dir);
  const { keys, unverifiable } = await outsideDirectories($, state, targets);
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
    const codex = await classifyCodex($, reads ? redirect.stripped : words, state);
    if (codex !== null) {
      if (!punctuated || reads) return codex;
      const expanded = redirect !== null;
      return outcome(codex.keys, codex.destructive, false, codex.mustAsk || (expanded && !codex.destructive));
    }
  }
  if (isRoleRunner(words)) return classifyRoleRunner($, words, state, punctuated);
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
  const state = { dir: root, root, created: new Set(), real: new Map() };
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

export async function classify($, tool, input) {
  if (tool === "Bash") {
    const isRecord = input !== null && typeof input === "object" && !Array.isArray(input);
    return classifyBash($, isRecord ? input.command : undefined);
  }
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

async function recordKeys($) {
  const id = await sessionId($);
  if (id === null) return;
  const now = await $.clock.now();
  const entries = storedEntries(await $.store.get(STORE_KEY), now);
  const kept = entries.filter(([key]) => key !== id);
  kept.push([id, { time: now, keys: [SESSION_KEY] }]);
  await $.store.set(STORE_KEY, Object.fromEntries(kept));
}

function writeLabel(key) {
  if (key === "git:tag") return "git tag";
  if (key === "git:push-tag") return "git push of a tag";
  if (key === "gh:release") return "gh release";
  if (key.startsWith("codex-dir:")) return `codex write in ${key.slice("codex-dir:".length)}`;
  return key;
}

function isDeny(result) {
  return typeof result?.deny === "string";
}

function bashCommand(input) {
  const isRecord = input !== null && typeof input === "object" && !Array.isArray(input);
  return isRecord && typeof input.command === "string" ? input.command : null;
}

function createClassificationCache() {
  const entries = new Map();
  return {
    store(id, tool, input, classified) {
      if (typeof id !== "string" || !id) return;
      entries.delete(id);
      entries.set(id, { tool, command: bashCommand(input), classified });
      while (entries.size > CLASSIFICATION_CACHE_LIMIT) entries.delete(entries.keys().next().value);
    },
    take(id, tool, input) {
      if (typeof id !== "string" || !id) return undefined;
      const entry = entries.get(id);
      if (entry === undefined) return undefined;
      entries.delete(id);
      return entry.tool === tool && entry.command === bashCommand(input) ? entry.classified : undefined;
    },
  };
}

export function registerApproval(on) {
  const cache = createClassificationCache();

  on("tool.check", { tool: TOOL_MATCHER }, async ($, e, next) => {
    const decided = await next(e);
    if (decided.decision === "deny") return decided;
    const classified = await classify($, e.tool, e.input);
    cache.store(e.tool_use_id, e.tool, e.input, classified);
    const { keys, destructive, known, mustAsk } = classified;
    if (destructive) return { decision: "ask", reason: DESTRUCTIVE_REASON };
    if (mustAsk) return { decision: "ask", reason: UNVERIFIABLE_REASON };
    if (keys.size === 0) return decided;
    if (!known) return { decision: "ask", reason: UNVERIFIABLE_REASON };
    const listed = [...keys].sort().map(writeLabel).join(" + ");
    if (!e.agentId) {
      const approved = await approvedKeys($);
      if (approved.has(SESSION_KEY)) {
        return { decision: "allow", reason: `Approved earlier in this session: ${listed}` };
      }
    }
    return {
      decision: "ask",
      reason: `Write: ${listed}. Approve once; git tag/push, gh release, and extra-directory writes then run without asking for the rest of this session.`,
    };
  }).catch(($, e, next) => next(e));

  on("tool.call", { tool: TOOL_MATCHER }, async ($, e, next) => {
    const result = await next(e);
    const cached = cache.take(e.tool_use_id, e.tool, e);
    if (e.agentId || isDeny(result) || result?.isError) return result;
    const { keys, destructive, known, mustAsk } = cached ?? (await classify($, e.tool, e));
    if (destructive || mustAsk || !known || keys.size === 0) return result;
    await recordKeys($);
    return result;
  }).catch(($, e, next) => next(e));
}
