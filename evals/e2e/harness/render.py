"""Headless render of one screen of a TSX fixture at several viewport widths, for layout checks and screenshots.

`bun build` bundles the screen with the fixture's own JSX runtime, and headless Chrome loads the bundle once per width
inside an iframe of exactly that width, so media queries see the real viewport. Chrome's headless window is never
narrower than 500 px, which is why the width is set on the iframe and not on the window. Each page posts its metrics to
the wrapper, which writes them into the DOM for `--dump-dom`; a second Chrome run per width writes the screenshot.
"""

from __future__ import annotations

import html
import json
import os
import re
import shutil
import signal
import subprocess
import tempfile
import time
from pathlib import Path, PurePosixPath
from typing import Any, Mapping, Sequence

try:
    from .process import GradingInterrupted, run_cleaning_tree
except ImportError:
    from process import GradingInterrupted, run_cleaning_tree  # type: ignore[no-redef]

BUN_ENV = "E2E_BUN_BIN"
CHROME_ENV = "E2E_CHROME_BIN"
CHROME_FALLBACKS = (
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
)
CHROME_NAMES = ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "chrome")
DEFAULT_WIDTHS = (1280, 375)
MIN_WINDOW_WIDTH = 500
MIN_SCREEN_HEIGHT = 400
MAX_SCREEN_HEIGHT = 6000
BUILD_TIMEOUT_SECONDS = 60
CHROME_TIMEOUT_SECONDS = 60
VIRTUAL_TIME_MS = 1500
CHROME_POLL_SECONDS = 0.1
OVERFLOW_TOLERANCE_PX = 1
RESULT_PATTERN = re.compile(r'<pre id="out">(.*?)</pre>', re.DOTALL)

MEASURE_SCRIPT = """
window.__errors = [];
window.addEventListener("error", function (e) { window.__errors.push(String(e.message)); });
window.addEventListener("load", function () { setTimeout(report, 50); });
function report() {
  var root = document.getElementById("root");
  var width = window.innerWidth;
  var boxes = {};
  root.querySelectorAll("[data-testid]").forEach(function (el) {
    var r = el.getBoundingClientRect();
    var id = el.getAttribute("data-testid");
    (boxes[id] = boxes[id] || []).push({
      left: r.left, top: r.top, right: r.right, bottom: r.bottom, width: r.width, height: r.height,
      text: (el.innerText || "").slice(0, 400)
    });
  });
  var wide = 0;
  root.querySelectorAll("*").forEach(function (el) {
    var r = el.getBoundingClientRect();
    if (r.width > 0 && r.right > width + %(tolerance)d) wide += 1;
  });
  parent.postMessage({
    type: "metrics", width: width, scrollWidth: document.documentElement.scrollWidth,
    scrollHeight: document.documentElement.scrollHeight, contentHeight: document.body.scrollHeight,
    overflowingElements: wide, boxes: boxes,
    text: (root.innerText || "").slice(0, 2000), errors: window.__errors
  }, "*");
}
""" % {"tolerance": OVERFLOW_TOLERANCE_PX}

WRAPPER_SCRIPT = """
var expected = %(widths)s, results = {};
window.addEventListener("message", function (e) {
  if (!e.data || e.data.type !== "metrics") return;
  results[String(e.data.width)] = e.data;
  if (Object.keys(results).length === expected.length) {
    document.getElementById("out").textContent = JSON.stringify(results);
  }
});
"""


class RenderUnavailable(RuntimeError):
    """bun or Chrome is missing, so no verdict is possible; a grader raising it records `grade_error` and `regrade` retries."""

    no_verdict = True


class RenderFailed(RuntimeError):
    """The screen cannot be bundled or Chrome returned no metrics; the cause is for the check's detail."""


def find_tool(env_name: str, names: Sequence[str], fallbacks: Sequence[str] = ()) -> str | None:
    configured = os.environ.get(env_name)
    if configured:
        return configured if Path(configured).is_file() else None
    for name in names:
        found = shutil.which(name)
        if found:
            return found
    return next((path for path in fallbacks if Path(path).is_file()), None)


