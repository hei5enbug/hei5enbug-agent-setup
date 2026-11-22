from parcel.labels import format_label, format_quote
from parcel.models import Parcel
from parcel.quote import build_quote


def test_quote_adds_the_surcharges_to_the_base_fee():
    quote = build_quote(Parcel(1200, "B", 20_000))
    assert (quote.billed_grams, quote.base_cents, quote.fuel_cents, quote.insurance_cents) == (1500, 1350, 108, 200)
    assert quote.total_cents == 1658


def test_label_shows_the_billed_weight():
    assert format_label(Parcel(1200, "A")) == "Zone A\nWeight: 1200 g (billed as 1500 g)"


def test_quote_text_lists_every_amount():
    text = format_quote(build_quote(Parcel(1200, "A")))
    assert text == "Base: 9.00\nFuel: 0.72\nInsurance: 0.00\nTotal: 9.72"
