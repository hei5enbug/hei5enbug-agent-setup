const TIMEOUT_MS = 3000;
const FILE_CAP = 10000;
const SHOWN = 3;
const SHELL_UNSAFE = /[$`<>|(){}\n\\]|(?<!&)&(?!&)/;
const PART = String.raw`(?:"[^"]+"|\x60[^\x60]+\x60|\[[^\]]+\]|\w+)`;
const NAME = String.raw`${PART}(?:\.${PART})*`;
const NAMES = String.raw`${NAME}(?:\s*,\s*${NAME})*`;
const DROP = new RegExp(String.raw`\bdrop\s+(table|view|materialized\s+view|schema|database|index|sequence)\s+(?:if\s+exists\s+)?(${NAMES})`, "i");
const TRUNCATE = new RegExp(String.raw`\btruncate\s+(?:table\s+)?(?:only\s+)?(${NAMES})`, "i");
const DELETE = new RegExp(String.raw`\bdelete\s+from\s+(?:only\s+)?(${NAME})`, "i");
const SQL_NOISE = /'(?:[^']|'')*'|--[^\n]*|\/\*[\s\S]*?\*\//g;
const SQL_IDENTIFIERS = /"[^"]*"|\x60[^\x60]*\x60|\[[^\]]*\]/g;
const KUBECTL_VALUES = new Set(["-n", "--namespace", "--context", "-l", "--selector", "--field-selector"]);
const KUBECTL_FLAGS = new Set(["-A", "--all-namespaces"]);
const KUBECTL_DROPPED = /^--(?:all|force|now|wait|ignore-not-found|cascade)(?:=\S*)?$|^--(?:grace-period|timeout)=\S+$/;
const PHRASES = {
  English: {
    unchanged: "nothing to discard",
    discards: (files, added, removed) => `discards ${count(files, "file")} (+${added}/-${removed})`,
    removes: (paths, names) => `removes ${count(paths, "path")}: ${names}`,
    unremoved: "nothing to remove",
    undeleted: "nothing to delete",
    deletes: (files, amount) => `deletes ${count(files, "file")} (${amount})`,
    deletesMany: (amount) => `deletes ${FILE_CAP}+ files (${amount})`,
    resources: (total, names) => `deletes ${total}: ${names}`,
    unmatched: "matches nothing",
    drops: (kind, names) => `drops ${kind} ${names}`,
    truncates: (names) => `truncates ${names}`,
    deletesFrom: (name, hasWhere) => `deletes from ${name}${hasWhere ? "" : " without WHERE"}`,
  },
  Korean: {
    unchanged: "버릴 변경 없음",
    discards: (files, added, removed) => `파일 ${files}개 변경 버림 (+${added}/-${removed})`,
    removes: (paths, names) => `경로 ${paths}개 삭제: ${names}`,
    unremoved: "지울 대상 없음",
    undeleted: "지울 대상 없음",
    deletes: (files, amount) => `파일 ${files}개 삭제 (${amount})`,
    deletesMany: (amount) => `파일 ${FILE_CAP}개 이상 삭제 (${amount})`,
    resources: (total, names) => `${total}개 삭제: ${names}`,
    unmatched: "일치하는 리소스 없음",
    drops: (kind, names) => `${kind} ${names} 삭제`,
    truncates: (names) => `${names} 비움`,
    deletesFrom: (name, hasWhere) => `${name} 행 삭제${hasWhere ? "" : " (WHERE 없음)"}`,
  },
};

function count(value, noun) {
  const number = Number(value);
  return `${number} ${noun}${number === 1 ? "" : "s"}`;
}

function phrasesOf(language) {
  return Object.hasOwn(PHRASES, language) ? PHRASES[language] : PHRASES.English;
}

function listed(names) {
  return names.slice(0, SHOWN).join(", ") + (names.length > SHOWN ? ", ..." : "");
}

function size(kb) {
  if (kb < 1024) return `${kb} KB`;
  return kb < 1024 * 1024 ? `${(kb / 1024).toFixed(1)} MB` : `${(kb / 1024 / 1024).toFixed(1)} GB`;
}

function words(text) {
  const out = [];
  let word = "";
  let quote;
  let started = false;
  for (const char of text) {
    if (quote !== undefined) {
      if (char === quote) quote = undefined;
      else word += char;
    } else if (char === "'" || char === '"') {
      quote = char;
      started = true;
    } else if (/\s/.test(char)) {
      if (started) out.push(word);
      word = "";
      started = false;
    } else {
      word += char;
      started = true;
    }
  }
  if (quote !== undefined) return undefined;
  return started ? [...out, word] : out;
}

async function expandHome($, path) {
  if (path !== "~" && !path.startsWith("~/")) return path;
  const home = await $.env.get("HOME");
  return home ? home + path.slice(1) : path;
}

async function resolved($, path, cwd) {
  const expanded = await expandHome($, path);
  return expanded.startsWith("/") ? expanded : `${cwd}/${expanded}`;
}

