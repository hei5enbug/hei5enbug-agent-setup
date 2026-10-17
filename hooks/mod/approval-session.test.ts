import { expect, test } from "claude-code/testing";
import { DESTRUCTIVE_REASON, registerApproval } from "./approval.js";

const REPO_WITH_V1 = "/repos/with-v1";
const REPO_WITHOUT = "/repos/without-tags";
const NO_REMOTE_REPO = "/repos/no-remote";
const REPOS = {
  [REPO_WITH_V1]: { tags: ["v1"], remotes: ["origin"] },
  [REPO_WITHOUT]: { tags: [], remotes: ["origin"] },
  [NO_REMOTE_REPO]: { tags: [], remotes: [] },
};
const TAG = ["git:tag"];
const PUSH_TAG = ["git:push-tag"];
const TAG_PUSH = ["git:push-tag", "git:tag"];
const RELEASE = ["gh:release"];
const NONE = [];
const PLUGIN = "/plugin";
const MISSING_PLUGIN = "/missing-plugin";
const REGISTRY_TEXT = JSON.stringify({
  pins: {},
  claude_agents: {
    "hei5enbug-agent-setup:scout": { role: "scout", model: "claude-sonnet-5-5", effort: "medium", access: "read" },
    "hei5enbug-agent-setup:sonnet-worker": { role: "worker", model: "claude-sonnet-5-5", effort: "high", access: "write" },
  },
  codex_agents: {
    scout: { model: "gpt-5.6-luna", effort: "xhigh", access: "read" },
    worker: { model: "gpt-5.6-luna", effort: "xhigh", access: "write" },
  },
  effort_rules: {},
  gpt_gateway_models: [],
  capabilities: Object.fromEntries(
    ["investigation", "implementation", "design", "language", "review"]
      .map(name => [name, {}]),
  ),
});

const NOW = Date.UTC(2026, 9, 7, 12, 0, 0);
const DAY = 24 * 60 * 60 * 1000;
const CORE = { decision: "ask", reason: "core" };
const OK_RESULT = { result: "ok", text: "ok", ref: 1 };

function gitRunner(argv) {
  const repo = REPOS[argv[2]];
  if (repo === undefined) return { exitCode: 128, stdout: "", stderr: "fatal: not a git repository" };
  if (argv[3] === "remote") return { exitCode: 0, stdout: repo.remotes.map(name => `${name}\n`).join(""), stderr: "" };
  if (argv[3] === "rev-parse") {
    const name = argv[argv.length - 1].replace("refs/tags/", "");
    return { exitCode: repo.tags.includes(name) ? 0 : 1, stdout: "", stderr: "" };
  }
  throw new Error(`unexpected command: ${argv.join(" ")}`);
}

function stubRealpath(env, path) {
  if (env.realpathThrows) throw new Error("timed out");
  if (env.realpathFails.some(failing => path === failing || path.startsWith(`${failing}/`))) {
    return { exitCode: 1, stdout: "", stderr: "realpath: No such file or directory" };
  }
  const link = Object.keys(env.links)
    .filter(from => path === from || path.startsWith(`${from}/`))
    .sort((a, b) => b.length - a.length)[0];
  const real = link === undefined ? path : `${env.links[link]}${path.slice(link.length)}`;
  return { exitCode: 0, stdout: `${real}\n`, stderr: "" };
}

function createEnv(options = {}) {
  const env = {
    cwd: "cwd" in options ? options.cwd : REPO_WITH_V1,
    sessionId: "sessionId" in options ? options.sessionId : "sess-1",
    now: options.now ?? NOW,
    data: options.data ?? {},
    run: options.run ?? gitRunner,
    links: options.links ?? {},
    realpathFails: options.realpathFails ?? [],
    realpathThrows: options.realpathThrows ?? false,
    failGet: options.failGet ?? false,
    failSet: options.failSet ?? false,
    calls: [],
    writes: [],
  };
  env.$ = {
    plugin: { root: options.registryFails ? MISSING_PLUGIN : PLUGIN },
    fs: {
      read: async path => {
        if (path.startsWith(MISSING_PLUGIN)) throw new Error("registry missing");
        return REGISTRY_TEXT;
      },
    },
    session: {
      cwd: async () => {
        if (env.cwd instanceof Error) throw env.cwd;
        return env.cwd;
      },
      id: async () => {
        if (env.sessionId instanceof Error) throw env.sessionId;
        return env.sessionId;
      },
    },
    process: {
      run: async (argv, init) => {
        env.calls.push({ argv, init });
        if (argv[0] === "/bin/realpath") return stubRealpath(env, argv[1]);
        return env.run(argv, init);
      },
    },
    clock: { now: async () => env.now },
    store: {
      get: async key => {
        if (env.failGet) throw new Error("store unavailable");
        return key in env.data ? JSON.parse(JSON.stringify(env.data[key])) : undefined;
      },
      set: async (key, value) => {
        if (env.failSet) throw new Error("store unavailable");
        env.writes.push(key);
        env.data[key] = JSON.parse(JSON.stringify(value));
      },
    },
  };
  return env;
}

