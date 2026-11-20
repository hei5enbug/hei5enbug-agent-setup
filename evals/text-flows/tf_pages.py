#!/usr/bin/env python3
"""Text flow comparison: collect the texts of each flow, summarize the form checks and the cost, and write the blind ranking pages.

  python3 evals/text-flows/tf_pages.py --run-root <root> --campaign <name> --flows F1=f1:claude,F3=f3:codex --out <folder>

The pages carry neutral labels (A, B, ...) in an order that differs per text kind and is fixed by the seed; `key.json` in the
same folder names the flow of each label and is never linked from a page. `summary.json` holds the form checks, cost, and wall
time per flow and text kind. No model is called."""

from __future__ import annotations

import argparse
import html
import json
import random
import re
import sys
from pathlib import Path
from typing import Any

KINDS = {"T13": ("PR description", "out/pr-description.txt"), "T15": ("Issue body", "out/issue-body.txt"), "T20": ("Final report", None)}
MODEL_REVIEW_CHECKS = ("text-review-clean", "ran-text-review")
DEFAULT_SEED = "text-flows-2026-11"


def run_dir(root: Path, campaign: str, task: str, variant: str, host: str) -> Path:
    base = root / campaign / "results" / task / variant
    return (base / "codex" if host == "codex" else base) / "rep1"


def work_repo(root: Path, campaign: str, task: str, variant: str, host: str) -> Path:
    suffix = f"{variant}-codex-r1" if host == "codex" else f"{variant}-r1"
    return root / campaign / "work" / f"{task}-{suffix}" / "repo"


def read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def text_of(root: Path, campaign: str, task: str, variant: str, host: str) -> str | None:
    relative = KINDS[task][1]
    if relative is None:
        view = read_json(run_dir(root, campaign, task, variant, host) / "view.json") or {}
        text = str(view.get("final_answer", "")).strip()
    else:
        path = work_repo(root, campaign, task, variant, host) / relative
        text = path.read_text(encoding="utf-8").strip() if path.is_file() else ""
    return text or None


def form_summary(root: Path, campaign: str, task: str, variant: str, host: str) -> dict[str, Any]:
    """Form checks: every required check of the task except the two that call the model reviewer. The model review result is kept
    beside it for reference and never decides."""
    directory = run_dir(root, campaign, task, variant, host)
    grade = read_json(directory / "grade" / "grade.json") or {}
    metrics = read_json(directory / "metrics.json") or {}
    checks = grade.get("checks") or []
    form = [item for item in checks if item.get("required") and item["id"] not in MODEL_REVIEW_CHECKS]
    cost = metrics.get("cost") or {}
    spent = sum(float(cost.get(key) or 0) for key in ("claude_list_cost_usd", "claude_runner_list_cost_usd", "codex_list_cost_usd_estimate"))
    review = next((item for item in checks if item["id"] == "text-review-clean"), None)
    return {
        "form_pass": bool(form) and all(item.get("passed") for item in form), "form_failed": [item["id"] for item in form if not item.get("passed")],
        "model_review_clean": None if review is None else bool(review.get("passed")), "status": metrics.get("status"),
        "cost_usd": round(spent, 4), "wall_seconds": metrics.get("wall_seconds"),
    }


def parse_flows(value: str) -> dict[str, tuple[str, str]]:
    flows = {}
    for item in value.split(","):
        name, _, rest = item.partition("=")
        variant, _, host = rest.partition(":")
        if not name or not variant or host not in ("claude", "codex"):
            raise ValueError(f"flow must look like F1=<variant>:<claude|codex>, got {item!r}")
        flows[name] = (variant, host)
    return flows


def labels_for(task: str, flows: list[str], seed: str) -> dict[str, str]:
    rng = random.Random(f"{seed}-{task}")
    order = sorted(flows)
    rng.shuffle(order)
    return {chr(ord("A") + index): flow for index, flow in enumerate(order)}


MARKED_URL = "https://cdn.jsdelivr.net/npm/marked@12.0.2/marked.min.js"
MARKED_SRI = "sha384-/TQbtLCAerC3jgaim+N78RZSDYV7ryeoBCVqTuzRrFec2akfBkHS7ACQ3PQhvMVi"

