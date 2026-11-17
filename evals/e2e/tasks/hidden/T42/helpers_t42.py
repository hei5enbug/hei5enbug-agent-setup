import io
import json

from notes_cli.cli import main
from notes_cli.settings import Settings


def run(*argv, store):
    out, err = io.StringIO(), io.StringIO()
    code = main(["--store", str(store), *argv], stdout=out, stderr=err, settings=Settings(page_size=5))
    return code, out.getvalue(), err.getvalue()


def entry(memo_id, title, body="", tags=(), created="2026-01-0%dT09:00:00+00:00"):
    return {"id": memo_id, "title": title, "body": body, "tags": list(tags), "created_at": created % memo_id}


def write_old(path, entries):
    path.write_text(json.dumps(entries, indent=2) + "\n", encoding="utf-8")


def write_new(path, entries):
    path.write_text(json.dumps({"version": 2, "memos": entries}, indent=2) + "\n", encoding="utf-8")


def stored_memos(path):
    raw = json.loads(path.read_text(encoding="utf-8"))
    return raw["memos"] if isinstance(raw, dict) else raw
