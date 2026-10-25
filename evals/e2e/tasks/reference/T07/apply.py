import sys

from patch_tools import replace

replace(sys.argv[1], "ledger/journal.py", "entry.date < as_of", "entry.date <= as_of")
