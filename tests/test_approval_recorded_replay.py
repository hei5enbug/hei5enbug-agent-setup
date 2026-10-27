"""Replay of every approval-guard ask recorded in interactive sessions since 2026-10-26, rebuilt with fictional paths.

Each case is a call where the agent made no mistake, so the guard must neither ask nor deny. The case the coordinator
kept, a removal whose target goes through `$PWD`, must still ask every time."""
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import approval_guard as guard  # noqa: E402
import approval_state as state_mod  # noqa: E402

READ_ONLY_BODY = "import json, re, sys\nfrom pathlib import Path\nprint(len(list(Path(sys.argv[1]).glob('*'))))\n"
GIT_CONFIG = {"GIT_CONFIG_COUNT": "2", "GIT_CONFIG_KEY_0": "credential.interactive", "GIT_CONFIG_VALUE_0": "false",
              "GIT_CONFIG_KEY_1": "credential.guiPrompt", "GIT_CONFIG_VALUE_1": "false"}


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "xdg"))
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "claude-config"))
    monkeypatch.setenv("HEI5ENBUG_RESPONSE_LANGUAGE", "English")
    state_mod.prompt_language.cache_clear()
    for name in [name for name in os.environ if name.startswith("GIT_")] + [
            "HEI5ENBUG_PARENT_SESSION", "KUBECONFIG", "AWS_PROFILE", "CLOUDSDK_CORE_PROJECT", "DOCKER_CONTEXT",
            "DOCKER_HOST", "HEI5ENBUG_LANGUAGE", "CLAUDE_PROJECT_DIR"]:
        monkeypatch.delenv(name, raising=False)
    scratch = tmp_path / "scratchpad"
    scratch.mkdir()
    (scratch / "files.txt").write_text("a.jsonl\n")
    (scratch / "template.html").write_text("<p>a</p>\n")
    (scratch / "preview").mkdir()
    (scratch / "preview" / "convert.py").write_text(
        "import sys\ntext = open(sys.argv[2]).read()\nopen(sys.argv[3], 'w').write(text)\n")
    (scratch / "blog").mkdir()
    (scratch / "wt1").mkdir()
    project = tmp_path / "project"
    project.mkdir()
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(project))
    return tmp_path


def bash(command, cwd, name="PreToolUse", session="s1"):
    return {"hook_event_name": name, "tool_name": "Bash", "tool_input": {"command": command}, "session_id": session,
            "cwd": str(cwd)}


def decision(output):
    return output["hookSpecificOutput"]["permissionDecision"] if output else None


def grant_write(cwd, session="s1"):
    """Hold the session write approval, as the recorded sessions did before these calls."""
    command = "kubectl apply -f a.yaml"
    guard.handle(bash(command, cwd, "PreToolUse", session), "claude")
    guard.handle(bash(command, cwd, "PostToolUse", session), "claude")


def stash_repo(root):
    def git(*args):
        subprocess.run(["git", "-c", "user.name=demo", "-c", "user.email=demo@example.com", *args], cwd=root,
                       check=True, capture_output=True)
    root.mkdir()
    (root / "tests").mkdir()
    (root / "tests" / "a.py").write_text("x = 1\n")
    git("init", "-q")
    git("add", "-A")
    git("commit", "-q", "-m", "base")
    (root / "tests" / "a.py").write_text("x = 2\n")
    git("stash", "-q")
    git("stash", "apply", "-q")
    return root


def heredoc(path, body=READ_ONLY_BODY):
    return f"cat > {path} <<'EOF'\n{body}EOF\n"


