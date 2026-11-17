# guard-kit

Small checks that a command-line agent runs before a tool call. Each check reads one command and returns a
decision: allow, ask, or deny.

| Module | What it does |
|---|---|
| `guardkit.targets` | Finds the paths a shell command writes to. |
| `guardkit.protect` | Denies a write into a protected folder. |
| `guardkit.hook` | Reads one hook payload from stdin and prints the decision as JSON. |
| `guardkit.boundary` | Finds fictional secret values in text and in a range of commits. |
| `guardkit.pushes` | Finds the refs a `git push` command sends. |

Run the tests with `python3 -m pytest -q`.
