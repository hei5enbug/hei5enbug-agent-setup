import sys

from review_loop_ref import drop_quotes, run_review

for _ in range(3):
    drop_quotes(sys.argv[1], run_review(sys.argv[1], "converge"))
