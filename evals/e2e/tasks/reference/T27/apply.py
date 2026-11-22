import sys

from patch_tools import commit, replace

repo = sys.argv[1]
replace(repo, "config/review.yaml", "reviewer_model: demo-model-x", "reviewer_model: demo-model-y")
commit(repo, "chore: switch the reviewer model to demo-model-y")