def cases(base):
    s = base / "scratchpad"
    state = base / "xdg" / "hei5enbug-agent-setup"
    evals = state / "harness-eval"
    write_body = (f"S = '{s}/blog'\ntext = open(S + '/original.html', encoding='utf-8').read()\n"
                  "open(S + '/assembled.html', 'w', encoding='utf-8').write(text)\n")
    page_body = "text = open('template.html').read()\nopen('page_pre.html', 'w').write(text)\n"
    return [
        ("A1 heredoc script in the scratchpad", heredoc(f"{s}/linkcheck.py") + f"python3 {s}/linkcheck.py .", {}),
        ("A1 heredoc script in plugin state, piped", f"C={evals}/closure\nmkdir -p $C\n" + heredoc("$C/collect.py")
         + "python3 $C/collect.py final | python3 -c \"import sys\nfor l in sys.stdin: print(l)\"", {}),
        ("A1 while-read loop then heredoc script", f"S={s}; cd {base}/project; while read f; do du -k \"$f\"; done < "
         "$S/files.txt | sort -rn | head -5; " + heredoc("$S/survey.py") + "python3 $S/survey.py $S/files.txt", {}),
        ("A1 mkdir, heredoc, cd, run", f"mkdir -p {evals}/final/v12 && " + heredoc(f"{evals}/final/v12/measure.py")
         + f"cd {evals}/final/v12 && python3 measure.py 14", {}),
        ("A1 heredoc script that writes in the scratchpad", f"S={s}/blog; " + heredoc("$S/build.py", write_body)
         + f"python3 $S/build.py && python3 {s}/preview/convert.py dark $S/assembled.html $S/converted.html; "
         "echo exit $?", {}),
        ("A1 sed -i, two heredocs, run", f"S={s}; cd $S; sed -i 's/a/b/' template.html\n"
         + heredoc("fig.svg", "<svg></svg>\n") + heredoc("build_page.py", page_body) + "python3 build_page.py", {}),
        ("A1 heredoc script analysis run (this task)", f"S={s}; " + heredoc("$S/survey2.py")
         + "python3 $S/survey2.py $S/files.txt", {}),
        ("A2 find | xargs wc -c", f"B={s}/backup; find $B -type f | xargs wc -c; echo; ls -la {base}/project/; "
         f"wc -c {base}/project/*", {}),
        ("A2 xargs grep -l per pattern", f"cd {base}/project; find . -name '*.jsonl' -newer {s}/files.txt > "
         f"{s}/list.txt; for p in 'a b' 'c'; do printf '%s: ' \"$p\"; xargs -I{{}} grep -l -- \"$p\" {{}} < "
         f"{s}/list.txt | wc -l; done", {}),
        ("A3 env | grep -c and env | grep ^GIT", "env | grep -c '^GIT_CONFIG' ; env -u GIT_CONFIG_COUNT -u "
         "GIT_CONFIG_KEY_0 -u GIT_CONFIG_VALUE_0 python3 -m pytest -q tests/test_demo.py -k clean 2>&1 | grep -E "
         "'Error|assert' | head -15; env | grep '^GIT' | cut -c1-60", GIT_CONFIG),
        ("A3 env | grep -i GIT_CONFIG", "env | grep -i GIT_CONFIG; GIT_CONFIG_COUNT=2 "
         "GIT_CONFIG_KEY_0=credential.interactive GIT_CONFIG_VALUE_0=false GIT_CONFIG_KEY_1=credential.guiPrompt "
         "GIT_CONFIG_VALUE_1=false python3 -m pytest tests/test_demo.py -q -x 2>&1 | tail -30", GIT_CONFIG),
        ("A4 local docker labels and system df", "docker system df -v 2>/dev/null | sed -n '/Local Volumes/,/Build "
         "cache/p' | awk 'NR<=3 || $2==0' | head -45; echo; for v in $(docker volume ls -f dangling=true -q); do "
         "echo \"$v $(docker volume inspect -f '{{json .Labels}}' $v | cut -c1-120)\"; done", {}),
        ("A5 bash -c with $1", f"S={s}; bash -c 'shopt -s dotglob nullglob; rm -rf \"$1\"/*' _ \"$S\"; "
         "ls -A \"$S\" | wc -l; du -sh \"$S\"", {}),
        ("A5 ${W:?} over a static list", f"W={s}/wt1; G1=\"api/cmd/x docs/a.md\"; for p in $G1; do "
         "rm -rf \"${W:?}\"/\"${p:?}\"; if [ -e \"$p\" ]; then mkdir -p \"$(dirname \"$W/$p\")\"; "
         "cp -R \"$p\" \"$W/$p\"; fi; done", {}),
        ("A5 bash -c script with a literal loop", f"bash -c '\nW={s}/wt1\nfor p in api/cmd/x docs/a.md; do\n"
         "  rm -rf \"${W:?}/${p:?}\"; mkdir -p \"$(dirname \"$W/$p\")\"; cp -R \"$p\" \"$W/$p\"\ndone\n"
         "git -C \"$W\" status --short | wc -l'", {}),
        ("A5 second bash -c loop", f"bash -c '\nW={s}/wt1\nfor p in AGENTS.md api/internal web/src; do\n"
         "  rm -rf \"${W:?}/${p:?}\"; mkdir -p \"$(dirname \"$W/$p\")\"; cp -R \"$p\" \"$W/$p\"\ndone'", {}),
        ("A5 unquoted $W/$p", f"W={s}/wt1 && G1=\"api/cmd/x docs/a.md\" && for p in $G1; do rm -rf $W/$p; "
         "[ -e $p ] && mkdir -p $(dirname $W/$p) && cp -R $p $W/$p; done", {}),
        ("A6 empty the scratchpad with docker cleanup", f"S={s}; chmod -R u+w \"$S\" 2>/dev/null; rm -rf \"$S\"/* "
         "\"$S\"/.[!.]* 2>/dev/null; ls -A \"$S\" | wc -l; docker rmi python:3.12-slim 2>&1 | tail -2; "
         "docker system df | sed -n '1,2p'; docker run --rm alpine:latest df -h / | tail -1", {"write": True}),
        ("A7 eval work copy after a run", f"C7={evals}/deterministic/c7; mkdir -p $C7/cwd/after $C7/after; "
         "rm -rf \"$C7/cwd/after\"; cd $C7 && python3 -c \"print(1)\"", {"outside_temp": True}),
        ("A7 recreate final copy", f"D={evals}/deterministic/c6; rm -rf \"$D/final\"; mkdir -p \"$D/final\" && "
         "echo copied", {"outside_temp": True}),
        ("A7 recreate final copy again", f"D={evals}/deterministic/c6; ls $D/final.json 2>/dev/null; "
         "rm -rf \"$D/final\" && mkdir -p \"$D/final\"", {"outside_temp": True}),
        ("A8 stash drop after stash and apply", "git stash drop -q; git status --short; ls tests/a.py",
         {"write": True, "cwd": "repo"}),
        ("A9 unset keeps mktemp tracking", "T=$(mktemp -d); unset DEMO_STORE; python3 -c \"print(1)\"; cd /; "
         "rm -rf \"$T\"", {}),
    ]


