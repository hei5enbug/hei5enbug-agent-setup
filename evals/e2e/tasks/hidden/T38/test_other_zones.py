from parcel.labels import format_label
from parcel.models import Parcel
from parcel.quote import build_quote
from parcel.rates import base_fee_cents, billable_grams


def test_zones_a_and_b_keep_500_gram_steps():
    assert build_quote(Parcel(1180, "A")).billed_grams == 1500
    assert build_quote(Parcel(1180, "B")).billed_grams == 1500
    assert base_fee_cents(1180, "A") == 900
    assert base_fee_cents(1180, "B") == 1350


def test_labels_of_zones_a_and_b_keep_the_500_gram_weight():
    assert format_label(Parcel(1180, "A")) == "Zone A\nWeight: 1180 g (billed as 1500 g)"
    assert format_label(Parcel(1180, "B")) == "Zone B\nWeight: 1180 g (billed as 1500 g)"


def test_billing_a_weight_without_a_zone_keeps_500_gram_steps():
    assert billable_grams(1180) == 1500
