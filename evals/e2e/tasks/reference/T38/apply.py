import sys

from patch_tools import append, replace

repo = sys.argv[1]

replace(repo, "parcel/rates.py", 'RATE_PER_500_GRAMS_CENTS = {"A": 300, "B": 450, "C": 600}\n',
        'RATE_PER_500_GRAMS_CENTS = {"A": 300, "B": 450, "C": 600}\nZONE_STEP_GRAMS = {"C": 250}\n')
replace(repo, "parcel/rates.py", 'def billable_grams(weight_grams: int) -> int:\n    """Round the weight up to the next billing step."""',
        'def billable_grams(weight_grams: int, zone: str | None = None) -> int:\n    """Round the weight up to the next billing step of the zone; without a zone the standard step applies."""')
replace(repo, "parcel/rates.py", "    steps = -(-weight_grams // WEIGHT_STEP_GRAMS)\n    return steps * WEIGHT_STEP_GRAMS\n",
        "    step = ZONE_STEP_GRAMS.get(zone, WEIGHT_STEP_GRAMS)\n    return -(-weight_grams // step) * step\n")
replace(repo, "parcel/rates.py", "return billable_grams(weight_grams) * RATE", "return billable_grams(weight_grams, zone) * RATE")
replace(repo, "parcel/quote.py", "billed_grams=billable_grams(parcel.weight_grams),", "billed_grams=billable_grams(parcel.weight_grams, parcel.zone),")
replace(repo, "parcel/labels.py", "billed = billable_grams(parcel.weight_grams)", "billed = billable_grams(parcel.weight_grams, parcel.zone)")
append(repo, "tests/test_rates.py", '''

def test_zone_c_weight_is_billed_in_250_gram_steps():
    assert billable_grams(1180, "C") == 1250
    assert billable_grams(1180, "B") == 1500
    assert base_fee_cents(1180, "C") == 1500
''')
replace(repo, "README.md", "- Weight is billed in 500 g steps, rounded up. The base fee",
        "- Weight is billed in 500 g steps, rounded up, and in 250 g steps in zone C. The base fee")
replace(repo, "docs/ko/README.ko.md", "- 무게는 500 g 단위로 올림해 청구합니다. 기본 요금은",
        "- 무게는 500 g 단위로 올림해 청구하고, 구역 C는 250 g 단위로 올림합니다. 기본 요금은")
