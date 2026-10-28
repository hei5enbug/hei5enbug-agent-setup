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
            print(" | ".join((run.relative_to(root).as_posix(), str(len(found)), reason.replace("x", "\n"))))


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


# --- J4. text that mentions a guard state folder without touching it ---------------------------------------------------------

PYCACHE = "$XDG_STATE_HOME/hei5enbug-agent-setup/pycache"
TEST_BODY = '''

def arguments_interpreter(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('#!/bin/sh\\nfor argument in "$@"; do echo "$argument"; done\\necho END\\ncat\\nexit 3\\n')
    return path


def test_pycache_prefix(plugin, tmp_path):
    # given
    state = tmp_path / "state"
    # then
    assert arguments[:3] == ["-X", f"pycache_prefix={state}/hei5enbug-agent-setup/pycache", "-c"]
    assert `echo` in "$XDG_STATE_HOME/hei5enbug-agent-setup/pycache"
'''
README_EDIT = f'''p='README.md'
s=open(p).read()
a="Python per project.\\n"
assert s.count(a)==1
s=s.replace(a,a+"""The launcher caches compiled bytecode under `{PYCACHE}/` (default
`~/.local/state`). This is a guard state folder, so the approval guard denies agent writes there like those to
`approvals/` and `heartbeats/`.
""")
open(p,'w').write(s)
'''
REVIEW_TEXT = f'''Review the uncommitted change (`git diff HEAD`). Do not edit files.
- This change moves the cache to {PYCACHE} and protects that folder exactly like approvals/ and heartbeats/.
- The guard adds `_guard_state_dirs()` to `_state_path`; checks already run: full pytest passed.
'''


def j4_allowed(base):
    repo = base / "project"
    s = base / "scratchpad"
    return [
        ("cat >> a test file, body names the cache", f"cd {repo} && cat >> tests/test_x.py <<'PYEOF'\n{TEST_BODY}PYEOF\n"
         "env -u GIT_CONFIG_COUNT python3 -m pytest -p no:cacheprovider -q tests/test_x.py 2>&1 | tail -30"),
        ("python heredoc edits README with the cache path", f"cd {repo} && python3 - <<'PYEOF'\n{README_EDIT}PYEOF\n"
         "git diff README.md docs | grep '^[+-]'\nE=\"env -u GIT_CONFIG_COUNT\"\n"
         "$E python3 -m pytest -p no:cacheprovider -q tests/ -k approval 2>&1 | tail -8\ngit status --short"),
        ("review assignment written beside a diff", f"S={s}; git diff > $S/c6.diff; wc -l $S/c6.diff; cat > "
         f"$S/review-c6.md <<'EOF'\n{REVIEW_TEXT}EOF\ngrep -c pycache $S/review-c6.md"),
        ("git commit message with the cache path", f"cd {repo} && git commit -q -m \"fix: cache bytecode under {PYCACHE}\""),
        ("git commit single-quoted message", f"cd {repo} && git commit -q -m 'docs: the guard protects {PYCACHE}'"),
        ("git commit heredoc message", f"cd {repo} && git commit -q -m \"$(cat <<'EOF'\nfix: keep {PYCACHE} guarded\n\n"
         "The `approvals/` folder stays protected.\nEOF\n)\""),
        ("echo the cache path into a note", f"echo \"bytecode goes to {PYCACHE}\" > {s}/notes.md"),
        ("printf the cache path into a note", f"printf '%s\\n' \"see {PYCACHE}\" >> {s}/notes.md"),
    ]


def j4_denied(base):
    state = base / "xdg" / "hei5enbug-agent-setup"
    s = base / "scratchpad"
    return [
        ("ls the cache folder then touch a file", f"ls {state}/pycache; touch {state}/pycache/f"),
        ("rm the approvals", f"rm -rf {state}/approvals"),
        ("cat into an approval file", f"cat > {state}/approvals/x <<'EOF'\nx\nEOF"),
        ("python opens a state path for writing", f"python3 - <<'EOF'\nopen('{state}/approvals/x', 'w').write('1')\nEOF"),
        ("python writes a state path held in a name", f"python3 - <<'EOF'\np = '{state}/pycache/x.py'\n"
         "open(p, 'w').write('1')\nEOF"),
        ("python spawns a command that names a state path", f"python3 - <<'EOF'\nimport os\n"
         f"os.system('rm -rf {state}/approvals')\nEOF"),
        ("python opens a path it builds from the state text", f"python3 - <<'EOF'\nimport sys\n"
         f"name = '{state}/approvals/'\nopen(name + sys.argv[1], 'w').write('1')\nEOF"),
        ("cd into heartbeats", f"cd {state}/heartbeats"),
        ("echo into an approval file", f"echo 1 > {state}/approvals/y"),
        ("echo that runs a substitution", f"echo \"$(rm -rf {state}/approvals)\" > {s}/n.md"),
        ("git commit message that runs a substitution", f"git commit -q -m \"see `ls {state}/approvals`\""),
        ("heredoc piped to bash", f"cat <<'EOF' | bash\nrm -rf {state}/approvals\nEOF"),
        ("heredoc written to a script that runs", f"cat > {s}/x.sh <<'EOF'\nrm -rf {state}/approvals\nEOF\nbash {s}/x.sh"),
        ("cat of a state file into a note", f"cat {state}/approvals/s.json > {s}/copy.json"),
        ("heredoc script that python runs", f"cat > {s}/x.py <<'EOF'\nprint('{state}/approvals')\nEOF\npython3 {s}/x.py"),
        ("heredoc script run from another folder", f"cd {s} && cat > x.py <<'EOF'\nprint('{state}/approvals')\nEOF\n"
         "python3 -u x.py"),
        ("unquoted python heredoc", f"python3 - <<EOF\nopen('{state}/approvals/x', 'w')\nEOF"),
        ("python heredoc with an extra import", f"python3 - <<'EOF'\nimport subprocess\n"
         f"print('{state}/pycache')\nsubprocess.run(['ls'])\nEOF"),
    ]


@pytest.mark.parametrize("index", range(8))
def test_가드_상태_폴더_경로가_글자로만_나오는_명령은_거부하지_않는다(home, index):
    # given
    title, command = j4_allowed(home)[index]
    # when
    output = guard.handle(bash(command, home / "project"), "claude")
    # then
    assert decision(output) != "deny", (title, output)


@pytest.mark.parametrize("index", range(18))
def test_가드_상태_폴더를_실제로_다루는_명령은_계속_거부한다(home, index):
    # given
    title, command = j4_denied(home)[index]
    # when
    output = guard.handle(bash(command, home / "project"), "claude")
    # then
    assert decision(output) == "deny", (title, output)


# --- J6. anchored grep -o and list-file xargs greps over transcripts ---------------------------------------------------------

J6_LOOP = ("while read f; do head -c 200000 \"$f\" | grep -o '\"entrypoint\":\"[^\"]*\"' | head -1 | tr '\\n' ' '; "
           "echo \"$f\" | grep -c subagents; done < $S/files.txt | sort | uniq -c")
J6_CONTENT = "xargs grep -h -o '\"content\":\"[^\"]\\{0,40\\}doesn.t want to proceed[^\"]\\{0,200\\}' < $S/files.txt | head -3"
J6_EVENT = "xargs grep -h -o '\"hookEvent\":\"PermissionRequest\"' < $S/files.txt | wc -l"
J6_TYPES = "xargs grep -h -o '\"type\":\"[a-z_]*\"' < $S/files.txt | sort | uniq -c | sort -rn | head -40"
J6_NAME = ("f=$(xargs grep -l '쓰기 승인:' < $S/files.txt | head -1); echo $f; grep -n '쓰기 승인:' \"$f\" | head -2 | "
           "cut -c1-1500")


def j6(base, body):
    return f"cd {base}/project; S={base}/scratchpad; {body}"


@pytest.mark.parametrize("body", [
    J6_LOOP + "; " + J6_CONTENT + "; " + J6_EVENT,
    J6_TYPES,
    J6_NAME,
    "xargs grep -c 'anything at all' < $S/files.txt | sort | uniq -c",
    "xargs grep -l -i 'x' < $S/files.txt | wc -l",
    "xargs grep -h -o '\"entrypoint\":\"[^\"]*\"' < $S/files.txt | sort | uniq -c",
    "xargs grep -h -oE '\"entrypoint\":\"[^\"]{0,40}\"' < $S/files.txt | head -3",
    "while read f; do head -c 100 \"$f\" | grep -o '\"entrypoint\":\"[^\"]*\"' | head -1; done < $S/files.txt",
])
def test_목록_파일의_xargs_grep과_고정_앵커_grep_o는_기록된_모양으로_묻지_않는다(home, body):
    # given
    command = j6(home, body)
    # when
    output = guard.handle(bash(command, home / "project"), "claude")
    # then
    assert decision(output) not in ("ask", "deny"), (body, output)


@pytest.mark.parametrize("body", [
    "xargs grep -h -o 'ab[^\"]*' < $S/files.txt",
    "xargs grep -h -o '\"api_token\":\"[^\"]*\"' < $S/files.txt",
    "xargs grep -h -o '\"entrypoint\":\"[^\"]*\"' < /home/test/list.txt",
    "xargs grep -h -o 'entrypoint.*' < $S/files.txt",
    "xargs grep -h -o '\"entrypoint\"[\\s\\S]*' < $S/files.txt",
    "xargs grep -h -o '\"entrypoint\":\"[^\"]\\{0,\\}\"' < $S/files.txt",
    "xargs grep -h '\"entrypoint\":\"' < $S/files.txt",
    "xargs grep -h -o -A3 '\"entrypoint\":\"[^\"]*\"' < $S/files.txt",
    "xargs grep -h -o -f /home/test/patterns '\"entrypoint\":\"' < $S/files.txt",
    "xargs rg -o '\"entrypoint\":\"[^\"]*\"' < $S/files.txt",
    "xargs rg -l 'x' < $S/files.txt",
    "xargs grep -l 'x' < /home/test/list.txt",
    "xargs grep -c 'x' < /home/test/list.txt",
    "xargs grep -h -o '\"entrypoint\":\"[^\"]*\"' -- < $S/files.txt",
    "xargs grep -h -o '\"entrypoint\":\"[^\"]*\"' < $S/files.txt > /home/test/out.txt",
])
def test_짧은_앵커나_비밀_이름이나_범위_없는_패턴이나_목록_밖_파일이면_계속_묻는다(home, body):
    # given
    command = j6(home, body)
    # when
    output = guard.handle(bash(command, home / "project"), "claude")
    # then
    assert decision(output) == "ask", (body, output)


