import { expect, test } from "claude-code/testing";
import { impactOf, sqlImpact } from "./impact.js";

function host(answer = () => ({ stdout: "" }), exists = () => true) {
  const runs = [];
  const checked = [];
  const $ = {
    session: { cwd: async () => "/work" },
    env: { get: async (name) => ({ HOME: "/home/test" })[name] },
    fs: {
      exists: async (path) => {
        checked.push(path);
        return exists(path);
      },
    },
    process: {
      run: async (argv, init) => {
        runs.push({ argv, cwd: init?.cwd, timeoutMs: init?.timeoutMs });
        const result = answer(argv);
        if (result instanceof Error) throw result;
        return { exitCode: 0, stderr: "", isStdoutTruncated: false, isStderrTruncated: false, ...result };
      },
    },
  };
  return { $, runs, checked };
}

test("git reset --hard는 작업 트리와 인덱스를 대상 ref와 비교해 스테이징만 된 변경까지 합쳐 보여준다", async () => {
  // given
  const { $, runs } = host((argv) => ({ stdout: argv.includes("--cached") ? "3\t1\ta.txt\n1\t0\tb.txt\n" : "5\t2\ta.txt\n" }));

  // when
  const text = await impactOf($, "Bash", { command: "cd repo && git reset --hard origin/main" });

  // then
  expect(text).toBe("discards 2 files (+6/-2)");
  expect(runs).toEqual([
    { argv: ["git", "diff", "--numstat", "origin/main"], cwd: "/work/repo", timeoutMs: 3000 },
    { argv: ["git", "diff", "--numstat", "--cached", "origin/main"], cwd: "/work/repo", timeoutMs: 3000 },
  ]);
});

test("작업 트리가 HEAD와 같아도 스테이징된 변경이 있으면 git reset --hard가 버릴 변경으로 센다", async () => {
  // given
  const { $ } = host((argv) => ({ stdout: argv.includes("--cached") ? "4\t0\tstaged.txt\n" : "" }));

  // when
  const text = await impactOf($, "Bash", { command: "git reset --hard" });

  // then
  expect(text).toBe("discards 1 file (+4/-0)");
});

test("git checkout -- 경로와 git restore 경로는 작업 트리만 그 경로로 좁혀 비교하고 변경이 없으면 그렇게 알린다", async () => {
  // given
  const { $, runs } = host((argv) => ({ stdout: argv.includes("a.txt") ? "2\t0\ta.txt\n" : "" }));

  // when
  const checkout = await impactOf($, "Bash", { command: "git checkout -- a.txt b.txt" });
  const restore = await impactOf($, "Bash", { command: "git -C /repo restore --source=HEAD~1 src" });

  // then
  expect(checkout).toBe("discards 1 file (+2/-0)");
  expect(restore).toBe("nothing to discard");
  expect(runs.map((run) => [run.argv, run.cwd])).toEqual([
    [["git", "diff", "--numstat", "--", "a.txt", "b.txt"], "/work"],
    [["git", "diff", "--numstat", "HEAD~1", "--", "src"], "/repo"],
  ]);
});

test("git clean은 -n으로 미리 보고 -f가 두 번 이상이면 -ff를 남겨 중첩 저장소까지 보여준다", async () => {
  // given
  const output = ["Would remove a.log", "Would remove build/", "Would remove c.tmp", "Would remove nested/", ""].join("\n");
  const { $, runs } = host(() => ({ stdout: output }));

  // when
  const double = await impactOf($, "Bash", { command: "git clean -ffdx -e keep.txt" });
  await impactOf($, "Bash", { command: "git clean -fd" });
  await impactOf($, "Bash", { command: "git clean --force -f -d" });

  // then
  expect(double).toBe("removes 4 paths: a.log, build/, c.tmp, ...");
  expect(runs.map((run) => run.argv)).toEqual([
    ["git", "clean", "-n", "-ff", "-dx", "-e", "keep.txt"],
    ["git", "clean", "-n", "-d"],
    ["git", "clean", "-n", "-ff", "-d"],
  ]);
});

test("rm -r는 있는 경로만 세어 파일 수와 전체 크기를 보여주고 상한을 넘으면 N+로 줄인다", async () => {
  // given
  const small = host((argv) => ({ stdout: argv[0] === "du" ? "2048\tbuild\n4\tdist\n" : "      12\n" }), (path) => path !== "/work/gone");
  const large = host((argv) => ({ stdout: argv[0] === "du" ? "5242880\t/home/test/cache\n" : "10001\n" }));
  const none = host(() => ({ stdout: "" }), () => false);

  // when
  const counted = await impactOf(small.$, "Bash", { command: "rm -rf build gone dist" });
  const capped = await impactOf(large.$, "Bash", { command: "rm -r ~/cache" });
  const nothing = await impactOf(none.$, "Bash", { command: "rm -rf gone" });

  // then
  expect(counted).toBe("deletes 12 files (2.0 MB)");
  expect(capped).toBe("deletes 10000+ files (5.0 GB)");
  expect(nothing).toBe("nothing to delete");
  expect(small.checked).toEqual(["/work/build", "/work/gone", "/work/dist"]);
  expect(small.runs.map((run) => run.argv)).toEqual([
    ["sh", "-c", 'find "$@" -type f 2>/dev/null | head -n 10001 | wc -l', "sh", "build", "dist"],
    ["du", "-sk", "build", "dist"],
  ]);
  expect(none.runs).toEqual([]);
});

