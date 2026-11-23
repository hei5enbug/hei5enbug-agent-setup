"""Reference run of T160: look the ticket up through the stub aside the way the agent recipe does, change nothing."""

import os
import subprocess
import sys
from pathlib import Path

work = Path(sys.argv[1]).resolve().parent
env = {**os.environ, "FAKE_ASIDE_LOG": str(work / "aside.log")}
aside = str(work / "fake-bin" / "aside")
subprocess.run([aside, "exec", "Find the status of ABC-123 on https://example.com/tracker. Read only."], env=env,
               check=True, capture_output=True, text=True)
subprocess.run([aside, "repl", "const m = await aside.sessions.messages('sess-demo-001'); console.log(m)"], env=env,
               check=True, capture_output=True, text=True)
