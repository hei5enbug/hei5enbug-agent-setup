import sys

from patch_tools import write

write(sys.argv[1], "out/ticket-comment-demo-j.txt", """Run 0 Check and build first, then 3 Compare, 4 Enable reads, 5 Enable writes, 6 Watch, 7 Remove old path, and 8 Confirm in order.
""")
