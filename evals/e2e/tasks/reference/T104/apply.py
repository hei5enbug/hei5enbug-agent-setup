import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from repeated_review_reference import fix_guide_rounds

fix_guide_rounds(Path(sys.argv[1]), 3)