def run_case(home, command, options, monkeypatch):
    for name, value in options.items():
        if name.startswith("GIT_CONFIG"):
            monkeypatch.setenv(name, value)
    cwd = home / "project"
    if options.get("outside_temp"):
        monkeypatch.setattr(guard, "TEMPORARY_ROOTS", ("/nonexistent-temp-root",))
        monkeypatch.setenv("TMPDIR", "/nonexistent-tmpdir")
        monkeypatch.setenv("HOME", "/nonexistent-home")
    if options.get("cwd") == "repo":
        cwd = stash_repo(home / "repo")
    if options.get("write"):
        grant_write(cwd)
    return guard.handle(bash(command, cwd), "claude")


@pytest.mark.parametrize("index", range(23))
def test_기록된_실수_없는_호출은_다시_실행해도_묻지_않는다(home, monkeypatch, index):
    # given
    title, command, options = cases(home)[index]
    # when
    output = run_case(home, command, options, monkeypatch)
    # then
    assert decision(output) not in ("ask", "deny"), (title, output)


def test_코디네이터가_남긴_PWD_삭제_사례는_계속_매번_묻는다(home, monkeypatch):
    # given
    command = ("cd /home/test/repo/api/internal/x && cp a.go /tmp/sig.bak 2>/dev/null; B=$PWD/../../../scratch_bak; "
               "mkdir -p $B; cp a.go $B/; rm -rf $B /tmp/sig.bak")
    # when
    output = guard.handle(bash(command, home / "project"), "claude")
    # then
    assert decision(output) == "ask"


# --- J1. heredoc analysis scripts whose bodies use str.replace, os.environ reads, token-named JSON keys, and writes to
# a temp path passed as an argument ------------------------------------------------------------------------------------

LINKCHECK_BODY = r'''import re, sys, os, unicodedata
from pathlib import Path
root = Path(sys.argv[1])
files = [root/'README.md', root/'AGENTS.md'] + sorted((root/'docs').rglob('*.md'))
def slug(h):
    h = re.sub(r'`([^`]*)`', r'\1', h)
    h = h.strip().lower()
    h = ''.join(c for c in h if c.isalnum() or c in ' -_' or unicodedata.category(c).startswith('L'))
    return h.replace(' ', '-')
def anchors(p):
    out, seen, fence = set(), {}, False
    for line in p.read_text().splitlines():
        if line.lstrip().startswith('```'): fence = not fence; continue
        if fence: continue
        m = re.match(r'^(#{1,6})\s+(.*?)\s*#*\s*$', line)
        if m:
            s = slug(m.group(2)); n = seen.get(s, 0); seen[s] = n+1
            out.add(s if n == 0 else f'{s}-{n}')
    return out
bad = 0
for f in files:
    text = f.read_text(); fence = False
    refs = dict(re.findall(r'^\[([^\]]+)\]:\s*(\S+)', text, re.M))
    for i, line in enumerate(text.splitlines(), 1):
        for m in re.finditer(r'\[[^\]]+\]\[([^\]]+)\]', line):
            if m.group(1) not in refs: print(f'{f}:{i}: undefined ref [{m.group(1)}]'); bad += 1
print('problems:', bad)
'''

