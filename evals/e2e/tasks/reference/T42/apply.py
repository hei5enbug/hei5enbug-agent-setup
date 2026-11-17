import sys

from patch_tools import replace

repo = sys.argv[1]
replace(repo, "notes_cli/storage.py", "import json\nfrom pathlib import Path\n",
        "import json\nfrom dataclasses import replace\nfrom pathlib import Path\n")
replace(repo, "notes_cli/storage.py", "class MemoStore:\n", '''class ImportFileMissing(Exception):
    """The file named for an import does not exist."""


STORE_VERSION = 2


def read_memos(path: Path) -> list[Memo]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    entries = raw["memos"] if isinstance(raw, dict) else raw
    return sorted((memo_from_dict(entry) for entry in entries), key=lambda memo: memo.id)


class MemoStore:
''')
replace(repo, "notes_cli/storage.py", '''        raw = json.loads(self.path.read_text(encoding="utf-8"))
        return sorted((memo_from_dict(entry) for entry in raw), key=lambda memo: memo.id)
''', "        return read_memos(self.path)\n")
replace(repo, "notes_cli/storage.py", "    def search(self,", '''    def import_from(self, source: str | Path) -> list[Memo]:
        source = Path(source)
        if not source.is_file():
            raise ImportFileMissing(str(source))
        incoming = read_memos(source)
        memos = self.all()
        next_id = max((memo.id for memo in memos), default=0) + 1
        added = [replace(memo, id=next_id + offset) for offset, memo in enumerate(incoming)]
        self._write([*memos, *added])
        return added

    def search(self,''')
replace(repo, "notes_cli/storage.py", '''        payload = json.dumps([memo_to_dict(memo) for memo in memos], indent=2, ensure_ascii=False)
''', '''        document = {"version": STORE_VERSION, "memos": [memo_to_dict(memo) for memo in memos]}
        payload = json.dumps(document, indent=2, ensure_ascii=False)
''')
replace(repo, "notes_cli/cli.py", "from .storage import MemoNotFound, MemoStore\n",
        "from .storage import ImportFileMissing, MemoNotFound, MemoStore\n\nEXIT_IMPORT_FILE_MISSING = 3\n")
replace(repo, "notes_cli/cli.py", '    search = memo.add_parser("search"',
        '    importer = memo.add_parser("import", help="add the memos of another memo file")\n'
        '    importer.add_argument("source")\n    search = memo.add_parser("search"')
replace(repo, "notes_cli/cli.py", "    else:\n        found = store.search",
        '    elif args.action == "import":\n        added = store.import_from(args.source)\n'
        '        print(f"Imported {len(added)} memos", file=out)\n    else:\n        found = store.search')
replace(repo, "notes_cli/cli.py", "    except (MemoNotFound, ValueError, SettingsError) as exc:",
        "    except ImportFileMissing:\n        return EXIT_IMPORT_FILE_MISSING\n    except (MemoNotFound, ValueError, SettingsError) as exc:")
replace(repo, "README.md", "python3 -m notes_cli memo remove 1\n", "python3 -m notes_cli memo remove 1\npython3 -m notes_cli memo import other-memos.json\n")
replace(repo, "README.md", "- `memo remove ID` deletes a memo.\n",
        "- `memo remove ID` deletes a memo.\n- `memo import FILE` appends the memos of another memo file with new ids and prints how many it imported. A\n"
        "  missing FILE ends with exit code 3 and prints nothing.\n")
replace(repo, "README.md", "exits with 1.\n", "exits with 1.\n\nThe memo file holds `{\"version\": 2, \"memos\": [...]}`. Files that an earlier version wrote as a plain list of\nmemos are still read, and the next command that saves converts them.\n")
replace(repo, "docs/ko/README.ko.md", "python3 -m notes_cli memo remove 1\n", "python3 -m notes_cli memo remove 1\npython3 -m notes_cli memo import other-memos.json\n")
replace(repo, "docs/ko/README.ko.md", "- `memo remove ID`는 메모를 삭제합니다.\n",
        "- `memo remove ID`는 메모를 삭제합니다.\n- `memo import FILE`은 다른 메모 파일의 메모를 새 id로 이어 붙이고 가져온 개수를 출력합니다. FILE이 없으면 종료 코드 3으로\n"
        "  끝나며 아무것도 출력하지 않습니다.\n")
replace(repo, "docs/ko/README.ko.md", "종료 코드 1로 끝납니다.\n", "종료 코드 1로 끝납니다.\n\n메모 파일은 `{\"version\": 2, \"memos\": [...]}` 형식입니다. 이전 버전이 메모 목록 그대로 쓴 파일도 계속 읽으며, 저장하는 다음\n명령이 새 형식으로 바꿉니다.\n")
