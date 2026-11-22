import sys

from patch_tools import write

write(sys.argv[1], "out/review-reply.txt", """Thanks, the empty list now writes only the header row.

- Added `test_demo_alpha`, `test_demo_beta`, and `test_demo_gamma`.
- Ran `python3 -m pytest -q`: 12 passed.
""")