BUILD_BLOG_BODY = r'''import re
S="{S}"
R="/home/test/repo/docs/blog/page.html"
old=open(f"{S}/backup/docs/blog/new/page.html").read()
svgs=re.findall(r"<svg.*?</svg>",old,flags=re.S)
assert len(svgs)==5
def rep(s,pairs):
    for a,b in pairs:
        assert a in s,a
        s=s.replace(a,b)
    return s
f1=rep(svgs[0],[("first wording","second wording")])
f3=open(f"{S}/fig3_stage1.svg").read().rstrip()
t=open(f"{S}/map_blog_template.html").read()
for i,f in enumerate([f1,f3],1):
    t=t.replace("{{FIG%d}}"%i,f)
open(f"{S}/map_blog_pre.html","w").write(t)
'''

BUILD_STAGES_BODY = r'''import re,sys
S='{S}/ais-blog'
orig=open(S+'/original.html',encoding='utf-8').read()
svgs=re.findall(r'<svg .*?</svg>',orig,flags=re.S)
assert len(svgs)==6,len(svgs)
chain,struct=svgs[2],svgs[3]

def rep(text,pairs):
    for a,b in pairs:
        assert a in text,a
        text=text.replace(a,b)
    return text

chain=rep(chain,[('aria-label="before"','aria-label="after"')])
struct=rep(struct,[('<rect x="556" y="8" width="16" height="12" rx="3" fill="#161616" stroke="#52a9ff"/>','<rect x="496"/>')])
t=open(S+'/template.html',encoding='utf-8').read()
for k,v in {'SVG_CHAIN':chain,'SVG_STRUCT':struct}.items():
    assert '{{%s}}'%k in t
    t=t.replace('{{%s}}'%k,v)
open(S+'/assembled.html','w',encoding='utf-8').write(t)
'''

MEASURE_BODY = r'''"""Count rewrites in the last 14 days of transcripts.

usage: python3 measure_language_guard.py [days]
"""
import collections
import glob
import json
import os
import re
import sys
import time

DAYS = int(sys.argv[1]) if len(sys.argv) > 1 else 14
NOW = time.time()
ROOTS = sorted({
    os.path.realpath(os.path.join(os.environ.get("CLAUDE_CONFIG_DIR", os.path.expanduser("~/.claude")), "projects")),
    os.path.realpath(os.path.expanduser("~/.claude/projects")),
})
SCRIPT = re.compile(r"hook_python\.sh\"?\s+language_guard\.py")


def entries(path):
    with open(path, errors="replace") as stream:
        for line in stream:
            try:
                yield json.loads(line)
            except ValueError:
                continue


def main():
    stats = collections.Counter()
    extra_tokens = []
    for root in ROOTS:
        for path in glob.glob(os.path.join(root, "**", "*.jsonl"), recursive=True):
            pending = 0
            for d in entries(path):
                msg = d.get("message") or {}
                if d.get("type") == "assistant":
                    pending += int((msg.get("usage") or {}).get("output_tokens") or 0)
            extra_tokens.append(pending)
    print(json.dumps({
        "window_days": DAYS,
        "counts": dict(stats),
        "rewrite_output_tokens_real": {"n": len(extra_tokens), "sum": sum(extra_tokens), "p50": 0},
    }, indent=1))


if __name__ == "__main__":
    main()
'''

ASKS_BODY = r'''import json, sys, collections, re
out = []
for line in open(sys.argv[1]):
    f = line.strip()
    uses, hooks, results = {}, {}, []
    entry = None
    for raw in open(f, errors="replace"):
        try: r = json.loads(raw)
        except ValueError: continue
        entry = entry or r.get("entrypoint")
        a = r.get("attachment")
        if isinstance(a, dict) and a.get("type") == "hook_success" and a.get("hookEvent") == "PreToolUse":
            hooks[a.get("toolUseID")] = (a.get("stdout"), a.get("command"))
    out.append({"file": f, "entry": entry, "hook": hooks})
json.dump(out, open(sys.argv[2], "w"), ensure_ascii=False, indent=1, default=str)
c = collections.Counter((o["entry"], len(o["hook"])) for o in out)
for k, n in c.most_common(): print(n, k)
'''

