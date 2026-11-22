import sys

from patch_tools import write

write(sys.argv[1], "out/pr-description.txt", """The export now skips rows with an empty name instead of failing on them.
""")
