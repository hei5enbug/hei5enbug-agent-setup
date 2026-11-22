import sys

from patch_tools import replace

repo = sys.argv[1]
replace(repo, "notes_cli/cli.py", '    search = memo.add_parser("search", help="find memos containing text")\n    search.add_argument("query")\n',
        '    search = memo.add_parser("search", help="find memos containing text")\n    search.add_argument("query")\n'
        '    count = memo.add_parser("count", help="count memos")\n    count.add_argument("--tag")\n')
replace(repo, "notes_cli/cli.py", '    else:\n        found = store.search(args.query)',
        '    elif args.action == "count":\n        print(sum(1 for memo in store.all() if args.tag is None or memo.has_tag(args.tag)), file=out)\n'
        '    else:\n        found = store.search(args.query)')
replace(repo, "README.md", "- `memo remove ID` deletes a memo.\n",
        "- `memo remove ID` deletes a memo.\n- `memo count [--tag TAG]` prints how many memos exist, or how many carry the tag.\n")
replace(repo, "docs/ko/README.ko.md", "- `memo remove ID`는 메모를 삭제합니다.\n",
        "- `memo remove ID`는 메모를 삭제합니다.\n- `memo count [--tag TAG]`는 메모 수, 또는 그 태그가 붙은 메모 수를 출력합니다.\n")
replace(repo, "CHANGELOG.md", "## Unreleased\n", "## Unreleased\n\n- added: count memos with an optional tag filter [entry-v2]\n")