@pytest.mark.parametrize("body", [
    "read S < /home/test/where.txt; xargs grep -l x < $S/files.txt",
    "for S in /home/test; do xargs grep -l x < $S/files.txt; done",
    "xargs grep -l x < $UNSET/files.txt",
    "xargs -a /home/test/list.txt grep -l x < $S/files.txt",
])
def test_목록_경로가_바뀌었거나_앵커가_앞에_없으면_xargs_grep은_계속_묻는다(home, body):
    # given
    command = j6(home, body)
    # when
    output = guard.handle(bash(command, home / "project"), "claude")
    # then
    assert decision(output) == "ask", (body, output)


# --- J7. a git read script in the scratchpad, and the work tree's own code run from an archive copy -------------------------

SAME_DEFS_BODY = '''import ast, subprocess, sys
from pathlib import Path
root, orig_rel, new_glob = Path(sys.argv[1]), sys.argv[2], sys.argv[3]
def defs(src):
    out = {}
    for node in ast.parse(src).body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            out[node.name] = ast.dump(node)
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for t in targets:
                if isinstance(t, ast.Name): out[t.id] = ast.dump(node.value) if node.value else ""
    return out
old = defs(subprocess.run(["git", "-C", str(root), "show", f"HEAD:{orig_rel}"], capture_output=True, text=True, check=True).stdout)
new = {}
for p in sorted(root.glob(new_glob)):
    for k, v in defs(p.read_text()).items():
        new.setdefault(k, []).append((p.name, v))
missing = [k for k in old if k not in new]
changed = [k for k in old if k in new and all(v != old[k] for _, v in new[k])]
dup = {k: [n for n, _ in v] for k, v in new.items() if len(v) > 1}
print("old defs", len(old), "missing", missing, "changed", changed)
print("defined in several files", dup)
'''

J7_COMMAND = ("S={s}; cd $S/wt-split && python3 $S/same_defs.py . skills/demo/scripts/demo_tool.py "
              "'skills/demo/scripts/*.py'; wc -l skills/demo/scripts/*.py | tail -9; "
              "rm -rf skills/demo/scripts/__pycache__; d=$(mktemp -d $S/pyc.XXXX); git archive HEAD | tar -x -C $d; "
              "cp skills/demo/scripts/*.py $d/skills/demo/scripts/; "
              "python3 $d/skills/demo/scripts/demo_tool.py --help >/dev/null; "
              "ls $d/skills/demo/scripts/ $d/scripts | grep -c pycache; rm -rf $d")


def j7_tree(base, name=PLUGIN_NAME, defs_body=SAME_DEFS_BODY):
    scratch = base / "scratchpad"
    tree = scratch / "wt-split"
    (tree / ".claude-plugin").mkdir(parents=True)
    (tree / ".claude-plugin" / "plugin.json").write_text(f'{{"name": "{name}"}}\n')
    (tree / "skills" / "demo" / "scripts").mkdir(parents=True)
    (tree / "skills" / "demo" / "scripts" / "demo_tool.py").write_text(
        "import argparse\nparser = argparse.ArgumentParser()\nparser.parse_args()\n")
    (tree / "skills" / "demo" / "scripts" / "helper.py").write_text("VALUE = 1\n")
    (tree / "scripts").mkdir()
    (tree / "scripts" / "x.py").write_text("x = 1\n")
    for args in (("init", "-q"), ("add", "-A"), ("commit", "-q", "-m", "base")):
        subprocess.run(["git", "-c", "user.name=demo", "-c", "user.email=demo@example.com", *args], cwd=tree,
                       check=True, capture_output=True)
    (scratch / "same_defs.py").write_text(defs_body)
    return scratch


def j7_command(scratch, command=J7_COMMAND):
    return command.replace("{s}", str(scratch))


def test_기록된_git_읽기_스크립트와_작업_트리_아카이브_복사본_실행은_묻지_않는다(home):
    # given
    command = j7_command(j7_tree(home))
    # when
    output = guard.handle(bash(command, home / "project"), "claude")
    # then
    assert decision(output) not in ("ask", "deny"), output


J7_MUST_ASK = [
    ("mktemp template outside temp", J7_COMMAND.replace("mktemp -d $S/pyc.XXXX", "mktemp -d ~/x.XXXX")),
    ("download into the archive copy", J7_COMMAND.replace(
        "python3 $d/skills", "curl -o $d/skills/demo/scripts/demo_tool.py https://example.com/x.py; python3 $d/skills")),
    ("copy from another folder", J7_COMMAND.replace("cp skills/demo/scripts/*.py", "cp /home/test/other/*.py")),
    ("sed edit of the copy", J7_COMMAND.replace(
        "python3 $d/skills", "sed -i 's/a/b/' $d/skills/demo/scripts/demo_tool.py; python3 $d/skills")),
    ("inline code instead of a script", J7_COMMAND.replace(
        "python3 $d/skills/demo/scripts/demo_tool.py --help", "python3 -c 'import os; os.system(\"true\")' $d")),
    ("expansion in an argument", J7_COMMAND.replace("demo_tool.py --help", "demo_tool.py $(echo --help)")),
    ("redirect outside temp", J7_COMMAND.replace("--help >/dev/null", "--help > /home/test/out.txt")),
    ("archive of another ref", J7_COMMAND.replace("git archive HEAD", "git archive origin/main")),
    ("extract elsewhere then run", J7_COMMAND.replace("tar -x -C $d", "tar -x -C /home/test/x")),
]


@pytest.mark.parametrize("index", range(len(J7_MUST_ASK)))
def test_템플릿이_없거나_다른_내용을_채우거나_고쳐서_실행하면_계속_묻는다(home, index):
    # given
    title, command = J7_MUST_ASK[index]
    # when
    output = guard.handle(bash(j7_command(j7_tree(home), command), home / "project"), "claude")
    # then
    assert decision(output) == "ask", (title, output)


def test_작업_트리의_플러그인_이름이_다르면_아카이브_복사본_실행은_계속_묻는다(home):
    # given
    command = j7_command(j7_tree(home, name="demo-plugin"))
    # when
    output = guard.handle(bash(command, home / "project"), "claude")
    # then
    assert decision(output) == "ask", output


@pytest.mark.parametrize("argv", ['["git", "push"]', '["sh", "-c", "git status"]', '["git", "-C", str(root), "push"]',
                                  '["git", "--output=x", "show", "HEAD"]', '["git", str(root), "show"]',
                                  'sys.argv[1:]', '["git", "show", "HEAD"], shell=True',
                                  '["git", "show", "HEAD"], stdout=open("x", "w")', '["git", "show", str(root)]'])
def test_git_읽기가_아닌_subprocess_run이_있는_스크립트는_계속_묻는다(home, argv):
    # given
    body = SAME_DEFS_BODY.replace('["git", "-C", str(root), "show", f"HEAD:{orig_rel}"]', argv)
    command = j7_command(j7_tree(home, defs_body=body), "S={s}; cd $S/wt-split && python3 $S/same_defs.py . a b")
    # when
    output = guard.handle(bash(command, home / "project"), "claude")
    # then
    assert decision(output) == "ask", (argv, output)


# --- J8. grep -o with a bounded context around a literal ---------------------------------------------------------------------

J8_CONTEXT = "xargs grep -h -o '.\\{150\\}PermissionRequest.\\{150\\}' < $S/files.txt | grep -v '\"text\"' | head -3"
J8_TYPES = "xargs grep -h -o '\"type\":\"[a-z_]*\"' < $S/files.txt | sort | uniq -c | sort -rn | head -40"


@pytest.mark.parametrize("body", [
    J8_CONTEXT + "; echo ===; " + J8_TYPES,
    "xargs grep -h -oE '.{150}PermissionRequest.{150}' < $S/files.txt | head -3",
    "xargs grep -h -o '.\\{20,200\\}PermissionRequest' < $S/files.txt | head -3",
    "xargs grep -h -o '\"type\":\"[A-Za-z0-9_]*\"' < $S/files.txt | sort | uniq -c",
    "xargs grep -h -o '[^\"]*\"PermissionRequest\"[^\"]*' < $S/files.txt | head",
    "xargs grep -h -o 'PermissionRequest.\\{512\\}' < $S/files.txt | head",
])
def test_고정_문자열_둘레의_범위가_있는_grep_o는_목록_파일에서도_묻지_않는다(home, body):
    # given
    command = j6(home, body)
    # when
    output = guard.handle(bash(command, home / "project"), "claude")
    # then
    assert decision(output) not in ("ask", "deny"), (body, output)


