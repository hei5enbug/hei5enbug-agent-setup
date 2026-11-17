import sys

from patch_tools import replace

repo = sys.argv[1]
replace(repo, "timesheet/store.py", "from contextlib import contextmanager\n", "")
replace(repo, "timesheet/store.py", "import os\nimport time\n", "")
replace(repo, "timesheet/store.py", "from typing import Any, Iterator\n", "from typing import Any\n")
text = open(f"{repo}/timesheet/store.py", encoding="utf-8").read()
start, end = text.index("@contextmanager"), text.index("def save(")
open(f"{repo}/timesheet/store.py", "w", encoding="utf-8").write(text[:start] + text[end:])
replace(repo, "timesheet/store.py", "LOCK_WAIT_SECONDS = 5.0\n", "")
replace(repo, "timesheet/store.py", '''    with locked():
        entries = _read_file()
        entry = {"id": max((item["id"] for item in entries), default=0) + 1, "date": entry_date.isoformat(),
                 "project": project, "minutes": minutes}
        save([*entries, entry])
    return entry''', '''    entries = _read_file()
    entry = {"id": max((item["id"] for item in entries), default=0) + 1, "date": entry_date.isoformat(),
             "project": project, "minutes": minutes}
    save([*entries, entry])
    return entry''')
replace(repo, "timesheet/store.py", '''    with locked():
        entries = _read_file()
        kept = [item for item in entries if item["id"] != entry_id]
        if len(kept) == len(entries):
            return False
        save(kept)
    return True''', '''    entries = _read_file()
    kept = [item for item in entries if item["id"] != entry_id]
    if len(kept) == len(entries):
        return False
    save(kept)
    return True''')
replace(repo, "timesheet/store.py", '''    load_settings().data_file.write_text(''', '''    path = load_settings().data_file
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(''')
replace(repo, "README.md", """- Adds are safe to run in parallel: the store takes a lock file while it changes the data file, so two adds at once
  never lose an entry.
""", """- The store takes no lock, so two adds at the same time can lose an entry; run one add at a time.
""")
replace(repo, "docs/ko/README.ko.md", """- 더하기는 병렬로 실행해도 안전합니다. 저장소가 데이터 파일을 바꾸는 동안 잠금 파일을 잡아서, 동시에 둘을 더해도 기록을 잃지 않습니다.
""", """- 저장소는 잠금을 잡지 않으므로, 동시에 둘을 더하면 기록을 잃을 수 있습니다. 한 번에 하나씩 더하세요.
""")
