"""Reference run of T181: search the tracker, find the open issue that covers the gap, create nothing."""

import sys

from stub_gh_tools import search

search(sys.argv[1])
