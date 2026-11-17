import json
import os
import subprocess
import sys
import time
from pathlib import Path

from handoff_tools import orca

repo = sys.argv[1]
hook = Path(__file__).resolve().parents[5] / "scripts" / "orca_status_hook.py"
work = Path(repo).parent
ENV = {**os.environ, "ORCA_TERMINAL_HANDLE": "term_demo_a", "FAKE_ORCA_STATE": str(work / "orca-state" / "state.json"),
       "PATH": f"{work / 'fake-bin'}:{os.environ['PATH']}"}


def fire(event, command=None):
    payload = {"hook_event_name": event, "session_id": "reference", "cwd": repo}
    if command:
        payload.update({"tool_name": "Bash", "tool_input": {"command": command}, "tool_response": {"stdout": ""}})
    subprocess.run([sys.executable, "-B", str(hook)], input=json.dumps(payload), env=ENV, text=True,
                   capture_output=True, check=True)


settings = Path(repo) / "config" / "settings.toml"
settings.write_text(settings.read_text(encoding="utf-8").replace("page_size = 20", "page_size = 50"), encoding="utf-8")
create = "orca worktree create --repo name:demo-b --name ABC-123 --branch feature/ABC-123 --json"
made = orca(repo, *create.split()[1:-1])["result"]["worktree"]
fire("PostToolUse", create)
start = f'orca orchestration worker-start --worktree id:{made["id"]} --agent claude --spec "prepare" --json'
orca(repo, "orchestration", "worker-start", "--worktree", f"id:{made['id']}", "--agent", "claude", "--spec", "prepare")
fire("PostToolUse", start)
fire("Stop")
state_home = Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local" / "state")
lock = state_home / "hei5enbug-agent-setup" / "orca-status" / "reference.cleanup.lock"
deadline = time.monotonic() + 60
while lock.exists() and time.monotonic() < deadline:
    time.sleep(0.2)
