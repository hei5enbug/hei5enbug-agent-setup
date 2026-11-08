import sys

from patch_tools import commit, replace

repo = sys.argv[1]
replace(repo, "config/settings.toml", "page_size = 20", "page_size = 50")
commit(repo, "chore: raise the default page size to 50")