def require_tools() -> tuple[str, str]:
    bun, chrome = find_tool(BUN_ENV, ("bun",)), find_tool(CHROME_ENV, CHROME_NAMES, CHROME_FALLBACKS)
    missing = [name for name, path in (("bun", bun), ("Chrome", chrome)) if not path]
    if missing:
        raise RenderUnavailable(f"{' and '.join(missing)} not found; set {BUN_ENV} or {CHROME_ENV} or install it")
    return str(bun), str(chrome)


def screen_slug(module: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "-", PurePosixPath(module).stem).strip("-").lower() or "screen"


def stylesheet_text(repo: Path) -> str:
    sheets = sorted((repo / "src").rglob("*.css")) if (repo / "src").is_dir() else []
    return "\n".join(sheet.read_text(encoding="utf-8", errors="replace") for sheet in sheets)


def write_build_files(repo: Path, module: str, build: Path) -> Path:
    runtime = repo / "src" / "mini" / "jsx-runtime.ts"
    if not (repo / module).is_file():
        raise RenderFailed(f"{module} does not exist")
    tsconfig = {"compilerOptions": {
        "jsx": "react-jsx", "jsxImportSource": "mini", "moduleResolution": "bundler", "module": "ESNext", "target": "ES2022",
        "baseUrl": str(repo), "paths": {"mini/jsx-runtime": [str(runtime)], "mini/jsx-dev-runtime": [str(runtime)]}}}
    (build / "tsconfig.json").write_text(json.dumps(tsconfig), encoding="utf-8")
    entry = build / "entry.tsx"
    entry.write_text(
        f'import Screen from {json.dumps(str(repo / module))};\n'
        'import { jsx } from "mini/jsx-runtime";\n'
        'document.getElementById("root")!.appendChild(jsx(Screen as never, {}));\n', encoding="utf-8")
    return entry


def bundle(bun: str, repo: Path, module: str, build: Path, interrupt: Any = None) -> Path:
    entry = write_build_files(repo, module, build)
    out = build / "bundle.js"
    command = [bun, "build", str(entry), "--target=browser", "--format=iife", f"--outfile={out}",
               f"--tsconfig-override={build / 'tsconfig.json'}"]
    try:
        done = run_cleaning_tree(command, cwd=build, timeout=BUILD_TIMEOUT_SECONDS, encoding="utf-8", errors="replace",
                                 interrupt=interrupt)
    except subprocess.TimeoutExpired as error:
        raise RenderFailed("bun build timed out") from error
    if done.returncode != 0 or not out.is_file():
        raise RenderFailed(f"bun build failed: {(done.stderr or done.stdout).strip()[:600]}")
    return out


def page_html(css: str) -> str:
    return ('<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, '
            f'initial-scale=1"><style>{css}</style><script>{MEASURE_SCRIPT}</script></head>'
            '<body><div id="root"></div><script src="bundle.js"></script></body></html>')


def wrapper_html(widths: Sequence[int], heights: Mapping[int, int] | None = None) -> str:
    frames = "".join(
        f'<iframe src="page.html" width="{width}" height="{(heights or {}).get(width, 900)}" '
        'style="display:block;border:0;background:#fff"></iframe>' for width in widths)
    script = WRAPPER_SCRIPT % {"widths": json.dumps(list(widths))}
    return (f'<!doctype html><html><body style="margin:0;background:#fff">{frames}<pre id="out"></pre>'
            f'<script>{script}</script></body></html>')


def chrome_command(chrome: str, profile: Path, *extra: str) -> list[str]:
    return [chrome, "--headless=new", "--disable-gpu", "--hide-scrollbars", "--no-first-run", "--no-default-browser-check",
            "--force-device-scale-factor=1", f"--user-data-dir={profile}", f"--virtual-time-budget={VIRTUAL_TIME_MS}", *extra]


