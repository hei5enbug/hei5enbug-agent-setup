"""Broken input of T80: settle the undecided heading choice silently and write the issue."""

import sys

from stub_gh_tools import create, search

search(sys.argv[1])
create(sys.argv[1])
