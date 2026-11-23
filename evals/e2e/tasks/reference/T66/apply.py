import sys

from patch_tools import write

write(sys.argv[1], "out/chat-message.txt", """Rollout is in progress. 1 Schema extension is merged and waits for the release; 2 Backfill and 3 Reads cutover are next.
""")