def run_chrome(command: list[str], interrupt: Any = None) -> subprocess.CompletedProcess:
    """Run Chrome with its output in files, because its helper processes can keep a pipe open after the browser exits."""
    with tempfile.TemporaryDirectory(prefix="render-out-") as folder:
        out, err = Path(folder) / "stdout", Path(folder) / "stderr"
        with out.open("wb") as stdout, err.open("wb") as stderr:
            process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=stdout, stderr=stderr, start_new_session=True)
            deadline = time.monotonic() + CHROME_TIMEOUT_SECONDS
            timed_out = False
            try:
                while process.poll() is None:
                    if interrupt is not None and interrupt.is_set():
                        raise GradingInterrupted("grading stopped by a harness interrupt")
                    if time.monotonic() > deadline:
                        timed_out = True
                        break
                    time.sleep(CHROME_POLL_SECONDS)
            finally:
                end_group(process)
        if timed_out:
            raise RenderFailed("Chrome timed out")
        return subprocess.CompletedProcess(command, process.returncode, out.read_text(encoding="utf-8", errors="replace"),
                                           err.read_text(encoding="utf-8", errors="replace"))


def end_group(process: subprocess.Popen) -> None:
    """Kill Chrome and every helper it started in its own session."""
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass
    process.wait()


def measure(chrome: str, build: Path, widths: Sequence[int], interrupt: Any = None) -> dict[str, dict[str, Any]]:
    wrapper = build / "measure.html"
    wrapper.write_text(wrapper_html(widths), encoding="utf-8")
    with tempfile.TemporaryDirectory(prefix="render-profile-") as profile:
        done = run_chrome(chrome_command(chrome, Path(profile), "--dump-dom", wrapper.as_uri()), interrupt)
    found = RESULT_PATTERN.search(done.stdout or "")
    text = html.unescape(found.group(1)).strip() if found else ""
    if not text:
        raise RenderFailed(f"Chrome returned no layout metrics (exit {done.returncode}): {(done.stderr or '')[-300:].strip()}")
    return json.loads(text)


def screenshot(chrome: str, build: Path, width: int, height: int, target: Path, interrupt: Any = None) -> None:
    wrapper = build / f"shot-{width}.html"
    wrapper.write_text(wrapper_html([width], {width: height}), encoding="utf-8")
    window = f"{max(width, MIN_WINDOW_WIDTH)},{height}"
    with tempfile.TemporaryDirectory(prefix="render-profile-") as profile:
        run_chrome(chrome_command(chrome, Path(profile), f"--window-size={window}", f"--screenshot={target}", wrapper.as_uri()),
                   interrupt)
    if not target.is_file() or target.stat().st_size == 0:
        raise RenderFailed(f"Chrome wrote no screenshot for {width} px")


def render_component(repo: Path, module: str, out_dir: Path, widths: Sequence[int] = DEFAULT_WIDTHS,
                     interrupt: Any = None) -> dict[str, Any]:
    """Render `module` (a path in `repo`, its default export a screen) at each width.

    Returns `{"module", "widths": {"<w>": metrics + "screenshot"}, "error": None}`, or `"error"` set to the cause when the
    screen does not bundle or does not render. Missing tools raise RenderUnavailable."""
    bun, chrome = require_tools()
    repo, out_dir = Path(repo).resolve(), Path(out_dir).resolve()
    build = out_dir / "build" / screen_slug(module)
    shots = out_dir / "screens"
    for folder in (build, shots):
        folder.mkdir(parents=True, exist_ok=True)
    result: dict[str, Any] = {"module": module, "widths": {}, "error": None}
    try:
        bundle(bun, repo, module, build, interrupt)
        (build / "page.html").write_text(page_html(stylesheet_text(repo)), encoding="utf-8")
        metrics = measure(chrome, build, widths, interrupt)
        for width in widths:
            entry = metrics.get(str(width))
            if entry is None:
                raise RenderFailed(f"no metrics for width {width}")
            height = min(max(int(entry["contentHeight"]), MIN_SCREEN_HEIGHT), MAX_SCREEN_HEIGHT)
            target = shots / f"{screen_slug(module)}-{width}.png"
            screenshot(chrome, build, width, height, target, interrupt)
            result["widths"][str(width)] = {**entry, "screenshot": str(target)}
    except RenderFailed as error:
        result["error"] = str(error)
    return result
