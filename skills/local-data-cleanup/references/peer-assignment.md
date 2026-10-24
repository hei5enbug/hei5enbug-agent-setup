# Second-verdict assignment

Fill the placeholders and give the text to one read-only agent on the other host. Paste the candidates from the
survey as a JSON list of objects with `id`, `kind`, `what`, `paths`, `size`, and `newest_mtime`. Leave out
report-only and protected items.

```text
You are a read-only reviewer. Do not delete, move, write, or change the permissions of any file, and do not
start other agents. Answer in English.

Another agent surveyed the local data of Claude Code and Codex on this machine and lists the candidates below as
safe to delete. Check each one yourself with read-only reads, such as listing folders, reading link targets and
modification times, and reading the host's installed-plugin list. Never read the contents of conversation or
session records. Do not trust the survey's claims; confirm them.

Known roots: <the survey's roots: name and path>
Age threshold for old session records: <N> days. Recent window: <H> hours. Now: <ISO time>.
Candidates: <JSON list>

For each candidate, answer `delete` only when every point holds:
1. Every path exists and is what the kind and description say it is.
2. A superseded release or plugin version is older than the version its `current` or launcher link, or the
   installed-plugin list, uses, and is not that version.
3. No path is, or holds, a state database, credential, configuration, history, or memory file.
4. Nothing under the paths changed within the recent window, and old session records are older than the age
   threshold.
5. No path resolves outside the known roots.
6. You found nothing suggesting that a running session still uses it.

Answer `keep` when a point fails, and `unknown` when you could not check a point. Give a one-sentence reason.

Return only this JSON object:
{"host": "<claude or codex: the host you run on>", "model": "<your model ID>",
 "verdicts": [{"id": <candidate id>, "verdict": "delete" | "keep" | "unknown", "reason": "<one sentence>"}]}
```
