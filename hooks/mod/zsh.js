const OPERATORS = ";&|<>()";
const ASSIGNMENT = /[A-Za-z_][A-Za-z0-9_]*(?:\[[^\]\s]*\])?\+?=/y;
const KEYWORDS = new Set(["if", "then", "elif", "else", "do", "while", "until", "time", "!", "{"]);
const DECLARATIONS = new Set(["export", "local", "declare", "typeset", "readonly", "integer", "float"]);
const SHELL_NAMES = new Set(["bash", "zsh"]);
const MAX_WORD = 60;
const shells = new Map();

class Unparseable extends Error {}

let firstWord;

export function zshDenial(word) {
  return `zsh expands an unquoted word that starts with \`=\` (here \`${word}\`) to a command path, so this command fails before it runs. Quote the word, such as \`echo '====='\`, or write \`[[ ... == ... ]]\` for a comparison; for a command's path use \`$(command -v <name>)\`.`;
}

function shellName(path) {
  return typeof path === "string" ? path.slice(path.lastIndexOf("/") + 1) : "";
}

export function shellIsZsh(claudeShell, shell) {
  for (const path of [claudeShell, shell]) {
    const name = shellName(path);
    if (SHELL_NAMES.has(name)) return name === "zsh";
  }
  return true;
}

const isSpace = (c) => c === " " || c === "\t" || c === "\n" || c === "\r";
const isOperator = (c) => c !== undefined && OPERATORS.includes(c);
const isBoundary = (c) => c === undefined || isSpace(c) || (isOperator(c) && c !== "(");

function wordAt(src, start) {
  let end = start;
  while (end < src.length && end - start < MAX_WORD && !isSpace(src[end]) && !isOperator(src[end])) end++;
  return src.slice(start, end);
}

function checkLeadingEquals(src, at, start) {
  const next = src[at + 1];
  if (!isBoundary(next) && next !== "(") firstWord ??= wordAt(src, start);
}

function checkWordStart(src, start, assignPos) {
  if (src[start] === "=") {
    checkLeadingEquals(src, start, start);
    return false;
  }
  if (!assignPos) return false;
  ASSIGNMENT.lastIndex = start;
  const found = ASSIGNMENT.exec(src);
  if (found === null) return false;
  const value = start + found[0].length;
  if (src[value] === "=") checkLeadingEquals(src, value, start);
  return true;
}

function skipSingle(src, from) {
  const end = src.indexOf("'", from);
  if (end === -1) throw new Unparseable();
  return end + 1;
}

function skipAnsiC(src, from) {
  for (let i = from; i < src.length; i++) {
    if (src[i] === "\\") i++;
    else if (src[i] === "'") return i + 1;
  }
  throw new Unparseable();
}

function skipArithmetic(src, from) {
  let depth = 2;
  for (let i = from; i < src.length; i++) {
    if (src[i] === "(") depth++;
    else if (src[i] === ")" && --depth === 0) return i + 1;
  }
  throw new Unparseable();
}