test("rm -r 미리보기는 du가 실패하거나 오류를 쓰거나 일부 경로만 답하면 개수를 보여주지 않는다", async () => {
  // given
  const outcomes = [
    { exitCode: 1, stdout: "2048\tbuild\n4\tdist\n", stderr: "" },
    { exitCode: 0, stdout: "2048\tbuild\n4\tdist\n", stderr: "du: dist/private: Permission denied\n" },
    { exitCode: 0, stdout: "2048\tbuild\n", stderr: "" },
  ];

  // when
  const texts = [];
  for (const outcome of outcomes) {
    const { $ } = host((argv) => (argv[0] === "du" ? outcome : { stdout: "12\n" }));
    texts.push(await impactOf($, "Bash", { command: "rm -rf build dist" }));
  }

  // then
  expect(texts).toEqual([undefined, undefined, undefined]);
});

test("kubectl delete는 기본 kubeconfig로 같은 리소스, 이름, 네임스페이스, 컨텍스트, 셀렉터의 kubectl get -o name을 실행한다", async () => {
  // given
  const { $, runs } = host(() => ({ stdout: "pod/web-1\npod/web-2\n" }));

  // when
  const named = await impactOf($, "Bash", { command: "kubectl --context demo-prod delete pod web-1 web-2 -n web --grace-period=0 --wait" });
  const selected = await impactOf($, "Bash", { command: "kubectl delete pods -l app=web --namespace=web" });

  // then
  expect(named).toBe("deletes 2: pod/web-1, pod/web-2");
  expect(selected).toBe("deletes 2: pod/web-1, pod/web-2");
  expect(runs.map((run) => run.argv)).toEqual([
    ["kubectl", "get", "pod", "web-1", "web-2", "--context", "demo-prod", "-n", "web", "-o", "name"],
    ["kubectl", "get", "pods", "-l", "app=web", "--namespace=web", "-o", "name"],
  ]);
});

test("kubectl delete가 다른 kubeconfig, 토큰, 서버, 가장, 인증서를 지정하면 미리보기 명령을 실행하지 않는다", async () => {
  // given
  const { $, runs } = host(() => ({ stdout: "pod/web-1\n" }));
  const commands = [
    "kubectl delete pod web-1 --kubeconfig /tmp/untrusted",
    "kubectl --kubeconfig=/tmp/untrusted delete pod web-1",
    "kubectl delete pod web-1 --token abc",
    "kubectl delete pod web-1 --server https://example.com",
    "kubectl delete pod web-1 -s https://example.com",
    "kubectl delete pod web-1 --as admin",
    "kubectl delete pod web-1 --as-group system:masters",
    "kubectl delete pod web-1 --certificate-authority /tmp/ca.crt",
    "kubectl delete pod web-1 --client-certificate /tmp/c.crt --client-key /tmp/c.key",
    "kubectl delete pod web-1 --cluster other --user other",
    "kubectl delete -f /tmp/manifest.yaml",
    "KUBECONFIG=/tmp/untrusted kubectl delete pod web-1",
    "cd /work && KUBECONFIG=/tmp/untrusted kubectl delete pod web-1",
  ];

  // when
  const texts = [];
  for (const command of commands) texts.push(await impactOf($, "Bash", { command }));

  // then
  expect(texts).toEqual(commands.map(() => undefined));
  expect(runs).toEqual([]);
});

test("kubectl get이 실패하면 출력이 있어도 영향 문구를 보여주지 않는다", async () => {
  // given
  const { $ } = host(() => ({ exitCode: 1, stdout: "pod/web-1\n", stderr: "Error from server (NotFound)\n" }));

  // when
  const text = await impactOf($, "Bash", { command: "kubectl delete pod web-1 web-2" });

  // then
  expect(text).toBeUndefined();
});

test("안전하게 옮길 수 없는 인자와 셸 확장이 있는 명령은 아무것도 실행하지 않는다", async () => {
  // given
  const { $, runs } = host();
  const commands = [
    "kubectl delete pod web-1 --grace-period 0",
    "kubectl delete pod web-1 --raw /x",
    "rm -rf $TARGET",
    "rm -rf build/*",
    "git reset --hard && rm -rf build | tee log",
    "git reset --hard $(git rev-parse HEAD~1)",
    "sudo rm -rf /opt/x",
  ];

  // when
  const texts = [];
  for (const command of commands) texts.push(await impactOf($, "Bash", { command }));

  // then
  expect(texts).toEqual(commands.map(() => undefined));
  expect(runs).toEqual([]);
});