@pytest.mark.parametrize("body", [
    "xargs grep -h -o '.\\{600\\}PermissionRequest' < $S/files.txt",
    "xargs grep -h -o '.\\{300\\}PermissionRequest.\\{300\\}' < $S/files.txt",
    "xargs grep -h -o '.*PermissionRequest.*' < $S/files.txt",
    "xargs grep -h -o '.\\{150\\}token.\\{150\\}' < $S/files.txt",
    "xargs grep -h -o '.\\{150\\}abc.\\{150\\}' < $S/files.txt",
    "xargs grep -h -o '[^a]*PermissionRequest' < $S/files.txt",
    "xargs grep -h -o '.\\{150\\}PermissionRequest.\\{150\\}' < /home/test/list.txt",
    "xargs rg -o '.\\{150\\}PermissionRequest.\\{150\\}' < $S/files.txt",
    "xargs grep -h -o '.\\{150\\}PermissionRequest.\\{0,\\}' < $S/files.txt",
])
def test_범위가_없거나_너무_넓거나_짧은_고정_문자열이면_grep_o는_계속_묻는다(home, body):
    # given
    command = j6(home, body)
    # when
    output = guard.handle(bash(command, home / "project"), "claude")
    # then
    assert decision(output) == "ask", (body, output)


# --- J9. a stdlib HTML parser in a heredoc analysis script -------------------------------------------------------------------

BLOGCHECK_BODY = r'''import re, sys
from html.parser import HTMLParser
pairs = [('page_a','A'),('page_b','B')]
css = open('docs/blog/blog.css').read()
defined = set(re.findall(r'\.([a-zA-Z][\w-]*)', css))
for name, pre in pairs:
    h = open(f'docs/blog/{name}.html').read(); md = open(f'docs/notes/{name}.md').read()
    table = {}
    for line in md.splitlines():
        m = re.match(rf'^\|\s*({pre}-\d\d)\s*\|(.*)\|\s*$', line)
        if m:
            cells = [c.strip() for c in m.group(2).split('|')]
            table[m.group(1)] = cells[2] if len(cells) > 2 else '?'
    print(f'== {name}: md metrics', table)
    for m in re.finditer(r'<(span|text)([^>]*)data-metric="([^"]+)"([^>]*)>(.*?)</\1>', h, re.S):
        attrs = m.group(2) + m.group(4); mid = m.group(3); val = re.sub('<[^>]+>','',m.group(5))
        cls = re.search(r'class="([^"]*)"', attrs); cls = cls.group(1) if cls else ''
        ok = mid in table
        print(f'  {mid:9} [{cls}] {val!r}  md={table.get(mid)!r}{"" if ok else "  !!MISSING"}')
    used = set()
    for c in re.findall(r'class="([^"]*)"', h): used |= set(c.split())
    undef = sorted(c for c in used if c not in defined)
    print('  undefined classes:', undef)
    class P(HTMLParser):
        void = {'meta','link','br','img','hr','input','path','rect','circle','line','use'}
        def __init__(s): super().__init__(); s.st=[]; s.err=[]
        def handle_starttag(s,t,a):
            if t not in s.void: s.st.append(t)
        def handle_startendtag(s,t,a): pass
        def handle_endtag(s,t):
            if t in s.void: return
            if s.st and s.st[-1]==t: s.st.pop()
            else: s.err.append((t, s.getpos(), s.st[-3:]))
    p = P(); p.feed(h); print('  tag errors:', p.err[:5], 'unclosed:', p.st[:5])
'''


def blogcheck_command(base, body=BLOGCHECK_BODY):
    s = base / "scratchpad"
    return f"cd {base}/project && cat > {s}/blogcheck.py <<'EOF'\n{body}EOF\npython3 {s}/blogcheck.py"


def test_html_parser를_쓰는_읽기_전용_heredoc_점검_스크립트는_묻지_않는다(home):
    # given
    command = blogcheck_command(home)
    # when
    output = guard.handle(bash(command, home / "project"), "claude")
    # then
    assert decision(output) not in ("ask", "deny"), output


@pytest.mark.parametrize("extra", ["open('/home/test/x', 'w').write('1')\n", "import urllib.request\n",
                                   "import subprocess\nsubprocess.run(['ls'])\n"])
def test_점검_스크립트에_밖으로_쓰기나_네트워크_가져오기가_더해지면_계속_묻는다(home, extra):
    # given
    command = blogcheck_command(home, BLOGCHECK_BODY + extra)
    # when
    output = guard.handle(bash(command, home / "project"), "claude")
    # then
    assert decision(output) == "ask", (extra, output)


# --- J10. Python heredocs that write state-folder spellings only as text --------------------------------------------------------

README_TWO_FILES = f'''p='README.md'
s=open(p).read()
a="Python per project.\\n"
assert s.count(a)==1
s=s.replace(a,a+"""The launcher caches compiled bytecode under `{PYCACHE}/` (default
`~/.local/state`). This is a guard state folder, so the approval guard denies agent writes there like those to
`approvals/` and `heartbeats/`. Without an absolute state folder, hooks run without a cache.
""")
open(p,'w').write(s)
p='docs/ko/README.ko.md'
s=open(p).read()
a="Another sentence.\\n"
assert s.count(a)==1
s=s.replace(a,a+"""The launcher caches bytecode under `{PYCACHE}/` (default `~/.local/state`).
This folder is a guard state folder, so the guard denies writes like those to `approvals/` and `heartbeats/`.
""")
open(p,'w').write(s)
'''
README_FOLLOWERS = (
    "git diff README.md docs | grep '^[+-]'\n"
    "E=\"env -u GIT_CONFIG_COUNT -u GIT_CONFIG_KEY_0 -u GIT_CONFIG_KEY_1 -u GIT_CONFIG_VALUE_0 -u GIT_CONFIG_VALUE_1\"\n"
    "$E python3 -m pytest -p no:cacheprovider -o addopts=\"\" -q tests/test_hook_python.py tests/test_approval_guard.py "
    "2>&1 | tail -8\n"
    "$E python3 -m pytest -p no:cacheprovider -o addopts=\"\" -q tests/ -k approval 2>&1 | tail -8\n"
    "git status --short")


def test_두_README를_고치는_python_heredoc은_상태_폴더_경로가_글자로만_있으면_거부하지_않는다(home):
    # given
    command = f"cd {home}/project && python3 - <<'PYEOF'\n{README_TWO_FILES}PYEOF\n{README_FOLLOWERS}"
    # when
    output = guard.handle(bash(command, home / "project"), "claude")
    # then
    assert decision(output) != "deny", output


@pytest.mark.parametrize("body", [
    "import os\nopen(os.path.expandvars('$XDG_STATE_HOME/hei5enbug-agent-setup/approvals/x'), 'w').write('1')\n",
    "from pathlib import Path\n(Path.home() / '.local/state/hei5enbug-agent-setup/heartbeats').write_text('1')\n",
    "from pathlib import Path\np = Path.home() / '.local/state' / 'hei5enbug-agent-setup/pycache'\np.write_text('1')\n",
    "import shutil\nshutil.copy('a', '$XDG_STATE_HOME/hei5enbug-agent-setup/approvals/x')\n",
    "import os\nos.remove('$XDG_STATE_HOME/hei5enbug-agent-setup/approvals/x')\n",
    "import subprocess\nsubprocess.run(['rm', '$XDG_STATE_HOME/hei5enbug-agent-setup/approvals/x'])\n",
    "target = '$XDG_STATE_HOME/hei5enbug-agent-setup/approvals/x'\nopen(target, 'w').write('1')\n",
    "import os\nname = '$XDG_STATE_HOME/hei5enbug-agent-setup/approvals/x'\nos.rename('a', name)\n",
    "text = 'hei5enbug-agent-setup/approvals'\nopen(text + '/x', 'w').write('1')\n",
    "import os\nos.chdir('$XDG_STATE_HOME/hei5enbug-agent-setup/heartbeats')\n",
])
def test_python_heredoc이_상태_경로를_실제_경로_피연산자로_쓰면_계속_거부한다(home, body):
    # given
    command = f"cd {home}/project && python3 - <<'PYEOF'\n{body}PYEOF\n"
    # when
    output = guard.handle(bash(command, home / "project"), "claude")
    # then
    assert decision(output) == "deny", (body, output)


# --- J11. shell scripts run by path that set their own variables, as on 390dd1c ---------------------------------------------

KEYSNAP_BODY = '''"""Snapshot per-top-level-key hashes of a settings file (never content).

usage: python3 keysnap.py <label>
"""

import hashlib
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
SNAPSHOTS = HERE / "snapshots"
SENSITIVE = re.compile(r"key|secret|pass|auth|cred|env|header|url", re.I)


def main():
    SNAPSHOTS.mkdir(exist_ok=True)
    settings = Path(os.path.expanduser("~/.claude/settings.json"))
    data = json.loads(settings.read_text()) if settings.exists() else {}
    hashes = {key: hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()[:12] for key, value in data.items()}
    stamp = datetime.now(timezone.utc).isoformat()
    (SNAPSHOTS / f"settings-keyhash-{sys.argv[1]}.json").write_text(json.dumps({"at": stamp, "keys": hashes}))
    print(len(hashes), "keys at", stamp)


if __name__ == "__main__":
    main()
'''
FINAL_REGRESSION = '''#!/bin/sh
# Final regression of the main tip against the investigation start on all tasks.
# Resume: run this file again; finished runs are skipped. Exit 75 = usage limit.
REPO=/tmp/work/demo/repo
F=$HOME/.local/state/hei5enbug-agent-setup/harness-eval/final
E=$HOME/.local/state/hei5enbug-agent-setup/harness-eval/experiments
cd "$REPO" || exit 1
python3 "$E/scripts/keysnap.py" final-regression-start > "$F/logs/final-regression-keysnap.txt" 2>&1
echo "$(date -u +%FT%TZ) start final-regression control-0abc123,main-0def456 all tasks reps=3" >> "$F/logs/driver.log"
python3 -u evals/e2e/harness/cli.py run --campaign final-regression --variants control-0abc123,main-0def456 \\
  --reps 3 --variants-root "$F/variants" >> "$F/logs/final-regression-run.log" 2>&1
code=$?
echo "$(date -u +%FT%TZ) end final-regression exit=$code" >> "$F/logs/driver.log"
python3 "$E/scripts/keysnap.py" final-regression-end >> "$F/logs/final-regression-keysnap.txt" 2>&1
exit $code
'''
CLOSURE_RUN = '''#!/bin/sh
# Campaigns: a closure task, then the final main run.
# Resume: run this file again; finished runs are skipped. Exit 75 = usage limit, 4 = Codex hooks untrusted.
REPO=/tmp/work/demo/repo
S=$HOME/.local/state/hei5enbug-agent-setup/harness-eval
G=$S/closure
E=$S/experiments
cd "$REPO" || exit 1
step() {
  campaign=$1; variants=$2; tasks=$3; reps=$4
  "$G/probe.sh" || return $?
  python3 "$E/scripts/keysnap.py" "$campaign-start" >> "$G/logs/keysnap.txt" 2>&1
  echo "$(date -u +%FT%TZ) start $campaign variants=$variants tasks=$tasks reps=$reps" >> "$G/logs/driver.log"
  if [ -n "$tasks" ]; then set -- --tasks "$tasks"; else set --; fi
  python3 -u evals/e2e/harness/cli.py run --campaign "$campaign" --variants "$variants" "$@" \\
    --reps "$reps" --variants-root "$G/variants" >> "$G/logs/$campaign-run.log" 2>&1
  code=$?
  echo "$(date -u +%FT%TZ) end $campaign exit=$code" >> "$G/logs/driver.log"
  python3 "$E/scripts/keysnap.py" "$campaign-end" >> "$G/logs/keysnap.txt" 2>&1
  return $code
}
case "${1:-all}" in
  t09|all) step t09-closure control-0abc123,main-0def456 T09 6 || exit $? ;;
esac
case "${1:-all}" in
  final|all) step final-main main-0def456 "" 1 || exit $? ;;
esac
echo "$(date -u +%FT%TZ) campaigns done" >> "$G/logs/driver.log"
'''


