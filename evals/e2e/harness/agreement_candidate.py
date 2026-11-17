"""The candidate of the requirements agreement: rendered from templates and edits, built as git refs for measurement, and
written into the working tree only when the record adopts it.

`evals/e2e/candidates/agreement/` holds the rule file and the drafter agent as templates and every edit to a file that exists
today. Nothing there is part of the plugin, so the shipped files change only when `adopt` runs. A measurement builds one git ref
per drafter step from a base revision, and a variant names that ref. The drafter step of a host is `step1` (the main session
writes the draft), `step2` (`claude-opus-5-5` at `xhigh`), `step3-high`, or `step3-xhigh` (`claude-fable-5-2`).
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
import textwrap
from pathlib import Path
from typing import Any, Mapping, Protocol, Sequence

from .config import CAP_EXCEPTION_MODEL, E2E_ROOT, HOSTS

CANDIDATE_DIR = E2E_ROOT / "candidates" / "agreement"
REF_PREFIX = "refs/e2e/agreement-"
STEP1 = "step1"
AGENT_STEPS = {"step2": ("claude-opus-5-5", "xhigh"), "step3-high": (CAP_EXCEPTION_MODEL, "high"),
               "step3-xhigh": (CAP_EXCEPTION_MODEL, "xhigh")}
STEPS = (STEP1, *AGENT_STEPS)
INSTRUCTION = "instructions/requirements-agreement.md"
INSTRUCTION_KO = "docs/ko/instructions/requirements-agreement.ko.md"
AGENT = "agents/spec-drafter.md"
AGENT_KO = "docs/ko/agents/spec-drafter.ko.md"
PIN_TEST = "tests/test_spec_drafter_pin.py"
REGISTRY = "config/model-registry.json"
REVIEWER_ENTRY = '    "hei5enbug-agent-setup:reviewer": {"role": "reviewer", "model": "claude-opus-5-5", "effort": "high", "access": "read",'
HOST_NAMES = {"claude": ("Claude Code", "Claude Code에서는"), "codex": ("Codex", "Codex에서는")}
IDENTITY = {"GIT_AUTHOR_NAME": "Demo Dev", "GIT_AUTHOR_EMAIL": "dev@example.com", "GIT_COMMITTER_NAME": "Demo Dev",
            "GIT_COMMITTER_EMAIL": "dev@example.com", "GIT_AUTHOR_DATE": "2026-01-15T09:00:00+00:00",
            "GIT_COMMITTER_DATE": "2026-01-15T09:00:00+00:00"}


class CandidateError(ValueError):
    pass


class Source(Protocol):
    def read(self, path: str) -> str | None: ...

    def paths(self, prefix: str) -> list[str]: ...


class DiskSource:
    def __init__(self, root: Path):
        self.root = Path(root)

    def read(self, path: str) -> str | None:
        try:
            return (self.root / path).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return None

    def paths(self, prefix: str) -> list[str]:
        base = self.root / prefix
        return sorted(item.relative_to(self.root).as_posix() for item in base.rglob("*") if item.is_file()) if base.is_dir() else []


class GitSource:
    def __init__(self, repo_root: Path, ref: str):
        self.repo_root, self.ref = Path(repo_root), ref

    def read(self, path: str) -> str | None:
        done = subprocess.run(["git", "show", f"{self.ref}:{path}"], cwd=self.repo_root, capture_output=True)
        return done.stdout.decode("utf-8") if done.returncode == 0 else None

    def paths(self, prefix: str) -> list[str]:
        done = subprocess.run(["git", "ls-tree", "-r", "--name-only", self.ref, "--", prefix], cwd=self.repo_root,
                              capture_output=True, text=True, check=True)
        return sorted(done.stdout.splitlines())


def template(name: str) -> str:
    return (CANDIDATE_DIR / name).read_text(encoding="utf-8")


def load_edits() -> dict[str, Any]:
    return json.loads((CANDIDATE_DIR / "edits.json").read_text(encoding="utf-8"))


def validate_steps(steps: Mapping[str, str]) -> dict[str, str]:
    if set(steps) != set(HOSTS) or any(step not in STEPS for step in steps.values()):
        raise CandidateError(f"steps must name each of {', '.join(HOSTS)} with one of {', '.join(STEPS)}; got {dict(steps)}")
    return dict(steps)


def uses_agent(steps: Mapping[str, str]) -> bool:
    return any(step in AGENT_STEPS for step in steps.values())


def agent_of(steps: Mapping[str, str]) -> tuple[str, str] | None:
    """The drafter model and effort every agent step in `steps` names; two hosts with different agent steps cannot share one agent file."""
    found = {AGENT_STEPS[step] for step in steps.values() if step in AGENT_STEPS}
    if len(found) > 1:
        raise CandidateError(f"hosts registered different drafter agents {sorted(found)}; one agent file cannot hold both")
    return next(iter(found), None)


def drafter_text(steps: Mapping[str, str], language: str = "en") -> str:
    """The paragraph of the rule file that says who writes the draft on each host."""
    steps = validate_steps(steps)
    model, effort = agent_of(steps) or (None, None)

    def sentence(host: str) -> str:
        if language == "ko":
            if steps[host] == STEP1:
                return f"{HOST_NAMES[host][1]} 메인 세션이 초안을 쓴다."
            runner = ("플러그인 에이전트 `hei5enbug-agent-setup:spec-drafter`가" if host == "claude" else
                      f"`scripts/role_runner.py reviewer --model {model} --effort {effort}`가")
            return f"{HOST_NAMES[host][1]} 읽기 전용 `spec-drafter`({model}, {effort})가 초안을 쓴다. 실행은 {runner} 맡는다."
        if steps[host] == STEP1:
            return f"On {HOST_NAMES[host][0]}, the main session writes the draft."
        way = ("the plugin agent `hei5enbug-agent-setup:spec-drafter`" if host == "claude" else
               f"`scripts/role_runner.py reviewer --model {model} --effort {effort}`")
        return f"On {HOST_NAMES[host][0]}, a read-only `spec-drafter` on `{model}` at `{effort}` writes the draft, run as {way}."

    lines = [sentence(host) for host in HOSTS]
    if language == "ko":
        tail = ("드래프터는 요청, 근거 경로, 답을 받은 모든 결정이 들어간 현재 명세, 열린 결정만 받고 대화는 받지 않는다. 아무에게도 묻지 않고 "
                "아무것도 수정하지 않으며, 명세마다 한 번 초안을 쓰고 답이 선택한 방향을 바꿀 때만 다시 쓴다.")
    else:
        tail = ("The drafter receives only the request, the evidence paths, the current specification with every answered decision, "
                "and the open decisions, never the conversation. It asks no one, edits nothing, and drafts once per specification "
                "and again only when an answer changes the chosen direction.")
    return "\n".join(textwrap.fill(item, width=118) for item in [*lines, *([tail] if uses_agent(steps) else [])])


def agent_values(steps: Mapping[str, str]) -> dict[str, str]:
    """Placeholders of the agent group's edits: the model, the effort, and the key of the model in the registry's pins."""
    model, effort = agent_of(steps) or ("", "")
    return {"model": model, "effort": effort, "pin_key": model.rsplit("-", 2)[0]}


def fill(text: str, values: Mapping[str, str]) -> str:
    for key, value in values.items():
        text = text.replace("{{" + key + "}}", value)
    if "{{" in text:
        raise CandidateError("a template placeholder is left unfilled")
    return text


def exact_edit(path: str, text: str, old: str, new: str) -> str:
    if text.count(old) != 1:
        raise CandidateError(f"{path}: expected exactly one match for {old[:60]!r}, found {text.count(old)}")
    return text.replace(old, new)


def registry_entry(model: str, effort: str) -> str:
    return (f'    "hei5enbug-agent-setup:spec-drafter": {{"role": "spec-drafter", "model": "{model}", "effort": "{effort}", "access": "read", '
            '"fallback": {"model": "gpt-6.1-sol", "effort": "high", "max_effort": "xhigh", "via": "runner"}}')


def pin_test_text(model: str, effort: str) -> str:
    return fill(template("spec_drafter_pin_test.py.tmpl"), {"model": model, "effort": effort})


def new_files(steps: Mapping[str, str]) -> dict[str, str]:
    """The files the candidate adds: the rule file with its mirror, and for an agent step the agent, its mirror, and its pin test."""
    agent = agent_of(steps)
    files = {
        INSTRUCTION: fill(template("requirements-agreement.md.tmpl"), {"drafter": drafter_text(steps)}),
        INSTRUCTION_KO: fill(template("requirements-agreement.ko.md.tmpl"), {"drafter": drafter_text(steps, "ko")}),
    }
    if agent:
        values = {"model": agent[0], "effort": agent[1]}
        files |= {AGENT: fill(template("spec-drafter.md.tmpl"), values), AGENT_KO: fill(template("spec-drafter.ko.md.tmpl"), values),
                  PIN_TEST: pin_test_text(*agent)}
    return files


def candidate_changes(source: Source, steps: Mapping[str, str], retire: bool = False) -> dict[str, str | None]:
    """Every path the candidate writes, with its new text, or None for a deleted file. `retire` also removes the interview
    skill and every reference to it, which happens only on adoption."""
    steps = validate_steps(steps)
    groups = {"rules", *(["agent"] if uses_agent(steps) else []), *(["retire"] if retire else [])}
    changes: dict[str, str | None] = dict(new_files(steps))
    spec = load_edits()
    for edit in spec["edits"]:
        if edit["group"] not in groups:
            continue
        current = changes.get(edit["path"]) if edit["path"] in changes else source.read(edit["path"])
        if current is None:
            raise CandidateError(f"{edit['path']} does not exist in the base revision")
        replacement = fill(edit["new"], agent_values(steps)) if "{{" in edit["new"] else edit["new"]
        changes[edit["path"]] = exact_edit(edit["path"], current, edit["old"], replacement)
    agent = agent_of(steps)
    if agent:
        text = changes.get(REGISTRY) if REGISTRY in changes else source.read(REGISTRY)
        if text is None:
            raise CandidateError(f"{REGISTRY} does not exist in the base revision")
        start = text.index(REVIEWER_ENTRY) if REVIEWER_ENTRY in text else -1
        if start < 0:
            raise CandidateError("the reviewer entry of claude_agents is not where the candidate expects it")
        end = text.index("\n", start)
        changes[REGISTRY] = text[:end] + ",\n" + registry_entry(*agent) + text[end:]
    if retire:
        for prefix in spec["retire_paths"]:
            changes |= {path: None for path in source.paths(prefix)}
    return changes


def git(repo_root: Path, *args: str, env: Mapping[str, str] | None = None, stdin: bytes | None = None) -> str:
    done = subprocess.run(["git", *args], cwd=repo_root, input=stdin, capture_output=True, check=False,
                          env={**os.environ, **(env or {})})
    if done.returncode != 0:
        raise CandidateError(f"git {' '.join(args)} failed: {done.stderr.decode(errors='replace').strip()}")
    return done.stdout.decode()


def commit_ref(repo_root: Path, base_ref: str, name: str, steps: Mapping[str, str]) -> str:
    """Write one commit on top of `base_ref` that holds the candidate for `steps`, point `refs/e2e/agreement-<name>` at it, and
    return its sha. The working tree and the index of the repository are not touched. The commit is a measurement input only."""
    changes = candidate_changes(GitSource(repo_root, base_ref), steps)
    with tempfile.TemporaryDirectory() as folder:
        env = {"GIT_INDEX_FILE": str(Path(folder) / "index"), **IDENTITY}
        git(repo_root, "read-tree", base_ref, env=env)
        for path, text in sorted(changes.items()):
            if text is None:
                git(repo_root, "update-index", "--force-remove", path, env=env)
                continue
            blob = git(repo_root, "hash-object", "-w", "--stdin", stdin=text.encode("utf-8")).strip()
            git(repo_root, "update-index", "--add", "--cacheinfo", f"100644,{blob},{path}", env=env)
        tree = git(repo_root, "write-tree", env=env).strip()
    parent = git(repo_root, "rev-parse", "--verify", f"{base_ref}^{{commit}}").strip()
    commit = git(repo_root, "commit-tree", tree, "-p", parent, "-m", f"candidate: requirements agreement, {name}", env=IDENTITY).strip()
    git(repo_root, "update-ref", f"{REF_PREFIX}{name}", commit)
    return commit


def build_refs(repo_root: Path, base_ref: str, names: Sequence[str] = STEPS) -> dict[str, str]:
    """One candidate ref per drafter step, the same step on both hosts, from one base revision."""
    return {name: commit_ref(repo_root, base_ref, name, {host: name for host in HOSTS}) for name in names}


def write_changes(root: Path, changes: Mapping[str, str | None]) -> list[str]:
    """Apply `candidate_changes` to a working tree: write each new text and delete each removed file. Returns the paths touched."""
    for path, text in sorted(changes.items()):
        target = Path(root) / path
        if text is None:
            target.unlink(missing_ok=True)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    for prefix in load_edits()["retire_paths"]:
        for folder in sorted(Path(root, prefix).rglob("*"), reverse=True) if Path(root, prefix).is_dir() else []:
            if folder.is_dir() and not any(folder.iterdir()):
                folder.rmdir()
        if Path(root, prefix).is_dir() and not any(Path(root, prefix).iterdir()):
            Path(root, prefix).rmdir()
    return sorted(changes)


def adopt(root: Path, steps: Mapping[str, str]) -> list[str]:
    """Write the adopted candidate, with the interview skill retired, into the working tree of `root`."""
    return write_changes(root, candidate_changes(DiskSource(root), steps, retire=True))