SOURCES_BODY = r'''"""Attribute every eval permission prompt to a decision.

Usage: python3 approval_sources.py <results-dir> <arm> [<arm> ...]
"""
import collections
import json
import sys
from pathlib import Path


def decisions(stream):
    open_calls, found = [], collections.defaultdict(list)
    for line in stream.read_text(encoding="utf-8").splitlines():
        entry = json.loads(line)
        if entry.get("type") == "assistant":
            for block in entry["message"].get("content", []):
                if block.get("type") == "tool_use":
                    open_calls.append((block["id"], json.dumps(block.get("input"), ensure_ascii=False)))
        elif entry.get("subtype") == "hook_response":
            reason = entry.get("stdout") or ""
            found[open_calls[-1][0]].append(reason.split(": ", 1)[-1])
    return found


def main():
    root, arms = Path(sys.argv[1]), sys.argv[2:]
    for arm in arms:
        runs = sorted(path for path in root.glob(f"*/{arm}/rep*") if (path / "stream.jsonl").is_file())
        for run in runs:
            found = decisions(run / "stream.jsonl")
            print(" | ".join((run.relative_to(root).as_posix(), str(len(found)), "x".replace("x", "\n"))))


if __name__ == "__main__":
    main()
'''

CONVERT_BODY = ('"""Convert."""\nimport re\nimport sys\n\ntext = open(sys.argv[2], encoding="utf-8").read()\n'
                'converted = re.sub("a", "b", text).replace("c", "d")\n'
                'with open(sys.argv[3], "w", encoding="utf-8") as target:\n    target.write(converted)\n')


def j1_cases(base):
    s = base / "scratchpad"
    home = base / "home"
    state = home / ".local" / "state" / "hei5enbug-agent-setup"
    return [
        ("J1 linkcheck with str.replace", f"cd {base}/project && " + heredoc(f"{s}/linkcheck.py", LINKCHECK_BODY)
         + f"python3 {s}/linkcheck.py .", {}),
        ("J1 blog builder with str.replace and a template", f"S={s}; cd $S; sed -i 's/a/b/' map_blog_template.html\n"
         + heredoc("fig3_stage1.svg", "<svg viewBox=\"0 0 880 380\">\n  <g></g>\n</svg>\n")
         + heredoc("build_map_blog.py", BUILD_BLOG_BODY.replace("{S}", str(s)))
         + "python3 build_map_blog.py && python3 blog-preview/svg_to_dg.py light map_blog_pre.html \"$R\" 2>&1 | "
         "tail -5; R=\"/home/test/repo/docs/blog/page.html\"; ls -la \"$R\"", {"convert": "blog-preview"}),
        ("J1 stage builder then converter in the scratchpad", f"S={s}/ais-blog; cat > $S/build.py <<'EOF'\n"
         + BUILD_STAGES_BODY.replace("{S}", str(s)) + f"EOF\npython3 $S/build.py && python3 {s}/blog-preview/"
         f"svg_to_dg.py dark $S/assembled.html $S/converted.html; echo exit $?; grep -c 'dg-' $S/converted.html",
         {"convert": "blog-preview"}),
        ("J1 token-counting script in plugin state", "mkdir -p ~/.local/state/hei5enbug-agent-setup/harness-eval/final/v12"
         " && " + heredoc("~/.local/state/hei5enbug-agent-setup/harness-eval/final/v12/measure_language_guard.py",
                          MEASURE_BODY) + "cd ~/.local/state/hei5enbug-agent-setup/harness-eval/final/v12 && "
         "python3 measure_language_guard.py 14", {}),
        ("J1 script that writes its result to a scratchpad argument", f"S={s}; cd {home}/.claude/projects; "
         + heredoc("$S/asks.py", ASKS_BODY) + "python3 $S/asks.py $S/files.txt $S/asks.json", {}),
        ("J1 attribution script in plugin state", "D=~/.local/state/hei5enbug-agent-setup/harness-eval/followups; "
         + heredoc("$D/approval_sources.py", SOURCES_BODY) + "python3 $D/approval_sources.py ~/.local/state/"
         "hei5enbug-agent-setup/harness-eval/runs/final-regression/results control-0abc123 main-0def456", {}),
    ]


def run_j_case(base, command, options, monkeypatch):
    home = base / "home"
    (home / ".claude" / "projects").mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("XDG_STATE_HOME", str(home / ".local" / "state"))
    scratch = base / "scratchpad"
    if options.get("convert"):
        (scratch / options["convert"]).mkdir(exist_ok=True)
        (scratch / options["convert"] / "svg_to_dg.py").write_text(CONVERT_BODY)
    return guard.handle(bash(command, base / "project"), "claude")


@pytest.mark.parametrize("index", range(6))
def test_기록된_heredoc_분석_스크립트는_str_replace_환경변수_토큰_키_인자_쓰기가_있어도_묻지_않는다(home, monkeypatch, index):
    # given
    title, command, options = j1_cases(home)[index]
    # when
    output = run_j_case(home, command, options, monkeypatch)
    # then
    assert decision(output) not in ("ask", "deny"), (title, output)


