import json
import sys
from pathlib import Path

repo = Path(sys.argv[1])
target = repo / "release-notes-workspace/iteration-1/changelog-basic/with_skill/grading.json"
expectations = [
    {"text": "The output starts with the heading `# Release notes 2.4.0`.", "passed": True,
     "evidence": "The first line of release-notes.md is '# Release notes 2.4.0'."},
    {"text": "The output lists at most 5 changes, one line each, as bullets.", "passed": True,
     "evidence": "release-notes.md has five one-line bullets."},
    {"text": "The output ends with an Upgrade steps section that names the removal of the --legacy flag.", "passed": False,
     "evidence": "The output ends with 'No upgrade steps.' and never names the removal of the --legacy flag as an upgrade step."},
]
summary = {"passed": 2, "failed": 1, "total": 3, "pass_rate": 0.67}
target.write_text(json.dumps({"expectations": expectations, "summary": summary}, indent=2) + "\n", encoding="utf-8")
