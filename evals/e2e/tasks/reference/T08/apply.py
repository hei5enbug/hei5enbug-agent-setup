import sys

from patch_tools import replace

replace(sys.argv[1], "config/settings.toml", "page_size = 20", "page_size = 50")