J1_MUST_ASK = [
    ("os.replace", "import os, sys\nos.replace(sys.argv[1], sys.argv[1] + '.bak')\n", ""),
    ("aliased os.replace", "import os as o\no.replace('a.txt', 'b.txt')\n", ""),
    ("os module in a variable", "import os\nm = os\nm.replace('a.txt', 'b.txt')\n", ""),
    ("Path.replace", "import sys\nfrom pathlib import Path\nPath(sys.argv[1]).replace(sys.argv[2])\n", ""),
    ("unbound Path.replace", "from pathlib import Path\nPath.replace(Path('a.txt'), 'b.txt')\n", ""),
    ("type(path).replace", "from pathlib import Path\np = Path('a.txt')\ntype(p).replace(p, 'b.txt')\n", ""),
    ("replace with a keyword", "import re\nprint('abc'.replace('a', 'b', count=1), re)\n\nfrom pathlib import Path\n"
     "Path('a.txt').replace(target='b.txt')\n", ""),
    ("shutil.rmtree", "import shutil, sys\nshutil.rmtree(sys.argv[1])\n", ""),
    ("secret-named environment variable", "import os\nprint(os.environ.get('DEMO_API_TOKEN'))\n", ""),
    ("secret-named environment subscript", "import os\nprint(os.environ['DEMO_PASSWORD'])\n", ""),
    ("non-literal environment name", "import os, sys\nprint(os.environ.get(sys.argv[1]))\n", "HOME"),
    ("whole environment", "import os\nprint(dict(os.environ))\n", ""),
    ("environment write", "import os\nos.environ['DEMO_MODE'] = 'x'\n", ""),
    ("token as a singular word", "print('access_token')\n", ""),
    ("token key as a variable name", "print('API_TOKEN')\n", ""),
    ("tokens file", "print('~/.config/demo/tokens.json')\n", ""),
    ("env file", "print('.env')\n", ""),
    ("credential path", "print('.aws/credentials')\n", ""),
    ("argument write outside temp", "import sys\nopen(sys.argv[1], 'w').write('x')\n", "/home/test/out.txt"),
    ("argument write beyond the arguments", "import sys\nopen(sys.argv[3], 'w').write('x')\n", "{S}/a.txt {S}/b.txt"),
    ("argument write to the script itself", "import sys\nopen(sys.argv[1], 'w').write('x')\n", "{S}/t.py"),
    ("argument write to the script name", "import sys\nopen(sys.argv[0], 'w').write('x')\n", "{S}/a.txt"),
    ("argument write after changing argv", "import sys\nsys.argv[1] = '/home/test/out.txt'\nopen(sys.argv[1], 'w')."
     "write('x')\n", "{S}/a.txt"),
    ("argument write with an unresolved argument", "import sys\nopen(sys.argv[1], 'w').write('x')\n", "$UNSET/a.txt"),
]


@pytest.mark.parametrize("index", range(len(J1_MUST_ASK)))
def test_heredoc_스크립트가_경로_이동_비밀_이름_임시_폴더_밖_쓰기를_하면_계속_묻는다(home, monkeypatch, index):
    # given
    title, body, args = J1_MUST_ASK[index]
    s = home / "scratchpad"
    command = f"cat > {s}/t.py <<'EOF'\n{body}EOF\npython3 {s}/t.py {args.replace('{S}', str(s))}"
    # when
    output = run_j_case(home, command, {}, monkeypatch)
    # then
    assert decision(output) == "ask", (title, output)


def test_인자로_받은_임시_폴더_안_경로에_쓰는_heredoc_스크립트는_묻지_않는다(home, monkeypatch):
    # given
    s = home / "scratchpad"
    body = "import sys\nopen(sys.argv[2], 'a').write(open(sys.argv[1]).read())\n"
    command = f"cat > {s}/t.py <<'EOF'\n{body}EOF\npython3 {s}/t.py {s}/in.txt {s}/out.txt"
    # when
    output = run_j_case(home, command, {}, monkeypatch)
    # then
    assert decision(output) not in ("ask", "deny")


# --- J2. the plugin's own evaluation harness exports a commit under the plugin state folder -----------------------------

PLUGIN_NAME = "hei5enbug-agent-setup"
EXPORT = "python3 evals/e2e/harness/cli.py export-plugin"


