"""Which drafter step each host registers for the requirements agreement, whether the agreement is adopted, and what the
repository must hold for that result.

Steps run from the cheapest up, per host. Step 1 is the main session as drafter, step 2 a read-only agent on
`claude-opus-5-5` at `xhigh`, step 3 the same agent on `claude-fable-5-2` at `high`, and at `xhigh` only when `high` does not
pass. A step that runs on a host runs cases A to D twice there and passes when each of them passes both runs and cases E to G
passed both of their runs on that host with step 1; a pass of A to D under another step never counts for it. A host where
E, F, or G fails a run registers nothing. The first step that passes is registered for the host. The agreement is adopted
when both hosts registered a step, and not adopted when a host can register none.

A record holds only counted runs: a run that ended on a harness or infrastructure error, with no verdict from its checks,
is run again and is not in it. The pass condition of cases A to D for the `claude-fable-5-2` step is the owner's to set, so
`decide` takes it as an argument; the default is the condition of every other step.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from .agreement_candidate import AGENT, AGENT_STEPS, INSTRUCTION, PIN_TEST, REGISTRY, STEP1, STEPS, load_edits
from .config import HOSTS

ABCD = ("A", "B", "C", "D")
EFG = ("E", "F", "G")
CASES = (*ABCD, *EFG)
RUNS_REQUIRED = 2
REGISTERED, NO_REGISTRATION, PENDING = "registered", "no registration", "pending"
ADOPTED, NOT_ADOPTED, UNDECIDED = "adopted", "not adopted", "undecided"
STEP_ORDER = (STEP1, "step2", "step3-high", "step3-xhigh")
EFFORTS = frozenset({"low", "medium", "high", "xhigh", "max"})
Runs = Mapping[str, Sequence[bool]]
Rule = Callable[[Runs], bool]


def both_runs(runs: Sequence[bool] | None) -> bool | None:
    """True when the first two counted runs both passed, False when either failed, None when fewer than two are counted."""
    if runs is None or len(runs) < RUNS_REQUIRED:
        return None
    return all(runs[:RUNS_REQUIRED])


def default_rule(runs: Runs) -> bool:
    """Every case A to D passes both of its runs."""
    return all(both_runs(runs.get(case)) is True for case in ABCD)


def condition_state(runs: Runs, cases: Sequence[str]) -> str:
    """`complete` when every case has two counted runs, `failed` when a case has a failed run among those it has, else `incomplete`."""
    held = [both_runs(runs.get(case)) for case in cases]
    if any(item is False for item in held):
        return "failed"
    return "complete" if all(item is True for item in held) else "incomplete"


def decide_host(steps: Mapping[str, Mapping[str, Runs]], host: str, fable_rule: Rule | None = None) -> dict[str, Any]:
    """The result for one host: `registered` with its step, `no registration` with the reason, or `pending` with what is missing.

    `steps` maps each step to its runs per host and case, each case a list of counted run results in order."""
    first = steps.get(STEP1, {}).get(host, {})
    gate = condition_state(first, EFG)
    if gate == "failed":
        failing = next(case for case in EFG if both_runs(first.get(case)) is False)
        return {"host": host, "status": NO_REGISTRATION, "step": None, "reason": f"case {failing} fails a run, so no step is registered"}
    if gate == "incomplete":
        return {"host": host, "status": PENDING, "step": None, "reason": "cases E to G have not both passed twice with step 1"}
    for step in STEP_ORDER:
        runs = steps.get(step, {}).get(host)
        if runs is None:
            return {"host": host, "status": PENDING, "step": None, "reason": f"{step} has not run"}
        if step.startswith("step3") and fable_rule is not None:
            passed, state = fable_rule(runs), "complete" if fable_rule(runs) else "failed"
        else:
            state = condition_state(runs, ABCD)
            passed = state == "complete"
        if state == "incomplete":
            return {"host": host, "status": PENDING, "step": None, "reason": f"{step} lacks two counted runs of a case A to D"}
        if passed:
            return {"host": host, "status": REGISTERED, "step": step, "reason": f"{step} passes cases A to D and E to G"}
    return {"host": host, "status": NO_REGISTRATION, "step": None, "reason": "no step passes"}


def decide(steps: Mapping[str, Mapping[str, Runs]], fable_rule: Rule | None = None) -> dict[str, Any]:
    """The registered step per host and the adoption state. The agreement is adopted when both hosts registered a step, not adopted
    when a host registered none for good, and undecided while a host still waits on runs."""
    hosts = {host: decide_host(steps, host, fable_rule) for host in HOSTS}
    registered = {host: item["step"] for host, item in hosts.items()}
    if all(item["status"] == REGISTERED for item in hosts.values()):
        state = ADOPTED
    elif any(item["status"] == NO_REGISTRATION for item in hosts.values()):
        state = NOT_ADOPTED
    else:
        state = UNDECIDED
    drafters = {host: {"model": AGENT_STEPS[step][0], "effort": AGENT_STEPS[step][1]}
                for host, step in registered.items() if step in AGENT_STEPS}
    return {"hosts": hosts, "registered": registered, "state": state, "drafters": drafters}


def agreement_problems(section: Any, fable_rule: Rule | None = None) -> list[str]:
    """Problems of the `agreement` section of a record: its shape, the models and efforts it names, and whether the registered
    step and the state it states are the ones its runs decide."""
    if not isinstance(section, Mapping):
        return ["agreement is not an object"]
    problems = [f"agreement lacks {field}" for field in ("steps", "registered", "state") if field not in section]
    steps = section.get("steps")
    if not isinstance(steps, Mapping) or not steps:
        return [*problems, "agreement steps is not a non-empty object"]
    for step, hosts in steps.items():
        if step not in STEPS or not isinstance(hosts, Mapping) or set(hosts) - set(HOSTS):
            problems.append(f"agreement step {step} is not a known step with per-host runs")
            continue
        for host, runs in hosts.items():
            allowed = CASES if step == STEP1 else ABCD
            bad = [case for case, results in (runs.items() if isinstance(runs, Mapping) else [("", None)])
                   if case not in allowed or not (isinstance(results, list) and results and all(isinstance(r, bool) for r in results))]
            if bad:
                problems.append(f"agreement step {step} on {host} holds an unknown case or a run list that is not pass or fail: {bad}")
    drafters = section.get("drafters", {})
    for step, hosts in (drafters.items() if isinstance(drafters, Mapping) else []):
        for host, entry in (hosts.items() if isinstance(hosts, Mapping) else []):
            expected = AGENT_STEPS.get(step)
            if expected is None or not isinstance(entry, Mapping) or entry.get("model") != expected[0] or entry.get("effort") not in {
                    expected[1], "not measured"}:
                problems.append(f"agreement drafter of {step} on {host} does not name {expected}")
    if problems:
        return problems
    decided = decide(steps, fable_rule)
    if section["registered"] != decided["registered"]:
        problems.append(f"agreement registered {section['registered']} but its runs decide {decided['registered']}")
    if section["state"] != decided["state"]:
        problems.append(f"agreement state {section['state']} but its runs decide {decided['state']}")
    return problems


def expected_state(section: Mapping[str, Any] | None) -> dict[str, bool]:
    """What the repository must hold: the rules and the interview skill's retirement exactly when the agreement is adopted, and the
    agent exactly when it is adopted and a host registered step 2 or 3. No record leaves everything as it is today."""
    if not section:
        return {"rules": False, "agent": False, "retired": False}
    adopted = section.get("state") == ADOPTED
    return {"rules": adopted, "agent": adopted and any(step in AGENT_STEPS for step in section["registered"].values()),
            "retired": adopted}


RULE_MARKERS = (
    ("implementation-execution.md", "the condition for reading the rule file in task preparation", "requirements-agreement.md"),
    ("implementation-execution.md", "the first sentence of the existing-mechanism rule", "state that evidence and ask which to use before the first change"),
    ("implementation-execution.md", "the second sentence of the existing-mechanism rule", "decide every other implementation choice and state it with its basis"),
    ("implementation-execution.md", "the stated-reading rule", "write that reading in one line before the first change"),
    ("session/common.md", "the exception in planning and design routing", "requirements-agreement.md"),
    ("../skills/skill-issue-creator/SKILL.md", "the link to the objection rules in skill-issue-creator", "requirements-agreement.md#objections-and-replies"),
)
OBJECTION_HEADING = "## Objections and replies"
INTERVIEW = "deep" + "-interview"
REFERENCE_SCAN_SKIPS = ("evals/e2e/candidates/agreement/edits.json", ".git/")


def read(root: Path, path: str) -> str:
    try:
        return (Path(root) / path).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return ""


def interview_references(root: Path) -> list[str]:
    """Every file under `root` that names the interview skill, apart from the candidate's own edit list."""
    found = []
    for path in sorted(Path(root).rglob("*")):
        relative = path.relative_to(root).as_posix()
        if not path.is_file() or any(relative.startswith(skip) or skip in relative for skip in REFERENCE_SCAN_SKIPS) or "__pycache__" in relative:
            continue
        try:
            if INTERVIEW in path.read_text(encoding="utf-8"):
                found.append(relative)
        except (OSError, UnicodeDecodeError):
            continue
    return found