function run($, argv, cwd) {
  return $.process.run(argv, { cwd, timeoutMs: TIMEOUT_MS });
}

async function numstat($, args, cwd) {
  const result = await run($, ["git", "diff", "--numstat", ...args], cwd);
  if (result.exitCode !== 0) throw new Error("git diff failed");
  const changes = new Map();
  for (const line of result.stdout.split("\n")) {
    const match = /^(\d+|-)\t(\d+|-)\t(.+)$/.exec(line);
    if (match !== null) changes.set(match[3], [Number(match[1]) || 0, Number(match[2]) || 0]);
  }
  return changes;
}

async function diffImpact($, { ref, paths, staged }, cwd, say) {
  const args = [...(ref === undefined ? [] : [ref]), ...(paths.length > 0 ? ["--", ...paths] : [])];
  const [tree, index] = await Promise.all([numstat($, args, cwd), staged ? numstat($, ["--cached", ...args], cwd) : new Map()]);
  const changes = new Map([...index, ...tree]);
  if (changes.size === 0) return say.unchanged;
  const [added, removed] = [...changes.values()].reduce(([a, r], [plus, minus]) => [a + plus, r + minus], [0, 0]);
  return say.discards(changes.size, added, removed);
}

function resetScope(rest) {
  const refs = rest.filter((arg) => !["--hard", "-q", "--quiet"].includes(arg));
  if (!rest.includes("--hard") || refs.length > 1 || refs.some((arg) => arg.startsWith("-"))) return undefined;
  return { ref: refs[0] ?? "HEAD", paths: [], staged: true };
}

function checkoutScope(rest) {
  const split = rest.indexOf("--");
  if (split < 0 || split === rest.length - 1) return undefined;
  const refs = rest.slice(0, split).filter((arg) => arg !== "-q" && arg !== "--quiet");
  if (refs.length > 1 || refs.some((arg) => arg.startsWith("-"))) return undefined;
  return { ref: refs[0], paths: rest.slice(split + 1), staged: refs.length === 1 };
}

function restoreScope(rest) {
  let ref;
  const paths = [];
  let isPath = false;
  for (const arg of rest) {
    if (isPath || !arg.startsWith("-")) paths.push(arg);
    else if (arg === "--") isPath = true;
    else if (arg.startsWith("--source=") && arg.length > 9 && !arg.startsWith("--source=-")) ref = arg.slice(9);
    else if (!["--worktree", "-W", "-q", "--quiet"].includes(arg)) return undefined;
  }
  return paths.length > 0 ? { ref, paths, staged: false } : undefined;
}

async function cleanImpact($, rest, cwd, say) {
  const flags = [];
  const paths = [];
  let force = 0;
  let isPath = false;
  for (let index = 0; index < rest.length; index += 1) {
    const arg = rest[index];
    if (isPath || !arg.startsWith("-")) paths.push(arg);
    else if (arg === "--") isPath = true;
    else if (arg === "--force") force += 1;
    else if (arg === "-e" && index + 1 < rest.length) flags.push(arg, rest[(index += 1)]);
    else if (arg.startsWith("--exclude=")) flags.push(arg);
    else if (/^-[fdxXqn]+$/.test(arg)) {
      force += arg.split("f").length - 1;
      const kept = arg.slice(1).replace(/[fqn]/g, "");
      if (kept) flags.push(`-${kept}`);
    } else if (!["--quiet", "--dry-run"].includes(arg)) return undefined;
  }
  const argv = ["git", "clean", "-n", ...(force > 1 ? ["-ff"] : []), ...flags, ...(paths.length > 0 ? ["--", ...paths] : [])];
  const result = await run($, argv, cwd);
  if (result.exitCode !== 0) return undefined;
  const names = result.stdout.split("\n").flatMap((line) => /^Would remove (.+)$/.exec(line)?.slice(1) ?? []);
  return names.length > 0 ? say.removes(names.length, listed(names)) : say.unremoved;
}

async function gitImpact($, args, cwd, say) {
  let index = 0;
  let directory = cwd;
  while (args[index] === "-C" && index + 1 < args.length) {
    directory = await resolved($, args[index + 1], directory);
    index += 2;
  }
  const [verb, ...rest] = args.slice(index);
  if (verb === "clean") return cleanImpact($, rest, directory, say);
  const scope = verb === "reset" ? resetScope(rest) : verb === "checkout" ? checkoutScope(rest) : verb === "restore" ? restoreScope(rest) : undefined;
  return scope === undefined ? undefined : diffImpact($, scope, directory, say);
}

