import shutil
import sys
from pathlib import Path

repo = Path(sys.argv[1])
for name in ("build", "dist", "logs"):
    shutil.rmtree(repo / name, ignore_errors=True)
for pattern in ("*.log", "*.tmp"):
    for path in repo.rglob(pattern):
        path.unlink()
for cache in repo.rglob("__pycache__"):
    shutil.rmtree(cache, ignore_errors=True)