def plugin_repo(root, name=PLUGIN_NAME, tracked=True):
    def git(*args):
        subprocess.run(["git", "-c", "user.name=demo", "-c", "user.email=demo@example.com", *args], cwd=root,
                       check=True, capture_output=True)
    (root / ".claude-plugin").mkdir(parents=True)
    (root / ".claude-plugin" / "plugin.json").write_text(f'{{"name": "{name}"}}\n')
    (root / "evals" / "e2e" / "harness").mkdir(parents=True)
    (root / "evals" / "e2e" / "harness" / "cli.py").write_text("import subprocess, sys\nsubprocess.run(sys.argv[1:])\n")
    (root / "scripts").mkdir()
    (root / "scripts" / "x.py").write_text("x = 1\n")
    git("init", "-q")
    git("add", "-A")
    git("commit", "-q", "-m", "one")
    (root / "scripts" / "x.py").write_text("x = 2\n")
    git("commit", "-q", "-am", "two")
    if not tracked:
        git("rm", "-q", "--cached", "evals/e2e/harness/cli.py")
        git("commit", "-q", "-m", "untrack")
    return root


def export_command(base, repo, tail=f"{EXPORT} --ref a1b2c3d"):
    plugins = base / "xdg" / PLUGIN_NAME / "harness-eval" / "runs" / "plugins"
    return (f"cd {repo} && {tail} 2>&1 | tail -5; ls {plugins}/ | grep a1b2; "
            "diff <(git show HEAD~1:scripts/x.py) <(git show HEAD:scripts/x.py) && echo same")


def test_이_플러그인의_추적된_하네스_export_plugin_호출은_묻지_않는다(home):
    # given
    repo = plugin_repo(home / "repo")
    # when
    output = guard.handle(bash(export_command(home, repo), home / "project"), "claude")
    # then
    assert decision(output) not in ("ask", "deny")


@pytest.mark.parametrize("tail", [
    f"{EXPORT}",
    f"{EXPORT} --ref HEAD~1",
    "python3 ./evals/e2e/harness/cli.py export-plugin --ref a1b2c3d",
])
def test_export_plugin은_ref가_없거나_상대_경로여도_묻지_않는다(home, tail):
    # given
    repo = plugin_repo(home / "repo")
    # when
    output = guard.handle(bash(export_command(home, repo, tail), home / "project"), "claude")
    # then
    assert decision(output) not in ("ask", "deny")


def test_절대_경로로_부른_추적된_하네스의_export_plugin도_묻지_않는다(home):
    # given
    repo = plugin_repo(home / "repo")
    tail = f"python3 {repo}/evals/e2e/harness/cli.py export-plugin --ref a1b2c3d"
    # when
    output = guard.handle(bash(export_command(home, repo, tail), home / "project"), "claude")
    # then
    assert decision(output) not in ("ask", "deny")


@pytest.mark.parametrize("title", ["other subcommand", "unknown flag", "extra operand", "modified script",
                                   "untracked script", "another plugin", "no plugin manifest"])
def test_export_plugin이_아니거나_추적되지_않았거나_다른_저장소의_하네스는_계속_묻는다(home, title):
    # given
    tail = f"{EXPORT} --ref a1b2c3d"
    repo = plugin_repo(home / "repo", name="demo-plugin" if title == "another plugin" else PLUGIN_NAME,
                       tracked=title != "untracked script")
    if title == "other subcommand":
        tail = "python3 evals/e2e/harness/cli.py run --ref a1b2c3d"
    elif title == "unknown flag":
        tail = f"{EXPORT} --ref a1b2c3d --out /home/test/out"
    elif title == "extra operand":
        tail = f"{EXPORT} --ref a1b2c3d extra"
    elif title == "modified script":
        (repo / "evals" / "e2e" / "harness" / "cli.py").write_text("import os\nos.system('echo hi')\n")
    elif title == "no plugin manifest":
        (repo / ".claude-plugin" / "plugin.json").unlink()
        subprocess.run(["git", "-c", "user.name=d", "-c", "user.email=d@example.com", "commit", "-q", "-am", "x"],
                       cwd=repo, check=True, capture_output=True)
    # when
    output = guard.handle(bash(export_command(home, repo, tail), home / "project"), "claude")
    # then
    assert decision(output) == "ask", (title, output)


def test_프로세스_치환_안의_git_읽기는_읽기로_본다(home):
    # given
    repo = plugin_repo(home / "repo")
    command = f"cd {repo} && diff <(git show HEAD~1:scripts/x.py) <(git show HEAD:scripts/x.py) && echo same"
    # when
    output = guard.handle(bash(command, home / "project"), "claude")
    # then
    assert decision(output) not in ("ask", "deny")


