import sys

from patch_tools import write

write(sys.argv[1], "out/ticket-comment.txt", """Rollout ticket: what this comment covers.

Run 0 Check and build first, then 3 Compare, 4 Enable reads, 5 Enable writes, 6 Watch, 7 Remove old path, and 8 Confirm in order. Keep nesting at a depth of at most 2 levels and list at most 3 items in each progress update.
""")
