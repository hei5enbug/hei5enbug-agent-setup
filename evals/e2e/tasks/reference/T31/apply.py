import sys

from patch_tools import write

write(sys.argv[1], "out/ticket-comment-demo-l.txt", """Rollout starts once the review passes. Begin with 1 Schema extension.
""")
