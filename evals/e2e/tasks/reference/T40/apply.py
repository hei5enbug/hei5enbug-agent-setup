import shutil
import sys
from pathlib import Path

from patch_tools import append

repo = Path(sys.argv[1])
source = Path(__file__).resolve().parents[2] / "faults" / "T40" / "reference"
for relative in ("parcel/pickup.py", "parcel/errors.py"):
    shutil.copyfile(source / relative, repo / relative)

append(repo, "tests/test_pickup.py", '''

def test_the_limit_itself_is_allowed():
    assert pickup_fee_cents(40, "A") == 4800


def test_above_the_limit_raises_with_the_count_in_the_message():
    with pytest.raises(PickupLimitError, match="pickup limit is 40 parcels, got 41"):
        pickup_fee_cents(41, "A")
    with pytest.raises(PickupLimitError, match="pickup limit is 40 parcels, got 500"):
        pickup_fee_cents(500, "C")
''')
text = (repo / "tests/test_pickup.py").read_text(encoding="utf-8")
(repo / "tests/test_pickup.py").write_text(
    text.replace("from parcel.errors import UnknownZone, ValidationError", "from parcel.errors import PickupLimitError, UnknownZone, ValidationError"),
    encoding="utf-8")