PAGE = r"""<!doctype html>
<html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>@@TITLE@@ ranking</title>
<style>
:root { --bg:#fff; --fg:#1b1b1f; --card:#f4f4f6; --line:#d5d5dc; --code:#e8e8ee; --link:#1a56c4; }
@media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) { --bg:#16161a; --fg:#ececf1; --card:#202026; --line:#3a3a44; --code:#2c2c34; --link:#8ab4ff; } }
:root[data-theme="dark"] { --bg:#16161a; --fg:#ececf1; --card:#202026; --line:#3a3a44; --code:#2c2c34; --link:#8ab4ff; }
body { background:var(--bg); color:var(--fg); font:16px/1.6 system-ui, sans-serif; margin:0 auto; padding:16px; max-width:860px; overflow-wrap:anywhere; }
section { background:var(--card); border:1px solid var(--line); border-radius:8px; padding:12px 16px; margin:16px 0; }
.md > :first-child { margin-top:0; } .md > :last-child { margin-bottom:0; }
.md a { color:var(--link); } .md img { max-width:100%; }
.md pre { white-space:pre-wrap; word-break:break-word; overflow-x:auto; margin:0; font:inherit; }
.md pre code { background:none; padding:0; }
.md code { background:var(--code); padding:0 4px; border-radius:4px; font-size:.92em; }
.md pre:not(.plain) { background:var(--code); padding:8px 12px; border-radius:6px; font:.92em/1.5 ui-monospace, monospace; }
.md table { border-collapse:collapse; display:block; overflow-x:auto; max-width:100%; }
.md th, .md td { border:1px solid var(--line); padding:4px 8px; }
.md blockquote { margin:8px 0; padding-left:12px; border-left:3px solid var(--line); }
label { font-weight:600; } select, button { font:inherit; padding:4px 8px; }
output { display:block; margin-top:8px; white-space:pre-wrap; user-select:all; }
</style></head><body>
<h1>@@TITLE@@</h1>
<p>Rank the texts from best to worst for the reader. Equal texts may share a rank. Nothing on this page names how a text was made.</p>
@@SECTIONS@@
<button type="button" onclick="done()">Show my answer</button>
<output id="out"></output>
<script src="@@MARKED_URL@@" integrity="@@MARKED_SRI@@" crossorigin="anonymous"></script>
<script>
function escapeHtml(text) {
  return text.replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}
function renderTexts() {
  if (!window.marked) return;
  marked.use({ gfm: true, breaks: true, renderer: { html: escapeHtml } });
  document.querySelectorAll('section.text').forEach(section => {
    const raw = section.querySelector('script[type="text/markdown"]').textContent.replace(/<\\\/script/gi, '</script').replace(/<\\!--/g, '<!--');
    try { section.querySelector('.md').innerHTML = marked.parse(raw); } catch (error) { /* the plain text stays */ }
  });
}
function done() {
  const rows = [...document.querySelectorAll('select')].map(s => s.dataset.label + '=' + s.value);
  document.getElementById('out').textContent = '@@TASK@@ ' + rows.join(' ');
}
renderTexts();
</script>
</body></html>
"""
SECTION = """<section class="text"><h2>Text @@LABEL@@</h2><div class="md"><pre class="plain">@@PLAIN@@</pre></div><script type="text/markdown">@@RAW@@</script>
<p><label>Rank of @@LABEL@@ <select data-label="@@LABEL@@">@@OPTIONS@@</select></label></p></section>"""


def fill(template: str, values: dict[str, str]) -> str:
    for name, value in values.items():
        template = template.replace(f"@@{name}@@", value)
    return template


def protect_raw(text: str) -> str:
    """Keep the Markdown source intact inside a script block: the page script restores these two sequences."""
    return re.sub(r"</script", r"<\\/script", re.sub(r"<!--", r"<\\!--", text), flags=re.IGNORECASE)


def page(task: str, texts: dict[str, str]) -> str:
    options = "".join(f"<option>{rank}</option>" for rank in range(1, len(texts) + 1))
    sections = "\n".join(
        fill(SECTION, {"LABEL": label, "PLAIN": html.escape(text), "RAW": protect_raw(text), "OPTIONS": options})
        for label, text in sorted(texts.items()))
    return fill(PAGE, {"TITLE": KINDS[task][0], "TASK": task, "SECTIONS": sections, "MARKED_URL": MARKED_URL, "MARKED_SRI": MARKED_SRI})


def build(root: Path, campaign: str, flows: dict[str, tuple[str, str]], out: Path, seed: str = DEFAULT_SEED) -> dict[str, Any]:
    out.mkdir(parents=True, exist_ok=True)
    key: dict[str, dict[str, str]] = {}
    summary: dict[str, dict[str, Any]] = {}
    for task in KINDS:
        texts = {flow: text_of(root, campaign, task, *flows[flow]) for flow in flows}
        summary[task] = {flow: form_summary(root, campaign, task, *flows[flow]) for flow in flows}
        present = [flow for flow, text in texts.items() if text]
        if len(present) < 2:
            continue
        labels = labels_for(task, present, seed)
        key[task] = labels
        (out / f"{task.lower()}-ranking.html").write_text(page(task, {label: texts[flow] for label, flow in labels.items()}), encoding="utf-8")
    (out / "key.json").write_text(json.dumps(key, indent=1) + "\n", encoding="utf-8")
    (out / "summary.json").write_text(json.dumps(summary, indent=1) + "\n", encoding="utf-8")
    return {"pages": sorted(path.name for path in out.glob("*-ranking.html")), "key": "key.json", "summary": "summary.json"}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--run-root", required=True, type=Path)
    parser.add_argument("--campaign", required=True)
    parser.add_argument("--flows", required=True, help="F1=<variant>:<claude|codex>,...")
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--seed", default=DEFAULT_SEED)
    args = parser.parse_args(argv)
    print(json.dumps(build(args.run_root, args.campaign, parse_flows(args.flows), args.out, args.seed)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