@pytest.mark.parametrize("command", [
    "diff <(git show HEAD:scripts/x.py) <(git push origin main)",
    "diff <(git show HEAD:scripts/x.py) <(git reset --hard HEAD~1)",
    "cat <(rm -rf /home/test/work)",
    "bash <(git show HEAD:scripts/x.py)",
    "diff <(git show HEAD:scripts/x.py) <(git show HEAD:scripts/x.py",
])
def test_프로세스_치환_안의_쓰기나_실행은_계속_묻는다(home, command):
    # given
    repo = plugin_repo(home / "repo")
    # when
    output = guard.handle(bash(f"cd {repo} && {command}", home / "project"), "claude")
    # then
    assert decision(output) == "ask", output


# --- J3. `env | grep` stages that print only variable names ---------------------------------------------------------------

J3_RECORDED = ("cd {repo}; U=$(env | grep '^GIT_' | cut -d= -f1 | sed 's/^/-u /' | tr '\\n' ' '); env $U python3 -m pytest "
               "-q -p no:cacheprovider tests/test_demo.py 2>&1 | tail -1; env -u GIT_CONFIG_COUNT -u GIT_CONFIG_KEY_0 "
               "-u GIT_CONFIG_VALUE_0 -u GIT_CONFIG_KEY_1 -u GIT_CONFIG_VALUE_1 python3 -m pytest -q -p no:cacheprovider "
               "tests/test_demo.py 2>&1 | tail -1")


def secret_environment(monkeypatch):
    monkeypatch.setenv("DEMO_API_TOKEN", "abc123def456")
    monkeypatch.setenv("DEMO_PASSWORD", "hunter2hunter2")


def test_이름만_출력하는_env_grep_cut_파이프라인은_기록된_모양으로_묻지_않는다(home, monkeypatch):
    # given
    for name, value in GIT_CONFIG.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setenv("GIT_ASKPASS_TOKEN", "abc123def456")
    # when
    output = guard.handle(bash(J3_RECORDED.format(repo=home / "project"), home / "project"), "claude")
    # then
    assert decision(output) not in ("ask", "deny"), output


@pytest.mark.parametrize("cut", ["cut -d= -f1", "cut -d '=' -f1", "cut --delimiter== -f1", "cut -d= -f 1",
                                 "cut -d= --fields=1", "cut -f1 -d="])
@pytest.mark.parametrize("pattern", ["'^GIT_'", "token", "-i secret", "'.'"])
def test_cut으로_이름_열만_남기는_env_grep은_패턴과_상관없이_묻지_않는다(home, monkeypatch, cut, pattern):
    # given
    secret_environment(monkeypatch)
    # when
    output = guard.handle(bash(f"env | grep {pattern} | {cut}", home / "project"), "claude")
    # then
    assert decision(output) not in ("ask", "deny"), output


@pytest.mark.parametrize("stage", ["cut -d= -f2", "cut -f1", "cut -d= -f1-", "cut -d= -f1,2", "cut -c1-60",
                                   "cut -d= -f2-", "cut -d: -f1", "cut -d= -f1 -s -z"])
def test_값이_나올_수_있는_cut_단계는_비밀_이름과_맞으면_계속_민감_조회다(home, monkeypatch, stage):
    # given
    secret_environment(monkeypatch)
    # when
    output = guard.handle(bash(f"env | grep -i token | {stage}", home / "project"), "claude")
    # then
    assert decision(output) == "ask", (stage, output)


@pytest.mark.parametrize("pipeline", [
    "env | grep -i token | sed 's/^/-u /' | cut -d= -f1",
    "env | grep -i token | tr 'a-z' 'A-Z' | cut -d= -f1",
    "env | grep -i token | tr '\\n' ' '",
    "env | grep -i token | sed 's/^/-u /'",
    "env | grep -i token | cut -d= -f2 | sed 's/^/-u /'",
    "env | grep -i token | cut -d= -f1 | sed -n 'w /home/test/names.txt'",
    "env | grep -i token | cut -d= -f1 | sed 's/a/b/e'",
    "env | grep -i token | cut -d= -f1 | tr a b /home/test/names.txt",
])
def test_이름_열을_남기기_전의_변환이나_값을_남기는_변환은_계속_민감_조회다(home, monkeypatch, pipeline):
    # given
    secret_environment(monkeypatch)
    # when
    output = guard.handle(bash(pipeline, home / "project"), "claude")
    # then
    assert decision(output) == "ask", (pipeline, output)


def test_이름_열_뒤의_sed_tr_단계는_묻지_않는다(home, monkeypatch):
    # given
    secret_environment(monkeypatch)
    # when
    output = guard.handle(bash("env | grep -i token | cut -d= -f1 | sed 's/^/-u /' | tr '\\n' ' '",
                               home / "project"), "claude")
    # then
    assert decision(output) not in ("ask", "deny")