@pytest.fixture
def harness(home, monkeypatch):
    user = home / "user"
    state = user / ".local" / "state" / "hei5enbug-agent-setup" / "harness-eval"
    (state / "experiments" / "scripts").mkdir(parents=True)
    (state / "final").mkdir()
    (state / "closure").mkdir()
    (state / "experiments" / "scripts" / "keysnap.py").write_text(KEYSNAP_BODY)
    for path, body in ((state / "final" / "final_regression.sh", FINAL_REGRESSION),
                       (state / "closure" / "run.sh", CLOSURE_RUN)):
        path.write_text(body)
        path.chmod(0o755)
    monkeypatch.setenv("HOME", str(user))
    monkeypatch.setenv("XDG_STATE_HOME", str(user / ".local" / "state"))
    (home / "bin").mkdir()
    for name, body in (("final_regression.sh", FINAL_REGRESSION), ("run.sh", CLOSURE_RUN)):
        (home / "bin" / name).write_text(body.replace("/tmp/work/demo/repo", str(home / "repo")))
        (home / "bin" / name).chmod(0o755)
    for path in (state / "final" / "final_regression.sh", state / "closure" / "run.sh"):
        path.write_text(path.read_text().replace("/tmp/work/demo/repo", str(home / "repo")))
    (home / "repo" / "evals" / "e2e" / "harness").mkdir(parents=True)
    (home / "repo" / "evals" / "e2e" / "harness" / "cli.py").write_text("import argparse\nargparse.ArgumentParser().parse_args()\n")
    return state


@pytest.mark.parametrize("where", ["state", "elsewhere"])
@pytest.mark.parametrize("script, tail", [("final/final_regression.sh", ""), ("closure/run.sh", "; echo \"run.sh exit=$?\"")])
def test_자기_변수를_정하고_키_스냅샷_스크립트를_부르는_셸_스크립트는_390dd1c처럼_묻지_않는다(home, harness, script, tail, where):
    # given
    folder = "~/.local/state/hei5enbug-agent-setup/harness-eval/" if where == "state" else f"{home}/bin/"
    name = script if where == "state" else script.split("/")[-1]
    command = f"{folder}{name}{tail}"
    # when
    output = guard.handle(bash(command, home / "repo"), "claude")
    # then
    assert decision(output) not in ("ask", "deny"), output


# --- J12. a python heredoc that runs text read from a file of the plugin's work folders ----------------------------------------

J12_AGG = ('import tiktoken\nenc=tiktoken.get_encoding("o200k_base")\nA={"demo-one": "first text", "demo-two": "second text"}\n'
           't=sum(len(enc.encode(v)) for k, v in A.items())\nprint(t)\n')
J12_EXEC = ('exec(open(Path.home()/".local/state/hei5enbug-agent-setup/harness-eval/final/agg_tokens.py").read().split("t=sum")[0]'
            '.replace("import tiktoken\\nenc=tiktoken.get_encoding(\\"o200k_base\\")",""))\n')
J12_REWRITE = r'''for name, text in A.items():
    p = Path(f"skills/{name}/SKILL.md"); t = p.read_text(encoding="utf-8")
    body = "\n".join("  " + l for l in textwrap.wrap(text, 100, break_long_words=False, break_on_hyphens=False))
    new, n = re.subn(r"^description: >-\n(?:  .*\n)+", lambda m: "description: >-\n" + body + "\n", t, count=1, flags=re.M)
    assert n == 1, name; p.write_text(new, encoding="utf-8")
def sub(path, old, new):
    p = Path(path); t = p.read_text(encoding="utf-8")
    assert t.count(old) == 1, (path, old[:40]); p.write_text(t.replace(old, new), encoding="utf-8")
sub("docs/ko/skills/demo-one/SKILL.ko.md",
"""old line one
old line two""",
"""new line one""")
sub("docs/ko/skills/demo-two/SKILL.ko.md",
"""old two""",
"""new two""")
'''
J12_HEAD = "import re, textwrap\nfrom pathlib import Path\n"
J12_TAIL = ("env -u GIT_CONFIG_COUNT -u GIT_CONFIG_KEY_0 -u GIT_CONFIG_VALUE_0 python3 -m pytest -q tests/test_demo.py 2>&1 "
            "| tail -1; cd ~/.local/state/hei5enbug-agent-setup/harness-eval/final && uv run -q --no-project --with tiktoken "
            "--with pyyaml python listing_tokens.py {wt} < /dev/null | cut -c1-260")


def j12_command(wt, executes=J12_EXEC, rewrite=J12_REWRITE, tail=J12_TAIL):
    return f"cd {wt} && python3 - <<'EOF'\n{J12_HEAD}{executes}{rewrite}EOF\n{tail.replace('{wt}', str(wt))}"


@pytest.fixture
def j12(home, monkeypatch):
    user = home / "user"
    final = user / ".local" / "state" / "hei5enbug-agent-setup" / "harness-eval" / "final"
    final.mkdir(parents=True)
    (final / "agg_tokens.py").write_text(J12_AGG)
    (final / "listing_tokens.py").write_text("print(1)\n")
    monkeypatch.setenv("HOME", str(user))
    monkeypatch.setenv("XDG_STATE_HOME", str(user / ".local" / "state"))
    wt = home / "scratchpad" / "wt" / "skill-descriptions"
    wt.mkdir(parents=True)
    return wt


def j12_decision(home, command):
    return decision(guard.handle(bash(command, home / "project"), "claude"))


def test_상태_폴더_파일을_읽어_exec하는_heredoc은_임시_폴더_안에서만_쓰면_묻지_않는다(home, j12):
    # given
    command = j12_command(j12)
    # when
    result = j12_decision(home, command)
    # then
    assert result not in ("ask", "deny")


def test_기록된_exec_heredoc_모양은_분류가_pass다(home, j12):
    # given
    command = j12_command(j12)
    # when
    outcome = guard.classify_text(command, str(home / "project"))
    # then
    assert outcome.kind == "pass"


J12_P_BODIES = {
    "subprocess": 'import subprocess; subprocess.run(["curl", "https://example.com"])\nA={}\nt=sum(1 for k in A)\n',
    "urlopen": 'import urllib.request\nurllib.request.urlopen("https://example.com")\nA={}\nt=sum(1 for k in A)\n',
    "absolute write": 'from pathlib import Path\nPath("/home/test/out.md").write_text("x")\nA={}\nt=sum(1 for k in A)\n',
    "relative write outside the folder": 'from pathlib import Path\nPath("../../out.md").write_text("x")\nA={}\nt=sum(1 for k in A)\n',
    "write in an unresolved place": 'import sys\nfrom pathlib import Path\nPath(sys.argv[1]).write_text("x")\nA={}\nt=sum(1 for k in A)\n',
    "environment": 'import os\nA={"k": dict(os.environ)}\nt=sum(1 for k in A)\n',
    "nested exec": 'exec("print(1)")\nA={}\nt=sum(1 for k in A)\n',
    "third-party import left in the text": "import tiktoken\nenc=tiktoken.get_encoding(\"o200k_base\")\nA={}\nt=sum(1 for k in A)\n",
}


@pytest.mark.parametrize("title", list(J12_P_BODIES))
def test_exec한_파일이_프로세스_네트워크_밖_쓰기를_하면_계속_묻는다(home, j12, title):
    # given
    final = Path(os.environ["XDG_STATE_HOME"]) / "hei5enbug-agent-setup" / "harness-eval" / "final"
    body = J12_P_BODIES[title]
    (final / "agg_tokens.py").write_text(body)
    executes = J12_EXEC if title != "third-party import left in the text" else (
        'exec(open(Path.home()/".local/state/hei5enbug-agent-setup/harness-eval/final/agg_tokens.py").read().split("t=sum")[0])\n')
    # when
    result = j12_decision(home, j12_command(j12, executes=executes))
    # then
    assert result == "ask", (title, result)