def repository_state(root: Path) -> dict[str, Any]:
    """What `root` holds: per part of the rules whether it is present, whether the agent with its registry entry and pin test is
    present, and the interview skill's folder and references."""
    flat = lambda text: " ".join(text.split())  # noqa: E731
    rules = {f"{label} ({path.split('/')[-1]})": needle in flat(read(root / "instructions", path)) for path, label, needle in RULE_MARKERS}
    rules["the rule file with the objections heading"] = OBJECTION_HEADING in read(root, INSTRUCTION)
    entry_lines = [line for line in read(root, "instructions/session/common.md").splitlines()
                   if line.startswith("- Before") and "requirements-agreement" in line]
    agent = {"agent file": (Path(root) / AGENT).is_file(), "registry entry": "hei5enbug-agent-setup:spec-drafter" in read(root, REGISTRY),
             "pin test": (Path(root) / PIN_TEST).is_file()}
    return {"rules": rules, "entry_lines": entry_lines, "agent": agent,
            "skill_folder": (Path(root) / "skills" / INTERVIEW).exists(), "references": interview_references(root)}


def repository_problems(root: Path, expected: Mapping[str, bool]) -> list[str]:
    """Differences between `root` and the expected state: a part present when it should be absent, or absent when it should be present."""
    state, problems = repository_state(root), []
    for name, present in state["rules"].items():
        if present != expected["rules"]:
            problems.append(f"{name} is {'present' if present else 'absent'}, expected {'present' if expected['rules'] else 'absent'}")
    if state["entry_lines"]:
        problems.append("common.md holds a new entry line for the requirements agreement: " + "; ".join(state["entry_lines"]))
    for name, present in state["agent"].items():
        if present != expected["agent"]:
            problems.append(f"{name} is {'present' if present else 'absent'}, expected {'present' if expected['agent'] else 'absent'}")
    if state["skill_folder"] == expected["retired"]:
        problems.append(f"the interview skill folder is {'present' if state['skill_folder'] else 'absent'}, expected the opposite")
    if expected["retired"] and state["references"]:
        problems.append(f"files still name the interview skill: {state['references'][:5]}")
    if not expected["retired"] and not state["references"]:
        problems.append("no file names the interview skill, but it is not retired")
    return problems


def adoption_tree_paths() -> list[str]:
    """The paths a candidate touches or deletes, so a test can copy just those into a scratch tree."""
    edits = load_edits()
    return sorted({edit["path"] for edit in edits["edits"]} | {"config/model-registry.json"})