test("미리보기 명령이 시간 초과나 오류로 끝나면 영향 문구를 보여주지 않는다", async () => {
  // given
  const timedOut = host(() => new Error("timed out after 3000ms"));
  const failed = host(() => ({ exitCode: 128, stdout: "" }));

  // when
  const texts = [
    await impactOf(timedOut.$, "Bash", { command: "git reset --hard" }),
    await impactOf(timedOut.$, "Bash", { command: "rm -rf build" }),
    await impactOf(failed.$, "Bash", { command: "git clean -fd" }),
    await impactOf(failed.$, "Bash", { command: "git reset --hard" }),
  ];

  // then
  expect(texts).toEqual([undefined, undefined, undefined, undefined]);
  expect(timedOut.runs.every((run) => run.timeoutMs === 3000)).toBe(true);
});

test("SQL 문장은 DB에 묻지 않고 텍스트만으로 DROP, TRUNCATE 대상과 WHERE 없는 DELETE를 보여준다", async () => {
  // given
  const { $, runs } = host();

  // when
  const psql = await impactOf($, "Bash", { command: `psql -h demo --set ON_ERROR_STOP=1 -c "DELETE FROM orders; DROP TABLE IF EXISTS a, b"` });
  const mcp = await impactOf($, "mcp__demo__run_query", { connection_id: "c1", query: "truncate table logs; delete from users where id = 1" });
  const plain = sqlImpact("select 1");

  // then
  expect(psql).toBe("deletes from orders without WHERE; drops table a, b");
  expect(mcp).toBe("truncates logs; deletes from users");
  expect(plain).toBeUndefined();
  expect(runs).toEqual([]);
});

test("WHERE는 주석, 문자열 리터럴, 따옴표 식별자 안에 있으면 세지 않고 리터럴 안의 세미콜론으로 문장을 나누지 않는다", () => {
  // given
  const statements = [
    "DELETE FROM t -- WHERE id = 1",
    "DELETE FROM t /* WHERE id = 1 */",
    "DELETE FROM t RETURNING 'where'",
    'DELETE FROM "where"',
    "DELETE FROM t WHERE note = 'a;b'",
    "DELETE FROM t\n-- cleanup\nWHERE id = 1",
  ];

  // when
  const texts = statements.map((statement) => sqlImpact(statement));

  // then
  expect(texts).toEqual([
    "deletes from t without WHERE",
    "deletes from t without WHERE",
    "deletes from t without WHERE",
    'deletes from "where" without WHERE',
    "deletes from t",
    "deletes from t",
  ]);
});

test("언어로 Korean을 넘기면 모든 영향 문구를 한국어로 쓰고 개수, 크기, 이름, 목록과 문장 구분은 그대로 둔다", async () => {
  // given
  const outputs = {
    git: (argv) => (argv[1] === "clean" ? "Would remove a.log\nWould remove b/\n" : argv.includes("src") ? "" : "5\t2\ta.txt\n"),
    sh: () => "12\n",
    du: () => "2048\tbuild\n",
    kubectl: (argv) => (argv.includes("web-9") ? "" : "pod/web-1\n"),
  };
  const filled = host((argv) => ({ stdout: outputs[argv[0]](argv) }), (path) => path !== "/work/gone");
  const capped = host((argv) => ({ stdout: argv[0] === "du" ? "5242880\t/home/test/cache\n" : "10001\n" }));
  const empty = host(() => ({ stdout: "" }));
  const calls = [
    [filled.$, "Bash", { command: "git reset --hard" }],
    [filled.$, "Bash", { command: "git restore src" }],
    [filled.$, "Bash", { command: "git clean -fd" }],
    [empty.$, "Bash", { command: "git clean -fd" }],
    [filled.$, "Bash", { command: "rm -rf build" }],
    [capped.$, "Bash", { command: "rm -r ~/cache" }],
    [filled.$, "Bash", { command: "rm -rf gone" }],
    [filled.$, "Bash", { command: "kubectl delete pod web-1" }],
    [filled.$, "Bash", { command: "kubectl delete pod web-9" }],
    [empty.$, "mcp__demo__run_query", { query: "DROP MATERIALIZED VIEW IF EXISTS v; TRUNCATE logs; DELETE FROM orders; DELETE FROM users WHERE id = 1" }],
  ] as const;

  // when
  const texts = [];
  for (const [$, tool, input] of calls) texts.push(await impactOf($, tool, input, "Korean"));

  // then
  expect(texts).toEqual([
    "파일 1개 변경 버림 (+5/-2)",
    "버릴 변경 없음",
    "경로 2개 삭제: a.log, b/",
    "지울 대상 없음",
    "파일 12개 삭제 (2.0 MB)",
    "파일 10000개 이상 삭제 (5.0 GB)",
    "지울 대상 없음",
    "1개 삭제: pod/web-1",
    "일치하는 리소스 없음",
    "materialized view v 삭제; logs 비움; orders 행 삭제 (WHERE 없음); users 행 삭제",
  ]);
});

test("Bash와 MCP가 아닌 도구는 입력에 SQL이 있어도 영향을 계산하지 않는다", async () => {
  // given
  const { $, runs } = host();

  // when
  const text = await impactOf($, "Write", { file_path: "/work/a.sql", content: "DROP TABLE users" });

  // then
  expect(text).toBeUndefined();
  expect(runs).toEqual([]);
});