def test_replace가_exec한_텍스트에_프로세스_호출을_끼워_넣으면_묻는다(home, j12):
    # given
    injected = ('exec(open(Path.home()/".local/state/hei5enbug-agent-setup/harness-eval/final/agg_tokens.py").read()'
                '.replace("print(t)", "import subprocess; subprocess.run([\\"curl\\", \\"https://example.com\\"])"))\n')
    # when
    result = j12_decision(home, j12_command(j12, executes=injected))
    # then
    assert result == "ask"


@pytest.mark.parametrize("executes", [
    'exec(open("/home/test/x.py").read())\n',
    'import sys\nexec(open(sys.argv[1]).read())\n',
    'exec(open(Path.home()/".local/state/hei5enbug-agent-setup/harness-eval/final/missing.py").read())\n',
    'code = open("/tmp/work/demo/a.py").read()\nexec(code)\n',
    'exec(open(Path.home()/".local/state/hei5enbug-agent-setup/harness-eval/final/agg_tokens.py").read(), {})\n',
])
def test_exec의_대상이_작업_폴더_밖이거나_글자로_정해지지_않으면_묻는다(home, j12, executes):
    # given
    command = j12_command(j12, executes=executes)
    # when
    result = j12_decision(home, command)
    # then
    assert result == "ask", (executes, result)


def test_작업_폴더_밖의_파일을_exec하면_묻는다(home, j12, monkeypatch):
    # given
    monkeypatch.setattr(guard, "TEMPORARY_ROOTS", ("/nonexistent-temp-root",))
    monkeypatch.setenv("TMPDIR", "/nonexistent-tmpdir")
    elsewhere = Path(os.environ["HOME"]) / "elsewhere"
    elsewhere.mkdir()
    (elsewhere / "x.py").write_text("A = {}\n")
    command = f'cd {j12} && python3 - <<\'EOF\'\nexec(open("{elsewhere}/x.py").read())\nEOF\n'
    # when
    result = j12_decision(home, command)
    # then
    assert result == "ask"


def test_가드_상태_폴더의_파일을_exec하면_묻거나_거부한다(home, j12):
    # given
    approvals = Path(os.environ["XDG_STATE_HOME"]) / "hei5enbug-agent-setup" / "approvals"
    approvals.mkdir(parents=True)
    (approvals / "x.py").write_text("A = {}\n")
    executes = 'exec(open(Path.home()/".local/state/hei5enbug-agent-setup/approvals/x.py").read())\n'
    # when
    result = j12_decision(home, j12_command(j12, executes=executes, rewrite=""))
    # then
    assert result in ("ask", "deny")


J12_WRITES = {
    "absolute path outside temp": 'Path("/home/test/out.md").write_text("x")\n',
    "absolute open outside temp": 'open("/home/test/out.md", "w").write("x")\n',
    "parent folder": 'Path("../out.md").write_text("x")\n',
    "home path": 'Path.home().joinpath("out.md").write_text("x")\n',
    "the exec target itself": ('Path.home().joinpath(".local/state/hei5enbug-agent-setup/harness-eval/final/agg_tokens.py")'
                               '.write_text("x")\n'),
    "unresolved target": 'import sys\nPath(sys.argv[1]).write_text("x")\n',
}


@pytest.mark.parametrize("title", list(J12_WRITES))
def test_exec_heredoc이_임시_폴더_밖이나_정해지지_않은_경로에_쓰면_묻는다(home, j12, title):
    # given
    command = j12_command(j12, rewrite=J12_WRITES[title])
    # when
    result = j12_decision(home, command)
    # then
    assert result == "ask", (title, result)


def test_작업_폴더가_임시_폴더_밖이면_상대_경로_쓰기가_있는_exec_heredoc은_묻는다(home, j12, monkeypatch):
    # given
    monkeypatch.setattr(guard, "TEMPORARY_ROOTS", ("/nonexistent-temp-root",))
    monkeypatch.setenv("TMPDIR", "/nonexistent-tmpdir")
    # when
    result = j12_decision(home, j12_command(j12))
    # then
    assert result == "ask"


def test_앞선_줄에서_cd한_exec_heredoc의_상대_경로_쓰기는_폴더를_알_수_없어_묻는다(home, j12):
    # given
    command = f"cd /home/test\n{j12_command(j12)}"
    # when
    result = guard.handle(bash(command, j12), "claude")
    # then
    assert decision(result) == "ask"


def test_exec가_없는_heredoc의_쓰기_판정은_바뀌지_않는다(home, j12):
    # given
    command = f"cd {j12} && python3 - <<'EOF'\nfrom pathlib import Path\nPath('/home/test/out.md').write_text('x')\nEOF\n"
    # when
    result = j12_decision(home, command)
    # then
    assert result not in ("ask", "deny")


# --- J14. the repository's own tracked, unmodified scripts run as plain `python3 <path>` --------------------------------------

VALIDATE_SCRIPT = ("import subprocess, sys\n\ndef run(detector, skill):\n"
                   "    return subprocess.run([sys.executable, str(detector), str(skill)], capture_output=True, text=True)\n"
                   "\nif __name__ == '__main__':\n    print(run('check_x.py', sys.argv[1]))\n")
J14_SCRIPTS = ("skills/skill-builder/scripts/quick_validate.py", "scripts/role_runner.py", "scripts/host_tool.py",
               "skills/orca-plugin-refresh/scripts/orca_plugin_refresh.py", "hooks/x.py", "skills/demo/scripts/run_tests.py",
               "skills/demo/scripts/release_notes.py", "skills/demo/scripts/model_runner.py")
J14_EFFECTFUL = ("skills/local-data-cleanup/scripts/data_removal.py", "scripts/plugin_toggles.py",
                 "skills/skill-builder/scripts/run_eval.py", "skills/skill-builder/scripts/run_loop.py",
                 "skills/tiki-taka/scripts/detached_job.py", "skills/tiki-taka/scripts/stream_agent.py")
J14_SCRIPTS += J14_EFFECTFUL
J14_LOOP = ("for s in decision-navigator deep-interview flowchart-design session-retro tiki-taka report-skill-gap; "
            "do python3 skills/skill-builder/scripts/quick_validate.py skills/$s 2>&1 | tail -1; done")


def j14_git(root, *args):
    subprocess.run(["git", "-c", "user.name=demo", "-c", "user.email=demo@example.com", *args], cwd=root, check=True,
                   capture_output=True)


def j14_repo(root, name=PLUGIN_NAME):
    (root / ".claude-plugin").mkdir(parents=True)
    (root / ".claude-plugin" / "plugin.json").write_text(f'{{"name": "{name}"}}\n')
    for script in J14_SCRIPTS:
        (root / script).parent.mkdir(parents=True, exist_ok=True)
        (root / script).write_text(VALIDATE_SCRIPT)
    j14_git(root, "init", "-q")
    j14_git(root, "add", "-A")
    j14_git(root, "commit", "-q", "-m", "one")
    return root


@pytest.fixture
def j14(home, monkeypatch):
    monkeypatch.setenv("HOME", str(home / "user"))
    monkeypatch.setenv("XDG_STATE_HOME", str(home / "user" / ".local" / "state"))
    return j14_repo(home / "scratchpad" / "repo")


def j14_decision(home, command):
    return decision(guard.handle(bash(command, home / "project"), "claude"))


def test_추적되고_바뀌지_않은_저장소_검증_스크립트_반복_호출은_묻지_않는다(home, j14):
    # given
    command = f"cd {j14} && {J14_LOOP}"
    # when
    result = j14_decision(home, command)
    # then
    assert result not in ("ask", "deny")


@pytest.mark.parametrize("call", [
    "python3 -u skills/skill-builder/scripts/quick_validate.py skills/x",
    "python3 ./skills/skill-builder/scripts/quick_validate.py skills/x extra --flag",
    "python3 {repo}/skills/skill-builder/scripts/quick_validate.py {repo}/skills/x 2>&1 | tail -1",
    "python3 skills/demo/scripts/run_tests.py > /dev/null",
    "python3 skills/skill-builder/scripts/quick_validate.py x > {tmp}/out.txt",
])
def test_추적된_저장소_스크립트는_경로_표기와_일반_인자가_달라도_묻지_않는다(home, j14, call):
    # given
    command = f"cd {j14} && " + call.replace("{repo}", str(j14)).replace("{tmp}", str(home / "scratchpad"))
    # when
    result = j14_decision(home, command)
    # then
    assert result not in ("ask", "deny"), call


def j14_change(repo, title):
    script = repo / "skills" / "skill-builder" / "scripts" / "quick_validate.py"
    if title == "unstaged edit":
        script.write_text(VALIDATE_SCRIPT + "# edit\n")
    elif title == "staged edit":
        script.write_text(VALIDATE_SCRIPT + "# edit\n")
        j14_git(repo, "add", str(script))
    elif title == "untracked":
        script.parent.joinpath("new_check.py").write_text(VALIDATE_SCRIPT)
    elif title == "another plugin":
        (repo / ".claude-plugin" / "plugin.json").write_text('{"name": "demo-plugin"}\n')
        j14_git(repo, "commit", "-q", "-am", "rename")


