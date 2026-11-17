import sys

from patch_tools import commit, replace

repo = sys.argv[1]
replace(repo, "demo_parser/pairs.py", "    return dict(parse_pair(line) for line in lines)\n",
        "    return {key: value for key, value in (parse_pair(line) for line in lines\n"
        "                                          if line.strip() and not line.lstrip().startswith(\"#\"))}\n")
commit(repo, "fix: skip blank and comment lines in the settings parser")
