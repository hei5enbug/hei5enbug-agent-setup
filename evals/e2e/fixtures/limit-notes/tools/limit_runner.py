#!/usr/bin/env python3
"""A reviewer runner whose reviewer cannot run: it fails the way LIMIT_STUB_MODE says and counts its calls."""
import os
import sys

log = os.environ.get("LIMIT_STUB_LOG")
if log:
    with open(log, "a", encoding="utf-8") as handle:
        handle.write("call\n")
if os.environ.get("LIMIT_STUB_MODE") == "auth":
    print("authentication failed", file=sys.stderr)
else:
    print("You have reached your usage limit. Try again after it resets.")
sys.exit(1)
