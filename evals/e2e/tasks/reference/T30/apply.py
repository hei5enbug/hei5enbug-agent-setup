import sys

from patch_tools import write

write(sys.argv[1], "out/review-reply-demo-k.txt", """Keep nesting at a depth of at most 2 levels and list at most 3 items.
""")