function skipBackticks(src, from) {
  let i = from;
  while (i < src.length && src[i] !== "`") i += src[i] === "\\" ? 2 : 1;
  if (i >= src.length) throw new Unparseable();
  scanCommands(src.slice(from, i).replace(/\\([`\\$])/g, "$1"), 0, "");
  return i + 1;
}

function skipBraces(src, from) {
  let depth = 1;
  let i = from;
  while (i < src.length) {
    const c = src[i];
    if (c === "\\") i += 2;
    else if (c === "'") i = skipSingle(src, i + 1);
    else if (c === '"') i = skipDouble(src, i + 1);
    else if (c === "$") i = skipDollar(src, i);
    else {
      if (c === "{") depth++;
      else if (c === "}" && --depth === 0) return i + 1;
      i++;
    }
  }
  throw new Unparseable();
}

function skipDollar(src, i) {
  const next = src[i + 1];
  if (next === "(") return src[i + 2] === "(" ? skipArithmetic(src, i + 3) : scanCommands(src, i + 2, ")");
  if (next === "'") return skipAnsiC(src, i + 2);
  if (next === "{") return skipBraces(src, i + 2);
  return i + 1;
}

function skipDouble(src, from) {
  let i = from;
  while (i < src.length) {
    const c = src[i];
    if (c === '"') return i + 1;
    if (c === "\\") i += 2;
    else if (c === "`") i = skipBackticks(src, i + 1);
    else if (c === "$" && (src[i + 1] === "(" || src[i + 1] === "{")) i = skipDollar(src, i);
    else i++;
  }
  throw new Unparseable();
}

function skipConditional(src, from) {
  let i = from;
  while (i < src.length) {
    const c = src[i];
    if (c === "\\") i += 2;
    else if (c === "'") i = skipSingle(src, i + 1);
    else if (c === '"') i = skipDouble(src, i + 1);
    else if (c === "`") i = skipBackticks(src, i + 1);
    else if (c === "$") i = skipDollar(src, i);
    else if (c === "]" && src[i + 1] === "]" && isSpace(src[i - 1]) && isBoundary(src[i + 2])) return i + 2;
    else i++;
  }
  throw new Unparseable();
}

function scanWordBody(src, from) {
  let i = from;
  while (i < src.length && !isSpace(src[i]) && !isOperator(src[i])) {
    const c = src[i];
    if (c === "\\") i += 2;
    else if (c === "'") i = skipSingle(src, i + 1);
    else if (c === '"') i = skipDouble(src, i + 1);
    else if (c === "`") i = skipBackticks(src, i + 1);
    else if (c === "$") i = skipDollar(src, i);
    else i++;
  }
  return Math.min(i, src.length);
}

function readDelimiter(src, from) {
  let i = from;
  let delimiter = "";
  while (i < src.length && !isSpace(src[i]) && !isOperator(src[i])) {
    const c = src[i];
    if (c === "'" || c === '"') {
      const end = src.indexOf(c, i + 1);
      if (end === -1) throw new Unparseable();
      delimiter += src.slice(i + 1, end);
      i = end + 1;
    } else {
      delimiter += c === "\\" ? (src[i + 1] ?? "") : c;
      i += c === "\\" ? 2 : 1;
    }
  }
  if (delimiter === "") throw new Unparseable();
  return { delimiter, end: Math.min(i, src.length) };
}

function readHeredoc(src, from) {
  let i = from + 2;
  const strip = src[i] === "-";
  if (strip) i++;
  while (src[i] === " " || src[i] === "\t") i++;
  const { delimiter, end } = readDelimiter(src, i);
  return { heredoc: { delimiter, strip }, end };
}

function skipHeredocBodies(src, from, heredocs) {
  let i = from;
  for (const { delimiter, strip } of heredocs) {
    let closed = false;
    while (!closed) {
      if (i >= src.length) throw new Unparseable();
      const newline = src.indexOf("\n", i);
      const line = src.slice(i, newline === -1 ? src.length : newline);
      closed = (strip ? line.replace(/^\t+/, "") : line) === delimiter;
      i = newline === -1 ? src.length : newline + 1;
    }
  }
  return i;
}

function scanCommands(src, from, closer) {
  let i = from;
  let assignPos = true;
  let declaring = false;
  let heredocs = [];
  while (i < src.length) {
    const c = src[i];
    if (c === "\n") {
      i = skipHeredocBodies(src, i + 1, heredocs);
      heredocs = [];
      assignPos = true;
      declaring = false;
    } else if (isSpace(c)) {
      i++;
    } else if (c === "\\" && src[i + 1] === "\n") {
      i += 2;
    } else if (c === "#") {
      while (i < src.length && src[i] !== "\n") i++;
    } else if (c === ";" || c === "&" || c === "|") {
      i++;
      assignPos = true;
      declaring = false;
    } else if (c === "<" && src.startsWith("<<<", i)) {
      i += 3;
    } else if (c === "<" && src[i + 1] === "<") {
      const { heredoc, end } = readHeredoc(src, i);
      heredocs = [...heredocs, heredoc];
      i = end;
    } else if (c === "<" || c === ">") {
      i++;
    } else if (c === "(" && src[i + 1] === "(") {
      i = skipArithmetic(src, i + 2);
      assignPos = false;
    } else if (c === "(") {
      i = scanCommands(src, i + 1, ")");
      assignPos = true;
      declaring = false;
    } else if (c === ")") {
      i++;
      if (closer === ")") return i;
      assignPos = true;
    } else if (c === "[" && src[i + 1] === "[" && isSpace(src[i + 2])) {
      i = skipConditional(src, i + 3);
      assignPos = false;
    } else {
      const atCommand = assignPos && !declaring;
      const isAssignment = checkWordStart(src, i, assignPos || declaring);
      const end = scanWordBody(src, i);
      const text = src.slice(i, end);
      if (atCommand && DECLARATIONS.has(text)) declaring = true;
      if (!isAssignment) assignPos = declaring || (atCommand && KEYWORDS.has(text));
      i = end;
    }
  }
  if (closer !== "") throw new Unparseable();
  return i;
}

export function findEqualsWord(command) {
  firstWord = undefined;
  try {
    scanCommands(command, 0, "");
    return firstWord;
  } catch (error) {
    if (error instanceof Unparseable || error instanceof RangeError) return undefined;
    throw error;
  } finally {
    firstWord = undefined;
  }
}

async function bashUsesZsh($) {
  const session = await $.session.id();
  const known = shells.get(session);
  if (known !== undefined) return known;
  const zsh = shellIsZsh(await $.env.get("CLAUDE_CODE_SHELL"), await $.env.get("SHELL"));
  shells.set(session, zsh);
  return zsh;
}

export function registerZshGuard(on) {
  on("tool.check", { tool: /^Bash$/ }, async ($, e, next) => {
    const command = e.input?.command;
    if (typeof command !== "string" || !(await bashUsesZsh($))) return next(e);
    const word = findEqualsWord(command);
    return word === undefined ? next(e) : { decision: "deny", reason: zshDenial(word) };
  }).catch(($, e, next) => next(e));
}
