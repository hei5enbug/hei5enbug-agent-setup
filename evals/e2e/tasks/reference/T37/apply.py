import sys

from patch_tools import append, replace, write

repo = sys.argv[1]

replace(repo, "notes_cli/storage.py", "import json\nfrom pathlib import Path\n", "import json\nfrom pathlib import Path\nfrom typing import Any\n")
replace(repo, "notes_cli/storage.py", "class MemoStore:\n",
        '''FORMAT_VERSION = 2


class ImportSourceMissing(Exception):
    """The file to import from does not exist."""


def read_entries(path: Path) -> list[dict[str, Any]]:
    """Memo records of a file in either format: the version 2 object or the plain list the previous version wrote."""
    raw = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(raw, dict):
        raw = raw.get("memos", [])
    if not isinstance(raw, list):
        raise ValueError(f"{path} does not hold a memo list")
    return raw


class MemoStore:
''')
replace(repo, "notes_cli/storage.py",
        '        raw = json.loads(self.path.read_text(encoding="utf-8"))\n        return sorted((memo_from_dict(entry) for entry in raw), key=lambda memo: memo.id)',
        '        return sorted((memo_from_dict(entry) for entry in read_entries(self.path)), key=lambda memo: memo.id)')
replace(repo, "notes_cli/storage.py", "    def get(self, memo_id: int) -> Memo:",
        '''    def import_file(self, source: str | Path) -> int:
        source = Path(source)
        if not source.is_file():
            raise ImportSourceMissing(str(source))
        memos = self.all()
        next_id = max((memo.id for memo in memos), default=0) + 1
        added = [replace_id(memo_from_dict(entry), next_id + offset) for offset, entry in enumerate(read_entries(source))]
        self._write([*memos, *added])
        return len(added)

    def get(self, memo_id: int) -> Memo:''')
replace(repo, "notes_cli/storage.py",
        '        payload = json.dumps([memo_to_dict(memo) for memo in memos], indent=2, ensure_ascii=False)',
        '        payload = json.dumps({"version": FORMAT_VERSION, "memos": [memo_to_dict(memo) for memo in memos]}, indent=2,\n                             ensure_ascii=False)')
replace(repo, "notes_cli/storage.py", "from .memo import Memo, make_memo, memo_from_dict, memo_to_dict\n",
        "from dataclasses import replace as replace_fields\n\nfrom .memo import Memo, make_memo, memo_from_dict, memo_to_dict\n")
append(repo, "notes_cli/storage.py", "\n\ndef replace_id(memo: Memo, memo_id: int) -> Memo:\n    return replace_fields(memo, id=memo_id)\n")

replace(repo, "notes_cli/cli.py", "from .storage import MemoNotFound, MemoStore", "from .storage import ImportSourceMissing, MemoNotFound, MemoStore")
replace(repo, "notes_cli/cli.py", "DEFAULT_STORE = \"memos.json\"\n", "DEFAULT_STORE = \"memos.json\"\nEXIT_IMPORT_SOURCE_MISSING = 3\n")
replace(repo, "notes_cli/cli.py", '    search = memo.add_parser("search", help="find memos containing text")',
        '    importing = memo.add_parser("import", help="append the memos of another memo file")\n    importing.add_argument("file")\n'
        '    search = memo.add_parser("search", help="find memos containing text")')
replace(repo, "notes_cli/cli.py", '    else:\n        found = store.search(args.query)',
        '    elif args.action == "import":\n        print(f"Imported {store.import_file(args.file)} memos", file=out)\n    else:\n        found = store.search(args.query)')
replace(repo, "notes_cli/cli.py", "    except (MemoNotFound, ValueError, SettingsError) as exc:",
        "    except ImportSourceMissing:\n        return EXIT_IMPORT_SOURCE_MISSING\n    except (MemoNotFound, ValueError, SettingsError) as exc:")

replace(repo, "README.md", "python3 -m notes_cli memo remove 1\n```", "python3 -m notes_cli memo remove 1\npython3 -m notes_cli memo import other-memos.json\n```")
replace(repo, "README.md", "- `memo remove ID` deletes a memo.\n",
        "- `memo remove ID` deletes a memo.\n- `memo import FILE` appends the memos of another memo file with new ids and prints `Imported N memos`. When FILE\n"
        "  does not exist it prints nothing and exits with 3.\n")
replace(repo, "README.md", "exits with 1.\n",
        "exits with 1. The memo file is `{\"version\": 2, \"memos\": [...]}`; a plain list written by the previous version is\nstill read.\n")
replace(repo, "docs/ko/README.ko.md", "python3 -m notes_cli memo remove 1\n```", "python3 -m notes_cli memo remove 1\npython3 -m notes_cli memo import other-memos.json\n```")
replace(repo, "docs/ko/README.ko.md", "- `memo remove ID`는 메모를 삭제합니다.\n",
        "- `memo remove ID`는 메모를 삭제합니다.\n- `memo import FILE`은 다른 메모 파일의 메모를 새 id로 덧붙이고 `Imported N memos`를 출력합니다. FILE이 없으면\n"
        "  아무것도 출력하지 않고 종료 코드 3으로 끝납니다.\n")
replace(repo, "docs/ko/README.ko.md", "종료 코드 1로 끝납니다.\n",
        "종료 코드 1로 끝납니다. 메모 파일은 `{\"version\": 2, \"memos\": [...]}` 형식이며, 이전 버전이 쓴 메모 리스트 파일도\n계속 읽습니다.\n")

write(repo, "tests/test_import.py", '''import io
import json

from notes_cli.cli import main
from notes_cli.settings import Settings


def run(*argv, store):
    out, err = io.StringIO(), io.StringIO()
    code = main(["--store", str(store), *argv], stdout=out, stderr=err, settings=Settings(page_size=3))
    return code, out.getvalue(), err.getvalue()


def test_import_appends_memos_with_new_ids(tmp_path):
    source, store = tmp_path / "in.json", tmp_path / "m.json"
    source.write_text(json.dumps([{"id": 7, "title": "seven"}]), encoding="utf-8")
    run("memo", "add", "first", store=store)
    assert run("memo", "import", str(source), store=store) == (0, "Imported 1 memos\\n", "")
    assert [(m["id"], m["title"]) for m in json.loads(store.read_text(encoding="utf-8"))["memos"]] == [(1, "first"), (2, "seven")]


def test_import_of_a_missing_file_exits_with_three_and_prints_nothing(tmp_path):
    assert run("memo", "import", str(tmp_path / "gone.json"), store=tmp_path / "m.json") == (3, "", "")


def test_a_list_file_from_the_previous_version_is_still_read(tmp_path):
    store = tmp_path / "m.json"
    store.write_text(json.dumps([{"id": 1, "title": "old"}]), encoding="utf-8")
    assert "old" in run("memo", "list", store=store)[1]
''')
