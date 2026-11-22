import io

from parcel.cli import main
from parcel.labels import format_label
from parcel.models import Parcel
from parcel.quote import build_quote
from parcel.rates import base_fee_cents


def test_zone_c_weight_is_billed_in_250_gram_steps():
    assert build_quote(Parcel(1180, "C")).billed_grams == 1250
    assert build_quote(Parcel(1250, "C")).billed_grams == 1250
    assert build_quote(Parcel(1251, "C")).billed_grams == 1500
    assert build_quote(Parcel(1, "C")).billed_grams == 250


def test_zone_c_base_fee_follows_the_finer_step():
    assert base_fee_cents(1180, "C") == 1500
    assert base_fee_cents(250, "C") == 300
    assert base_fee_cents(251, "C") == 600


def test_zone_c_label_shows_the_finer_billed_weight():
    assert format_label(Parcel(1180, "C")) == "Zone C\nWeight: 1180 g (billed as 1250 g)"


def test_zone_c_quote_adds_the_surcharges_to_the_finer_base_fee():
    quote = build_quote(Parcel(1180, "C", 20_000))
    assert (quote.base_cents, quote.fuel_cents, quote.insurance_cents, quote.total_cents) == (1500, 120, 200, 1820)


def test_the_command_line_prints_the_zone_c_billing():
    out, err = io.StringIO(), io.StringIO()
    code = main(["quote", "--weight", "1180", "--zone", "c"], stdout=out, stderr=err)
    assert code == 0
    assert "Weight: 1180 g (billed as 1250 g)" in out.getvalue()
    assert out.getvalue().splitlines()[-1] == "Total: 16.20"
