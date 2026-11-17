from pathlib import Path

from host.options import load_options, option_value

ROOT = Path(__file__).resolve().parents[1]


def test_the_manifest_lists_delivery_values_with_auto_as_the_default():
    delivery = load_options(ROOT)["delivery"]
    assert delivery["options"][0] == "auto"
    assert delivery["default"] == "auto"


def test_option_values_are_trimmed_and_lowercased():
    assert option_value("delivery", {"HOST_OPTION_DELIVERY": " MANUAL "}) == "manual"
    assert option_value("delivery", {}) == ""