function registerHooks() {
  const entries = [];
  const on = (event, matcher, handler) => {
    const entry = { event, matcher, handler, catcher: undefined };
    entries.push(entry);
    return {
      catch(catcher) {
        entry.catcher = catcher;
        return this;
      },
    };
  };
  registerApproval(on);

  async function dispatch(event, env, e, answer) {
    const entry = entries.find(candidate => candidate.event === event);
    let called = false;
    let settled;
    const next = async () => {
      if (!called) {
        called = true;
        settled = answer;
      }
      return settled;
    };
    try {
      return await entry.handler(env.$, e, next);
    } catch (error) {
      const caught = async () => next();
      Object.defineProperty(caught, "called", { get: () => called });
      caught.error = error;
      return entry.catcher(env.$, e, caught);
    }
  }

  return {
    entries,
    check: (env, e, answer = CORE) => dispatch("tool.check", env, e, answer),
    call: (env, e, answer = OK_RESULT) => dispatch("tool.call", env, e, answer),
  };
}

function checkEvent(command, extra = {}) {
  return { tool: "Bash", input: { command }, tool_use_id: "toolu-1", ...extra };
}

function callEvent(command, extra = {}) {
  return { tool: "Bash", command, tool_use_id: "toolu-1", ...extra };
}

async function approve(hooks, env, ...commands) {
  for (const command of commands) await hooks.call(env, callEvent(command));
}


const ASK_TAIL = "Approve once; git tag/push, gh release, and extra-directory writes then run without asking for the rest of this session.";

function writeAsk(label) {
  return { decision: "ask", reason: `Write: ${label}. ${ASK_TAIL}` };
}

function earlier(label) {
  return { decision: "allow", reason: `Approved earlier in this session: ${label}` };
}

test("처음 쓰기는 무슨 쓰기인지 사람이 읽는 이름으로 짧게 묻는다", async () => {
  const hooks = registerHooks();
  const env = createEnv();
  expect(await hooks.check(env, checkEvent("git tag v2"))).toEqual(writeAsk("git tag"));
  expect(await hooks.check(env, checkEvent("gh release create v2"))).toEqual(writeAsk("gh release"));
});

test("한 번 승인하면 다른 종류의 쓰기도 세션 동안 허용하고 기록은 하나의 키다", async () => {
  const hooks = registerHooks();
  const env = createEnv();
  await approve(hooks, env, "git tag v2");
  expect(env.data.approvals).toEqual({ "sess-1": { time: NOW, keys: ["write:session"] } });
  expect(await hooks.check(env, checkEvent("gh release create v2"))).toEqual(earlier("gh release"));
  expect(await hooks.check(env, checkEvent("git push origin v1"))).toEqual(earlier("git push of a tag"));
  expect(await hooks.check(env, checkEvent("git tag v3"))).toEqual(earlier("git tag"));
});

test("여러 키가 든 명령은 이름을 키 순서대로 이어 보여 준다", async () => {
  const hooks = registerHooks();
  const env = createEnv();
  const first = await hooks.check(env, checkEvent("git tag v2 && git push origin v2"));
  expect(first).toEqual(writeAsk("git push of a tag + git tag"));
});

test("되돌릴 수 없는 작업은 승인 뒤에도 매번 묻고 키를 기록하지 않는다", async () => {
  const hooks = registerHooks();
  const env = createEnv();
  await approve(hooks, env, "git tag v2");
  const before = JSON.stringify(env.data);
  const result = await hooks.check(env, checkEvent("git tag -d v1"));
  await hooks.call(env, callEvent("git tag -d v1"));
  expect(result).toEqual({ decision: "ask", reason: DESTRUCTIVE_REASON });
  expect(JSON.stringify(env.data)).toBe(before);
});

test("다른 세션은 승인을 물려받지 않는다", async () => {
  const hooks = registerHooks();
  const env = createEnv();
  await approve(hooks, env, "git tag v2");
  const other = createEnv({ data: env.data, sessionId: "sess-2" });
  expect((await hooks.check(other, checkEvent("git tag v3"))).decision).toBe("ask");
});

test("하위 에이전트는 메인 세션의 승인을 쓰지 않고 묻는다", async () => {
  const hooks = registerHooks();
  const env = createEnv();
  await approve(hooks, env, "git tag v2");
  const result = await hooks.check(env, checkEvent("git tag v3", { agentId: "agent-1" }));
  expect(result).toEqual(writeAsk("git tag"));
});

test("쓰기를 기록하지 않는 읽기 명령은 코어 결정을 그대로 둔다", async () => {
  const hooks = registerHooks();
  const env = createEnv();
  expect(await hooks.check(env, checkEvent("git tag -l"))).toEqual(CORE);
  expect(await hooks.check(env, checkEvent("git status"))).toEqual(CORE);
});
