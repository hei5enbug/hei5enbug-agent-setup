import { expect, test } from "claude-code/testing";
import { findEqualsWord, shellIsZsh, zshDenial } from "./zsh.js";

const BLOCKED = [
  ["echo =====; ls /tmp/work", "====="],
  ["echo ==", "=="],
  ['[ "$a" == 1 ]', "=="],
  ["test a == b", "=="],
  ["x==foo", "x==foo"],
  ["FOO=1 y==foo true", "y==foo"],
  ["export x==foo", "x==foo"],
  ["local -r x==foo", "x==foo"],
  ["a[1]==foo", "a[1]==foo"],
  ["case =x in x) ;; esac", "=x"],
  ["case a in =*) echo y;; esac", "=*"],
  ["echo x =y", "=y"],
  ["echo =ls", "=ls"],
  ['echo ="ls"', '="ls"'],
  ["echo ok && echo ==", "=="],
  ["echo ok\necho ====", "===="],
  ["echo $(echo ====)", "===="],
  ['echo "$(echo =x)"', "=x"],
  ["echo `echo =x`", "=x"],
  ["( echo =x )", "=x"],
  ["echo ok | tr a b; echo ==", "=="],
  ["echo ok # note\necho ==", "=="],
  ["cat <<EOF\nbody\nEOF\necho ==", "=="],
  ["for x in =a; do echo $x; done", "=a"],
  ["true && export x==foo", "x==foo"],
  ["FOO=1 export x==foo", "x==foo"],
  ["true; local a==b", "a==b"],
  ["time export x==foo", "x==foo"],
  ["if true; then export x==foo; fi", "x==foo"],
] as const;

const ALLOWED = [
  "echo '====='",
  'echo "====="',
  "echo =",
  "echo =;echo ok",
  "echo =>/dev/null",
  "case a in =) echo y;; esac",
  "[[ $a == b ]]",
  "if [[ $a == b ]]; then echo ok; fi",
  '[[ "$a" == "=" && $b == [=] ]]',
  "(( 1 == 1 ))",
  "for ((i = 0; i == 0; i++)); do echo $i; done",
  "echo $(( 1 == 1 ))",
  "echo a=b --k==v",
  'echo "=quoted" \\=esc \'=x\'',
  "echo $'=x' $'it\\'s' =",
  "cat =(echo hi)",
  "echo x==foo",
  "env FOO==bar true",
  "echo $(date)=x",
  "echo ok # ==== note",
  "echo ok #=x",
  "cat <<EOF\n=====\nEOF\necho ok",
  "cat <<-EOF\n\t=====\n\tEOF\necho ok",
  "cat <<'EOF'\n=====\n$(echo ==)\nEOF",
  'cat <<"EOF"\n=====\nEOF',
  "cat <<EOF >out.txt; echo ok\n=====\nEOF",
  "cat <<A <<B\n==\nA\n==\nB",
  "echo ${x:-=y}",
  "echo \"${x:-a b}\" '='",
  "git commit -m \"==== title ====\"",
  "ls -la /tmp",
  "printf '%s\\n' export x==foo",
  "echo local a==b",
  "echo if x==foo",
  "echo then y==foo",
  "ls typeset a==b; echo ok",
  "",
] as const;

const UNPARSEABLE = [
  "echo 'unterminated =x",
  'echo "unterminated =x',
  "echo $(echo =x",
  "echo `echo =x",
  "echo ${x:-=y",
  "echo $(( 1 == 1 ",
  "[[ a == b",
  "cat <<EOF\n=====\nnever ends",
  "echo \\",
] as const;

test("등호로 시작하는 따옴표 없는 단어와 대입 값을 찾아 그 단어를 돌려준다", () => {
  // given
  const commands = BLOCKED.map(([command]) => command);

  // when
  const words = commands.map((command) => findEqualsWord(command));

  // then
  expect(words).toEqual(BLOCKED.map(([, word]) => word));
});

test("따옴표, 이스케이프, 비교식, 산술식, 프로세스 치환, 히어도큐먼트, 주석 안의 등호는 찾지 않는다", () => {
  // given
  const commands = [...ALLOWED];

  // when
  const words = commands.map((command) => findEqualsWord(command));

  // then
  expect(words).toEqual(commands.map(() => undefined));
});

test("끝나지 않은 따옴표나 치환처럼 해석할 수 없는 입력은 명령을 막지 않는다", () => {
  // given
  const commands = [...UNPARSEABLE];

  // when
  const words = commands.map((command) => findEqualsWord(command));

  // then
  expect(words).toEqual(commands.map(() => undefined));
});

test("안내 문구는 막힌 단어, 따옴표 예시, 비교식, command -v 대안을 포함한다", () => {
  // given
  const word = "=====";

  // when
  const text = zshDenial(word);

  // then
  expect(text).toContain("`=====`");
  expect(text).toContain("echo '====='");
  expect(text).toContain("[[ ... == ... ]]");
  expect(text).toContain("$(command -v <name>)");
});