J14_ASKS = [
    ("unstaged edit", "python3 skills/skill-builder/scripts/quick_validate.py x"),
    ("staged edit", "python3 skills/skill-builder/scripts/quick_validate.py x"),
    ("untracked", "python3 skills/skill-builder/scripts/new_check.py x"),
    ("another plugin", "python3 skills/skill-builder/scripts/quick_validate.py x"),
    ("excepted", "python3 skills/orca-plugin-refresh/scripts/orca_plugin_refresh.py status"),
    ("excepted", "python3 hooks/x.py"),
    ("excepted", "python3 skills/demo/scripts/model_runner.py x"),
    ("excepted", "python3 skills/demo/scripts/release_notes.py x"),
    ("excepted", "python3 scripts/approval_guard.py"),
    ("excepted", "python3 skills/local-data-cleanup/scripts/data_removal.py x"),
    ("excepted", "python3 scripts/plugin_toggles.py x"),
    ("excepted", "python3 skills/skill-builder/scripts/run_eval.py x"),
    ("excepted", "python3 skills/skill-builder/scripts/run_loop.py x"),
    ("excepted", "python3 skills/tiki-taka/scripts/detached_job.py x"),
    ("excepted", "python3 skills/tiki-taka/scripts/stream_agent.py x"),
    ("outside", "python3 other/quick_validate.py x"),
    ("environment", "DEMO=1 python3 skills/skill-builder/scripts/quick_validate.py x"),
    ("env wrapper", "env DEMO=1 python3 skills/skill-builder/scripts/quick_validate.py x"),
    ("redirect", "python3 skills/skill-builder/scripts/quick_validate.py x > /home/test/out"),
    ("earlier edit", "sed -i 's/x/y/' skills/skill-builder/scripts/quick_validate.py; python3 skills/skill-builder/scripts/"
     "quick_validate.py x"),
]


@pytest.mark.parametrize("title, call", J14_ASKS)
def test_바뀌었거나_추적되지_않았거나_제외된_스크립트와_환경_리다이렉트가_있는_호출은_계속_묻는다(home, j14, title, call):
    # given
    (j14 / "other").mkdir()
    (j14 / "other" / "quick_validate.py").write_text(VALIDATE_SCRIPT)
    j14_git(j14, "add", "-A")
    j14_git(j14, "commit", "-q", "-m", "other")
    j14_change(j14, title)
    # when
    result = j14_decision(home, f"cd {j14} && {call}")
    # then
    assert result in ("ask", "deny"), (title, call, result)


S04_TAIL = (J14_LOOP + "; env -u GIT_CONFIG_COUNT -u GIT_CONFIG_KEY_0 -u GIT_CONFIG_VALUE_0 python3 -m pytest -q "
            "tests/test_korean_mirrors.py tests/test_public_boundary.py 2>&1 | tail -1; cd ~/.local/state/hei5enbug-agent-setup/"
            "harness-eval/final && uv run -q --no-project --with tiktoken --with pyyaml python listing_tokens.py {wt} "
            "< /dev/null | cut -c1-260")


def test_기록된_s04_전체_명령은_묻지_않는다(home, j12, j14):
    # given
    command = j12_command(j14, tail=S04_TAIL)
    # when
    result = j12_decision(home, command)
    # then
    assert result not in ("ask", "deny")


def test_기록된_s04_명령에서_검증_스크립트가_바뀌었으면_묻는다(home, j12, j14):
    # given
    j14_change(j14, "unstaged edit")
    # when
    result = j12_decision(home, j12_command(j14, tail=S04_TAIL))
    # then
    assert result == "ask"


def test_role_runner는_기존_규칙대로_계속_묻지_않는다(home, j14):
    # given
    command = f"cd {j14} && python3 scripts/role_runner.py x"
    # when
    result = j14_decision(home, command)
    # then
    assert result not in ("ask", "deny")


# --- L2. a helper script whose removal target is a positional parameter, and an export before a names-only env listing --

HELPER_BODY = """#!/bin/bash
mode=$1; shift; bt=$1; shift
for v in $(env | grep -o '^GIT_CONFIG_[A-Z0-9_]*'); do unset $v; done
if [ "$mode" = orca ]; then
  export GIT_CONFIG_COUNT=2 GIT_CONFIG_KEY_0=credential.interactive GIT_CONFIG_VALUE_0=false GIT_CONFIG_KEY_1=credential.guiPrompt GIT_CONFIG_VALUE_1=false
fi
rm -rf {base}/pt/$bt
exec python3 -m pytest -q -p no:cacheprovider --basetemp={base}/pt/$bt "$@"
"""
HELPER_CALLS = [
    "{base}/pt.sh orca o1 tests/test_approval_local_scope.py tests/test_approval_session_scope.py 2>&1 "
    "| grep -E \"^E |passed|failed\" | head -8",
    "({base}/pt.sh clean fc -x -q 2>&1 | tail -4 > {base}/full-clean.txt) & wait",
]
LISTING = "env | grep GIT_CONFIG | sed 's/=.*//'"


def helper(base, body=HELPER_BODY):
    script = base / "pt.sh"
    script.write_text(body.replace("{base}", str(base)))
    script.chmod(0o755)
    return script


def bash_decision(home, monkeypatch, command):
    for name, value in GIT_CONFIG.items():
        monkeypatch.setenv(name, value)
    return decision(guard.handle(bash(command, home / "project"), "claude"))


@pytest.mark.parametrize("call", HELPER_CALLS)
def test_위치_인자로_삭제_대상을_만드는_임시_폴더_도우미_호출은_묻지_않는다(home, monkeypatch, call):
    # given
    helper(home)
    # when
    result = bash_decision(home, monkeypatch, call.replace("{base}", str(home)))
    # then
    assert result not in ("ask", "deny")


@pytest.mark.parametrize("body, call", [
    ("mode=$1; shift; bt=$1; shift\nrm -rf $bt\n", "{base}/pt.sh orca /home/test/data"),
    ("mode=$1; shift; bt=$1; shift\nrm -rf {base}/pt/$bt\n", "{base}/pt.sh orca " + "../" * 14 + "home/test/data"),
    ("mode=$1; shift; bt=$1; shift\nrm -rf {base}/pt/$bt\n", "{base}/pt.sh orca \"$(cat list)\""),
    ("mode=$1; shift; bt=$1; shift\nrm -rf {base}/pt/$bt\n", "{base}/pt.sh orca \"$UNSET_VARIABLE\""),
    ("mode=$1; shift; set -- /home/test/data; bt=$1\nrm -rf $bt\n", "{base}/pt.sh orca o1"),
    ("mode=$1; shift $n; bt=$1\nrm -rf {base}/pt/$bt\n", "{base}/pt.sh orca o1"),
    ("while true; do shift; bt=$1; rm -rf {base}/pt/$bt; done\n", "{base}/pt.sh orca o1"),
    ("mode=$1; [ -n \"$mode\" ] && shift; bt=$1\nrm -rf {base}/pt/$bt\n", "{base}/pt.sh orca o1"),
])
def test_위치_인자를_따라갈_수_없거나_임시_폴더_밖이면_도우미_호출은_계속_묻는다(home, monkeypatch, body, call):
    # given
    helper(home, "#!/bin/bash\n" + body)
    # when
    result = bash_decision(home, monkeypatch, call.replace("{base}", str(home)))
    # then
    assert result == "ask"


@pytest.mark.parametrize("prefix", [
    "export PYTEST_ADDOPTS=\"--basetemp=$TMPDIR/pt\"; ",
    "echo $TMPDIR; export PYTEST_ADDOPTS=\"--basetemp=$TMPDIR/pt\"; ",
    "FOO=1; ",
])
def test_비밀이_아닌_이름의_export_뒤_이름만_보이는_env_목록은_묻지_않는다(home, monkeypatch, prefix):
    # given
    command = prefix + LISTING + " ; GIT_CONFIG_COUNT=2 python3 -m pytest -q tests/test_demo.py 2>&1 | tail -3"
    # when
    result = bash_decision(home, monkeypatch, command)
    # then
    assert result not in ("ask", "deny")


@pytest.mark.parametrize("command", [
    "export DEMO_API_TOKEN=abc; " + LISTING,
    "export PYTEST_ADDOPTS=x; env | grep DEMO_API",
    "export PYTEST_ADDOPTS=x; env | grep DEMO_API | sed 's/=/:/'",
    "export PYTEST_ADDOPTS=x; env | grep DEMO_API | sed 's/GIT//'",
])
def test_비밀_이름의_export이거나_값이_나올_수_있는_env_목록은_계속_묻는다(home, monkeypatch, command):
    # given
    monkeypatch.setenv("DEMO_API_TOKEN", "abc")
    # when
    result = bash_decision(home, monkeypatch, command)
    # then
    assert result == "ask"


# --- L3. a recursive removal of a temporary root, or of a folder that holds one, asks every time -------------------------

SHARED_TEMP_TARGETS = [
    "/private/tmp", "/tmp", "/tmp/", "/private/tmp/claude-501", "/tmp/claude-501", "/var/folders", "/private/var/folders",
    "/private/var/folders/y1", "/private/var/folders/y1/abcdef", "/tmp/../tmp", "/tmp//", "/private", "/var",
    "\"$TMPDIR\"", "$TMPDIR", "~/.cache", "/tmp/*", "\"$TMPDIR\"/*",
]


@pytest.mark.parametrize("target", SHARED_TEMP_TARGETS)
def test_임시_폴더_자체나_그것을_담은_공용_폴더를_지우면_매번_묻는다(home, monkeypatch, target):
    # given
    monkeypatch.setenv("TMPDIR", str(home.parent))
    command = f"rm -rf {target}"
    # when
    result = bash_decision(home, monkeypatch, command)
    # then
    assert result == "ask", target


def test_TMPDIR가_가리키는_폴더를_위치_인자로_지우는_도우미_호출은_매번_묻는다(home, monkeypatch):
    # given
    monkeypatch.setenv("TMPDIR", str(home.parent))
    helper(home)
    # when
    result = bash_decision(home, monkeypatch, f"{home}/pt.sh orca ../..")
    # then
    assert result == "ask"


def test_임시_폴더_바로_아래_공용_폴더로_올라가는_도우미_호출은_매번_묻는다(home, monkeypatch):
    # given
    helper(home)
    # when
    result = bash_decision(home, monkeypatch, f"{home}/pt.sh orca " + "../" * 14 + "tmp")
    # then
    assert result == "ask"


