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