test("CLAUDE_CODE_SHELL이 bash나 zsh이면 그 값을, 아니면 SHELL을, 둘 다 아니면 zsh로 본다", () => {
  // given
  const cases = [
    { claude: "/opt/homebrew/bin/zsh", shell: "/bin/bash", zsh: true },
    { claude: "/usr/bin/bash", shell: "/bin/zsh", zsh: false },
    { claude: undefined, shell: "/bin/zsh", zsh: true },
    { claude: undefined, shell: "/usr/local/bin/bash", zsh: false },
    { claude: "", shell: "/bin/bash", zsh: false },
    { claude: "/usr/bin/fish", shell: "/bin/bash", zsh: false },
    { claude: "/usr/bin/fish", shell: "/usr/bin/fish", zsh: true },
    { claude: undefined, shell: undefined, zsh: true },
    { claude: "zsh", shell: undefined, zsh: true },
  ];

  // when
  const results = cases.map((item) => shellIsZsh(item.claude, item.shell));

  // then
  expect(results).toEqual(cases.map((item) => item.zsh));
});

test("10KB 명령을 검사하는 데 50ms가 들지 않는다", () => {
  // given
  const unit = "git log --oneline | grep 'fix: a == b' && echo \"$(date)\" # note =x\n";
  const command = unit.repeat(Math.ceil(10_240 / unit.length)) + "cat <<EOF\n=====\nEOF\n";
  const quoted = "echo '" + "=".repeat(10_240) + "'";
  const before = performance.now();

  // when
  const found = [findEqualsWord(command), findEqualsWord(quoted)];
  const elapsed = performance.now() - before;

  // then
  expect(found).toEqual([undefined, undefined]);
  expect(command.length).toBeGreaterThan(10_240);
  expect(elapsed).toBeLessThan(50);
});

const ENV_WORLD = [
  { name: "zsh 셸", env: { SHELL: "/bin/zsh" }, session: "zsh-shell", denied: true },
  { name: "CLAUDE_CODE_SHELL이 zsh", env: { CLAUDE_CODE_SHELL: "/bin/zsh", SHELL: "/bin/bash" }, session: "zsh-claude", denied: true },
  { name: "bash 셸", env: { SHELL: "/bin/bash" }, session: "bash-shell", denied: false },
  { name: "CLAUDE_CODE_SHELL이 bash", env: { CLAUDE_CODE_SHELL: "/bin/bash", SHELL: "/bin/zsh" }, session: "bash-claude", denied: false },
] as const;

for (const world of ENV_WORLD) {
  test(`실제 Mod 필터에서 ${world.name}이면 등호 단어 명령을 ${world.denied ? "거부한다" : "통과시킨다"}`, async ($, on) => {
    // given
    on("env.get", (_$, e) => ({ value: world.env[e.name] }));
    on("session.id", () => ({ value: world.session }));
    on("tool.check", () => ({ decision: "allow" }));

    // when
    const verdict = await $.tool.check({ tool: "Bash", input: { command: "echo =====; ls /tmp/work" } });

    // then
    expect(verdict.decision).toEqual(world.denied ? "deny" : "allow");
    if (world.denied) expect(verdict.reason).toEqual(zshDenial("====="));
  });
}

test("실제 Mod 필터에서 따옴표로 감싼 명령과 비교식은 zsh에서도 통과시킨다", async ($, on) => {
  // given
  on("env.get", (_$, e) => ({ value: ({ SHELL: "/bin/zsh" })[e.name] }));
  on("session.id", () => ({ value: "zsh-allowed" }));
  on("tool.check", () => ({ decision: "allow" }));
  const commands = ["echo '====='", "[[ $a == b ]]", '[ "$a" = b ]'];

  // when
  const verdicts = [];
  for (const command of commands) verdicts.push((await $.tool.check({ tool: "Bash", input: { command } })).decision);

  // then
  expect(verdicts).toEqual(["allow", "allow", "allow"]);
});

test("실제 Mod 필터에서 Bash가 아닌 도구와 command가 문자열이 아닌 입력은 검사하지 않는다", async ($, on) => {
  // given
  on("env.get", (_$, e) => ({ value: ({ SHELL: "/bin/zsh" })[e.name] }));
  on("session.id", () => ({ value: "zsh-other-tools" }));
  on("tool.check", () => ({ decision: "allow" }));

  // when
  const write = await $.tool.check({ tool: "Write", input: { file_path: "/tmp/work/x", content: "echo ====" } });
  const odd = await $.tool.check({ tool: "Bash", input: { command: 42 } });

  // then
  expect([write.decision, odd.decision]).toEqual(["allow", "allow"]);
});