@pytest.mark.parametrize("target", [
    "{base}/pt/o1", "{base}/pt", "{base}/x/y", "/tmp/work/a", "/private/tmp/claude-501/job1/x", "\"$TMPDIR\"/pt",
    "$TMPDIR/pt/o1", "/tmp/demo*", "~/.cache/demo",
])
def test_임시_폴더_안쪽_삭제는_그대로_묻지_않는다(home, monkeypatch, target):
    # given
    monkeypatch.setenv("TMPDIR", str(home.parent))
    command = "rm -rf " + target.replace("{base}", str(home))
    # when
    result = bash_decision(home, monkeypatch, command)
    # then
    assert result not in ("ask", "deny"), target


# --- L2-3. a python heredoc that reads a git blob through a literal subprocess call and writes the result to temp ----------

BLOB_PATH = "tests/test_demo.py"
BLOB_TEMPLATE = '''import subprocess, os
from pathlib import Path
cur = Path("{blob}").read_text()
head = subprocess.run({argv},capture_output=True,text=True,check=True).stdout
start = cur.index("\\n\\nCONFIG = {{")
{write}
'''
TMPDIR_WRITE = 'Path(os.environ["TMPDIR"],"item1.py").write_text(head + cur[start:])'


def blob_command(argv='["git","show","HEAD:tests/test_demo.py"]', write=TMPDIR_WRITE, call_extra=""):
    body = BLOB_TEMPLATE.format(blob=BLOB_PATH, argv=argv, write=write)
    if call_extra:
        body = body.replace("capture_output=True", call_extra + ",capture_output=True")
    return f"python3 - <<'EOF'\n{body}EOF"


def blob_decision(home, monkeypatch, command):
    monkeypatch.setenv("TMPDIR", str(home.parent))
    return decision(guard.handle(bash(command, home / "project"), "claude"))


@pytest.mark.parametrize("write", [
    TMPDIR_WRITE,
    'Path("/tmp/work/item1.py").write_text(head + cur[start:])',
    'open("/tmp/work/item1.py", "w").write(head + cur[start:])',
])
def test_리터럴_git_읽기_subprocess와_임시_폴더_쓰기가_함께_있는_heredoc은_묻지_않는다(home, monkeypatch, write):
    # given
    command = blob_command(write=write)
    # when
    result = blob_decision(home, monkeypatch, command)
    # then
    assert result not in ("ask", "deny"), (write, result)


@pytest.mark.parametrize("argv", [
    '["git","diff","HEAD","--","tests/test_demo.py"]', '["git","log","-1","--format=%H"]',
    '["git","rev-parse","HEAD"]', '["git","ls-files"]', '["git","cat-file","-p","HEAD:tests/test_demo.py"]',
    '["git","status","--short"]', '["git","-C","/tmp/work","show","HEAD:a.py"]',
])
def test_다른_읽기_git_하위_명령도_임시_폴더_쓰기와_함께_묻지_않는다(home, monkeypatch, argv):
    # given
    command = blob_command(argv=argv)
    # when
    result = blob_decision(home, monkeypatch, command)
    # then
    assert result not in ("ask", "deny"), (argv, result)


@pytest.mark.parametrize("argv", [
    '["git","commit","-m","x"]', '["git","push"]', '["git","checkout","main"]', '["git","reset","--hard"]',
    '["git","-c","core.pager=sh","show","HEAD"]', '["git","--exec-path=/tmp/work","show","HEAD"]',
    '["git","show","--output=x","HEAD"]', '["git","diff","--output","x"]', '["git","show",sys.argv[1]]',
    'sys.argv[1:]', '["git","show","HEAD"], shell=True', '"git show HEAD", shell=True',
])
def test_쓰기_git_하위_명령_비리터럴_argv_shell_true_git_c는_임시_쓰기와_함께여도_계속_묻는다(home, monkeypatch, argv):
    # given
    command = blob_command(argv=argv.replace(", shell=True", "")).replace(
        "check=True)", "check=True" + (", shell=True" if "shell=True" in argv else "") + ")")
    command = command.replace("import subprocess, os", "import subprocess, os, sys")
    # when
    result = blob_decision(home, monkeypatch, command)
    # then
    assert result == "ask", (argv, result)


@pytest.mark.parametrize("write", [
    'Path("/home/test/item1.py").write_text(head + cur[start:])',
    'Path(os.environ["HOME"], "item1.py").write_text(head + cur[start:])',
])
def test_git_읽기_subprocess와_임시_폴더_밖_쓰기가_함께_있으면_계속_묻는다(home, monkeypatch, write):
    # given
    command = blob_command(write=write)
    # when
    result = blob_decision(home, monkeypatch, command)
    # then
    assert result == "ask", (write, result)


def test_git_읽기_subprocess와_가드_모듈_가져오기가_함께_있으면_계속_막거나_묻는다(home, monkeypatch):
    # given
    body = ("import subprocess, sys\nsys.path.insert(0, 'scripts')\nimport approval_guard as g\n"
            "head = subprocess.run(['git','show','HEAD:a.py'],capture_output=True,text=True,check=True).stdout\n"
            "open('/tmp/work/x.py','w').write(head)\n")
    command = f"python3 - <<'EOF'\n{body}EOF"
    # when
    result = blob_decision(home, monkeypatch, command)
    # then
    assert result in ("ask", "deny"), result


# --- L2-3 recorded form. a search string that merely looks like a secret word is text, not a secret read ---------------

RECORDED_BODY = '''import subprocess, os
from pathlib import Path
cur = Path("tests/test_demo.py").read_text()
head = subprocess.run(["git","show","HEAD:tests/test_demo.py"],capture_output=True,text=True,check=True).stdout
start = cur.index("\\n\\nCREDENTIAL_PROMPT_CONFIG = {")
Path(os.environ["TMPDIR"],"item1.py").write_text(head + cur[start:])
'''


def secret_word_command(middle, writes_value="head + cur"):
    body = BLOB_TEMPLATE.format(blob=BLOB_PATH, argv='["git","show","HEAD:tests/test_demo.py"]',
                                write=f'{middle}\nPath("/tmp/work/out.py").write_text({writes_value})')
    return f"python3 - <<'EOF'\n{body}EOF"


def test_기록된_L2_3_본문은_검색_문자열에_credential이_있어도_묻지_않는다(home, monkeypatch):
    # given
    command = f"python3 - <<'EOF'\n{RECORDED_BODY}EOF"
    # when
    result = blob_decision(home, monkeypatch, command)
    # then
    assert result not in ("ask", "deny"), result


@pytest.mark.parametrize("middle", [
    'pos = cur.index("\\nTOKEN_LIMIT = ")',
    'pos = cur.find("password_hint")',
    'pos = cur.rfind("secret_key")',
    'parts = cur.split("# credentials")',
    'parts = cur.rsplit("token", 1)',
    'parts = cur.partition("PASSWORD_FIELD")',
    'parts = cur.rpartition("secret")',
    'cur = cur.replace("old_token", "new_name")',
    'ok = cur.startswith("# secret")',
    'ok = cur.endswith("token\\n")',
    'n = cur.count("password")',
    'cur = cur.strip("# credential ")',
    'ok = "API_TOKEN = " in cur',
    'ok = "password" not in cur',
    'import re\nm = re.search(r"(?m)^SECRET_\\w+", cur)',
    'import re\ncur = re.sub(r"token=\\w+", "", cur)',
    'import re\nfound = re.findall(r"password\\s*=", cur)',
    'import re\nm = re.match(r"credential", cur)',
    'import re\npattern = re.compile(r"secret_\\d+")',
])
def test_검색_문자열로만_쓰인_비밀_단어는_읽기_전용_임시_쓰기_스크립트에서_묻지_않는다(home, monkeypatch, middle):
    # given
    command = secret_word_command(middle)
    # when
    result = blob_decision(home, monkeypatch, command)
    # then
    assert result not in ("ask", "deny"), (middle, result)


@pytest.mark.parametrize("middle", [
    'secret = open(os.path.expanduser("~/.netrc")).read()',
    'print(os.environ["API_TOKEN"])',
    'print(Path("secrets.env").read_text())',
    'import keyring\nprint(keyring.get_password("svc", "user"))',
    'print(Path("credentials.json").read_text())',
    'text = open("password.txt").read()',
    'print("token")',
    'sys_name = "API_TOKEN"; value = os.environ.get(sys_name)',
    'print(os.environ.get("API_TOKEN"))',
    'path = "secrets.env"; print(Path(path).read_text())',
    'print(cur.replace("a", "b") + open("secret.txt").read())',
])
def test_비밀을_읽거나_출력하는_리터럴은_임시_쓰기와_함께여도_계속_묻는다(home, monkeypatch, middle):
    # given
    command = secret_word_command(middle)
    # when
    result = blob_decision(home, monkeypatch, command)
    # then
    assert result in ("ask", "deny"), (middle, result)


# --- L2-4. this plugin's tracked node test file runs before a loop of its tracked scripts --------------------------------

NODE_TEST = "skills/document-to-confluence/tests/test_render_diagrams.mjs"
NODE_LOOP = ('for s in skills/*/; do python3 skills/skill-builder/scripts/quick_validate.py "$s" >/dev/null 2>&1 || '
             'echo "FAIL $s"; done; echo validated')
NODE_RECORDED = (f"node --version; node --test {NODE_TEST} 2>&1 | tail -8 | grep -E \"pass|fail\"; {NODE_LOOP}")


@pytest.fixture
def l24(j14):
    (j14 / NODE_TEST).parent.mkdir(parents=True)
    (j14 / NODE_TEST).write_text("import test from 'node:test';\ntest('a', () => {});\n")
    (j14 / "tools").mkdir()
    (j14 / "tools" / "run.mjs").write_text("console.log(1);\n")
    j14_git(j14, "add", "-A")
    j14_git(j14, "commit", "-q", "-m", "node")
    return j14