async function rmImpact($, args, cwd, say) {
  let recursive = false;
  let isPath = false;
  const paths = [];
  for (const arg of args) {
    if (isPath || !arg.startsWith("-")) paths.push(arg);
    else if (arg === "--") isPath = true;
    else if (arg === "--recursive") recursive = true;
    else if (/^-[rRfvdiI]+$/.test(arg)) recursive ||= /[rR]/.test(arg);
    else if (!["--force", "--verbose", "--dir"].includes(arg)) return undefined;
  }
  if (!recursive || paths.length === 0 || paths.some((path) => /[*?[]/.test(path) || path.startsWith("-"))) return undefined;
  const existing = [];
  for (const path of paths) {
    const target = await expandHome($, path);
    if (await $.fs.exists(await resolved($, target, cwd))) existing.push(target);
  }
  if (existing.length === 0) return say.undeleted;
  const [found, sized] = await Promise.all([
    run($, ["sh", "-c", `find "$@" -type f 2>/dev/null | head -n ${FILE_CAP + 1} | wc -l`, "sh", ...existing], cwd),
    run($, ["du", "-sk", ...existing], cwd),
  ]);
  const sizes = sized.stdout.split("\n").filter((line) => line.trim() !== "");
  const files = Number.parseInt(found.stdout.trim(), 10);
  if (sized.exitCode !== 0 || sized.stderr.trim() !== "" || sizes.length !== existing.length) return undefined;
  if (found.exitCode !== 0 || !Number.isFinite(files)) return undefined;
  const kb = sizes.reduce((sum, line) => sum + (Number.parseInt(line, 10) || 0), 0);
  return files > FILE_CAP ? say.deletesMany(size(kb)) : say.deletes(files, size(kb));
}

async function kubectlImpact($, args, cwd, say) {
  const kept = [];
  const positional = [];
  for (let index = 0; index < args.length; index += 1) {
    const arg = args[index];
    const flag = arg.split("=", 1)[0];
    if (KUBECTL_VALUES.has(flag)) {
      if (arg.includes("=")) kept.push(arg);
      else if (index + 1 < args.length) kept.push(arg, args[(index += 1)]);
      else return undefined;
    } else if (KUBECTL_FLAGS.has(arg)) kept.push(arg);
    else if (KUBECTL_DROPPED.test(arg)) continue;
    else if (arg.startsWith("-")) return undefined;
    else positional.push(arg);
  }
  const [verb, ...targets] = positional;
  if (verb !== "delete" || targets.length === 0) return undefined;
  const result = await run($, ["kubectl", "get", ...targets, ...kept, "-o", "name"], cwd);
  if (result.exitCode !== 0) return undefined;
  const names = result.stdout.split("\n").map((line) => line.trim()).filter(Boolean);
  return names.length > 0 ? say.resources(names.length, listed(names)) : say.unmatched;
}

async function shellImpact($, command, say) {
  if (SHELL_UNSAFE.test(command)) return undefined;
  const segments = command.split(/&&|;/).map((segment) => words(segment.trim()));
  if (segments.some((segment) => segment === undefined || segment.length === 0)) return undefined;
  let cwd = await $.session.cwd();
  const [program, ...args] = segments.pop();
  for (const segment of segments) {
    if (segment[0] !== "cd" || segment.length !== 2 || segment[1] === "-") return undefined;
    cwd = await resolved($, segment[1], cwd);
  }
  if (program === "git") return gitImpact($, args, cwd, say);
  if (program === "rm") return rmImpact($, args, cwd, say);
  if (program === "kubectl") return kubectlImpact($, args, cwd, say);
  return undefined;
}

export function sqlImpact(text, language = "English") {
  const say = phrasesOf(language);
  const found = [];
  for (const statement of text.replace(SQL_NOISE, (match) => (match.startsWith("'") ? "''" : " ")).split(";")) {
    const drop = DROP.exec(statement);
    const truncate = TRUNCATE.exec(statement);
    const remove = DELETE.exec(statement);
    if (drop !== null) found.push(say.drops(drop[1].toLowerCase().replace(/\s+/g, " "), drop[2]));
    else if (truncate !== null) found.push(say.truncates(truncate[1]));
    else if (remove !== null) {
      const rest = statement.slice(remove.index + remove[0].length).replace(SQL_IDENTIFIERS, " ");
      found.push(say.deletesFrom(remove[1], /\bwhere\b/i.test(rest)));
    }
  }
  return found.length > 0 ? found.join("; ") : undefined;
}

function bashSql(command, language) {
  const found = (words(command) ?? []).map((word) => sqlImpact(word, language)).filter(Boolean);
  return found.length > 0 ? found.join("; ") : sqlImpact(command, language);
}

function strings(value, depth = 0) {
  if (typeof value === "string") return [value];
  if (depth > 4 || value === null || typeof value !== "object") return [];
  return Object.values(value).flatMap((item) => strings(item, depth + 1));
}

export async function impactOf($, tool, input, language = "English") {
  try {
    if (tool === "Bash" && typeof input?.command === "string") {
      return (await shellImpact($, input.command, phrasesOf(language))) ?? bashSql(input.command, language);
    }
    return tool.startsWith("mcp__") ? sqlImpact(strings(input).join(";\n"), language) : undefined;
  } catch {
    return undefined;
  }
}