@pytest.mark.parametrize("prefix", [
    "node --version; ",
    f"node --test {NODE_TEST}; ",
    f"node --test {NODE_TEST} 2>&1 | tail -3; ",
    f"node --version; node --test ./{NODE_TEST}; ",
    "",
])
def test_추적된_node_테스트_실행_뒤의_추적된_스크립트_반복은_묻지_않는다(home, l24, prefix):
    # given
    command = f"cd {l24} && " + prefix + NODE_LOOP
    # when
    result = j14_decision(home, command)
    # then
    assert result not in ("ask", "deny"), prefix


def test_기록된_L2_4_명령은_묻지_않는다(home, l24):
    # given
    command = f"cd {l24} && {NODE_RECORDED}"
    # when
    result = j14_decision(home, command)
    # then
    assert result not in ("ask", "deny")


def l24_change(repo, title):
    if title == "modified test":
        (repo / NODE_TEST).write_text("import test from 'node:test';\ntest('b', () => {});\n")
    elif title == "untracked test":
        (repo / NODE_TEST).with_name("test_new.mjs").write_text("console.log(2);\n")


L24_ASKS = [
    ("modified test", f"node --test {NODE_TEST}; "),
    ("untracked test", f"node --test {NODE_TEST.replace('render_diagrams', 'new')}; "),
    ("none", "node -e 'console.log(1)'; "),
    ("none", "node --eval 'console.log(1)'; "),
    ("none", f"node --test -e 'x' {NODE_TEST}; "),
    ("none", "node tools/run.mjs; "),
    ("none", f"node --test {NODE_TEST} extra.mjs; "),
    ("none", f"sed -i 's/a/b/' skills/skill-builder/scripts/quick_validate.py; node --test {NODE_TEST}; "),
    ("none", f"node --test {NODE_TEST}; cp scripts/host_tool.py skills/skill-builder/scripts/quick_validate.py; "),
    ("none", f"node --test {NODE_TEST} > skills/skill-builder/scripts/quick_validate.py; "),
    ("none", f"node --test {NODE_TEST}; git checkout HEAD~1 -- skills; "),
    ("none", f"node --test /home/test/other/test_x.mjs; "),
    ("none", "node --test tools/run.mjs; "),
    ("none", "echo a | sort -o skills/skill-builder/scripts/quick_validate.py; "),
    ("modified test", f"node --test {NODE_TEST} 2>&1 | tail -3; "),
]


@pytest.mark.parametrize("title, prefix", L24_ASKS)
def test_바뀌었거나_추적되지_않은_node_파일이나_node_e_또는_앞선_쓰기가_있으면_스크립트_반복은_계속_묻는다(home, l24, title, prefix):
    # given
    l24_change(l24, title)
    command = f"cd {l24} && " + prefix + NODE_LOOP
    # when
    result = j14_decision(home, command)
    # then
    assert result in ("ask", "deny"), (title, prefix, result)


# --- L2-5. a drop of the stash entry this command pushed under a tag and applied right before ----------------------------

STASH_PUSH = "git stash push -q -m h2tmp -- tests/a.py tests/b.py"
STASH_SHA = "$(git stash list --format='%H %gs' | grep h2tmp | cut -d' ' -f1)"
STASH_REF = "$(git stash list --format='%gd %gs' | grep h2tmp | cut -d' ' -f1)"
STASH_TEST = "python3 -m pytest -q tests/a.py"
STASH_RECORDED = (f"{STASH_PUSH}; {STASH_TEST}; S={STASH_SHA}; git stash apply -q $S && "
                  f"git stash drop -q \"{STASH_REF}\"")


def stash_decision(home, command):
    cwd = home / "project"
    grant_write(cwd)
    return decision(guard.handle(bash(command, cwd), "claude"))


@pytest.mark.parametrize("command", [
    STASH_RECORDED,
    f"{STASH_PUSH}; {STASH_TEST}; S={STASH_SHA}; git stash apply -q $S && git stash drop -q stash@{{0}}",
    f"{STASH_PUSH}; {STASH_TEST}; git stash apply -q stash@{{0}} && git stash drop -q stash@{{0}}",
    f"{STASH_PUSH}; git stash apply stash@{{0}} && git stash drop stash@{{0}}",
    f"{STASH_PUSH}; S={STASH_SHA}; git stash apply --quiet \"$S\" && git stash drop --quiet \"{STASH_REF}\"",
    f"{STASH_PUSH}; S={STASH_SHA}; git stash apply -q ${{S}} && git stash drop \"{STASH_REF}\"",
    f"{STASH_PUSH}; git stash apply -q \"{STASH_REF}\" && git stash drop -q \"{STASH_REF}\"",
    f"{STASH_PUSH}; {STASH_TEST}; git stash apply -q stash@{{0}} && git stash drop -q \"{STASH_REF}\"",
])
def test_같은_명령에서_태그로_만들고_적용한_스태시의_drop은_세션_쓰기로_묻지_않는다(home, command):
    # when
    result = stash_decision(home, command)
    # then
    assert result not in ("ask", "deny"), command


def test_태그_스태시_drop은_세션_쓰기_승인이_없으면_한_번_묻는다(home):
    # when
    result = decision(guard.handle(bash(STASH_RECORDED, home / "project"), "claude"))
    # then
    assert result == "ask"


STASH_OTHER_REF = STASH_REF.replace("h2tmp", "other")
STASH_OTHER_SHA = STASH_SHA.replace("h2tmp", "other")


@pytest.mark.parametrize("title, command", [
    ("drop without apply", f"{STASH_PUSH}; {STASH_TEST}; git stash drop -q \"{STASH_REF}\""),
    ("drop literal without apply", f"{STASH_PUSH}; git stash drop -q stash@{{0}}"),
    ("drop of another tag", f"{STASH_PUSH}; S={STASH_SHA}; git stash apply -q $S && git stash drop -q \"{STASH_OTHER_REF}\""),
    ("apply of another tag", f"{STASH_PUSH}; S={STASH_OTHER_SHA}; git stash apply -q $S && git stash drop -q \"{STASH_REF}\""),
    ("joined by semicolon", f"{STASH_PUSH}; S={STASH_SHA}; git stash apply -q $S; git stash drop -q \"{STASH_REF}\""),
    ("joined by or", f"{STASH_PUSH}; S={STASH_SHA}; git stash apply -q $S || git stash drop -q \"{STASH_REF}\""),
    ("apply behind or", f"{STASH_PUSH}; true || git stash apply -q stash@{{0}} && git stash drop -q stash@{{0}}"),
    ("apply in pipeline", f"{STASH_PUSH}; git stash apply -q stash@{{0}} | cat && git stash drop -q stash@{{0}}"),
    ("clear", f"{STASH_PUSH}; git stash apply -q stash@{{0}} && git stash clear"),
    ("not created here", f"S={STASH_SHA}; git stash apply -q $S && git stash drop -q \"{STASH_REF}\""),
    ("not created here literal", "git stash apply -q stash@{0} && git stash drop -q stash@{0}"),
    ("push behind or", f"false || {STASH_PUSH}; git stash apply -q stash@{{0}} && git stash drop -q stash@{{0}}"),
    ("push inside condition", f"if true; then {STASH_PUSH}; fi; git stash apply -q stash@{{0}} && git stash drop -q stash@{{0}}"),
    ("push without tag", "git stash push -q -- tests/a.py; git stash apply -q stash@{0} && git stash drop -q stash@{0}"),
    ("push with another tag", f"git stash push -q -m other; git stash apply -q stash@{{0}} && git stash drop -q \"{STASH_REF}\""),
    ("later push moves the top", f"{STASH_PUSH}; S={STASH_SHA}; git stash push -q -m other; git stash apply -q $S && "
     "git stash drop -q stash@{0}"),
    ("pop in between", f"{STASH_PUSH}; git stash pop -q; git stash apply -q stash@{{0}} && git stash drop -q stash@{{0}}"),
    ("drop in between", f"{STASH_PUSH}; git stash drop -q stash@{{1}}; git stash apply -q stash@{{0}} && git stash drop -q stash@{{0}}"),
    ("other index", f"{STASH_PUSH}; git stash apply -q stash@{{0}} && git stash drop -q stash@{{1}}"),
    ("directory change", f"{STASH_PUSH}; cd /home/test/other; git stash apply -q stash@{{0}} && git stash drop -q stash@{{0}}"),
    ("git dir variable", f"{STASH_PUSH}; export GIT_DIR=/home/test/other/.git; git stash apply -q stash@{{0}} && git stash drop -q stash@{{0}}"),
    ("git global option", f"{STASH_PUSH}; git stash apply -q stash@{{0}} && git -C /home/test/other stash drop -q stash@{{0}}"),
    ("second drop", f"{STASH_PUSH}; git stash apply -q stash@{{0}} && git stash drop -q stash@{{0}}; git stash drop -q stash@{{0}}"),
    ("tag by pattern", f"{STASH_PUSH}; S=$(git stash list --format='%H %gs' | grep h2 | cut -d' ' -f1); "
     f"git stash apply -q $S && git stash drop -q \"{STASH_REF}\""),
    ("different variable", f"{STASH_PUSH}; S={STASH_SHA}; T=abc; git stash apply -q $T && git stash drop -q \"{STASH_REF}\""),
    ("variable reassigned", f"{STASH_PUSH}; S={STASH_SHA}; S=abc; git stash apply -q $S && git stash drop -q \"{STASH_REF}\""),
    ("in a loop", f"{STASH_PUSH}; for i in 1 2; do git stash apply -q stash@{{0}} && git stash drop -q stash@{{0}}; done"),
])
def test_스태시를_이_명령이_만들고_적용하지_않았거나_다른_항목이면_drop은_계속_매번_묻는다(home, title, command):
    # when
    result = stash_decision(home, command)
    # then
    assert result in ("ask", "deny"), (title, command, result)
